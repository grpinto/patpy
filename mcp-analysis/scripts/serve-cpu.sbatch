#!/usr/bin/env bash
# SLURM wrapper that runs `patpy-analysis-mcp --transport http` on a CPU
# compute node so you can drive the analysis tools from your laptop without
# touching the login node.
#
# Usage from a login node:
#     sbatch mcp-analysis/scripts/serve-cpu.sbatch
#
# Then watch the job's stdout for the SSH-tunnel and mcp.json snippets:
#     tail -f mcp-analysis/scripts/slurm-<jobid>.out
#
# Defaults: 4 CPUs, 16 GB RAM, 12 h walltime — enough for the
# breast-cancer pipeline (Pseudobulk + CellGroupComposition + heatmap on
# ~100k cells). Bump for bigger datasets or longer interactive sessions.

#SBATCH --job-name=patpy-mcp-srv
#SBATCH --partition=cpu_p
#SBATCH --qos=cpu_normal
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --nice=10000
#SBATCH --output=mcp-analysis/scripts/slurm-%j.out
#SBATCH --error=mcp-analysis/scripts/slurm-%j.err

set -euo pipefail

REPO=/lustre/groups/ml01/workspace/goncalo.pinto/patpy
cd "$REPO"

# Activate the venv that has patpy-analysis-mcp installed.
source .venv-patpy-run/bin/activate

# Pick an ephemeral port that's free on this node so two server jobs don't
# collide. Falls back to $MCP_PORT if you exported one.
if [[ -z "${MCP_PORT:-}" ]]; then
    MCP_PORT=$(python -c '
import socket
s = socket.socket()
s.bind(("", 0))
print(s.getsockname()[1])
s.close()
')
fi

export PATPY_MCP_CACHE="$REPO/.cache-patpy-mcp-test"
export MPLBACKEND=agg
export PYTHONUNBUFFERED=1

NODE=$(hostname -s)
# Default to the submission host (the login node the user ran sbatch from)
# but let them override with $LOGIN_HOST if they SSH in via a different
# alias or a jumphost.
LOGIN_HOST="${LOGIN_HOST:-${SLURM_SUBMIT_HOST:-$(hostname -f)}}"

# This cluster firewalls direct TCP from login -> compute on user ports
# (`No route to host` from the laptop's `ssh -L PORT:cpusrvNN:PORT login`).
# Work around that by opening a *reverse* SSH tunnel from this compute
# node back to the login node, exposing the same port on the login
# node's loopback. The user's laptop tunnel then targets `localhost`
# (i.e. the login node itself) instead of the compute-node hostname.
#
# Compute -> login over SSH is passwordless on this cluster, so this
# happens silently. If it ever fails (no key forwarding, login changed
# host key), the script still runs the server; the user can fall back
# to the direct cpusrv tunnel and it'll work on clusters that don't
# firewall inter-node TCP.
REVERSE_TUNNEL=""
if ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
       -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
       -o ConnectTimeout=10 \
       -fN -R "${MCP_PORT}:localhost:${MCP_PORT}" "${LOGIN_HOST}" \
       2>/tmp/reverse-tunnel-${SLURM_JOB_ID}.log; then
    REVERSE_TUNNEL="up"
    echo "[serve] reverse tunnel: $(hostname -s):${MCP_PORT} -> ${LOGIN_HOST}:${MCP_PORT} (OK)"
else
    REVERSE_TUNNEL=""
    echo "[serve] reverse tunnel to ${LOGIN_HOST} FAILED; see /tmp/reverse-tunnel-${SLURM_JOB_ID}.log"
    echo "[serve] users will need to tunnel directly to ${NODE} (only works without inter-node firewall)"
fi

if [[ -n "${REVERSE_TUNNEL}" ]]; then
    TUNNEL_TARGET="localhost"
    TUNNEL_NOTE="(via reverse tunnel from ${NODE} -> ${LOGIN_HOST}:${MCP_PORT}, set up automatically)"
else
    TUNNEL_TARGET="${NODE}"
    TUNNEL_NOTE="(direct compute-node tunnel; only works on clusters that don't firewall login->compute TCP)"
fi

cat <<EOF
================================================================================
patpy-analysis-mcp HTTP server is starting on a SLURM compute node.

  job_id          : ${SLURM_JOB_ID:-<not in slurm>}
  partition       : ${SLURM_JOB_PARTITION:-?}
  node            : ${NODE}
  port            : ${MCP_PORT}
  endpoint        : http://${NODE}:${MCP_PORT}/mcp
  reverse tunnel  : ${REVERSE_TUNNEL:-not opened}  ${TUNNEL_NOTE}
  python          : $(which python)
  cache           : $PATPY_MCP_CACHE

--- 1. Open an SSH tunnel from your laptop -------------------------------------
On your laptop, in a terminal you can leave open:

    ssh -N -L ${MCP_PORT}:${TUNNEL_TARGET}:${MCP_PORT} ${USER}@${LOGIN_HOST}

(No output is the correct state. Ctrl-C to close it when you're done.)

--- 2. Point an MCP client at it ----------------------------------------------
After the tunnel is up, the server is reachable from your laptop at
http://localhost:${MCP_PORT}/mcp

Cursor / Claude Desktop / Continue.dev mcp.json:

    {
      "mcpServers": {
        "patpy-analysis-mcp": {
          "url": "http://localhost:${MCP_PORT}/mcp"
        }
      }
    }

MCP Inspector (browser UI) — on your laptop:

    npx @modelcontextprotocol/inspector
    # then in the browser, choose Transport=Streamable HTTP and
    # paste http://localhost:${MCP_PORT}/mcp

--- 3. Stop the server --------------------------------------------------------
    scancel ${SLURM_JOB_ID:-<jobid>}
================================================================================
EOF

# Hand off to the server in foreground so SLURM keeps the job alive while
# the server is running. The server speaks streamable HTTP on /mcp.
exec patpy-analysis-mcp \
    --transport http \
    --host 0.0.0.0 \
    --port "${MCP_PORT}" \
    --env production
