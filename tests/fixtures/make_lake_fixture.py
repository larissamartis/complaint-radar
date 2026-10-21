"""Regenerate the tiny lake fixture used by CI's dbt build: `python tests/fixtures/make_lake_fixture.py`."""

from pathlib import Path

from complaint_radar.ingest.normalize import normalize_csv

here = Path(__file__).parent
normalize_csv(here / "archive_sample.csv", here / "lake" / "complaints_archive" / "sample.parquet", "archive_sample")
