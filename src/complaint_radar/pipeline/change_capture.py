"""Select new or changed complaint versions for an append-only warehouse.

The BigQuery sandbox has no DML (no MERGE/UPDATE), so instead of updating rows we append a new
version whenever a complaint's structured fields change, and dbt picks the latest version per
complaint. A row is "new" when its (complaint_id, row_hash) pair is not already in the warehouse,
which also makes reruns idempotent: a second run on the same snapshot selects nothing.
"""

from datetime import date, timedelta
from pathlib import Path

import duckdb

from complaint_radar.schema import CANONICAL_COLUMNS

WAREHOUSE_COLUMNS: tuple[str, ...] = tuple(c for c in CANONICAL_COLUMNS if c not in {"narrative", "source_file"}) + (
    "loaded_date",
    "run_id",
)


def select_changes(
    snapshot_parquet: Path,
    existing_keys: Path | None,
    as_of: date,
    run_id: str,
    out_path: Path,
    window_days: int = 60,
) -> int:
    """Write snapshot rows inside the hot window whose (complaint_id, row_hash) is not yet loaded."""
    window_start = as_of - timedelta(days=window_days)
    con = duckdb.connect()
    try:
        con.execute("SET preserve_insertion_order = false")
        if existing_keys is not None:
            con.execute(
                f"CREATE VIEW existing AS SELECT complaint_id, row_hash FROM read_parquet('{existing_keys.as_posix()}')"
            )
        else:
            con.execute("CREATE TABLE existing (complaint_id BIGINT, row_hash VARCHAR)")
        select = ", ".join(
            f"DATE '{as_of.isoformat()}' AS loaded_date"
            if c == "loaded_date"
            else "? AS run_id"
            if c == "run_id"
            else f"s.{c}"
            for c in WAREHOUSE_COLUMNS
        )
        tmp = out_path.with_suffix(".tmp")
        con.execute(
            f"""
            COPY (
                SELECT {select}
                FROM read_parquet('{snapshot_parquet.as_posix()}') AS s
                ANTI JOIN existing AS e USING (complaint_id, row_hash)
                WHERE s.date_received >= DATE '{window_start.isoformat()}'
            ) TO '{tmp.as_posix()}' (FORMAT parquet, COMPRESSION zstd)
            """,
            [run_id],
        )
        rows = con.execute(f"SELECT count(*) FROM read_parquet('{tmp.as_posix()}')").fetchone()[0]
    finally:
        con.close()
    tmp.replace(out_path)
    return rows
