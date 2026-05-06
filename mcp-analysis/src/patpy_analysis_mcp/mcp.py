"""Module-level FastMCP instance shared by every tool in :mod:`patpy_analysis_mcp.tools`.

The cookiecutter convention is to define the server as a module-level
singleton so that every ``tools/_<toolname>.py`` file can import it and
attach itself with ``@mcp.tool``. Setting ``on_duplicate="error"``
catches accidental name clashes at import time.
"""

from fastmcp import FastMCP

mcp: FastMCP = FastMCP(
    name="patpy-analysis-mcp",
    instructions=(
        "patpy MCP server for sample-level single-cell analysis. Inputs are "
        "absolute paths to AnnData (.h5ad) files; every tool returns absolute "
        "paths to its outputs (also .h5ad / .csv / .png), so tools chain by "
        "passing paths between calls. The recommended order is: "
        "(1) inspect_anndata to discover sample_key / cell_group_key candidates "
        "and check whether obsm['X_pca'] exists; "
        "(2) pp_preprocess to filter small samples and (optionally) run PCA; "
        "(3) tl_sample_representation per method to compute a sample-level "
        "embedding (Pseudobulk, CellGroupComposition, RandomVector); "
        "(4) tl_associate_embedding_with_covariates to test each embedding "
        "against obs metadata; (5) pl_embedding_covariate_heatmap to visualise. "
        "If you'd rather run the whole pipeline in one call, use pipeline_run. "
        "For dataset discovery (CellxGene), chain this server with "
        "lueckenlab/patpy-mcp; for arbitrary AnnData inspection, chain with "
        "biocontext-ai/anndata-mcp."
    ),
    on_duplicate="error",
)
