"""``pp_preprocess`` tool: apply patpy.pp filtering and (optionally) PCA."""

from __future__ import annotations

from typing import Any

import scanpy as sc

from patpy_analysis_mcp._helpers import assert_writable, resolve_path
from patpy_analysis_mcp.mcp import mcp


def pp_preprocess(
    h5ad_path: str,
    out_path: str,
    sample_key: str,
    cell_group_key: str | None = None,
    sample_size_threshold: int = 200,
    max_cells: int | None = 40_000,
    run_pca: bool = True,
    n_top_genes: int = 2_000,
    n_pcs: int = 30,
    seed: int = 0,
) -> dict[str, Any]:
    """Filter small samples, optionally subsample, and run a standard PCA.

    Implements the canonical preprocessing pipeline from
    ``src/patpy/skills/preprocessing/SKILL.md``:

    1. ``patpy.pp.filter_small_samples`` (drop donors with < threshold cells)
    2. ``sc.pp.subsample`` if more than ``max_cells`` remain (preserves
       per-donor distribution since step 1 already filtered)
    3. (optional) ``sc.pp.normalize_total`` + ``log1p`` if ``X`` looks like
       count data, ``sc.pp.highly_variable_genes`` (flavor=``"seurat"``),
       subset to HVG, ``sc.pp.scale`` (max_value=10), ``sc.tl.pca``

    Note on ``filter_small_cell_groups``: the patpy filter requires every
    cell type to be present in every sample with >= N cells, which is
    incompatible with ``CellGroupComposition`` (it needs the global cell-
    type set). This tool deliberately does NOT call
    ``filter_small_cell_groups``; if you want it, do it yourself before
    calling this tool.

    Parameters
    ----------
    h5ad_path
        Input ``.h5ad`` file path.
    out_path
        Where to write the preprocessed AnnData (``.h5ad``).
    sample_key
        Column in ``adata.obs`` that identifies samples / donors.
    cell_group_key
        Column in ``adata.obs`` for cell types. Used only for diagnostic
        counts in the return dict; not required for the filtering itself.
    sample_size_threshold
        Drop samples with fewer than this many cells (default 200).
    max_cells
        If non-None, ``sc.pp.subsample`` to this many cells after sample
        filtering. Pass ``None`` to disable subsampling.
    run_pca
        If True, run normalization + HVG + scale + PCA so that
        ``adata.obsm['X_pca']`` is populated for downstream Pseudobulk.
    n_top_genes
        HVG count for the (optional) PCA step.
    n_pcs
        Number of principal components for the (optional) PCA step.
    seed
        Random seed for the (optional) ``sc.pp.subsample``.

    Returns
    -------
    dict
        ``out_path`` (absolute), ``sample_key``, ``cell_group_key``, and a
        nested ``counts`` block with ``n_obs`` / ``n_samples`` /
        ``n_cell_groups`` after each filter step. Plus ``pca_done`` and
        ``n_pcs`` if PCA was run.
    """
    import patpy

    in_path = resolve_path(h5ad_path, must_exist=True)
    out_path_resolved = resolve_path(out_path, must_exist=False)
    assert_writable(out_path_resolved)

    adata = sc.read_h5ad(in_path)

    if sample_key not in adata.obs.columns:
        raise ValueError(
            f"sample_key={sample_key!r} not in adata.obs.columns "
            f"(available: {list(adata.obs.columns)[:20]}...)"
        )
    if cell_group_key is not None and cell_group_key not in adata.obs.columns:
        raise ValueError(
            f"cell_group_key={cell_group_key!r} not in adata.obs.columns"
        )

    def _counts(a):
        return {
            "n_obs": int(a.n_obs),
            "n_vars": int(a.n_vars),
            "n_samples": int(a.obs[sample_key].nunique()),
            "n_cell_groups": int(a.obs[cell_group_key].nunique())
            if cell_group_key is not None
            else None,
        }

    counts: dict[str, Any] = {"input": _counts(adata)}

    adata = patpy.pp.filter_small_samples(
        adata, sample_key=sample_key, sample_size_threshold=sample_size_threshold
    )
    counts["after_filter_small_samples"] = _counts(adata)

    if max_cells is not None and adata.n_obs > max_cells:
        sc.pp.subsample(adata, n_obs=max_cells, random_state=seed)
        counts["after_subsample"] = _counts(adata)
        # Re-apply with a relaxed threshold so heavily down-sampled donors
        # don't disappear silently.
        adata = patpy.pp.filter_small_samples(
            adata,
            sample_key=sample_key,
            sample_size_threshold=max(20, sample_size_threshold // 10),
        )
        counts["after_final_filter"] = _counts(adata)

    pca_info: dict[str, Any] = {"pca_done": False, "n_pcs": None}
    if run_pca and "X_pca" not in adata.obsm:
        if patpy.pp.is_count_data(adata.X):
            sc.pp.normalize_total(adata, target_sum=1e4)
            sc.pp.log1p(adata)
        sc.pp.highly_variable_genes(adata, n_top_genes=n_top_genes, flavor="seurat")
        adata = adata[:, adata.var["highly_variable"]].copy()
        sc.pp.scale(adata, max_value=10)
        sc.tl.pca(adata, n_comps=n_pcs)
        pca_info = {"pca_done": True, "n_pcs": int(adata.obsm["X_pca"].shape[1])}
    elif "X_pca" in adata.obsm:
        pca_info = {
            "pca_done": False,
            "n_pcs": int(adata.obsm["X_pca"].shape[1]),
            "note": "X_pca was already present, skipped re-running PCA",
        }

    adata.write_h5ad(out_path_resolved, compression="gzip")

    return {
        "out_path": str(out_path_resolved),
        "sample_key": sample_key,
        "cell_group_key": cell_group_key,
        "counts": counts,
        **pca_info,
    }


mcp.tool(pp_preprocess)
