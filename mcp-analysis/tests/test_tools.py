"""End-to-end unit tests that exercise each MCP tool against a synthetic AnnData.

The fixture ``synthetic_anndata_path`` (see ``conftest.py``) builds a
1000-cell × 200-gene Poisson dataset with 5 donors / 4 cell types — small
enough to run every tool in well under a second, large enough that
``patpy.tl.Pseudobulk`` and ``patpy.tl.CellGroupComposition`` produce
non-degenerate distance matrices and ``MDS`` can return at least 4
components.
"""

from __future__ import annotations

import pytest

# All of these hard-depend on patpy + scanpy + matplotlib + sklearn. If any
# is missing we skip the whole module rather than fail noisily, so the test
# matrix can run on minimal Python images that don't have the analysis stack.
pytest.importorskip("patpy")
pytest.importorskip("scanpy")
pytest.importorskip("matplotlib")
pytest.importorskip("sklearn")

import pandas as pd

from patpy_analysis_mcp.tools import (
    inspect_anndata,
    pipeline_run,
    pl_embedding_covariate_heatmap,
    pp_preprocess,
    tl_associate_embedding_with_covariates,
    tl_sample_representation,
)


def test_inspect_anndata_reports_schema(synthetic_anndata_path):
    info = inspect_anndata(str(synthetic_anndata_path))

    assert info["n_obs"] == 1000
    assert info["n_vars"] == 200
    assert "donor_id" in info["obs_columns"]
    assert "cell_type" in info["obs_columns"]
    sample_names = {c["name"] for c in info["sample_key_candidates"]}
    cell_group_names = {c["name"] for c in info["cell_group_key_candidates"]}
    assert "donor_id" in sample_names
    assert "cell_type" in cell_group_names
    # synthetic data has no PCA pre-computed
    assert info["has_x_pca"] is False


def test_pp_preprocess_runs_pca_and_writes_h5ad(synthetic_anndata_path, workspace):
    out_path = workspace / "preprocessed.h5ad"
    res = pp_preprocess(
        h5ad_path=str(synthetic_anndata_path),
        out_path=str(out_path),
        sample_key="donor_id",
        cell_group_key="cell_type",
        sample_size_threshold=50,
        max_cells=None,
        run_pca=True,
        n_top_genes=100,
        n_pcs=10,
    )

    assert out_path.exists()
    assert res["sample_key"] == "donor_id"
    assert res["pca_done"] is True
    assert res["n_pcs"] == 10

    # Reload and verify the new file has X_pca.
    import anndata as ad

    adata = ad.read_h5ad(out_path)
    assert "X_pca" in adata.obsm
    assert adata.obsm["X_pca"].shape[1] == 10
    assert adata.obs["donor_id"].nunique() == 5


@pytest.mark.parametrize("method", ["Pseudobulk", "CellGroupComposition", "RandomVector"])
def test_tl_sample_representation_writes_pdata(
    method, synthetic_anndata_path, workspace
):
    pre_path = workspace / "preprocessed.h5ad"
    pp_preprocess(
        h5ad_path=str(synthetic_anndata_path),
        out_path=str(pre_path),
        sample_key="donor_id",
        cell_group_key="cell_type",
        sample_size_threshold=50,
        max_cells=None,
        run_pca=True,
        n_top_genes=100,
        n_pcs=10,
    )

    out_path = workspace / f"pdata_{method.lower()}.h5ad"
    res = tl_sample_representation(
        h5ad_path=str(pre_path),
        out_path=str(out_path),
        method=method,
        sample_key="donor_id",
        cell_group_key="cell_type",
        n_mds_components=3,
    )

    assert out_path.exists()
    assert res["method"] == method
    assert res["n_samples"] == 5
    assert res["n_mds_components"] == 3

    import anndata as ad

    pdata = ad.read_h5ad(out_path)
    assert pdata.n_obs == 5
    assert res["obsm_key"] in pdata.obsm
    assert pdata.obsm[res["obsm_key"]].shape == (5, 3)
    assert "disease" in pdata.obs.columns


