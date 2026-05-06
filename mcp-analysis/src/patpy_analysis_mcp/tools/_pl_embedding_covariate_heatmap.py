"""``pl_embedding_covariate_heatmap`` tool: render the heatmap from an assoc CSV."""

from __future__ import annotations

from typing import Any

import matplotlib

matplotlib.use("Agg")  # safe default for an MCP server (no display)
import matplotlib.pyplot as plt
import pandas as pd

from patpy_analysis_mcp._helpers import assert_writable, resolve_path
from patpy_analysis_mcp.mcp import mcp


def pl_embedding_covariate_heatmap(
    assoc_csv: str,
    out_png: str,
    title: str | None = None,
    pc_col: str = "PC",
    covariate_col: str = "covariate",
    value_col: str = "-log10p",
    p_thresh: float = 0.05,
    dpi: int = 150,
) -> dict[str, Any]:
    """Render an embedding-covariate association heatmap.

    Wraps ``patpy.pl.embedding_covariate_heatmap`` (see
    ``src/patpy/skills/plotting/SKILL.md``).

    The default ``pc_col="PC"`` matches what
    ``tl_associate_embedding_with_covariates`` writes when
    ``component_label="PC"`` is used (its default in this server).

    Parameters
    ----------
    assoc_csv
        Tidy association CSV produced by
        ``tl_associate_embedding_with_covariates``.
    out_png
        Where to write the PNG.
    title
        Optional figure title. Defaults to the CSV stem.
    pc_col, covariate_col, value_col
        Column names in the CSV; defaults match this server's other tools.
    p_thresh
        p-value threshold used to draw significance markers (``*``, ``**``,
        ``***``).
    dpi
        Figure resolution.

    Returns
    -------
    dict
        ``out_png`` (absolute), ``n_covariates``, ``n_components``, and the
        ``title`` used.
    """
    import patpy

    csv_path = resolve_path(assoc_csv, must_exist=True)
    png_path = resolve_path(out_png, must_exist=False)
    assert_writable(png_path)

    assoc_df = pd.read_csv(csv_path)
    for col in (pc_col, covariate_col, value_col):
        if col not in assoc_df.columns:
            raise ValueError(
                f"column {col!r} not in {csv_path.name} "
                f"(available: {list(assoc_df.columns)})"
            )

    used_title = title or csv_path.stem
    fig = patpy.pl.embedding_covariate_heatmap(
        assoc_df,
        covariate_col=covariate_col,
        pc_col=pc_col,
        value_col=value_col,
        p_thresh=p_thresh,
        title=used_title,
        return_fig=True,
    )
    fig.savefig(png_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)

    return {
        "out_png": str(png_path),
        "n_covariates": int(assoc_df[covariate_col].nunique()),
        "n_components": int(assoc_df[pc_col].nunique()),
        "title": used_title,
    }


mcp.tool(pl_embedding_covariate_heatmap)
