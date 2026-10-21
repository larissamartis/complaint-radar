"""Convert a raw CFPB CSV into a canonical, typed Parquet file."""

import csv
from pathlib import Path

import duckdb

from complaint_radar.schema import CANONICAL_COLUMNS, COLUMN_MAP, DATE_COLUMNS, HASH_COLUMNS


def _read_header(csv_path: Path) -> list[str]:
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        return next(csv.reader(f))


def _column_expr(name: str, present: set[str]) -> str:
    if name not in present:
        return f"NULL::VARCHAR AS {name}"
    if name == "complaint_id":
        return "CAST(complaint_id AS BIGINT) AS complaint_id"
    if name in DATE_COLUMNS:
        return f"CAST(NULLIF(TRIM({name}), '') AS DATE) AS {name}"
    return f"NULLIF(TRIM({name}), '') AS {name}"


def normalize_csv(csv_path: Path, out_path: Path, source_file: str) -> int:
    """Write `csv_path` as canonical Parquet at `out_path`; return the number of rows written."""
    header = _read_header(csv_path)
    unknown = [h for h in header if h not in COLUMN_MAP]
    if unknown:
        raise ValueError(f"Unknown columns in {csv_path.name}: {unknown}")
    present = {COLUMN_MAP[h] for h in header}

    renamed = ", ".join(f'"{h}" AS {COLUMN_MAP[h]}' for h in header)
    # Hash the trimmed raw text (before typing) so the value is stable across file formats.
    hash_input = ", ".join(f"COALESCE(NULLIF(TRIM({c}), ''), '')" if c in present else "''" for c in HASH_COLUMNS)
    typed = ", ".join(_column_expr(c, present) for c in CANONICAL_COLUMNS if c not in {"row_hash", "source_file"})
    select = ", ".join(f"'{source_file}' AS source_file" if c == "source_file" else c for c in CANONICAL_COLUMNS)

    tmp = out_path.with_suffix(".tmp")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute("SET preserve_insertion_order = false")
        con.execute(
            f"""
            COPY (
                WITH raw AS (
                    SELECT {renamed}
                    FROM read_csv('{csv_path.as_posix()}', header = true, all_varchar = true,
                                  quote = '"', escape = '"', parallel = false, max_line_size = 10000000)
                ), typed AS (SELECT {typed}, md5(concat_ws('|', {hash_input})) AS row_hash FROM raw)
                SELECT {select} FROM typed
            ) TO '{tmp.as_posix()}' (FORMAT parquet, COMPRESSION zstd)
            """
        )
        rows = con.execute(f"SELECT count(*) FROM read_parquet('{tmp.as_posix()}')").fetchone()[0]
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        con.close()
    tmp.replace(out_path)
    return rows
