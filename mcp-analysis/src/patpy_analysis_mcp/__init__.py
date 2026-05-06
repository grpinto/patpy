"""patpy-analysis-mcp: MCP server for sample-level single-cell analysis.

Built with the BioContextAI MCP server cookiecutter conventions
(https://github.com/biocontext-ai/mcp-server-cookiecutter): one tool per
file under :mod:`patpy_analysis_mcp.tools`, a shared
:data:`patpy_analysis_mcp.mcp.mcp` FastMCP instance, and a click-based
CLI in :mod:`patpy_analysis_mcp.main`.

This server wraps the ``patpy`` library so an LLM agent can drive a
donor-level analysis end-to-end on a downloaded AnnData, chaining after
``lueckenlab/patpy-mcp`` (dataset discovery) and
``biocontext-ai/anndata-mcp`` (AnnData inspection).
"""

from importlib.metadata import PackageNotFoundError, version

from patpy_analysis_mcp.main import run_app
from patpy_analysis_mcp.mcp import mcp

try:
    __version__ = version("patpy-analysis-mcp")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = ["__version__", "mcp", "run_app"]


if __name__ == "__main__":
    run_app()
