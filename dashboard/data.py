"""Data access for the dashboard.

Live serving files come from the `serving-data` branch (refreshed by the daily job); research results come from
`docs/results` on `main`. Set CR_SERVING_DIR / CR_RESULTS_DIR to read local folders instead (used by tests).
"""

import json
import os
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

REPO = "larissamartis/complaint-radar"
SERVING_URL = f"https://raw.githubusercontent.com/{REPO}/serving-data/{{name}}.json"
RESULTS_URL = f"https://raw.githubusercontent.com/{REPO}/main/docs/results/{{name}}.json"
ROOT = Path(__file__).resolve().parents[1]


def _read_json(name: str, local_env: str, url_template: str, default_dir: Path | None = None):
    local = os.environ.get(local_env)
    folder = Path(local) if local else default_dir
    if folder is not None and (folder / f"{name}.json").is_file():
        return json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
    if os.environ.get("CR_OFFLINE"):  # tests: never reach the network
        return None
    try:
        resp = requests.get(url_template.format(name=name), timeout=20)
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException:
        pass
    return None


# Columns of each serving file, so the app works (with empty tables) before the first export exists.
COLUMNS = {
    "alerts": ["alert_id", "as_of", "week_start", "week_age", "segment", "company", "product", "issue", "n",
               "expected", "completeness", "score", "wave_companies", "pattern", "typical_topics", "summary",
               "summary_method", "created_at"],
    "weekly_volume": ["week_start", "segment", "product", "complaints", "relief", "in_progress"],
    "top_series": ["company", "product", "issue", "week_start", "complaints"],
    "pipeline_runs": ["run_id", "as_of", "started_at", "finished_at", "status", "step", "rows_loaded",
                      "snapshot_rows", "api_latest_date", "message"],
    "drift": ["as_of", "metric", "value", "status", "rows"],
    "triage_summary": ["as_of", "priority", "complaints", "mean_probability", "already_closed"],
    "triage_top": ["as_of", "complaint_id", "date_received", "company", "product", "issue", "relief_probability",
                   "priority", "company_response", "days_since_received"],
    "vintages": ["as_of", "segment", "week_start", "age", "n_published"],
}  # fmt: skip


@st.cache_data(ttl=3600, show_spinner=False)
def serving(name: str) -> pd.DataFrame:
    rows = _read_json(name, "CR_SERVING_DIR", SERVING_URL)
    df = pd.DataFrame(rows or [])
    for col in COLUMNS.get(name, []):
        if col not in df:
            df[col] = pd.Series(dtype="object")
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def serving_meta() -> dict:
    return _read_json("meta", "CR_SERVING_DIR", SERVING_URL) or {}


@st.cache_data(ttl=3600, show_spinner=False)
def result(name: str) -> dict:
    """Research results; read from the repo checkout when available (Streamlit Cloud deploys the repo)."""
    return _read_json(name, "CR_RESULTS_DIR", RESULTS_URL, default_dir=ROOT / "docs" / "results") or {}
