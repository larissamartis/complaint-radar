from pathlib import Path

import duckdb
import pytest

from complaint_radar.ingest.normalize import normalize_csv
from complaint_radar.schema import CANONICAL_COLUMNS

FIX = Path(__file__).parents[1] / "fixtures"


def _rows(path: Path) -> list[dict]:
    rel = duckdb.sql(f"select * from read_parquet('{path.as_posix()}') order by complaint_id")
    return [dict(zip(rel.columns, r, strict=True)) for r in rel.fetchall()]


def test_archive_rows_parse_exactly(tmp_path):
    out = tmp_path / "a.parquet"
    assert normalize_csv(FIX / "archive_sample.csv", out, "archive_sample") == 4
    rows = _rows(out)
    assert list(rows[0].keys()) == list(CANONICAL_COLUMNS)
    paypal = next(r for r in rows if r["complaint_id"] == 4200002)
    assert '"permanently limited"' in paypal["narrative"]
    assert "\n" in paypal["narrative"]
    assert paypal["source_file"] == "archive_sample"
    assert str(paypal["date_received"]) == "2021-03-15"


def test_empty_narrative_becomes_null(tmp_path):
    out = tmp_path / "a.parquet"
    normalize_csv(FIX / "archive_sample.csv", out, "x")
    chime = next(r for r in _rows(out) if r["complaint_id"] == 11800003)
    assert chime["narrative"] is None
    assert chime["tags"] is None


def test_live_file_has_null_narrative_and_same_hash(tmp_path):
    a, b = tmp_path / "a.parquet", tmp_path / "l.parquet"
    normalize_csv(FIX / "archive_sample.csv", a, "archive")
    normalize_csv(FIX / "live_sample.csv", b, "live")
    archive, live = _rows(a), _rows(b)
    assert all(r["narrative"] is None for r in live)
    assert [r["row_hash"] for r in archive] == [r["row_hash"] for r in live]
    assert len({r["row_hash"] for r in archive}) == 4


def test_unknown_column_raises(tmp_path):
    src = tmp_path / "bad.csv"
    text = (FIX / "live_sample.csv").read_text(encoding="utf-8").splitlines()
    src.write_text("\n".join([text[0] + ",Foo"] + [t + ",x" for t in text[1:]]), encoding="utf-8")
    with pytest.raises(ValueError, match="Foo"):
        normalize_csv(src, tmp_path / "o.parquet", "bad")


def test_no_partial_file_on_error(tmp_path):
    src = tmp_path / "bad.csv"
    lines = (FIX / "live_sample.csv").read_text(encoding="utf-8").splitlines()
    src.write_text("\n".join([lines[0], lines[1].replace("2022-10-03", "not-a-date", 1)]), encoding="utf-8")
    out = tmp_path / "o.parquet"
    with pytest.raises(duckdb.Error):
        normalize_csv(src, out, "bad")
    assert not out.exists()
    assert not out.with_suffix(".tmp").exists()
