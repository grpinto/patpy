#!/usr/bin/env bash
# SLURM wrapper that runs both patpy MCP servers on a GPU compute node.
# Use this when you'll be calling tools that need a CUDA device (PULSAR,
# MixMIL, MrVI, SCPoli, scVI, ...) - the current six tools in
# patpy-analysis-mcp are CPU-only, so for those, prefer
# `serve-cpu.sbatch` to leave the GPU pool free.
#
#   - patpy-mcp           : CellxGene discovery (search / metadata / download)
#   - patpy-analysis-mcp  : preprocessing, sample representation, plotting
#
# Both servers share the same on-disk dataset cache so a dataset downloaded
# by `cellxgene_download_dataset` is immediately readable by the analysis
# tools without copying files around.
#
# Usage from a login node:
#     sbatch mcp-analysis/scripts/serve-gpu.sbatch
#
# Then watch the job's stdout for the SSH-tunnel and mcp.json snippets:
#     tail -f mcp-analysis/scripts/slurm-<jobid>.out
#
# Defaults: 1x A100 (3g.20gb slice), 8 CPUs, 64 GB RAM, 6 h walltime.

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

pick_port() {
    python -c '
import socket
s = socket.socket()
s.bind(("", 0))
print(s.getsockname()[1])
s.close()
'
}
ANALYSIS_PORT="${MCP_ANALYSIS_PORT:-$(pick_port)}"
DISCOVERY_PORT="${MCP_DISCOVERY_PORT:-$(pick_port)}"
while [[ "$DISCOVERY_PORT" == "$ANALYSIS_PORT" ]]; do
    DISCOVERY_PORT=$(pick_port)
done

export PATPY_MCP_CACHE="$REPO/.cache-patpy-mcp-test"
export MPLBACKEND=agg
export PYTHONUNBUFFERED=1

NODE=$(hostname -s)
LOGIN_HOST="${LOGIN_HOST:-${SLURM_SUBMIT_HOST:-$(hostname -f)}}"

# See serve-cpu.sbatch for the rationale: this cluster firewalls direct
# TCP from login -> compute on user ports, so we open a reverse SSH
# tunnel back to the login node and have users target localhost there.
open_reverse_tunnel() {
    local port=$1
    if ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
           -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
           -o ConnectTimeout=10 \
           -fN -R "${port}:localhost:${port}" "${LOGIN_HOST}" \
           2>>/tmp/reverse-tunnel-${SLURM_JOB_ID}.log; then
        echo "ok"
    else
        echo "fail"
    fi
}

ANALYSIS_TUNNEL=$(open_reverse_tunnel "$ANALYSIS_PORT")
DISCOVERY_TUNNEL=$(open_reverse_tunnel "$DISCOVERY_PORT")

if [[ "$ANALYSIS_TUNNEL" == "ok" && "$DISCOVERY_TUNNEL" == "ok" ]]; then
    TUNNEL_TARGET="localhost"
    TUNNEL_NOTE="(via reverse tunnels from ${NODE} -> ${LOGIN_HOST}, set up automatically)"
else
    TUNNEL_TARGET="${NODE}"
    TUNNEL_NOTE="(reverse tunnel FAILED; falling back to direct compute-node tunnel - only works without inter-node firewall)"
fi

cat <<EOF
================================================================================
patpy MCP servers are starting on a SLURM GPU node.

  job_id           : ${SLURM_JOB_ID:-<not in slurm>}
  partition        : ${SLURM_JOB_PARTITION:-?}
  node             : ${NODE}
  gpu              : ${CUDA_VISIBLE_DEVICES:-<unset>}
  analysis port    : ${ANALYSIS_PORT}    (patpy-analysis-mcp)
  discovery port   : ${DISCOVERY_PORT}    (patpy-mcp / CellxGene)
  shared cache     : ${PATPY_MCP_CACHE}
  reverse tunnels  : analysis=${ANALYSIS_TUNNEL}, discovery=${DISCOVERY_TUNNEL}  ${TUNNEL_NOTE}
  python           : $(which python)

--- 1. Open SSH tunnels from your laptop --------------------------------------
In one terminal you can leave open (combined into a single SSH connection):

    ssh -N \\
        -L ${ANALYSIS_PORT}:${TUNNEL_TARGET}:${ANALYSIS_PORT} \\
        -L ${DISCOVERY_PORT}:${TUNNEL_TARGET}:${DISCOVERY_PORT} \\
        ${USER}@${LOGIN_HOST}

--- 2. Point your MCP client at BOTH servers ----------------------------------
mcp.json snippet (Cursor / Claude Desktop / Continue.dev):

    {
      "mcpServers": {
        "patpy-mcp": {
          "url": "http://localhost:${DISCOVERY_PORT}/mcp"
        },
        "patpy-analysis-mcp": {
          "url": "http://localhost:${ANALYSIS_PORT}/mcp"
        }
      }
    }

--- 3. Stop everything --------------------------------------------------------
    scancel ${SLURM_JOB_ID:-<jobid>}
================================================================================
EOF

# Run patpy-mcp (CellxGene discovery) in the background...
patpy-mcp \
    --transport http \
    --host 0.0.0.0 \
    --port "${DISCOVERY_PORT}" \
    --env production \
    >>"mcp-analysis/scripts/slurm-${SLURM_JOB_ID}.discovery.log" 2>&1 &
DISCOVERY_PID=$!
echo "[serve] patpy-mcp pid=${DISCOVERY_PID} -> mcp-analysis/scripts/slurm-${SLURM_JOB_ID}.discovery.log"

# ...and patpy-analysis-mcp in the foreground so SLURM keeps the job alive.
trap "kill ${DISCOVERY_PID} 2>/dev/null || true" EXIT
exec patpy-analysis-mcp \
    --transport http \
    --host 0.0.0.0 \
    --port "${ANALYSIS_PORT}" \
    --env production
