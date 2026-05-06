"""``pipeline_run`` tool: chain the five fine-grained tools end-to-end."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anndata as ad
import numpy as np
import pandas as pd
import scanpy as sc

from patpy_analysis_mcp._helpers import (
    CELL_GROUP_KEY_CANDIDATES,
    SAMPLE_KEY_CANDIDATES,
    assert_writable,
    auto_pick_obs_column,
    resolve_path,
)
from patpy_analysis_mcp.mcp import mcp

# Re-import the underlying tools so we call them as plain functions. They are
# also still exposed individually over MCP, so an LLM agent can chain them
# manually if it wants finer control / branching.
from patpy_analysis_mcp.tools._pl_embedding_covariate_heatmap import (
    pl_embedding_covariate_heatmap,
)
from patpy_analysis_mcp.tools._pp_preprocess import pp_preprocess
from patpy_analysis_mcp.tools._tl_associate_embedding_with_covariates import (
    tl_associate_embedding_with_covariates,
)
from patpy_analysis_mcp.tools._tl_sample_representation import (
    tl_sample_representation,
)


def _merge_pdatas(pdata_paths: list[Path], out_path: Path) -> Path:
    """Merge multiple sample-level pdatas into one by intersecting obs_names.

    Each input pdata has a single method's embedding in ``obsm``; the
    merged pdata has one obsm key per method (and per ``*_distances`` key).
    """
    pdatas = [sc.read_h5ad(p) for p in pdata_paths]
    if not pdatas:
        raise ValueError("pdata_paths is empty")
    common = pdatas[0].obs_names
    for p in pdatas[1:]:
        common = common.intersection(p.obs_names)
    common = pd.Index(sorted(common))

    merged = ad.AnnData(
        X=np.zeros((len(common), 1), dtype=np.float32),
        obs=pdatas[0].obs.loc[common].copy(),
    )
    merged.obs_names = common.astype(str)
    for p in pdatas:
        sub = p[common]
        for k, v in sub.obsm.items():
            merged.obsm[k] = np.asarray(v)
    merged.write_h5ad(out_path, compression="gzip")
    return out_path


def pipeline_run(
    h5ad_path: str,
    output_dir: str,
    methods: list[str] | None = None,
    sample_key: str | None = None,
    cell_group_key: str | None = None,
    covariates: list[str] | None = None,
    sample_size_threshold: int = 200,
    max_cells: int | None = 40_000,
    n_mds_components: int = 10,
    seed: int = 0,
) -> dict[str, Any]:
    """Run the full breast-cancer-style pipeline end-to-end in one call.

    This convenience tool chains all five fine-grained tools:

      1. ``inspect_anndata``  → resolve sample_key / cell_group_key / covariates
      2. ``pp_preprocess``    → ``output_dir/preprocessed.h5ad``
      3. for each method in ``methods`` (default: Pseudobulk + CellGroupComposition)
         ``tl_sample_representation`` → ``output_dir/pdata_<method>.h5ad``
      4. merge per-method pdatas → ``output_dir/pdata.h5ad`` (one obsm per method)
      5. for each method
         ``tl_associate_embedding_with_covariates`` → ``output_dir/assoc_<method>.csv``
         ``pl_embedding_covariate_heatmap``         → ``output_dir/heatmap_<method>.png``

    For more control (branching, early stopping, custom params per method),
    call the underlying tools directly instead.

    Parameters
    ----------
    h5ad_path
        Input ``.h5ad`` (e.g. the path returned by ``cellxgene_download_dataset``).
    output_dir
        Directory for all artifacts. Created if absent.
    methods
        Methods to compute. Defaults to
        ``["Pseudobulk", "CellGroupComposition"]``.
    sample_key, cell_group_key
        Override auto-detection. If ``None``, the first matching column from
        the canonical CellxGene schema (``donor_id``, ``cell_type``, …) is used.
    covariates
        Categorical obs columns to test. If ``None``, defaults to the
        sample-level subset of ``("disease", "sex", "development_stage", "assay")``.
    sample_size_threshold, max_cells, n_mds_components, seed
        Forwarded to the underlying tools.

    Returns
    -------
    dict
        Manifest of every artifact written (``preprocessed_h5ad``,
        ``pdata_h5ad``, ``per_method`` list with ``method`` + ``obsm_key`` +
        ``assoc_csv`` + ``heatmap_png`` + top hits), plus the
        auto-detected ``sample_key`` / ``cell_group_key`` / ``covariates``.
    """
    methods = list(methods or ["Pseudobulk", "CellGroupComposition"])

    in_path = resolve_path(h5ad_path, must_exist=True)
    out_dir = resolve_path(output_dir, must_exist=False)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) Auto-detect keys if not provided.
    adata_peek = ad.read_h5ad(in_path, backed="r")
    obs_cols = list(adata_peek.obs.columns)
    sample_key = sample_key or auto_pick_obs_column(obs_cols, SAMPLE_KEY_CANDIDATES)
    cell_group_key = cell_group_key or auto_pick_obs_column(
        obs_cols, CELL_GROUP_KEY_CANDIDATES
    )
    if sample_key is None:
        raise ValueError(
            "Could not auto-detect sample_key; pass it explicitly. "
            f"Tried: {SAMPLE_KEY_CANDIDATES}; obs has: {obs_cols[:20]}..."
        )
    needs_cell_group = "CellGroupComposition" in methods
    if needs_cell_group and cell_group_key is None:
        raise ValueError(
            "CellGroupComposition needs cell_group_key; pass it explicitly. "
            f"Tried: {CELL_GROUP_KEY_CANDIDATES}; obs has: {obs_cols[:20]}..."
        )

    # 2) Preprocess.
    pre_path = out_dir / "preprocessed.h5ad"
    pre_info = pp_preprocess(
        h5ad_path=str(in_path),
        out_path=str(pre_path),
        sample_key=sample_key,
        cell_group_key=cell_group_key,
        sample_size_threshold=sample_size_threshold,
        max_cells=max_cells,
        run_pca="X_pca" not in adata_peek.obsm,
        seed=seed,
    )

    # 3) Per-method sample representation.
    per_method_pdata_paths: list[Path] = []
    rep_infos: list[dict[str, Any]] = []
    for method in methods:
        pdata_method_path = out_dir / f"pdata_{method.lower()}.h5ad"
        info = tl_sample_representation(
            h5ad_path=str(pre_path),
            out_path=str(pdata_method_path),
            method=method,
            sample_key=sample_key,
            cell_group_key=cell_group_key,
            n_mds_components=n_mds_components,
            seed=seed,
        )
        rep_infos.append(info)
        per_method_pdata_paths.append(pdata_method_path)

    # 4) Merge per-method pdatas into one.
    merged_pdata_path = out_dir / "pdata.h5ad"
    _merge_pdatas(per_method_pdata_paths, merged_pdata_path)

    # 5) Resolve covariates (sample-level, categorical, >=2 levels).
    pdata = sc.read_h5ad(merged_pdata_path)
    if covariates is None:
        candidates = ["disease", "sex", "development_stage", "assay"]
        covariates = [
            c for c in candidates
            if c in pdata.obs.columns
            and pdata.obs[c].astype(str).nunique() >= 2
            and pdata.obs[c].astype(str).nunique() < pdata.n_obs
        ]
    if not covariates:
        raise ValueError(
            "No usable covariates left after filtering; "
            f"pdata.obs columns are {list(pdata.obs.columns)}"
        )

    # 6) Associate + plot per method.
    per_method_artifacts: list[dict[str, Any]] = []
    for info in rep_infos:
        method = info["method"]
        obsm_key = info["obsm_key"]
        assoc_csv = out_dir / f"assoc_{method.lower()}.csv"
        heatmap_png = out_dir / f"heatmap_{method.lower()}.png"

        assoc_info = tl_associate_embedding_with_covariates(
            pdata_path=str(merged_pdata_path),
            covariates=covariates,
            obsm_key=obsm_key,
            out_csv=str(assoc_csv),
            n_components=info["n_mds_components"],
            component_label="PC",
        )
        plot_info = pl_embedding_covariate_heatmap(
            assoc_csv=str(assoc_csv),
            out_png=str(heatmap_png),
            title=f"Covariate associations: {method}",
        )
        per_method_artifacts.append({
            "method": method,
            "obsm_key": obsm_key,
            "pdata_method": str(per_method_pdata_paths[len(per_method_artifacts)]),
            "assoc_csv": assoc_info["out_csv"],
            "heatmap_png": plot_info["out_png"],
            "top_hits": assoc_info["top_hits"],
        })

    return {
        "input": str(in_path),
        "output_dir": str(out_dir),
        "sample_key": sample_key,
        "cell_group_key": cell_group_key,
        "covariates": covariates,
        "preprocessed_h5ad": pre_info["out_path"],
        "pdata_h5ad": str(merged_pdata_path),
        "per_method": per_method_artifacts,
    }


mcp.tool(pipeline_run)
