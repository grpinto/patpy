"""``tl_sample_representation`` tool: build a sample-level embedding."""

from __future__ import annotations

from typing import Any, Literal

import anndata as ad
import numpy as np
import pandas as pd
import scanpy as sc
from sklearn.manifold import MDS

from patpy_analysis_mcp._helpers import (
    assert_writable,
    resolve_path,
    sample_level_columns,
)
from patpy_analysis_mcp.mcp import mcp

# Default sample-level metadata columns we attempt to surface.
_DEFAULT_META_COLS = (
    "disease",
    "tissue",
    "sex",
    "self_reported_ethnicity",
    "development_stage",
    "assay",
    "suspension_type",
)

_METHODS = ("Pseudobulk", "CellGroupComposition", "RandomVector")
_METHOD_OBSM_KEYS = {
    "Pseudobulk": "X_pseudobulk",
    "CellGroupComposition": "X_composition",
    "RandomVector": "X_random",
}
_METHOD_DIST_KEYS = {
    "Pseudobulk": "X_pseudobulk_distances",
    "CellGroupComposition": "X_composition_distances",
    "RandomVector": "X_random_distances",
}


def tl_sample_representation(
    h5ad_path: str,
    out_path: str,
    method: Literal["Pseudobulk", "CellGroupComposition", "RandomVector"],
    sample_key: str,
    cell_group_key: str | None = None,
    layer: str | None = "X_pca",
    n_mds_components: int = 10,
    metadata_columns: list[str] | None = None,
    seed: int = 0,
) -> dict[str, Any]:
    """Compute a sample-level embedding via a patpy.tl method, project with MDS.

    Wraps the canonical ``patpy.tl`` protocol from
    ``src/patpy/skills/sample_representation/SKILL.md``::

        m = MethodClass(sample_key, cell_group_key, layer, seed)
        m.prepare_anndata(adata)
        D = m.calculate_distance_matrix()

    Then projects the resulting square distance matrix to
    ``n_mds_components`` coordinates with classical MDS so the heatmap's
    "PC" axis is meaningful (the raw distance matrix is ``(n×n)`` and
    cannot be passed straight to ``associate_embedding_with_covariates``).

    Output is a sample-level AnnData (``pdata``) with:
    - ``X`` = a 1-column zero matrix (placeholder; embeddings live in obsm)
    - ``obs`` = the constant-per-sample subset of the input ``adata.obs``
    - ``obsm[<method>]`` = ``(n_samples, n_mds_components)`` MDS coordinates
    - ``obsm[<method>_distances]`` = ``(n_samples, n_samples)`` distances

    Parameters
    ----------
    h5ad_path
        Input cell-level ``.h5ad`` (e.g. the output of ``pp_preprocess``).
    out_path
        Where to write the sample-level AnnData. Saved with gzip
        compression because it is small (one row per sample).
    method
        One of ``"Pseudobulk"``, ``"CellGroupComposition"``,
        ``"RandomVector"`` — the three dependency-free baselines from the
        ``sample_representation`` skill.
    sample_key
        Column in ``adata.obs`` identifying samples.
    cell_group_key
        Column for cell types. Required for ``CellGroupComposition``;
        ignored by ``RandomVector``; optional for ``Pseudobulk`` (pass
        ``None`` for un-grouped pseudobulk).
    layer
        Feature source for ``Pseudobulk`` (defaults to ``"X_pca"``);
        ignored by the other two methods.
    n_mds_components
        Number of MDS coordinates. Capped at ``n_samples - 1``.
    metadata_columns
        Subset of ``adata.obs`` columns to carry over to ``pdata.obs``.
        Defaults to ``("disease", "tissue", "sex", "self_reported_ethnicity",
        "development_stage", "assay", "suspension_type")`` filtered to
        those that are constant per sample.
    seed
        Random seed (used by all three methods for reproducibility).

    Returns
    -------
    dict
        ``out_path`` (absolute), ``method``, ``obsm_key``,
        ``distances_obsm_key``, ``n_samples``, ``n_mds_components``,
        ``sample_metadata_columns``.
    """
    import patpy
    import patpy.tl

    if method not in _METHODS:
        raise ValueError(f"method must be one of {_METHODS}, got {method!r}")

    in_path = resolve_path(h5ad_path, must_exist=True)
    out_path_resolved = resolve_path(out_path, must_exist=False)
    assert_writable(out_path_resolved)

    adata = sc.read_h5ad(in_path)
    if sample_key not in adata.obs.columns:
        raise ValueError(f"sample_key={sample_key!r} not in adata.obs")

    # Build the method instance per the skill's protocol.
    if method == "Pseudobulk":
        m = patpy.tl.Pseudobulk(
            sample_key=sample_key,
            cell_group_key=cell_group_key,  # may be None
            layer=layer,
            seed=seed,
        )
    elif method == "CellGroupComposition":
        if cell_group_key is None:
            raise ValueError(
                "CellGroupComposition requires cell_group_key (it builds a "
                "fraction vector across cell groups)."
            )
        m = patpy.tl.CellGroupComposition(
            sample_key=sample_key,
            cell_group_key=cell_group_key,
            seed=seed,
        )
    else:  # RandomVector
        m = patpy.tl.RandomVector(
            sample_key=sample_key,
            cell_group_key=cell_group_key or sample_key,
            seed=seed,
        )

    m.prepare_anndata(adata)
    D = np.asarray(m.calculate_distance_matrix())
    samples = list(m.samples)

    # MDS projection so downstream tools see a (n, k) embedding, not (n, n).
    n_comp = max(1, min(n_mds_components, len(samples) - 1))
    mds_coords = MDS(
        n_components=n_comp,
        dissimilarity="precomputed",
        random_state=seed,
        normalized_stress="auto",
    ).fit_transform(D)

    # Carry sample-level metadata across.
    candidate_cols = list(metadata_columns or _DEFAULT_META_COLS)
    keep_cols = sample_level_columns(adata, sample_key, candidate_cols)
    meta = patpy.pp.extract_metadata(
        adata, sample_key=sample_key, columns=keep_cols
    ).loc[samples]

    pdata = ad.AnnData(
        X=np.zeros((len(samples), 1), dtype=np.float32),
        obs=meta,
    )
    pdata.obs_names = pd.Index([str(s) for s in samples])
    obsm_key = _METHOD_OBSM_KEYS[method]
    dist_key = _METHOD_DIST_KEYS[method]
    pdata.obsm[obsm_key] = np.asarray(mds_coords, dtype=np.float32)
    pdata.obsm[dist_key] = np.asarray(D, dtype=np.float32)

    pdata.write_h5ad(out_path_resolved, compression="gzip")

    return {
        "out_path": str(out_path_resolved),
        "method": method,
        "obsm_key": obsm_key,
        "distances_obsm_key": dist_key,
        "n_samples": len(samples),
        "n_mds_components": n_comp,
        "sample_metadata_columns": keep_cols,
    }


mcp.tool(tl_sample_representation)
