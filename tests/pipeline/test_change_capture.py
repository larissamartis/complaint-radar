from datetime import date, timedelta
from pathlib import Path

import duckdb

from complaint_radar.pipeline.change_capture import WAREHOUSE_COLUMNS, select_changes
from complaint_radar.schema import CANONICAL_COLUMNS

AS_OF = date(2026, 10, 21)


def snapshot(tmp_path: Path, rows: list[tuple[int, date, str]], name="snap.parquet") -> Path:
    """rows: (complaint_id, date_received, company_response); other columns NULL, hash derived."""
    out = tmp_path / name
    values = ", ".join(f"({i}, DATE '{d}', '{r}')" for i, d, r in rows)
    cols = ", ".join(
        "complaint_id"
        if c == "complaint_id"
        else "date_received"
        if c == "date_received"
        else "company_response"
        if c == "company_response"
        else "md5(complaint_id::varchar || company_response) AS row_hash"
        if c == "row_hash"
        else "'snapshot' AS source_file"
        if c == "source_file"
        else f"NULL::VARCHAR AS {c}"
        for c in CANONICAL_COLUMNS
    )
    duckdb.sql(
        f"COPY (SELECT {cols} FROM (VALUES {values}) t(complaint_id, date_received, company_response)) "
        f"TO '{out.as_posix()}' (FORMAT parquet)"
    )
    return out


def read(path: Path) -> list[tuple]:
    return duckdb.sql(f"select complaint_id, company_response from '{path.as_posix()}' order by 1").fetchall()


def test_first_run_loads_only_window(tmp_path):
    snap = snapshot(
        tmp_path, [(1, AS_OF - timedelta(days=10), "In progress"), (2, AS_OF - timedelta(days=90), "Closed")]
    )
    out = tmp_path / "changes.parquet"
    assert select_changes(snap, None, AS_OF, "run1", out) == 1
    assert read(out) == [(1, "In progress")]


def test_rerun_appends_nothing(tmp_path):
    snap = snapshot(tmp_path, [(1, AS_OF - timedelta(days=1), "In progress")])
    first = tmp_path / "first.parquet"
    select_changes(snap, None, AS_OF, "run1", first)
    assert select_changes(snap, first, AS_OF, "run2", tmp_path / "second.parquet") == 0


def test_status_change_is_new_version(tmp_path):
    old = snapshot(tmp_path, [(1, AS_OF - timedelta(days=5), "In progress")], "old.parquet")
    loaded = tmp_path / "loaded.parquet"
    select_changes(old, None, AS_OF - timedelta(days=1), "run1", loaded)
    new = snapshot(tmp_path, [(1, AS_OF - timedelta(days=5), "Closed with explanation")], "new.parquet")
    out = tmp_path / "changes.parquet"
    assert select_changes(new, loaded, AS_OF, "run2", out) == 1
    assert read(out) == [(1, "Closed with explanation")]


def test_output_columns_match_warehouse_columns(tmp_path):
    snap = snapshot(tmp_path, [(1, AS_OF, "In progress")])
    out = tmp_path / "changes.parquet"
    select_changes(snap, None, AS_OF, "run-x", out)
    rel = duckdb.sql(f"select * from '{out.as_posix()}'")
    assert tuple(rel.columns) == WAREHOUSE_COLUMNS
    assert "narrative" not in rel.columns
    loaded_date, run_id = duckdb.sql(f"select loaded_date, run_id from '{out.as_posix()}'").fetchone()
    assert loaded_date == AS_OF and run_id == "run-x"
