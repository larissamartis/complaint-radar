"""Daily structured snapshot of the full CFPB complaint database (no narratives since 2026-08-14)."""

import shutil
import tempfile
import zipfile
from datetime import date
from pathlib import Path

import requests

from complaint_radar.ingest.http import download
from complaint_radar.ingest.normalize import normalize_csv

SNAPSHOT_URL = "https://files.consumerfinance.gov/ccdb/complaints.csv.zip"
API_URL = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"


def fetch_snapshot(dest_dir: Path, as_of: date, session=None) -> Path:
    return download(SNAPSHOT_URL, dest_dir / f"complaints_{as_of.isoformat()}.zip", session=session)


def api_latest_date(session=None) -> date:
    """Newest `date_received` the CFPB API currently serves: a cheap freshness pre-check."""
    session = session or requests.Session()
    params = {"size": 1, "sort": "created_date_desc", "no_aggs": "true"}
    resp = session.get(API_URL, params=params, timeout=120)
    resp.raise_for_status()
    hit = resp.json()["hits"]["hits"][0]["_source"]
    return date.fromisoformat(hit["date_received"][:10])


def snapshot_to_parquet(zip_path: Path, out_path: Path) -> int:
    """Normalise the snapshot zip's CSV into canonical Parquet; returns rows written."""
    snapshot_date = zip_path.stem.removeprefix("complaints_")
    tmp = Path(tempfile.mkdtemp(dir=out_path.parent if out_path.parent.exists() else None))
    try:
        with zipfile.ZipFile(zip_path) as zf:
            member = next((m for m in zf.namelist() if m.lower().endswith(".csv")), None)
            if member is None:
                raise ValueError(f"{zip_path.name} contains no CSV file")
            csv_path = Path(zf.extract(member, tmp))
        return normalize_csv(csv_path, out_path, source_file=f"snapshot_{snapshot_date}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
