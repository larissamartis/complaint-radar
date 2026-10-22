"""Data and score drift with the Population Stability Index (PSI), a standard model-monitoring measure in banking.

PSI = sum((actual% - expected%) * ln(actual% / expected%)). Common reading: < 0.10 stable, 0.10-0.25 moderate
shift (watch), > 0.25 significant shift (investigate / consider retraining).
"""

import numpy as np
import pandas as pd

EPS = 1e-4


def psi(expected: dict[str, float], actual: dict[str, float]) -> float:
    keys = set(expected) | set(actual)
    e = np.array([max(expected.get(k, 0.0), EPS) for k in keys])
    a = np.array([max(actual.get(k, 0.0), EPS) for k in keys])
    e, a = e / e.sum(), a / a.sum()
    return float(np.sum((a - e) * np.log(a / e)))


def score_psi(reference_quantiles: list[float], scores: np.ndarray) -> float:
    """PSI of a score distribution against the reference deciles (each holds ~10% of reference scores)."""
    edges = np.unique(np.asarray(reference_quantiles, dtype=float))
    if len(edges) < 3 or len(scores) == 0:
        return float("nan")
    inner = edges[1:-1]
    expected_counts = np.diff(np.searchsorted(reference_quantiles, edges, side="left"))  # deciles merged by ties
    expected = {str(i): float(c) for i, c in enumerate(expected_counts) if c > 0}
    bins = np.searchsorted(inner, np.asarray(scores, dtype=float), side="right")
    actual = pd.Series(bins).value_counts(normalize=True)
    return psi(expected, {str(k): float(v) for k, v in actual.items()})


def status(value: float) -> str:
    if np.isnan(value):
        return "insufficient_data"
    return "stable" if value < 0.10 else "moderate" if value < 0.25 else "significant"


def drift_report(metadata: dict, products: pd.Series, scores: np.ndarray, min_rows: int = 200) -> list[dict]:
    rows = []
    n = int(len(scores))
    mix = products.value_counts(normalize=True).to_dict() if n else {}
    for metric, value in (
        ("product_mix_psi", psi(metadata.get("reference_product_mix", {}), mix) if n >= min_rows else float("nan")),
        (
            "score_psi",
            score_psi(metadata.get("reference_score_quantiles", []), scores) if n >= min_rows else float("nan"),
        ),
    ):
        rows.append(
            {
                "metric": metric,
                "value": None if np.isnan(value) else round(value, 4),
                "status": status(value),
                "rows": n,
            }
        )
    return rows
