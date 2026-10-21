from datetime import date, timedelta

import duckdb

from complaint_radar.detect.live import completeness, detect_current, target_week
from complaint_radar.schema import CANONICAL_COLUMNS

AS_OF = date(2026, 10, 21)
W1 = target_week(AS_OF)  # age 1 (2026-10-12)
W2 = W1 - timedelta(weeks=1)  # age 2


def snapshot(tmp_path, weekly_counts: dict[str, list[int]], published: dict[int, float]):
    """weekly_counts[company] = true counts for 12 weeks ending at age-1 week; `published[age]` = share visible."""
    rows, cid = [], 0
    start = W1 - timedelta(weeks=11)
    for company, counts in weekly_counts.items():
        for w, true_n in enumerate(counts):
            week = start + timedelta(weeks=w)
            age = (W1 - week).days // 7 + 1
            for i in range(round(true_n * published.get(age, 1.0))):
                cid += 1
                rows.append((cid, week + timedelta(days=i % 7), company))
    con = duckdb.connect()
    con.execute("create table t (complaint_id bigint, date_received date, company varchar)")
    con.executemany("insert into t values (?, ?, ?)", rows)
    cols = ", ".join(
        c
        if c in ("complaint_id", "date_received", "company")
        else "'P' AS product"
        if c == "product"
        else "'I' AS issue"
        if c == "issue"
        else f"NULL::VARCHAR AS {c}"
        for c in CANONICAL_COLUMNS
    )
    out = tmp_path / "snap.parquet"
    con.execute(f"COPY (SELECT {cols} FROM t) TO '{out.as_posix()}' (FORMAT parquet)")
    return out


def test_completeness_by_age(tmp_path):
    snap = snapshot(tmp_path, {f"C{i}": [100] * 12 for i in range(5)}, {1: 0.3, 2: 0.7})
    c = completeness(snap, AS_OF)
    got = {r.age: round(r.completeness, 2) for r in c[(c.segment == "other") & (c["product"] == "P")].itertuples()}
    assert got[1] == 0.3 and got[2] == 0.7


def test_spike_in_immature_week_is_found_with_adjusted_expectation(tmp_path):
    counts = {f"C{i}": [100] * 12 for i in range(5)}
    counts["A"] = [30] * 11 + [300]  # 10x spike in the age-1 week, only 60% published so far
    al = detect_current(snapshot(tmp_path, counts, {1: 0.6, 2: 0.9}), AS_OF)
    a = al[al["company"] == "A"].iloc[0]
    assert a["week_start"] == W1 and a["week_age"] == 1 and a["n"] == 180
    assert abs(a["expected"] - 18) < 1  # 30/week x 60% completeness
    assert set(al["company"]) == {"A"}  # normal companies are not flagged despite incomplete weeks


def test_baseline_uses_mature_weeks_only(tmp_path):
    counts = {f"C{i}": [100] * 12 for i in range(5)}
    counts["A"] = [30] * 10 + [300, 300]  # spike already in the age-2 week
    al = detect_current(snapshot(tmp_path, counts, {1: 0.6, 2: 0.9}), AS_OF)
    ages = set(al.loc[al["company"] == "A", "week_age"])
    assert ages == {1, 2}  # the age-2 spike does not leak into the age-1 baseline and hide it


def test_weeks_less_than_half_published_are_not_scored(tmp_path):
    counts = {f"C{i}": [100] * 12 for i in range(5)}
    counts["A"] = [30] * 11 + [300]
    al = detect_current(snapshot(tmp_path, counts, {1: 0.3, 2: 0.7}), AS_OF)
    assert al.empty or set(al["week_age"]) == {2}


def test_completeness_is_per_product(tmp_path):
    rows = {f"C{i}": [100] * 12 for i in range(5)}
    snap = snapshot(tmp_path, rows, {1: 0.4, 2: 0.8})
    c = completeness(snap, AS_OF)
    assert {"segment", "product", "age", "completeness"} <= set(c.columns)
