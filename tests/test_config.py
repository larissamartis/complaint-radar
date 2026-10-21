from pathlib import Path

from complaint_radar import config


def test_data_root_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("CR_DATA_DIR", str(tmp_path))
    assert config.data_root() == tmp_path
    assert config.raw_archive_dir() == tmp_path / "raw" / "archive"
    assert config.archive_parquet_dir() == tmp_path / "lake" / "complaints_archive"
    assert config.duckdb_path() == tmp_path / "lake" / "complaint_radar.duckdb"


def test_data_root_default(monkeypatch):
    monkeypatch.delenv("CR_DATA_DIR", raising=False)
    assert config.data_root() == Path.home() / "data" / "complaint-radar"
