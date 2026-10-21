"""Live weekly detection on the daily snapshot, with a nowcast for publication delay.

The CFPB publishes a complaint only after the company responds (or after about 15 days). On any given day,
the most recent weeks are therefore incomplete: for non-bureau companies, about 30% of last week and 70% of
the week before are visible, against about 100% from three weeks back. Comparing an incomplete week with a
complete baseline would hide real spikes. So the live detector:

1. builds each series' baseline only from mature weeks (age >= 3 weeks);
2. estimates each recent week's completeness per segment and product (see `_completeness`);
3. scores a week only once it is at least half published, comparing the observed count with
   baseline x completeness.
"""

import hashlib
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd

from complaint_radar.detect.detectors import BASELINE_WEEKS, MIN_BASELINE_MEAN, MIN_COUNT, MIN_RATIO
from complaint_radar.schema import BUREAU_COMPANIES

PRODUCTION_DETECTOR = "volume_rule"
PRODUCTION_THRESHOLD = 1.75  # tuned on 2016-2021, see docs/results/phase3.md
MATURE_AGE = 3  # weeks after which a week is treated as fully published
SCORED_AGES = (1, 2)
MIN_COMPLETENESS = 0.05
MIN_SCORED_COMPLETENESS = 0.5  # weeks less than half published are too noisy to score
MIN_PRODUCT_BASELINE = 50  # complaints/week needed for a product-specific completeness estimate

ALERT_COLUMNS = (
    "alert_id",
    "week_start",
    "week_age",
    "segment",
    "company",
    "product",
    "issue",
    "detector",
    "threshold",
    "n",
    "expected",
    "completeness",
    "score",
)


def target_week(as_of: date) -> date:
    """Monday of the last complete calendar week before `as_of`'s week (age 1)."""
    return as_of - timedelta(days=as_of.weekday()) - timedelta(weeks=1)


def alert_id(week: date, segment: str, company: str, product: str, issue: str, detector: str) -> str:
    key = "|".join([week.isoformat(), segment, company, product, issue, detector])
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def _series_frame(snapshot_parquet: Path, as_of: date) -> pd.DataFrame:
    """One row per series with observed counts at scored ages and the mature-week baseline mean."""
    w1 = target_week(as_of)
    oldest = w1 - timedelta(weeks=MATURE_AGE + BASELINE_WEEKS - 2)
    bureaus = ", ".join("'" + b.replace("'", "''") + "'" for b in BUREAU_COMPANIES)
    age_cols = ", ".join(f"sum(n) FILTER (WHERE age = {a}) AS n_age{a}" for a in SCORED_AGES)
    con = duckdb.connect()
    try:
        return con.execute(
            f"""
            WITH weekly AS (
                SELECT CASE WHEN company IN ({bureaus}) THEN 'bureau' ELSE 'other' END AS segment,
                       company, product, coalesce(issue, '(none)') AS issue,
                       date_diff('week', date_trunc('week', date_received)::DATE, ?::DATE) + 1 AS age,
                       count(*) AS n
                FROM read_parquet(?)
                WHERE date_received >= ? AND date_received < ?
                GROUP BY ALL
            )
            SELECT segment, company, product, issue, {age_cols},
                   sum(n) FILTER (WHERE age >= {MATURE_AGE}) / {BASELINE_WEEKS}.0 AS baseline_mean
            FROM weekly
            GROUP BY ALL
            """,
            [w1, snapshot_parquet.as_posix(), oldest, w1 + timedelta(days=7)],
        ).df()
    finally:
        con.close()


