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

cat <<EOF
================================================================================
patpy-analysis-mcp HTTP server is starting on a SLURM GPU node.

  job_id      : ${SLURM_JOB_ID:-<not in slurm>}
  partition   : ${SLURM_JOB_PARTITION:-?}
  node        : ${NODE}
  gpu         : ${CUDA_VISIBLE_DEVICES:-<unset>}
  port        : ${MCP_PORT}
  endpoint    : http://${NODE}:${MCP_PORT}/mcp
  python      : $(which python)
  cache       : $PATPY_MCP_CACHE

--- 1. Open an SSH tunnel from your laptop -------------------------------------
On your laptop:

    ssh -N -L ${MCP_PORT}:${NODE}:${MCP_PORT} ${USER}@${LOGIN_HOST}

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
