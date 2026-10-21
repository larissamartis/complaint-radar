"""Emerging-issue detectors on weekly series.

Every feature for week t is computed from weeks t-8..t-1 only, so the score never peeks at the week it
is scoring. An alert needs a statistical signal (score >= threshold) AND practical significance
(at least 20 complaints, and at least 1.5x the expected count). The second gate stops tiny series
from alerting on noise.
"""

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from scipy import stats

from complaint_radar.detect.series import SERIES_KEY

BASELINE_WEEKS = 8
MIN_BASELINE_MEAN = 2.0
MIN_COUNT = 20
MIN_RATIO = 1.5
DETECTORS = ("volume_rule", "robust_z", "nb_surprise")


def _features(x: np.ndarray) -> dict[str, np.ndarray]:
    n = len(x)
    out = {k: np.full(n, np.nan) for k in ("mean_8", "median_8", "mad_8", "var_8")}
    if n <= BASELINE_WEEKS:
        return out
    win = sliding_window_view(x[:-1].astype(float), BASELINE_WEEKS)  # row i = weeks i..i+7 -> scores week i+8
    med = np.median(win, axis=1)
    out["mean_8"][BASELINE_WEEKS:] = win.mean(axis=1)
    out["median_8"][BASELINE_WEEKS:] = med
    out["mad_8"][BASELINE_WEEKS:] = np.median(np.abs(win - med[:, None]), axis=1)
    out["var_8"][BASELINE_WEEKS:] = win.var(axis=1, ddof=1)
    return out


def add_baseline_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values([*SERIES_KEY, "week"]).reset_index(drop=True)
    parts = {k: np.empty(len(df)) for k in ("mean_8", "median_8", "mad_8", "var_8")}
    for idx in df.groupby(SERIES_KEY, sort=False, observed=True).indices.values():
        feats = _features(df["n"].to_numpy()[idx])
        for k, v in feats.items():
            parts[k][idx] = v
    for k, v in parts.items():
        df[k] = v
    df["expected"] = df["mean_8"]
    return df


def score(df: pd.DataFrame, detector: str) -> pd.Series:
    n, mean = df["n"].astype(float), df["mean_8"]
    valid = mean >= MIN_BASELINE_MEAN
    if detector == "volume_rule":
        s = n / mean
    elif detector == "robust_z":
        spread = np.maximum(1.4826 * df["mad_8"], np.sqrt(df["median_8"] + 1))
        s = (n - df["median_8"]) / spread
    elif detector == "nb_surprise":
        var = np.maximum(df["var_8"], mean * 1.01)
        p = (mean / var).clip(1e-9, 1 - 1e-9)
        r = (mean**2 / (var - mean)).clip(lower=1e-6)
        tail = stats.nbinom.sf(n - 1, r, p)  # P(X >= n)
        s = -np.log10(np.clip(tail, 1e-300, 1.0))
    else:
        raise ValueError(f"unknown detector {detector!r}; choose from {DETECTORS}")
    return pd.Series(np.where(valid, s, np.nan), index=df.index, name=detector)


def alerts(df: pd.DataFrame, detector: str, threshold: float) -> pd.DataFrame:
    s = score(df, detector)
    mask = (s >= threshold) & (df["n"] >= MIN_COUNT) & (df["n"] >= MIN_RATIO * df["expected"])
    out = df.loc[mask].copy()
    out["detector"], out["score"] = detector, s[mask]
    return out
