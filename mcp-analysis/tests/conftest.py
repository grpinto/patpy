"""Shared pytest fixtures for the patpy-analysis-mcp test suite."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(scope="session")
def synthetic_anndata_path(tmp_path_factory):
    """Return a path to a tiny synthetic ``.h5ad`` with all the columns our tools need.

    The dataset has 5 donors × 4 cell types × ~50 cells = 1000 cells, and
    ~200 genes. Each donor has consistent ``disease`` / ``sex`` /
    ``development_stage`` / ``assay`` annotations (so they survive the
    sample-level metadata projection). Counts are Poisson-distributed so
    ``patpy.pp.is_count_data`` returns True and the canonical
    normalize → log → HVG → scale → PCA path runs.
    """
    pytest.importorskip("anndata")
    pytest.importorskip("scanpy")
    import anndata as ad

    rng = np.random.default_rng(0)

    n_donors, n_types, n_cells_per = 5, 4, 50
    n_cells = n_donors * n_types * n_cells_per
    n_genes = 200

    donor_ids: list[str] = []
    cell_types: list[str] = []
    diseases: list[str] = []
    sexes: list[str] = []
    stages: list[str] = []
    assays: list[str] = []
    tissues: list[str] = []
    for d in range(n_donors):
        for t in range(n_types):
            for _ in range(n_cells_per):
                donor_ids.append(f"donor_{d}")
                cell_types.append(f"cell_type_{t}")
                diseases.append("breast cancer" if d % 2 == 0 else "normal")
                sexes.append("female" if d < 3 else "male")
                stages.append(f"adult_{d % 2}")
                assays.append("10x 3' v3")
                tissues.append("breast")

    obs = pd.DataFrame(
        {
            "donor_id": pd.Categorical(donor_ids),
            "cell_type": pd.Categorical(cell_types),
            "disease": pd.Categorical(diseases),
            "sex": pd.Categorical(sexes),
            "development_stage": pd.Categorical(stages),
            "assay": pd.Categorical(assays),
            "tissue": pd.Categorical(tissues),
        }
    )
    var = pd.DataFrame({"gene_id": [f"g{i}" for i in range(n_genes)]}).set_index(
        "gene_id"
    )

    # Cell-type-specific Poisson means so PCA / pseudobulk pick up structure.
    type_means = rng.uniform(0.2, 5.0, size=(n_types, n_genes))
    cell_type_idx = np.array([int(c.split("_")[-1]) for c in cell_types])
    X = rng.poisson(type_means[cell_type_idx]).astype(np.float32)

    adata = ad.AnnData(X=X, obs=obs, var=var)
    adata.obs_names = pd.Index([f"cell_{i}" for i in range(n_cells)])

    out_path = tmp_path_factory.mktemp("data") / "synthetic.h5ad"
    adata.write_h5ad(out_path, compression="gzip")
    return Path(out_path)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Per-test scratch directory for tool outputs."""
    return tmp_path
