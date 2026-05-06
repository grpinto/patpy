# Deploying `patpy-analysis-mcp` on a SLURM cluster

The `mcp-analysis/` server can run in two modes:

- **`stdio`** (the default) — spawned as a subprocess by an MCP client on
  the same machine, communicates over stdin/stdout. Good for local dev,
  unusable across machines.
- **`http`** — listens on a TCP port; any MCP client that supports
  Streamable HTTP can connect across the network. **This is the mode
  you want on a cluster** because the analysis tools need RAM / CPU /
  GPU that the login node doesn't have.

This directory contains two SLURM wrappers that boot the server in HTTP
mode on a compute node, plus this README documenting how to plug each
common MCP client into the running server.

## TL;DR — three steps

```bash
# 1. From the login node: launch the server on a compute node
sbatch mcp-analysis/scripts/serve-cpu.sbatch        # CPU-only tools (default)
# or
sbatch mcp-analysis/scripts/serve-gpu.sbatch        # later, when GPU tools land

# 2. Read the job log for the assigned compute node + port
tail -f mcp-analysis/scripts/slurm-<jobid>.out

# 3. From your laptop: open an SSH tunnel using the line printed in (2)
ssh -N -L <PORT>:<NODE>:<PORT> <user>@<login-host>

# Then point any MCP client at  http://localhost:<PORT>/mcp
```

The job logs spell out the exact tunnel command and `mcp.json` snippet
each time, with the actual port that was assigned — there is no fixed
port, so two server jobs from the same user can coexist.

> Verified end-to-end on the Helmholtz Munich cluster (jobs 36073378
> and 36074741): server listens on `0.0.0.0:<port>`, MCP `initialize`
> handshake succeeds, `tools/list` returns all six tools, both via the
> reverse-tunnel path and from inside the compute node.

> **Login-node firewall — important.** This cluster blocks direct TCP
> from the login nodes to compute-node user ports (`No route to host`)
> AND blocks direct SSH login → compute (`Permission denied`). So the
> obvious tunnel command `ssh -L PORT:cpusrvNN:PORT login_host` from
> your laptop fails: it reaches the login node, but the login node
> can't reach the compute node's port to forward traffic.
>
> The wrappers work around this by opening a **reverse SSH tunnel from
> the compute node back to the login node** (compute → login SSH is
> passwordless on this cluster) when the job starts. That binds the
> same port on the login node's loopback interface, and the printed
> tunnel command targets `localhost` instead of the compute hostname:
>
> ```
> ssh -N -L <PORT>:localhost:<PORT> <user>@<login-host>
> ```
>
> If your cluster *doesn't* firewall login → compute, the reverse
> tunnel still works but is unnecessary; the wrappers fall back to the
> direct path automatically when the reverse tunnel can't be opened.

## What the wrapper actually does

`serve-cpu.sbatch` walks through:

1. Activate `.venv-patpy-run/` (so `patpy-analysis-mcp` is on `PATH`).
2. Pick a free TCP port on the compute node (or use `$MCP_PORT` if set).
3. Print the node hostname, port, exact SSH-tunnel command, and the
   `mcp.json` snippet — so the user just copy-pastes from the job log.
4. Exec `patpy-analysis-mcp --transport http --host 0.0.0.0 --port <port>
   --env production` in the foreground (so SLURM keeps the job alive
   while the server runs).

`serve-gpu.sbatch` is the same script with a `gpu_p` SBATCH header and a
`--gres=gpu:a100_3g.20gb:1` request. None of the six tools currently
shipped with `patpy-analysis-mcp` need a GPU, so prefer `serve-cpu.sbatch`
unless you've added a tool that needs CUDA.

## Plugging clients into the running server

All snippets below assume your tunnel is up and `http://localhost:8000/mcp`
on your laptop forwards to the compute node — replace `8000` with the
port the job log shows.

### Cursor / Claude Desktop / Continue.dev / Goose (`mcp.json`)

Drop this into the MCP config of whichever desktop tool you use:

```json
{
  "mcpServers": {
    "patpy-analysis-mcp": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

For Claude Desktop the file lives at `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows). For Cursor it's the global "MCP Servers" setting. The shape is identical.

You'll typically also keep `patpy-mcp` (the discovery server) running locally as `stdio`, so a full config looks like:

```json
{
  "mcpServers": {
    "patpy-mcp": {
      "command": "uvx",
      "args": ["patpy-mcp"]
    },
    "patpy-analysis-mcp": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

The two servers chain: `patpy-mcp` runs locally and produces an `.h5ad`
path; the LLM passes that path to `patpy-analysis-mcp` over HTTP and the
heavy work happens on the compute node.

### MCP Inspector (browser UI, good for poking the server tool-by-tool)

On your laptop, in a separate terminal from the SSH tunnel:

```bash
npx @modelcontextprotocol/inspector
```

It opens a tab at `http://localhost:6274`. In the UI:

1. Set **Transport Type** = `Streamable HTTP`.
2. Set **URL** = `http://localhost:8000/mcp`.
3. Click **Connect**. The left panel lists all six tools; click any one
   to see its schema and call it interactively.

This is the closest thing to "use the server in a website": no LLM in
the loop, you call tools directly from the browser. Useful for
debugging and for understanding what the LLM would see.

### Open WebUI / LibreChat (full chat UI in the browser)

If you want a ChatGPT-like web interface that drives the MCP server via
an LLM (Llama, GPT-4, Claude, …), [Open WebUI](https://github.com/open-webui/open-webui)
and [LibreChat](https://github.com/danny-avila/LibreChat) both speak
MCP. Install them on your laptop (or any machine that can reach the
tunnel), and point them at `http://localhost:8000/mcp` — the same URL
the desktop clients use.

### `mcp-cli` (terminal client, scriptable)

```bash
pipx install mcp-cli
mcp-cli --server http://localhost:8000/mcp tool-list
mcp-cli --server http://localhost:8000/mcp tool-call inspect_anndata \
    --argument h5ad_path=/path/to/dataset.h5ad
```

Useful for shell scripts and CI, no GUI required.

## Stopping the server

```bash
scancel <jobid>           # cancel the SLURM job
# or, if the job is the only one of its kind for your user:
scancel -n patpy-mcp-srv
```

The SSH tunnel on your laptop stays open until you Ctrl-C it; that's
harmless once the server is gone.

## Why HTTP transport over stdio?

| | `stdio` | `http` |
|---|---|---|
| Server runs on | same machine as the client | any machine the client can reach |
| Auth | OS-level (it's a subprocess) | network-level (tunnel / TLS / token) |
| Multiple clients | one (subprocess is bound to its parent) | many (long-running shared service) |
| GPU needed | only if the client machine has one | yes — server runs on a GPU node |
| Login-node-friendly | no (heavy imports get killed) | yes — server lives on the compute node |
| Best for | local dev | clusters, shared deployments |

The stdio mode you've used so far (`uvx patpy-analysis-mcp`,
`fastmcp.Client(mcp)` in the test suite) is fine on your laptop or for
unit tests. The moment the analysis touches a real CellxGene-sized
AnnData, switch to HTTP + a SLURM-hosted server.
