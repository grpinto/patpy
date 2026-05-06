#!/usr/bin/env bash
# SLURM wrapper that runs `patpy-analysis-mcp --transport http` on a GPU
# compute node. Use this when you'll be calling tools that need a CUDA
# device (PULSAR, MixMIL, MrVI, SCPoli, scVI, …) — the current six tools
# in patpy-analysis-mcp are CPU-only, so for those, prefer
# `serve-cpu.sbatch` to leave the GPU pool free.
#
# Usage from a login node:
#     sbatch mcp-analysis/scripts/serve-gpu.sbatch
#
# Then watch the job's stdout for the SSH-tunnel and mcp.json snippets:
#     tail -f mcp-analysis/scripts/slurm-<jobid>.out
#
# Defaults: 1× A100 (3g.20gb slice), 8 CPUs, 64 GB RAM, 6 h walltime.

#SBATCH --job-name=patpy-mcp-srv-gpu
#SBATCH --partition=gpu_p
#SBATCH --qos=gpu_normal
#SBATCH --gres=gpu:a100_3g.20gb:1
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --nice=10000
#SBATCH --output=mcp-analysis/scripts/slurm-%j.out
#SBATCH --error=mcp-analysis/scripts/slurm-%j.err

set -euo pipefail

REPO=/lustre/groups/ml01/workspace/goncalo.pinto/patpy
cd "$REPO"

source .venv-patpy-run/bin/activate

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
LOGIN_HOST="${LOGIN_HOST:-${SLURM_SUBMIT_HOST:-$(hostname -f)}}"

# See serve-cpu.sbatch for the rationale: this cluster firewalls direct
# TCP from login -> compute on user ports, so we open a reverse SSH
# tunnel back to the login node and have users target localhost there.
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
fi

if [[ -n "${REVERSE_TUNNEL}" ]]; then
    TUNNEL_TARGET="localhost"
    TUNNEL_NOTE="(via reverse tunnel from ${NODE} -> ${LOGIN_HOST}:${MCP_PORT}, set up automatically)"
else
    TUNNEL_TARGET="${NODE}"
    TUNNEL_NOTE="(direct compute-node tunnel; only works without inter-node firewall)"
fi

cat <<EOF
================================================================================
patpy-analysis-mcp HTTP server is starting on a SLURM GPU node.

  job_id          : ${SLURM_JOB_ID:-<not in slurm>}
  partition       : ${SLURM_JOB_PARTITION:-?}
  node            : ${NODE}
  gpu             : ${CUDA_VISIBLE_DEVICES:-<unset>}
  port            : ${MCP_PORT}
  endpoint        : http://${NODE}:${MCP_PORT}/mcp
  reverse tunnel  : ${REVERSE_TUNNEL:-not opened}  ${TUNNEL_NOTE}
  python          : $(which python)
  cache           : $PATPY_MCP_CACHE

--- 1. Open an SSH tunnel from your laptop -------------------------------------
On your laptop:

    ssh -N -L ${MCP_PORT}:${TUNNEL_TARGET}:${MCP_PORT} ${USER}@${LOGIN_HOST}

--- 2. Point an MCP client at it ----------------------------------------------
After the tunnel is up the server is reachable from your laptop at
http://localhost:${MCP_PORT}/mcp

mcp.json snippet:

    {
      "mcpServers": {
        "patpy-analysis-mcp": {
          "url": "http://localhost:${MCP_PORT}/mcp"
        }
      }
    }

--- 3. Stop the server --------------------------------------------------------
    scancel ${SLURM_JOB_ID:-<jobid>}
================================================================================
EOF

exec patpy-analysis-mcp \
    --transport http \
    --host 0.0.0.0 \
    --port "${MCP_PORT}" \
    --env production
