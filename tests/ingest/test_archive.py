import os
import zipfile
from pathlib import Path

import pytest

from complaint_radar.contracts.checker import default_contract_path
from complaint_radar.ingest.archive import ContractViolation, backfill_archive, download_archive

FIX = Path(__file__).parents[1] / "fixtures"
CONTRACT = default_contract_path()


def make_zip(raw: Path, name: str, csv_text: str) -> Path:
    raw.mkdir(parents=True, exist_ok=True)
    z = raw / f"{name}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{name}.csv", csv_text)
    return z


def sample() -> str:
    return (FIX / "archive_sample.csv").read_text(encoding="utf-8")


def test_backfill_creates_one_parquet_per_zip(tmp_path):
    make_zip(tmp_path / "raw", "CCDB_Export_A", sample())
    make_zip(tmp_path / "raw", "CCDB_Export_B", sample())
    report = backfill_archive(tmp_path / "raw", tmp_path / "out", CONTRACT)
    assert sorted(report.processed) == ["CCDB_Export_A", "CCDB_Export_B"]
    assert report.rows == 8
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["CCDB_Export_A.parquet", "CCDB_Export_B.parquet"]


def test_backfill_rerun_skips(tmp_path):
    make_zip(tmp_path / "raw", "CCDB_Export_A", sample())
    backfill_archive(tmp_path / "raw", tmp_path / "out", CONTRACT)
    out = tmp_path / "out" / "CCDB_Export_A.parquet"
    before = os.stat(out).st_mtime_ns
    report = backfill_archive(tmp_path / "raw", tmp_path / "out", CONTRACT)
    assert report.processed == [] and report.skipped == ["CCDB_Export_A"]
    assert os.stat(out).st_mtime_ns == before


def test_contract_failure_leaves_no_file(tmp_path):
    lines = sample().splitlines()
    duplicated = "\n".join(lines + [lines[-1]]) + "\n"  # last complaint appears twice
    make_zip(tmp_path / "raw", "CCDB_Export_Bad", duplicated)
    with pytest.raises(ContractViolation) as exc:
        backfill_archive(tmp_path / "raw", tmp_path / "out", CONTRACT)
    assert "CCDB_Export_Bad" in str(exc.value) and "unique" in str(exc.value)
    assert list((tmp_path / "out").glob("*")) == []


class FakeResponse:
    def __init__(self, headers=None, chunks=(), fail=False):
        self.headers = headers or {}
        self._chunks, self._fail = chunks, fail

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        if self._fail:
            raise ConnectionError("dropped")
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeSession:
    def __init__(self, size, fail_first=False):
        self.size, self.fail_first, self.gets = size, fail_first, 0

    def head(self, url, **kw):
        return FakeResponse({"Content-Length": str(self.size)})

    def get(self, url, **kw):
        self.gets += 1
        fail = self.fail_first and self.gets == 1
        return FakeResponse(chunks=[b"x" * self.size], fail=fail)


def test_download_skips_complete_files(tmp_path):
    (tmp_path / "F.zip").write_bytes(b"x" * 10)
    session = FakeSession(10)
    download_archive(tmp_path, names=("F",), session=session)
    assert session.gets == 0


def test_download_retries_after_failure(tmp_path):
    session = FakeSession(10, fail_first=True)
    paths = download_archive(tmp_path, names=("F",), session=session, backoff=0)
    assert paths == [tmp_path / "F.zip"] and paths[0].stat().st_size == 10
    assert session.gets == 2 and not list(tmp_path.glob("*.part"))


def test_interrupt_during_check_leaves_nothing_dbt_can_read(tmp_path, monkeypatch):
    import complaint_radar.ingest.archive as archive

    make_zip(tmp_path / "raw", "CCDB_Export_A", sample())

    def boom(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(archive, "check_parquet", boom)
    with pytest.raises(KeyboardInterrupt):
        backfill_archive(tmp_path / "raw", tmp_path / "out", CONTRACT)
    assert list((tmp_path / "out").glob("*.parquet")) == []
