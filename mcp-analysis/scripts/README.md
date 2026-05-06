# Deploying the patpy MCP servers on a SLURM cluster

The `serve-cpu.sbatch` / `serve-gpu.sbatch` wrappers in this directory boot
**both** patpy MCP servers on a single SLURM compute node so an LLM client
on your laptop can drive the entire CellxGene -> patpy analysis pipeline
without anything heavy happening on the login node:

| server | what it does | tools |
|---|---|---|
| `patpy-mcp` | CellxGene Discover discovery (search / metadata / download) | `cellxgene_search_datasets`, `cellxgene_get_collection`, `cellxgene_get_dataset`, `cellxgene_download_dataset`, `cellxgene_list_*`, `list_sources`, `describe_source` |
| `patpy-analysis-mcp` | preprocessing, sample-level representation, association testing, plotting | `inspect_anndata`, `pp_preprocess`, `tl_sample_representation`, `tl_associate_embedding_with_covariates`, `pl_embedding_covariate_heatmap`, `pipeline_run` |

Both servers share `$PATPY_MCP_CACHE`, so a `.h5ad` file written by
`cellxgene_download_dataset` is *immediately* readable by `inspect_anndata`
and the rest of the analysis tools — no copying, no path translation.

Each server can run in two transports:

- **`stdio`** (the default) — spawned as a subprocess by an MCP client on
  the same machine, communicates over stdin/stdout. Good for local dev,
  unusable across machines.
- **`http`** — listens on a TCP port; any MCP client that supports
  Streamable HTTP can connect across the network. **This is the mode
  the SLURM wrappers use** because the analysis tools need RAM / CPU /
  GPU that the login node doesn't have, and the discovery tools need to
  download datasets to the same filesystem the analysis tools read from.

## TL;DR — three steps

```bash
# 1. From the login node: launch BOTH servers on a compute node
sbatch mcp-analysis/scripts/serve-cpu.sbatch        # CPU-only tools (default)
# or
sbatch mcp-analysis/scripts/serve-gpu.sbatch        # later, when GPU tools land

# 2. Read the job log for the assigned compute node + ports
tail -f mcp-analysis/scripts/slurm-<jobid>.out

# 3. From your laptop: open ONE SSH tunnel that forwards both ports
ssh -N \
    -L <ANALYSIS_PORT>:localhost:<ANALYSIS_PORT> \
    -L <DISCOVERY_PORT>:localhost:<DISCOVERY_PORT> \
    <user>@<login-host>

# Then point any MCP client at BOTH URLs (mcp.json snippet below).
```

The job logs spell out the exact tunnel command and `mcp.json` snippet
each time, with the actual ports that were assigned — there is no fixed
port, so two server jobs from the same user can coexist.

> Verified end-to-end on the Helmholtz Munich cluster (job 36074741):
> both servers listen on `0.0.0.0:<port>`, MCP `initialize` handshake
> succeeds, `tools/list` returns the discovery tools (9) and analysis
> tools (6), reachable through the reverse-tunnel path from the login
> node and onward from a laptop.

> **Login-node firewall — important.** This cluster blocks direct TCP
> from the login nodes to compute-node user ports (`No route to host`)
> AND blocks direct SSH login -> compute (`Permission denied`). So the
> obvious tunnel command `ssh -L PORT:cpusrvNN:PORT login_host` from
> your laptop fails: it reaches the login node, but the login node
> can't reach the compute node's port to forward traffic.
>
> The wrappers work around this by opening a **reverse SSH tunnel from
> the compute node back to the login node** (compute -> login SSH is
> passwordless on this cluster) when the job starts — one tunnel per
> server. That binds the same ports on the login node's loopback
> interface, and the printed tunnel command targets `localhost`
> instead of the compute hostname:
>
> ```
> ssh -N -L <PORT>:localhost:<PORT> <user>@<login-host>
> ```
>
> If your cluster *doesn't* firewall login -> compute, the reverse
> tunnel still works but is unnecessary; the wrappers fall back to the
> direct path automatically when the reverse tunnel can't be opened.

## What the wrapper actually does

`serve-cpu.sbatch` walks through:

1. Activate `.venv-patpy-run/` (so both `patpy-mcp` and
   `patpy-analysis-mcp` are on `PATH`).
2. Pick two free TCP ports on the compute node (one per server). You can
   override either with `$MCP_ANALYSIS_PORT` / `$MCP_DISCOVERY_PORT`.
3. Open one reverse SSH tunnel per port from the compute node back to
   the login node so the laptop tunnel can target `localhost`.
4. Print the node hostname, both ports, the SSH-tunnel command, and the
   `mcp.json` snippet — copy-paste from the job log.
5. Start `patpy-mcp` (CellxGene discovery) in the background.
6. `exec patpy-analysis-mcp` in the foreground so SLURM keeps the job
   alive while either server is running. A trap kills the discovery
   server when the foreground server exits.

