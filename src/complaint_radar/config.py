"""Filesystem locations. Data lives outside the repo (and outside OneDrive)."""

import os
from pathlib import Path


def data_root() -> Path:
    override = os.environ.get("CR_DATA_DIR")
    return Path(override) if override else Path.home() / "data" / "complaint-radar"


def raw_archive_dir() -> Path:
    return data_root() / "raw" / "archive"


def lake_dir() -> Path:
    return data_root() / "lake"


def archive_parquet_dir() -> Path:
    return lake_dir() / "complaints_archive"


def duckdb_path() -> Path:
    return lake_dir() / "complaint_radar.duckdb"
