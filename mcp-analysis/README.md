# patpy-analysis-mcp

[![BioContextAI - Registry](https://img.shields.io/badge/Registry-package?style=flat&label=BioContextAI&labelColor=%23fff&color=%233555a1&link=https://biocontext.ai/registry)](https://biocontext.ai/registry)
[![PyPI](https://img.shields.io/pypi/v/patpy-analysis-mcp?label=PyPI)](https://pypi.org/project/patpy-analysis-mcp/)

`patpy-analysis-mcp` is an MCP (Model Context Protocol) server that lets
any MCP-capable LLM agent run a sample-level single-cell analysis
pipeline on a downloaded AnnData. It wraps the
[`patpy`](https://github.com/lueckenlab/patpy) library —
preprocessing (`patpy.pp`), sample-representation methods (`patpy.tl`),
embedding–covariate association, and plotting (`patpy.pl`) — as MCP
tools so an agent can drive an end-to-end donor-level analysis through
typed tool calls instead of writing a Python script.

It is the **analysis sibling** of
[`patpy-mcp`](../mcp/README.md): `patpy-mcp` discovers and downloads
public datasets (e.g. from CellxGene Discover); `patpy-analysis-mcp`
takes the resulting `.h5ad` path and runs the actual science. Both
servers live in the [`patpy`](https://github.com/lueckenlab/patpy)
monorepo as self-contained sub-projects, are built from the
[`biocontext-ai/mcp-server-cookiecutter`](https://github.com/biocontext-ai/mcp-server-cookiecutter)
template, and are released to PyPI independently.

## Quick start

You need Python ≥ 3.11. If you don't have Python yet, install [`uv`](https://github.com/astral-sh/uv) — it bootstraps Python and runs `patpy-analysis-mcp` in one step.

There are four equivalent ways to install / run `patpy-analysis-mcp`, mirroring the four patterns from the BioContextAI [`mcp-server-cookiecutter`](https://github.com/biocontext-ai/mcp-server-cookiecutter):

### 1. Run the latest published release on demand (recommended)

```bash
uvx patpy-analysis-mcp
```

### 2. Add it to a client that supports the `mcp.json` standard

Cursor, Claude Desktop, Continue.dev, mcp-cli, Goose, etc. all read this exact JSON shape — copy it verbatim from [`mcp.json`](mcp.json) and drop it into your client config.

**From PyPI** (after release):

```json
{
  "mcpServers": {
    "lueckenlab/patpy-analysis-mcp": {
      "command": "uvx",
      "args": ["patpy-analysis-mcp"]
    }
  }
}
```

**From the GitHub `main` branch** (before any release tag):

```json
{
  "mcpServers": {
    "lueckenlab/patpy-analysis-mcp": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/lueckenlab/patpy.git@main#subdirectory=mcp-analysis",
        "patpy-analysis-mcp"
      ]
    }
  }
}
```

**From a local checkout** (development):

```json
{
  "mcpServers": {
    "lueckenlab/patpy-analysis-mcp": {
      "command": "uvx",
      "args": ["--refresh", "--from", "/abs/path/to/patpy/mcp-analysis", "patpy-analysis-mcp"]
    }
  }
}
```

### 3. Install with `pip`

```bash
pip install --user patpy-analysis-mcp
patpy-analysis-mcp                       # stdio transport (default)
patpy-analysis-mcp --transport http      # HTTP transport for remote clients
patpy-analysis-mcp --version
```

### 4. Run on a SLURM cluster (HTTP transport + SSH tunnel)

For real datasets you don't want to run the server on a login node —
it'll be killed by the resource limits and is too slow for a 100k-cell
AnnData anyway. Submit the server as a long-running SLURM job that
speaks HTTP, then SSH-tunnel the port back to your laptop and point
any MCP client (Cursor / Claude Desktop / MCP Inspector / Open WebUI /
mcp-cli) at `http://localhost:<port>/mcp`.

The full recipe — including the SLURM wrappers, the tunnel command,
and `mcp.json` snippets for each common client — lives in
[`scripts/README.md`](scripts/README.md). One-line summary:

```bash
sbatch mcp-analysis/scripts/serve-cpu.sbatch
# read the printed tunnel command from the job log, run it on your laptop,
# point an MCP client at http://localhost:<port>/mcp
```

### 5. Run via Docker

Build context is the repo root (so the shared top-level `LICENSE` is present):

```bash
docker build -t patpy-analysis-mcp -f mcp-analysis/Dockerfile .
docker run --rm -i patpy-analysis-mcp
```

> Note: this image is large (~3 GB) because `patpy` pulls
> `scanpy`, `anndata`, `matplotlib`, `scikit-learn`, etc. If you only
> need dataset discovery, use the much lighter [`mcp/Dockerfile`](../mcp/Dockerfile)
> instead.

## What it exposes

The recommended order is: `inspect_anndata` → `pp_preprocess` →
`tl_sample_representation` (per method) →
`tl_associate_embedding_with_covariates` → `pl_embedding_covariate_heatmap`.
For one-call execution, use `pipeline_run`.

| Tool                                       | Purpose                                                                                                                              |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| `inspect_anndata`                          | Report n_obs / n_vars, obs columns, obsm keys, and `sample_key` / `cell_group_key` candidates for an `.h5ad`.                        |
| `pp_preprocess`                            | `patpy.pp.filter_small_samples` + optional subsample + (optional) standard PCA pipeline; writes a preprocessed `.h5ad`.              |
| `tl_sample_representation`                 | Compute one of `Pseudobulk`, `CellGroupComposition`, `RandomVector`; project the resulting distance matrix to MDS coordinates; write a sample-level `.h5ad`. |
| `tl_associate_embedding_with_covariates`   | One-way ANOVA / Kruskal-Wallis per `(covariate, component)` pair; writes a tidy CSV with `-log10p`.                                  |
| `pl_embedding_covariate_heatmap`           | Render the association CSV as a `patpy.pl` heatmap PNG.                                                                              |
| `pipeline_run`                             | Convenience wrapper: chains all of the above end-to-end with sensible defaults; writes a manifest of every artifact.                  |

Every tool takes file paths in and writes file paths out — there is no
in-memory session state — so tool calls compose by passing absolute
paths between them. This matches how `patpy-mcp` already works
(downloads to `~/.cache/patpy-mcp/`), so the two servers chain
naturally:

```
cellxgene_search_datasets        ─┐ patpy-mcp
cellxgene_download_dataset       ─┘
            │ (h5ad path)
            ▼
inspect_anndata                  ─┐
pp_preprocess                     │
tl_sample_representation          │ patpy-analysis-mcp
tl_associate_embedding_…          │
pl_embedding_covariate_heatmap   ─┘
```

## How it complements other BioContextAI servers

- [`lueckenlab/patpy-mcp`](../mcp/README.md) — dataset discovery (CellxGene
  Discover, more sources coming). Hand its
  `cellxgene_download_dataset` output straight to `inspect_anndata`.
- [`biocontext-ai/anndata-mcp`](https://github.com/biocontext-ai/anndata-mcp)
  — generic AnnData inspection. Use this if you want richer obs/var
  introspection than `inspect_anndata` provides.
- [`MaxMLang/cxg-census-mcp`](https://github.com/MaxMLang/cxg-census-mcp)
  — Census slice queries (TileDB-SOMA) when you need a custom slice
  rather than a pre-curated dataset.

## Layout

```
mcp-analysis/
├── pyproject.toml          # standalone PyPI package (build = hatchling)
├── README.md               # this file
├── meta.yaml               # BioContextAI Registry entry (Schema.org metadata)
├── mcp.json                # BioContextAI Registry entry (MCP client config snippet)
├── Dockerfile              # deploy image (heavy — bundles scanpy/patpy)
├── src/patpy_analysis_mcp/
│   ├── __init__.py
│   ├── main.py             # click CLI (run_app)
│   ├── mcp.py              # module-level FastMCP instance
│   ├── _helpers.py         # path/obs helpers shared between tools
│   └── tools/_*.py         # one tool per file (inspect, pp_, tl_, pl_, pipeline_run)
└── tests/
    ├── conftest.py         # synthetic AnnData fixture
    ├── test_app.py         # CLI + tool-registration smoke tests
    └── test_*.py           # per-tool unit tests
```

## Releasing to PyPI

Push a tag of the form `patpy-analysis-mcp-v0.1.0` to the repo. The
release workflow (mirroring `release-patpy-mcp.yaml`) runs `uv build`
inside `mcp-analysis/` and uploads the resulting distribution to PyPI
via trusted publishing — `patpy`, `patpy-mcp` and `patpy-analysis-mcp`
release independently from the same monorepo.
