import zipfile
from datetime import date
from pathlib import Path

import duckdb

from complaint_radar.ingest.snapshot import api_latest_date, fetch_snapshot, snapshot_to_parquet

FIX = Path(__file__).parents[1] / "fixtures"


class Resp:
    def __init__(self, headers=None, body=b"", payload=None):
        self.headers, self._body, self._payload = headers or {}, body, payload

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield self._body

    def json(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Session:
    def __init__(self, body=b"zipbytes", payload=None):
        self.body, self.payload, self.gets = body, payload, []

    def head(self, url, **kw):
        return Resp({"Content-Length": str(len(self.body))})

    def get(self, url, **kw):
        self.gets.append((url, kw.get("params")))
        return Resp(body=self.body, payload=self.payload)


def test_fetch_snapshot_names_file_by_date(tmp_path):
    path = fetch_snapshot(tmp_path, date(2026, 10, 21), session=Session())
    assert path == tmp_path / "complaints_2026-10-21.zip"
    assert path.read_bytes() == b"zipbytes"


def test_fetch_snapshot_skips_existing_complete(tmp_path):
    (tmp_path / "complaints_2026-10-21.zip").write_bytes(b"zipbytes")
    session = Session()
    fetch_snapshot(tmp_path, date(2026, 10, 21), session=session)
    assert session.gets == []


def test_api_latest_date_parses_first_hit():
    payload = {"hits": {"hits": [{"_source": {"date_received": "2026-10-20T00:58:30.000Z"}}]}}
    session = Session(payload=payload)
    assert api_latest_date(session=session) == date(2026, 10, 20)
    assert session.gets[0][1]["sort"] == "created_date_desc"


def test_snapshot_to_parquet_live_columns(tmp_path):
    z = tmp_path / "complaints_2026-10-21.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(FIX / "live_sample.csv", "complaints.csv")
    out = tmp_path / "snap.parquet"
    assert snapshot_to_parquet(z, out) == 4
    nulls, src = duckdb.sql(
        f"select count(*) filter (where narrative is null), any_value(source_file) from '{out.as_posix()}'"
    ).fetchone()
    assert nulls == 4 and src == "snapshot_2026-10-21"
