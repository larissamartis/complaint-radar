import csv
from datetime import date, timedelta
from pathlib import Path

import duckdb

from complaint_radar.detect.live import alert_id, detect_current, target_week
from complaint_radar.schema import BUREAU_COMPANIES, CANONICAL_COLUMNS

AS_OF = date(2026, 10, 21)  # a Wednesday -> target week starts Monday 2026-10-12


def test_target_week_is_last_complete_week():
    assert target_week(AS_OF) == date(2026, 10, 12)
    assert target_week(date(2026, 10, 19)) == date(2026, 10, 12)  # a Monday scores the week just ended


def test_bureau_list_matches_dbt_seed():
    seed = Path(__file__).parents[2] / "dbt" / "seeds" / "bureau_companies.csv"
    with seed.open(encoding="utf-8") as f:
        assert {r["company"] for r in csv.DictReader(f)} == set(BUREAU_COMPANIES)


def make_snapshot(tmp_path: Path) -> Path:
    """12 quiet weeks of 10 complaints/week for company A, then 60 in the target week; B stays quiet."""
    rows, cid = [], 0
    start = target_week(AS_OF) - timedelta(weeks=12)
    for w in range(13):
        week = start + timedelta(weeks=w)
        for company in ("A", "B"):
            n = 60 if (company == "A" and w == 12) else 10
            for i in range(n):
                cid += 1
                rows.append((cid, week + timedelta(days=i % 7), company))
    out = tmp_path / "snap.parquet"
    con = duckdb.connect()
    con.execute("create table t (complaint_id bigint, date_received date, company varchar)")
    con.executemany("insert into t values (?, ?, ?)", rows)
    cols = ", ".join(
        c
        if c in ("complaint_id", "date_received", "company")
        else "'Credit card' AS product"
        if c == "product"
        else "'Billing disputes' AS issue"
        if c == "issue"
        else f"NULL::VARCHAR AS {c}"
        for c in CANONICAL_COLUMNS
    )
    con.execute(f"COPY (SELECT {cols} FROM t) TO '{out.as_posix()}' (FORMAT parquet)")
    return out


def test_detect_current_flags_only_the_spiking_series(tmp_path):
    al = detect_current(make_snapshot(tmp_path), AS_OF)
    assert list(al["company"]) == ["A"]
    row = al.iloc[0]
    assert row["week_start"] == date(2026, 10, 12) and row["n"] == 60 and row["expected"] == 10
    assert row["segment"] == "other" and row["detector"] == "volume_rule"
    assert row["alert_id"] == alert_id(
        date(2026, 10, 12), "other", "A", "Credit card", "Billing disputes", "volume_rule"
    )


def test_detect_current_columns(tmp_path):
    from complaint_radar.detect.live import ALERT_COLUMNS

    assert tuple(detect_current(make_snapshot(tmp_path), AS_OF).columns) == ALERT_COLUMNS


def test_bureau_segment_uses_its_own_threshold():
    from complaint_radar.detect.live import PRODUCTION_THRESHOLDS

    assert PRODUCTION_THRESHOLDS == {"other": 1.75, "bureau": 3.0}