def _completeness(frame: pd.DataFrame) -> pd.DataFrame:
    """Share of each recent week already published, per (segment, product).

    Publication speed differs a lot by product (after one week: ~50% of debt-collection complaints are
    visible but ~7% of mortgage complaints), so one segment-wide figure would flood alerts from fast
    products. Estimate = observed / baseline summed over the product's series, after dropping the 10% of
    series with the highest ratio so that genuinely spiking series do not inflate it. Products with too
    little volume fall back to the segment-wide estimate.
    """

    def ratio_of_sums(part: pd.DataFrame, age: int) -> float | None:
        part = part[part["baseline_mean"] > 0]
        if part["baseline_mean"].sum() < MIN_PRODUCT_BASELINE:
            return None
        ratios = part[f"n_age{age}"].fillna(0) / part["baseline_mean"]
        keep = part[ratios <= ratios.quantile(0.9)] if len(part) >= 5 else part
        return float(keep[f"n_age{age}"].fillna(0).sum() / keep["baseline_mean"].sum())

    rows = []
    for segment, seg in frame.groupby("segment"):
        for age in SCORED_AGES:
            seg_c = ratio_of_sums(seg, age)
            seg_c = 1.0 if seg_c is None else seg_c
            for product, prod in seg.groupby("product"):
                c = ratio_of_sums(prod, age)
                c = seg_c if c is None else c
                rows.append(
                    {
                        "segment": segment,
                        "product": product,
                        "age": age,
                        "completeness": float(min(max(c, MIN_COMPLETENESS), 1.0)),
                    }
                )
    return pd.DataFrame(rows, columns=["segment", "product", "age", "completeness"])


def completeness(snapshot_parquet: Path, as_of: date) -> pd.DataFrame:
    """Estimated share of each recent week already published, per segment."""
    return _completeness(_series_frame(snapshot_parquet, as_of))


def detect_current(
    snapshot_parquet: Path,
    as_of: date,
    detector: str = PRODUCTION_DETECTOR,
    threshold: float = PRODUCTION_THRESHOLD,
) -> pd.DataFrame:
    frame = _series_frame(snapshot_parquet, as_of)
    if frame.empty:
        return pd.DataFrame(columns=ALERT_COLUMNS)
    comp = _completeness(frame).set_index(["segment", "product", "age"])["completeness"]
    w1 = target_week(as_of)
    found = []
    for age in SCORED_AGES:
        part = frame[["segment", "company", "product", "issue", "baseline_mean"]].copy()
        part["n"] = frame[f"n_age{age}"].fillna(0).astype(int)
        part["week_age"] = age
        part["week_start"] = w1 - timedelta(weeks=age - 1)
        part["completeness"] = [
            comp.get((s, p, age), 1.0) for s, p in zip(part["segment"], part["product"], strict=True)
        ]
        part["expected"] = part["baseline_mean"] * part["completeness"]
        part["score"] = part["n"] / part["expected"]
        ok = (
            (part["baseline_mean"] >= MIN_BASELINE_MEAN)
            & (part["n"] >= MIN_COUNT)
            & (part["n"] >= MIN_RATIO * part["expected"])
            & (part["score"] >= threshold)
            & (part["completeness"] >= MIN_SCORED_COMPLETENESS)
        )
        found.append(part[ok])
    out = pd.concat(found, ignore_index=True)
    out["detector"], out["threshold"] = detector, threshold
    out["alert_id"] = [
        alert_id(r.week_start, r.segment, r.company, r.product, r.issue, detector) for r in out.itertuples()
    ]
    return out.reindex(columns=ALERT_COLUMNS).sort_values("score", ascending=False).reset_index(drop=True)


def weekly_vintage(snapshot_parquet: Path, as_of: date, weeks: int = 12) -> pd.DataFrame:
    """Per-segment complaint counts for recent weeks as published on `as_of`.

    Stored daily, these vintages show how each week fills in over time and calibrate the nowcast.
    """
    w1 = target_week(as_of)
    bureaus = ", ".join("'" + b.replace("'", "''") + "'" for b in BUREAU_COMPANIES)
    con = duckdb.connect()
    try:
        df = con.execute(
            f"""
            SELECT CASE WHEN company IN ({bureaus}) THEN 'bureau' ELSE 'other' END AS segment,
                   date_trunc('week', date_received)::DATE AS week_start, count(*) AS n_published
            FROM read_parquet(?)
            WHERE date_received >= ? AND date_received < ?
            GROUP BY ALL ORDER BY 1, 2
            """,
            [snapshot_parquet.as_posix(), w1 - timedelta(weeks=weeks - 1), w1 + timedelta(days=14)],
        ).df()
    finally:
        con.close()
    df["week_start"] = pd.to_datetime(df["week_start"]).dt.date
    df["age"] = [((w1 - w).days // 7) + 1 for w in df["week_start"]]
    df["as_of"] = as_of
    return df[["as_of", "segment", "week_start", "age", "n_published"]]
