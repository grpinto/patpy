#!/usr/bin/env bash
# SLURM wrapper that runs both patpy MCP servers on a single CPU compute
# node so an LLM client (Cursor, Claude Desktop, Open WebUI, ...) can drive
# the full discover -> analyse pipeline without touching the login node.
#
#   - patpy-mcp           : CellxGene discovery (search / metadata / download)
#   - patpy-analysis-mcp  : preprocessing, sample representation, plotting
#
# Both servers share the same on-disk dataset cache so a dataset downloaded
# by `cellxgene_download_dataset` is immediately readable by
# `inspect_anndata` / `pp_preprocess` / etc. without copying files around.
#
# Usage from a login node:
#     sbatch mcp-analysis/scripts/serve-cpu.sbatch
#
# Then watch the job's stdout for the SSH-tunnel and mcp.json snippets:
#     tail -f mcp-analysis/scripts/slurm-<jobid>.out
#
# Defaults: 4 CPUs, 16 GB RAM, 12 h walltime - enough for the breast-cancer
# pipeline (Pseudobulk + CellGroupComposition + heatmap on ~100k cells).
# Bump for bigger datasets or longer interactive sessions.

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

# Activate the venv that has BOTH patpy-mcp and patpy-analysis-mcp installed.
source .venv-patpy-run/bin/activate

# Pick two free ephemeral ports so multiple server jobs (or other users)
# don't collide. Override either via $MCP_ANALYSIS_PORT / $MCP_DISCOVERY_PORT.
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

# Both servers must agree on the dataset cache so files downloaded by
# patpy-mcp.cellxgene_download_dataset are visible to patpy-analysis-mcp.
export PATPY_MCP_CACHE="$REPO/.cache-patpy-mcp-test"
export MPLBACKEND=agg
export PYTHONUNBUFFERED=1

NODE=$(hostname -s)
# Default to the submission host (the login node the user ran sbatch from)
# but let them override with $LOGIN_HOST if they SSH in via a different
# alias or jumphost.
LOGIN_HOST="${LOGIN_HOST:-${SLURM_SUBMIT_HOST:-$(hostname -f)}}"

# Open one reverse tunnel per port. This cluster firewalls direct TCP from
# login -> compute on user ports, so we expose each server on the login
# node's loopback via SSH `-R`. Compute -> login over SSH is passwordless,
# so this happens silently.
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
patpy MCP servers are starting on a SLURM compute node.

  job_id           : ${SLURM_JOB_ID:-<not in slurm>}
  partition        : ${SLURM_JOB_PARTITION:-?}
  node             : ${NODE}
  analysis port    : ${ANALYSIS_PORT}    (patpy-analysis-mcp)
  discovery port   : ${DISCOVERY_PORT}    (patpy-mcp / CellxGene)
  shared cache     : ${PATPY_MCP_CACHE}
  reverse tunnels  : analysis=${ANALYSIS_TUNNEL}, discovery=${DISCOVERY_TUNNEL}  ${TUNNEL_NOTE}
  python           : $(which python)

--- 1. Open one SSH tunnel per server from your laptop ------------------------
In two terminals you can leave open (or merge with -L flags into one):

    ssh -N -L ${ANALYSIS_PORT}:${TUNNEL_TARGET}:${ANALYSIS_PORT} ${USER}@${LOGIN_HOST}
    ssh -N -L ${DISCOVERY_PORT}:${TUNNEL_TARGET}:${DISCOVERY_PORT} ${USER}@${LOGIN_HOST}

Or combined into one connection:

    ssh -N \\
        -L ${ANALYSIS_PORT}:${TUNNEL_TARGET}:${ANALYSIS_PORT} \\
        -L ${DISCOVERY_PORT}:${TUNNEL_TARGET}:${DISCOVERY_PORT} \\
        ${USER}@${LOGIN_HOST}

(No output is the correct state. Ctrl-C closes the tunnel.)

--- 2. Point your MCP client at BOTH servers ----------------------------------
Cursor / Claude Desktop / Continue.dev mcp.json:

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

Once both are configured, ask your LLM things like:

    > Find a multi-donor breast cancer dataset on CellxGene with at least
    > 50k cells, download it, then run pseudobulk + composition embeddings
    > and show me the embedding-covariate heatmaps.

The LLM will call patpy-mcp.cellxgene_search_datasets ->
patpy-mcp.cellxgene_download_dataset -> patpy-analysis-mcp.pipeline_run
without you having to wire anything by hand.

MCP Inspector (browser UI) on your laptop, one server at a time:

    npx @modelcontextprotocol/inspector
    # Transport=Streamable HTTP, URL=http://localhost:${DISCOVERY_PORT}/mcp
    # or
    # Transport=Streamable HTTP, URL=http://localhost:${ANALYSIS_PORT}/mcp

--- 3. Stop everything --------------------------------------------------------
    scancel ${SLURM_JOB_ID:-<jobid>}
(stops both servers and tears the reverse tunnels down with them)
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

# ...and patpy-analysis-mcp in the foreground so SLURM keeps the job alive
# while either server is running. If the foreground server dies, scancel
# the job and resubmit.
trap "kill ${DISCOVERY_PID} 2>/dev/null || true" EXIT
exec patpy-analysis-mcp \
    --transport http \
    --host 0.0.0.0 \
    --port "${ANALYSIS_PORT}" \
    --env production