`serve-gpu.sbatch` is the same script with a `gpu_p` SBATCH header and a
`--gres=gpu:a100_3g.20gb:1` request. None of the six tools currently
shipped with `patpy-analysis-mcp` need a GPU, so prefer `serve-cpu.sbatch`
unless you've added a tool that needs CUDA.

## Plugging clients into the running servers

All snippets below use placeholders `<ANALYSIS_PORT>` and
`<DISCOVERY_PORT>` — replace each with the port the job log shows.

### Cursor / Claude Desktop / Continue.dev / Goose (`mcp.json`)

Add **both** servers to your MCP config so the LLM can chain them:

```json
{
  "mcpServers": {
    "patpy-mcp": {
      "url": "http://localhost:<DISCOVERY_PORT>/mcp"
    },
    "patpy-analysis-mcp": {
      "url": "http://localhost:<ANALYSIS_PORT>/mcp"
    }
  }
}
```

For Claude Desktop the file lives at
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or `%APPDATA%\Claude\claude_desktop_config.json` (Windows). For Cursor
it's the global "MCP Servers" setting. The shape is identical.

Why both run cluster-side: `cellxgene_download_dataset` writes the
`.h5ad` into the *cluster's* filesystem. If `patpy-mcp` ran on your
laptop, the analysis server on the cluster wouldn't see the file. With
both on the compute node sharing `$PATPY_MCP_CACHE`, the LLM can pass
the cluster-side path straight through. Once both URLs are configured,
ask your LLM things like:

> Find a multi-donor breast cancer dataset on CellxGene with at least
> 50k cells, download it, then run pseudobulk + composition embeddings
> and show me the embedding-covariate heatmaps.

The LLM will call `patpy-mcp.cellxgene_search_datasets` ->
`patpy-mcp.cellxgene_download_dataset` ->
`patpy-analysis-mcp.pipeline_run` without you having to wire anything by
hand.

### MCP Inspector (browser UI, good for poking the server tool-by-tool)

On your laptop, in a separate terminal from the SSH tunnel:

```bash
npx @modelcontextprotocol/inspector
```

It opens a tab at `http://localhost:6274`. In the UI:

1. Set **Transport Type** = `Streamable HTTP`.
2. Set **URL** = `http://localhost:<ANALYSIS_PORT>/mcp` (or
   `http://localhost:<DISCOVERY_PORT>/mcp`).
3. Click **Connect**. The left panel lists all of that server's tools;
   click any one to see its schema and call it interactively.

You connect to one server at a time; switch the URL to inspect the
other. This is the closest thing to "use the server in a website":
there's no LLM in the loop — you call tools directly from the browser.
Useful for debugging and for understanding what the LLM would see.

### Open WebUI / LibreChat (full chat UI in the browser)

If you want a ChatGPT-like web interface that drives the MCP servers
via an LLM (Llama, GPT-4, Claude, ...),
[Open WebUI](https://github.com/open-webui/open-webui) and
[LibreChat](https://github.com/danny-avila/LibreChat) both speak MCP.
Install one on your laptop (or any machine that can reach the tunnel)
and add **both** server URLs the same way as in the `mcp.json` snippet
above.

### `mcp-cli` (terminal client, scriptable)

```bash
pipx install mcp-cli

# Discovery
mcp-cli --server http://localhost:<DISCOVERY_PORT>/mcp tool-list
mcp-cli --server http://localhost:<DISCOVERY_PORT>/mcp tool-call \
    cellxgene_search_datasets --argument query=breast --argument tissue=breast

# Analysis
mcp-cli --server http://localhost:<ANALYSIS_PORT>/mcp tool-list
mcp-cli --server http://localhost:<ANALYSIS_PORT>/mcp tool-call \
    inspect_anndata --argument h5ad_path=/path/to/dataset.h5ad
```

Useful for shell scripts and CI, no GUI required.

## Stopping the servers

```bash
scancel <jobid>           # cancel the SLURM job
# or, if the job is the only one of its kind for your user:
scancel -n patpy-mcp-srv
```

That kills both servers and tears the reverse tunnels down with them.
The SSH tunnel on your laptop stays open until you Ctrl-C it; that's
harmless once the servers are gone.

## Why HTTP transport over stdio?

| | `stdio` | `http` |
|---|---|---|
| Server runs on | same machine as the client | any machine the client can reach |
| Auth | OS-level (it's a subprocess) | network-level (tunnel / TLS / token) |
| Multiple clients | one (subprocess is bound to its parent) | many (long-running shared service) |
| GPU needed | only if the client machine has one | yes — server runs on a GPU node |
| Login-node-friendly | no (heavy imports get killed) | yes — server lives on the compute node |
| Best for | local dev | clusters, shared deployments |

The stdio mode (`uvx patpy-analysis-mcp`, `fastmcp.Client(mcp)` in the
test suite) is fine on your laptop or for unit tests. The moment the
analysis touches a real CellxGene-sized AnnData — or the moment you
want both servers to share a single dataset cache — switch to HTTP +
the SLURM-hosted servers above.
