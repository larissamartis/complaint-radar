"""Run the detector backtest on the local lake and write results JSON."""

import json
import logging
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from complaint_radar.detect.backtest import evaluate, label_incidents, tune_threshold
from complaint_radar.detect.detectors import DETECTORS, add_baseline_features, alerts
from complaint_radar.detect.series import weekly_series

log = logging.getLogger(__name__)

TUNE = (pd.Timestamp("2016-01-01"), pd.Timestamp("2022-01-01"))
TEST = (pd.Timestamp("2022-01-01"), pd.Timestamp("2026-08-01"))  # archive ends mid-Aug 2026
GRIDS = {
    "volume_rule": list(np.round(np.arange(1.5, 8.01, 0.25), 2)),
    "robust_z": list(np.round(np.arange(0.5, 25.01, 0.5), 2)),
    "nb_surprise": list(np.round(np.arange(0.5, 40.01, 0.5), 2)),
}
BUDGETS = (0.5, 1.0, 2.0)  # false alarms per 100 series-months
MAX_FA_RATE = 2.0  # false alarms per 100 series-months allowed on the tuning period

NAMED = [
    ("MOHELA", "Dealing with your lender or servicer", "2022-10"),
    ("Paypal Holdings, Inc", "Managing, opening, or closing your mobile wallet account", "2021-03"),
    ("Chime Financial Inc", "Managing an account", "2025-02"),
    ("NAVY FEDERAL CREDIT UNION", "Problem caused by your funds being low", "2025-01"),
    ("WELLS FARGO & COMPANY", "Problem caused by your funds being low", "2023-01"),
    ("Block, Inc.", "Other transaction problem", "2025-01"),
]


def _named_leads(incidents: pd.DataFrame, alert_sets: dict[str, pd.DataFrame]) -> list[dict]:
    rows = []
    for company, issue, month in NAMED:
        m = pd.Timestamp(month + "-01")
        cand = incidents[
            (incidents["company"] == company)
            & (incidents["issue"] == issue)
            & (incidents["start_month"] <= m)
            & (incidents["end_month"] >= m)
        ]
        if cand.empty:
            rows.append({"company": company, "issue": issue, "month": month, "labelled_incident": False})
            continue
        inc = cand.sort_values("n", ascending=False).iloc[0]
        row = {
            "company": company,
            "issue": issue,
            "month": month,
            "labelled_incident": True,
            "peak_week": inc["peak_week"].date().isoformat(),
            "incident_complaints": int(inc["n"]),
            "baseline_month_median": float(inc["base"]),
        }
        for det, al in alert_sets.items():
            hits = al[
                (al["company"] == company)
                & (al["issue"] == issue)
                & (al["product"] == inc["product"])
                & (al["week"] <= inc["peak_week"])
                & (al["week"] >= inc["peak_week"] - pd.Timedelta(weeks=8))
            ]
            row[f"{det}_lead_days"] = int((inc["peak_week"] - hits["week"].min()).days) if len(hits) else None
        rows.append(row)
    return rows


def _share_early(al, incidents, start, end, days=7) -> float:
    """Share of test-period incidents with an alert at least `days` before the peak."""
    from complaint_radar.detect.backtest import _match

    inc = incidents[(incidents["peak_week"] >= start) & (incidents["peak_week"] < end)].reset_index(drop=True)
    pairs = _match(al, inc)
    early = pairs[(pairs["weeks_to_peak"] * 7 >= days) & (pairs["weeks_to_peak"] <= 8)]
    return float(early["incident_idx"].nunique() / len(inc)) if len(inc) else float("nan")


def budget_curve(seg, det, incidents, start, end) -> dict:
    """Best recall each detector reaches on [start, end) within each false-alarm budget.

    This compares how well the detectors *rank* weeks at equal noise. It is descriptive: the operating
    threshold used in production is still the one tuned on the earlier period.
    """
    points = []
    for t in GRIDS[det]:
        m = evaluate(alerts(seg, det, t), incidents, seg, start, end)
        points.append((m["false_alarms_per_100_series_months"], m["recall"], m["median_lead_days"], float(t)))
    out = {}
    for b in BUDGETS:
        ok = [p for p in points if p[0] <= b]
        best = max(ok, key=lambda p: p[1]) if ok else None
        out[str(b)] = {"recall": best[1], "median_lead_days": best[2], "threshold": best[3]} if best else None
    return out


def run_backtest(con: duckdb.DuckDBPyConnection, out_json: Path, daily_table: str = "fct_complaints_daily") -> dict:
    weekly = weekly_series(con, daily_table, date(2015, 1, 1), date(2026, 7, 31), min_peak=10)
    log.info("weekly grid: %d rows, %d series", len(weekly), weekly.groupby(["company", "product", "issue"]).ngroups)
    weekly = add_baseline_features(weekly)
    results: dict = {
        "definitions": {
            "tune": [str(TUNE[0].date()), str(TUNE[1].date())],
            "test": [str(TEST[0].date()), str(TEST[1].date())],
            "max_false_alarms_per_100_series_months_on_tune": MAX_FA_RATE,
        },
        "segments": {},
    }
    for segment in ("other", "bureau"):
        seg = weekly[weekly["segment"] == segment].reset_index(drop=True)
        incidents = label_incidents(seg)
        seg_res, alert_sets = {}, {}
        for det in DETECTORS:
            threshold, tune_m = tune_threshold(seg, det, GRIDS[det], incidents, seg, *TUNE, MAX_FA_RATE)
            al = alerts(seg, det, threshold)
            alert_sets[det] = al
            test_m = evaluate(al, incidents, seg, *TEST)
            for days in (7, 14, 21):
                test_m[f"share_caught_{days}d_early"] = _share_early(al, incidents, *TEST, days=days)
            seg_res[det] = {
                "threshold": float(threshold),
                "tune": tune_m,
                "test": test_m,
                "test_recall_at_equal_false_alarm_budget": budget_curve(seg, det, incidents, *TEST),
            }
            log.info("%s %s t=%.2f test=%s", segment, det, threshold, seg_res[det]["test"])
        results["segments"][segment] = {"detectors": seg_res, "n_incidents_total": int(len(incidents))}
        if segment == "other":
            results["named_incidents"] = _named_leads(incidents, alert_sets)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    return results
