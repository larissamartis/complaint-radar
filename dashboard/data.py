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
    try:
        resp = requests.get(url_template.format(name=name), timeout=20)
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException:
        pass
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def serving(name: str) -> pd.DataFrame:
    rows = _read_json(name, "CR_SERVING_DIR", SERVING_URL)
    return pd.DataFrame(rows or [])


@st.cache_data(ttl=3600, show_spinner=False)
def serving_meta() -> dict:
    return _read_json("meta", "CR_SERVING_DIR", SERVING_URL) or {}


@st.cache_data(ttl=3600, show_spinner=False)
def result(name: str) -> dict:
    """Research results; read from the repo checkout when available (Streamlit Cloud deploys the repo)."""
    return _read_json(name, "CR_RESULTS_DIR", RESULTS_URL, default_dir=ROOT / "docs" / "results") or {}
