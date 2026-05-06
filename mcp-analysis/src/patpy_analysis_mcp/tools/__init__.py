"""Tool registry for patpy-analysis-mcp.

Each ``_<toolname>.py`` module defines exactly one tool function and
calls ``mcp.tool(<toolname>)`` at module top level to register it on the
:data:`patpy_analysis_mcp.mcp.mcp` singleton. The
:mod:`patpy_analysis_mcp.main` module star-imports this package to
perform that side-effect at CLI startup.

Tools are also re-exported here as plain functions so peer tools (e.g.
``pipeline_run``) can call them directly without going through the MCP
transport layer.
"""

from ._inspect_anndata import inspect_anndata
from ._pipeline_run import pipeline_run
from ._pl_embedding_covariate_heatmap import pl_embedding_covariate_heatmap
from ._pp_preprocess import pp_preprocess
from ._tl_associate_embedding_with_covariates import (
    tl_associate_embedding_with_covariates,
)
from ._tl_sample_representation import tl_sample_representation

__all__ = [
    "inspect_anndata",
    "pipeline_run",
    "pl_embedding_covariate_heatmap",
    "pp_preprocess",
    "tl_associate_embedding_with_covariates",
    "tl_sample_representation",
]
