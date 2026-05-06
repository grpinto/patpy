"""``tl_associate_embedding_with_covariates`` tool: ANOVA / Kruskal per (covariate, PC)."""

from __future__ import annotations

from typing import Any, Literal

import scanpy as sc

from patpy_analysis_mcp._helpers import assert_writable, df_top_n, resolve_path
from patpy_analysis_mcp.mcp import mcp


def tl_associate_embedding_with_covariates(
    pdata_path: str,
    covariates: list[str],
    obsm_key: str,
    out_csv: str,
    n_components: int = 10,
    test: Literal["anova", "kruskal"] = "anova",
    component_label: str = "PC",
) -> dict[str, Any]:
    """Test each component of a sample-level embedding against obs covariates.

    Wraps ``patpy.tl.associate_embedding_with_covariates`` (see
    ``src/patpy/skills/evaluation/SKILL.md``). For every
    (covariate, component) pair, runs a one-way ANOVA (default) or
    Kruskal-Wallis test and returns a tidy DataFrame.

    Important: ``component_label`` defaults to ``"PC"`` so the output
    matches what ``pl_embedding_covariate_heatmap`` expects (``pc_col="PC"``).
    The underlying patpy function would otherwise auto-derive
    ``"Component"`` for non-PCA obsm keys, which silently breaks the
    plotting tool downstream.

    Parameters
    ----------
    pdata_path
        Path to a sample-level ``.h5ad`` with ``adata.obsm[obsm_key]``
        (typically the output of ``tl_sample_representation``).
    covariates
        Categorical columns in ``pdata.obs`` to test against.
    obsm_key
        Key in ``pdata.obsm`` whose columns are the components to test
        (e.g. ``"X_pseudobulk"`` after ``tl_sample_representation``).
    out_csv
        Where to write the tidy association DataFrame.
    n_components
        Number of components from ``obsm_key`` to test.
    test
        ``"anova"`` for one-way F-test, ``"kruskal"`` for Kruskal-Wallis.
    component_label
        Prefix used to name component columns in the output. Default
        ``"PC"`` is what the heatmap tool expects.

    Returns
    -------
    dict
        ``out_csv`` (absolute), ``n_rows``, ``n_covariates``, ``n_components``,
        and ``top_hits`` — the 5 most significant ``(covariate, PC)`` pairs
        by ``-log10p``.
    """
    import patpy

    pdata_path_resolved = resolve_path(pdata_path, must_exist=True)
    out_csv_resolved = resolve_path(out_csv, must_exist=False)
    assert_writable(out_csv_resolved)

    pdata = sc.read_h5ad(pdata_path_resolved)
    if obsm_key not in pdata.obsm:
        raise ValueError(
            f"obsm_key={obsm_key!r} not in pdata.obsm "
            f"(available: {list(pdata.obsm.keys())})"
        )
    missing = [c for c in covariates if c not in pdata.obs.columns]
    if missing:
        raise ValueError(
            f"covariates not in pdata.obs: {missing}. "
            f"Available: {list(pdata.obs.columns)}"
        )

    assoc = patpy.tl.associate_embedding_with_covariates(
        pdata,
        covariates=covariates,
        obsm_key=obsm_key,
        n_components=n_components,
        test=test,
        component_label=component_label,
    )
    assoc.to_csv(out_csv_resolved, index=False)

    return {
        "out_csv": str(out_csv_resolved),
        "n_rows": int(len(assoc)),
        "n_covariates": len(covariates),
        "n_components": int(n_components),
        "test": test,
        "component_label": component_label,
        "top_hits": df_top_n(assoc, by="-log10p", n=5),
    }


mcp.tool(tl_associate_embedding_with_covariates)
