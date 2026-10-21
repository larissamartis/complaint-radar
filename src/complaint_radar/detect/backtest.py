"""Backtest emerging-issue detectors on real past incidents.

Ground truth ("incident"): a series-month with at least 50 complaints and at least 3x the median of its
previous 6 months (that median >= 10). Consecutive incident months in one series are merged, and the
incident's peak is its busiest week. The definition is monthly while the detectors are weekly, so the
detectors cannot "find" an incident simply by restating the definition.

Catch: an alert in the same series within the 8 weeks up to and including the peak week.
Lead time: days from the first such alert to the peak.
False alarm: an alert with no incident peak from 4 weeks before it to 10 weeks after it.
"""

import numpy as np
import pandas as pd

from complaint_radar.detect.series import SERIES_KEY

INCIDENT_MIN_N = 50
INCIDENT_RATIO = 3.0
INCIDENT_MIN_BASE = 10
CATCH_WEEKS_BEFORE_PEAK = 8
FA_WEEKS_BEFORE, FA_WEEKS_AFTER = 4, 10


def label_incidents(weekly: pd.DataFrame) -> pd.DataFrame:
    w = weekly[[*SERIES_KEY, "week", "n"]].copy()
    w["month"] = w["week"].dt.to_period("M").dt.to_timestamp()
    monthly = w.groupby([*SERIES_KEY, "month"], sort=True, observed=True)["n"].sum().reset_index()
    g = monthly.groupby(SERIES_KEY, sort=False, observed=True)["n"]
    monthly["base"] = g.transform(lambda s: s.shift(1).rolling(6, min_periods=6).median())
    hit = monthly[
        (monthly["n"] >= INCIDENT_MIN_N)
        & (monthly["base"] >= INCIDENT_MIN_BASE)
        & (monthly["n"] >= INCIDENT_RATIO * monthly["base"])
    ].copy()
    if hit.empty:
        return pd.DataFrame(columns=[*SERIES_KEY, "start_month", "end_month", "peak_week", "n", "base"])

    # Merge consecutive incident months into one incident per series.
    hit = hit.sort_values([*SERIES_KEY, "month"])
    new_run = hit.groupby(SERIES_KEY, sort=False, observed=True)["month"].diff() != pd.DateOffset(months=1)
    new_run = hit["month"].diff().dt.days.fillna(999).gt(31) | new_run
    hit["incident_no"] = new_run.cumsum()
    incidents = (
        hit.groupby([*SERIES_KEY, "incident_no"], sort=False, observed=True)
        .agg(start_month=("month", "min"), end_month=("month", "max"), n=("n", "sum"), base=("base", "first"))
        .reset_index()
    )

    # Peak week inside the incident's months.
    w = w.merge(incidents[[*SERIES_KEY, "incident_no", "start_month", "end_month"]], on=SERIES_KEY)
    w = w[(w["month"] >= w["start_month"]) & (w["month"] <= w["end_month"])]
    peaks = w.loc[w.groupby("incident_no")["n"].idxmax(), ["incident_no", "week"]].rename(columns={"week": "peak_week"})
    return incidents.merge(peaks, on="incident_no").drop(columns="incident_no")


def _match(alert_df: pd.DataFrame, incidents: pd.DataFrame) -> pd.DataFrame:
    """One row per (alert, incident in the same series) pair, with week offsets."""
    a = alert_df[[*SERIES_KEY, "week"]].reset_index(names="alert_idx")
    i = incidents[[*SERIES_KEY, "peak_week"]].reset_index(names="incident_idx")
    pairs = a.merge(i, on=SERIES_KEY)
    pairs["peak_week"], pairs["week"] = pd.to_datetime(pairs["peak_week"]), pd.to_datetime(pairs["week"])
    pairs["weeks_to_peak"] = (pairs["peak_week"] - pairs["week"]).dt.days // 7
    return pairs


def evaluate(alert_df: pd.DataFrame, incidents: pd.DataFrame, weekly: pd.DataFrame, start, end) -> dict:
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    incidents = incidents.assign(peak_week=pd.to_datetime(incidents["peak_week"]))
    inc = incidents[(incidents["peak_week"] >= start) & (incidents["peak_week"] < end)].reset_index(drop=True)
    al = alert_df[(alert_df["week"] >= start) & (alert_df["week"] < end)].reset_index(drop=True)

    pairs = _match(al, inc)
    catches = pairs[(pairs["weeks_to_peak"] >= 0) & (pairs["weeks_to_peak"] <= CATCH_WEEKS_BEFORE_PEAK)]
    leads = catches.groupby("incident_idx")["weeks_to_peak"].max() * 7  # first alert = largest offset

    # A false alarm has no incident peak (in any period) from FA_WEEKS_BEFORE before to FA_WEEKS_AFTER after it.
    all_pairs = _match(al, incidents.reset_index(drop=True))
    near = all_pairs[(all_pairs["weeks_to_peak"] >= -FA_WEEKS_BEFORE) & (all_pairs["weeks_to_peak"] <= FA_WEEKS_AFTER)]
    n_false = len(al) - near["alert_idx"].nunique()

    eligible = weekly[(weekly["week"] >= start) & (weekly["week"] < end) & (weekly["mean_8"] >= 2)]
    series_months = len(eligible) / (52 / 12)
    return {
        "incidents": int(len(inc)),
        "caught": int(leads.size),
        "recall": float(leads.size / len(inc)) if len(inc) else float("nan"),
        "median_lead_days": float(np.median(leads)) if leads.size else float("nan"),
        "p25_lead_days": float(np.percentile(leads, 25)) if leads.size else float("nan"),
        "alerts": int(len(al)),
        "false_alarms": int(n_false),
        "precision": float(1 - n_false / len(al)) if len(al) else float("nan"),
        "false_alarms_per_100_series_months": float(100 * n_false / series_months) if series_months else float("nan"),
    }


def tune_threshold(scored: pd.DataFrame, detector: str, grid, incidents, weekly, start, end, max_fa_rate=2.0):
    """Lowest threshold (highest recall) whose false-alarm rate on the tuning period is <= max_fa_rate."""
    from complaint_radar.detect.detectors import alerts

    best = None
    for t in sorted(grid):
        m = evaluate(alerts(scored, detector, t), incidents, weekly, start, end)
        if m["false_alarms_per_100_series_months"] <= max_fa_rate:
            best = (t, m)
            break
    if best is None:
        t = max(grid)
        best = (t, evaluate(alerts(scored, detector, t), incidents, weekly, start, end))
    return best
