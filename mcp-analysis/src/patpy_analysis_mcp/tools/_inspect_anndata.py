"""``inspect_anndata`` tool: report schema of an .h5ad file."""

from __future__ import annotations

from typing import Any

import anndata as ad

from patpy_analysis_mcp._helpers import (
    CELL_GROUP_KEY_CANDIDATES,
    SAMPLE_KEY_CANDIDATES,
    resolve_path,
)
from patpy_analysis_mcp.mcp import mcp


def inspect_anndata(h5ad_path: str) -> dict[str, Any]:
    """Report the schema of an ``.h5ad`` file relevant to a patpy pipeline.

    Designed as the first step before calling any other tool: discover
    which ``obs`` columns can serve as ``sample_key`` and ``cell_group_key``,
    whether ``obsm['X_pca']`` is already populated, and how big the
    matrix is. Reads the file in backed mode so it does not pay the
    cost of loading ``.X`` into memory.

    Parameters
    ----------
    h5ad_path
        Absolute path to an existing ``.h5ad`` file (the path returned
        by ``cellxgene_download_dataset`` from ``patpy-mcp`` works).

    Returns
    -------
    dict
        Schema report with the following keys:

        ``path``
            Absolute resolved path.
        ``n_obs``, ``n_vars``
            Cell and gene counts.
        ``obs_columns``
            Full list of column names in ``adata.obs``.
        ``obsm_keys``, ``layers``
            Keys present in ``adata.obsm`` and ``adata.layers``.
        ``has_x_pca``
            ``True`` iff ``adata.obsm`` contains ``"X_pca"`` (the default
            ``layer`` for ``Pseudobulk`` is ``"X_pca"``).
        ``sample_key_candidates``
            ``[{"name": str, "n_unique": int}, ...]`` for the obs columns
            most likely to be a sample / donor identifier, ordered by the
            convention list (``donor_id`` first, then ``patient_id`` …).
        ``cell_group_key_candidates``
            Same shape, for cell-type / cluster columns.
    """
    path = resolve_path(h5ad_path, must_exist=True)
    # backed='r' reads obs/var/obsm without pulling .X into memory.
    adata = ad.read_h5ad(path, backed="r")

    obs_cols = list(adata.obs.columns)
    obsm_keys = list(adata.obsm.keys())
    layers = list(adata.layers.keys())

    sample_candidates = [
        {"name": c, "n_unique": int(adata.obs[c].nunique())}
        for c in SAMPLE_KEY_CANDIDATES
        if c in obs_cols
    ]
    cell_group_candidates = [
        {"name": c, "n_unique": int(adata.obs[c].nunique())}
        for c in CELL_GROUP_KEY_CANDIDATES
        if c in obs_cols
    ]

    return {
        "path": str(path),
        "n_obs": int(adata.n_obs),
        "n_vars": int(adata.n_vars),
        "obs_columns": obs_cols,
        "obsm_keys": obsm_keys,
        "layers": layers,
        "has_x_pca": "X_pca" in obsm_keys,
        "sample_key_candidates": sample_candidates,
        "cell_group_key_candidates": cell_group_candidates,
    }


# Register with the FastMCP server; the call has the side-effect of attaching
# the function to ``mcp.list_tools()`` while leaving the module-level
# ``inspect_anndata`` symbol bound to the plain function (so peer tools like
# ``pipeline_run`` can import and call it directly).
mcp.tool(inspect_anndata)
