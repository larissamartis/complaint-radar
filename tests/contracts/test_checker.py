from datetime import date
from pathlib import Path

import duckdb
import pytest

from complaint_radar.contracts.checker import check_parquet, default_contract_path, load_contract

CONTRACT = load_contract(default_contract_path())

GOOD = [
    (
        1,
        "2026-10-08",
        "Credit card",
        "Billing disputes",
        "Bank A",
        "Closed with explanation",
        "Yes",
        "Web",
        "h1",
    ),
    (2, "2026-10-09", "Mortgage", "Trouble paying", "Bank B", "In progress", "No", "Phone", "h2"),
    (3, "2026-10-10", "Debt collection", "Fraud", "Bank C", "Closed with monetary relief", "Yes", None, "h3"),
]
COLS = (
    "complaint_id, date_received, product, issue, company, company_response, timely_response, submitted_via, row_hash"
)


def make(tmp_path: Path, rows, drop: str | None = None) -> Path:
    out = tmp_path / "f.parquet"
    values = ", ".join(
        "(" + ", ".join("NULL" if v is None else repr(v) if isinstance(v, str) else str(v) for v in r) + ")"
        for r in rows
    )
    cols = [c.strip() for c in COLS.split(",") if c.strip() != drop]
    duckdb.sql(
        f"""COPY (SELECT {", ".join(cols)} FROM (
                SELECT complaint_id::BIGINT complaint_id, date_received::DATE date_received,
                       * EXCLUDE (complaint_id, date_received)
                FROM (VALUES {values}) t({COLS}))) TO '{out.as_posix()}' (FORMAT parquet)"""
    )
    return out


def rules(result) -> set[str]:
    return {v.split(":")[0] for v in result.violations}


def test_valid_file_passes(tmp_path):
    r = check_parquet(make(tmp_path, GOOD), CONTRACT)
    assert r.passed and r.violations == [] and r.row_count == 3


def test_missing_required_column(tmp_path):
    assert "required_columns" in rules(check_parquet(make(tmp_path, GOOD, drop="row_hash"), CONTRACT))


def test_duplicate_id(tmp_path):
    rows = GOOD + [(1, *GOOD[0][1:])]
    assert "unique" in rules(check_parquet(make(tmp_path, rows), CONTRACT))


def test_null_company(tmp_path):
    rows = [GOOD[0][:4] + (None,) + GOOD[0][5:]] + GOOD[1:]
    r = check_parquet(make(tmp_path, rows), CONTRACT)
    assert "not_null" in rules(r) and not r.passed
    assert any("company" in v for v in r.violations)


def test_unknown_response_value(tmp_path):
    rows = [GOOD[0][:5] + ("Resolved",) + GOOD[0][6:]] + GOOD[1:]
    assert "accepted_values" in rules(check_parquet(make(tmp_path, rows), CONTRACT))


def test_null_response_allowed(tmp_path):
    rows = [GOOD[0][:5] + (None,) + GOOD[0][6:]] + GOOD[1:]
    assert check_parquet(make(tmp_path, rows), CONTRACT).passed


@pytest.mark.parametrize("value", ["Closed", "Closed with relief", "Closed without relief"])
def test_historical_response_values_pass(tmp_path, value):
    rows = [GOOD[0][:5] + (value,) + GOOD[0][6:]] + GOOD[1:]
    assert check_parquet(make(tmp_path, rows), CONTRACT).passed


def test_freshness(tmp_path):
    f = make(tmp_path, GOOD)
    assert "freshness" in rules(check_parquet(f, CONTRACT, as_of=date(2026, 10, 21)))
    assert check_parquet(f, CONTRACT, as_of=date(2026, 10, 12)).passed


def test_future_dates_rejected(tmp_path):
    assert "date_range" in rules(check_parquet(make(tmp_path, GOOD), CONTRACT, as_of=date(2026, 10, 9)))


def test_row_count_change(tmp_path):
    f = make(tmp_path, GOOD)
    assert "row_count_change" in rules(check_parquet(f, CONTRACT, previous_row_count=5))
    assert check_parquet(f, CONTRACT, previous_row_count=3).passed
