"""Internal helpers shared across :mod:`patpy_analysis_mcp.tools`.

Keep this module small — anything that only one tool uses belongs in
that tool's file. Functions here are intentionally not decorated with
``@mcp.tool`` so they are not exposed over MCP.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import anndata as ad
import numpy as np
import pandas as pd

# Common obs columns that label a "sample" / "donor" in CellxGene-style data.
SAMPLE_KEY_CANDIDATES = (
    "donor_id",
    "Donor",
    "Donor.ID",
    "patient_id",
    "sample_id",
    "library_id",
)

# Common obs columns that label a "cell type" / "cell group".
CELL_GROUP_KEY_CANDIDATES = (
    "cell_type",
    "cell_type_ontology_term_id",
    "leiden",
    "louvain",
)


def resolve_path(path: str, *, must_exist: bool = True) -> Path:
    """Validate and absolutise ``path``.

    Parameters
    ----------
    path
        File path, either absolute or relative to the cwd of the server.
    must_exist
        If True (default), raise ``FileNotFoundError`` when the resolved
        path does not exist.

    Returns
    -------
    pathlib.Path
        Absolute, resolved path.
    """
    p = Path(path).expanduser().resolve()
    if must_exist and not p.exists():
        raise FileNotFoundError(f"path does not exist: {p}")
    return p


def auto_pick_obs_column(
    columns: Iterable[str], candidates: Iterable[str]
) -> str | None:
    """Return the first ``candidates`` member that is in ``columns`` (else None)."""
    cols = set(columns)
    for c in candidates:
        if c in cols:
            return c
    return None


def sample_level_columns(
    adata: ad.AnnData, sample_key: str, candidate_cols: Iterable[str]
) -> list[str]:
    """Filter ``candidate_cols`` to those that are constant per sample.

    Many CellxGene obs columns (``cell_type``, ``leiden``, etc.) are
    cell-level annotations and would fan out / collapse incorrectly in
    sample-level metadata. This helper keeps only columns that genuinely
    take a single value per sample.
    """
    keep: list[str] = []
    for c in candidate_cols:
        if c not in adata.obs.columns:
            continue
        # observed=True silences the pandas FutureWarning on grouped categoricals.
        n_unique_per_sample = (
            adata.obs.groupby(sample_key, observed=True)[c].nunique()
        )
        if (n_unique_per_sample <= 1).all():
            keep.append(c)
    return keep


def assert_writable(path: Path) -> None:
    """Make sure ``path``'s parent exists; create it if necessary."""
    path.parent.mkdir(parents=True, exist_ok=True)


def array_summary(arr: np.ndarray, name: str) -> dict:
    """Compact summary of a numeric array for tool return values."""
    return {
        "name": name,
        "shape": list(arr.shape),
        "dtype": str(arr.dtype),
        "min": float(np.min(arr)) if arr.size else None,
        "max": float(np.max(arr)) if arr.size else None,
    }


def df_top_n(
    df: pd.DataFrame, by: str, n: int = 5, ascending: bool = False
) -> list[dict]:
    """Return ``df.sort_values(by).head(n)`` as a list-of-dicts (for tool returns)."""
    if by not in df.columns:
        raise KeyError(f"column {by!r} not in DataFrame ({list(df.columns)})")
    return df.sort_values(by, ascending=ascending).head(n).to_dict(orient="records")