def test_tl_associate_writes_csv_with_PC_column(synthetic_anndata_path, workspace):
    pre_path = workspace / "preprocessed.h5ad"
    pp_preprocess(
        h5ad_path=str(synthetic_anndata_path),
        out_path=str(pre_path),
        sample_key="donor_id",
        cell_group_key="cell_type",
        sample_size_threshold=50,
        max_cells=None,
        run_pca=True,
        n_top_genes=100,
        n_pcs=10,
    )
    pdata_path = workspace / "pdata_pseudobulk.h5ad"
    rep = tl_sample_representation(
        h5ad_path=str(pre_path),
        out_path=str(pdata_path),
        method="Pseudobulk",
        sample_key="donor_id",
        cell_group_key="cell_type",
        n_mds_components=3,
    )

    assoc_csv = workspace / "assoc.csv"
    res = tl_associate_embedding_with_covariates(
        pdata_path=str(pdata_path),
        covariates=["disease", "sex"],
        obsm_key=rep["obsm_key"],
        out_csv=str(assoc_csv),
        n_components=3,
    )

    assert assoc_csv.exists()
    df = pd.read_csv(assoc_csv)
    # The default component_label="PC" must be honored so the heatmap tool
    # finds the column it expects.
    assert "PC" in df.columns
    assert set(df["covariate"].unique()) == {"disease", "sex"}
    assert res["n_rows"] == 6
    assert isinstance(res["top_hits"], list)


def test_pl_heatmap_writes_png(synthetic_anndata_path, workspace):
    pre_path = workspace / "preprocessed.h5ad"
    pp_preprocess(
        h5ad_path=str(synthetic_anndata_path),
        out_path=str(pre_path),
        sample_key="donor_id",
        cell_group_key="cell_type",
        sample_size_threshold=50,
        max_cells=None,
        run_pca=True,
        n_top_genes=100,
        n_pcs=10,
    )
    pdata_path = workspace / "pdata_pseudobulk.h5ad"
    rep = tl_sample_representation(
        h5ad_path=str(pre_path),
        out_path=str(pdata_path),
        method="Pseudobulk",
        sample_key="donor_id",
        cell_group_key="cell_type",
        n_mds_components=3,
    )
    assoc_csv = workspace / "assoc.csv"
    tl_associate_embedding_with_covariates(
        pdata_path=str(pdata_path),
        covariates=["disease", "sex"],
        obsm_key=rep["obsm_key"],
        out_csv=str(assoc_csv),
        n_components=3,
    )

    out_png = workspace / "heatmap.png"
    res = pl_embedding_covariate_heatmap(
        assoc_csv=str(assoc_csv),
        out_png=str(out_png),
        title="test",
    )

    assert out_png.exists() and out_png.stat().st_size > 0
    assert res["n_covariates"] == 2
    assert res["n_components"] == 3


def test_pipeline_run_writes_full_manifest(synthetic_anndata_path, workspace):
    out_dir = workspace / "pipeline"
    res = pipeline_run(
        h5ad_path=str(synthetic_anndata_path),
        output_dir=str(out_dir),
        methods=["Pseudobulk", "CellGroupComposition"],
        sample_key="donor_id",
        cell_group_key="cell_type",
        covariates=["disease", "sex"],
        sample_size_threshold=50,
        max_cells=None,
        n_mds_components=3,
    )

    assert (out_dir / "preprocessed.h5ad").exists()
    assert (out_dir / "pdata.h5ad").exists()
    assert (out_dir / "pdata_pseudobulk.h5ad").exists()
    assert (out_dir / "pdata_cellgroupcomposition.h5ad").exists()
    assert (out_dir / "assoc_pseudobulk.csv").exists()
    assert (out_dir / "assoc_cellgroupcomposition.csv").exists()
    assert (out_dir / "heatmap_pseudobulk.png").exists()
    assert (out_dir / "heatmap_cellgroupcomposition.png").exists()

    assert res["sample_key"] == "donor_id"
    assert res["cell_group_key"] == "cell_type"
    assert {m["method"] for m in res["per_method"]} == {
        "Pseudobulk",
        "CellGroupComposition",
    }
