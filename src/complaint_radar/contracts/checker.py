"""Check a canonical Parquet file against a YAML data contract, collecting every violation."""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import duckdb
import yaml


@dataclass
class ContractResult:
    passed: bool
    violations: list[str] = field(default_factory=list)
    row_count: int = 0


def load_contract(path: Path) -> dict:
    with Path(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def check_parquet(
    path: Path,
    contract: dict,
    *,
    as_of: date | None = None,
    previous_row_count: int | None = None,
) -> ContractResult:
    con = duckdb.connect()
    con.execute(f"CREATE VIEW f AS SELECT * FROM read_parquet('{Path(path).as_posix()}')")
    one = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    columns = {r[0] for r in con.execute("DESCRIBE f").fetchall()}
    row_count = one("SELECT count(*) FROM f")
    violations: list[str] = []

    missing = [c for c in contract.get("required_columns", []) if c not in columns]
    if missing:
        violations.append(f"required_columns: missing {missing}")

    for col in contract.get("not_null", []):
        if col in columns and (n := one(f"SELECT count(*) FROM f WHERE {col} IS NULL")):
            violations.append(f"not_null: {col} has {n} NULL rows")

    for col in contract.get("unique", []):
        if col in columns and (n := one(f"SELECT count(*) - count(DISTINCT {col}) FROM f")):
            violations.append(f"unique: {col} has {n} duplicate rows")

    nullable = set(contract.get("nullable_accepted", []))
    for col, allowed in contract.get("accepted_values", {}).items():
        if col not in columns:
            continue
        allowed_sql = ", ".join(_quote(v) for v in allowed)
        null_clause = "" if col in nullable else f" OR {col} IS NULL"
        bad = con.execute(
            f"SELECT {col}, count(*) FROM f WHERE {col} NOT IN ({allowed_sql}){null_clause} "
            f"GROUP BY 1 ORDER BY 2 DESC LIMIT 5"
        ).fetchall()
        if bad:
            violations.append(f"accepted_values: {col} has unexpected values {bad}")

    if (rng := contract.get("date_range")) and rng["column"] in columns:
        col = rng["column"]
        lo, hi = con.execute(f"SELECT min({col}), max({col}) FROM f").fetchone()
        if lo is not None and str(lo) < rng["min"]:
            violations.append(f"date_range: {col} min {lo} is before {rng['min']}")
        if as_of is not None and hi is not None and hi > as_of:
            violations.append(f"date_range: {col} max {hi} is after as_of {as_of}")

    if as_of is not None and (fr := contract.get("freshness")) and fr["column"] in columns:
        newest = one(f"SELECT max({fr['column']}) FROM f")
        if newest is None or (as_of - newest).days > fr["max_age_days"]:
            violations.append(
                f"freshness: newest {fr['column']} is {newest}, more than {fr['max_age_days']} days before {as_of}"
            )

    if previous_row_count and (rc := contract.get("row_count_change")):
        pct = abs(row_count - previous_row_count) / previous_row_count * 100
        if pct > rc["max_pct"]:
            violations.append(
                f"row_count_change: {row_count} rows vs {previous_row_count} previously ({pct:.0f}% > {rc['max_pct']}%)"
            )

    con.close()
    return ContractResult(passed=not violations, violations=violations, row_count=row_count)
