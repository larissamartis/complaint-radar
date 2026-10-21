"""Score the most recent complete week of the daily snapshot and produce alert records."""

import hashlib
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd

from complaint_radar.detect.detectors import BASELINE_WEEKS, add_baseline_features, alerts
from complaint_radar.detect.series import weekly_series
from complaint_radar.schema import BUREAU_COMPANIES

PRODUCTION_DETECTOR = "volume_rule"
PRODUCTION_THRESHOLD = 1.75  # tuned on 2016-2021, see docs/results/phase3.md

ALERT_COLUMNS = (
    "alert_id",
    "week_start",
    "segment",
    "company",
    "product",
    "issue",
    "detector",
    "threshold",
    "n",
    "expected",
    "score",
)


def target_week(as_of: date) -> date:
    """Monday of the last complete week before `as_of`'s week."""
    return as_of - timedelta(days=as_of.weekday()) - timedelta(weeks=1)


def alert_id(week: date, segment: str, company: str, product: str, issue: str, detector: str) -> str:
    key = "|".join([week.isoformat(), segment, company, product, issue, detector])
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def detect_current(
    snapshot_parquet: Path,
    as_of: date,
    detector: str = PRODUCTION_DETECTOR,
    threshold: float = PRODUCTION_THRESHOLD,
) -> pd.DataFrame:
    week = target_week(as_of)
    start = week - timedelta(weeks=BASELINE_WEEKS + 2)
    end = week + timedelta(days=6)
    bureaus = ", ".join("'" + b.replace("'", "''") + "'" for b in BUREAU_COMPANIES)
    con = duckdb.connect()
    try:
        con.execute(
            f"""
            CREATE TEMP TABLE daily AS
            SELECT date_received,
                   CASE WHEN company IN ({bureaus}) THEN 'bureau' ELSE 'other' END AS segment,
                   company, product, coalesce(issue, '(none)') AS issue, count(*) AS n_complaints
            FROM read_parquet(?)
            WHERE date_received BETWEEN ? AND ?
            GROUP BY ALL
            """,
            [snapshot_parquet.as_posix(), start, end],
        )
        weekly = weekly_series(con, "daily", start, end, min_peak=20)
    finally:
        con.close()
    if weekly.empty:
        return pd.DataFrame(columns=ALERT_COLUMNS)
    found = alerts(add_baseline_features(weekly), detector, threshold)
    found = found[found["week"] == pd.Timestamp(week)].copy()
    found["week_start"] = week
    found["threshold"] = threshold
    found["alert_id"] = [alert_id(week, r.segment, r.company, r.product, r.issue, detector) for r in found.itertuples()]
    return found.reindex(columns=ALERT_COLUMNS).sort_values("score", ascending=False).reset_index(drop=True)
