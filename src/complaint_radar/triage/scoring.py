"""Daily triage scoring of complaints appearing for the first time, plus drift monitoring.

Caveat for the public CFPB feed: a complaint is published only after the company responds (or after ~15 days),
so on "first appearance" many complaints are already closed and weeks old. Each score therefore stores the
complaint's status and age; on public data these scores are retrospective, while inside a bank the same model
would run at intake.
"""

import logging
from datetime import date
from functools import lru_cache
from importlib import resources
from pathlib import Path

import duckdb
import pandas as pd

from complaint_radar.monitor.drift import drift_report
from complaint_radar.schema import BUREAU_COMPANIES
from complaint_radar.storage.bigquery import DRIFT_ARROW, TRIAGE_SCORES_ARROW
from complaint_radar.triage.model import TriageModel, priority

log = logging.getLogger(__name__)
MODEL_FILE = "triage_model.joblib"


@lru_cache(maxsize=1)
def load_triage_model() -> TriageModel | None:
    path = resources.files("complaint_radar") / "data" / MODEL_FILE
    return TriageModel.load(Path(str(path))) if path.is_file() else None


def new_complaints(changes_parquet: Path, existing_keys: Path) -> pd.DataFrame:
    """Non-bureau complaints appearing in the warehouse for the first time in this run."""
    bureaus = ", ".join("'" + b.replace("'", "''") + "'" for b in BUREAU_COMPANIES)
    con = duckdb.connect()
    try:
        return con.execute(
            f"""
            SELECT c.* FROM read_parquet(?) AS c
            ANTI JOIN (SELECT DISTINCT complaint_id FROM read_parquet(?)) AS k USING (complaint_id)
            WHERE coalesce(c.company, '') NOT IN ({bureaus})
            """,
            [changes_parquet.as_posix(), existing_keys.as_posix()],
        ).df()
    finally:
        con.close()


def score_new_complaints(changes_parquet: Path, existing_keys: Path, as_of: date, wh, model=None) -> dict | None:
    """Score first-time non-bureau complaints, load scores and drift metrics. Returns a short summary."""
    model = model or load_triage_model()
    if model is None:
        log.warning("no triage model packaged; skipping scoring")
        return None
    if not changes_parquet.exists():
        return {"scored": 0, "drift": []}
    fresh = new_complaints(changes_parquet, existing_keys)
    if fresh.empty:
        return {"scored": 0, "drift": []}
    probs = model.predict(fresh)
    quantiles = model.metadata.get("reference_score_quantiles", [])
    received = pd.to_datetime(fresh["date_received"]).dt.date
    response = fresh["company_response"] if "company_response" in fresh else pd.Series(None, index=fresh.index)
    scores = fresh[["complaint_id", "date_received", "company", "product", "issue"]].assign(
        as_of=as_of,
        relief_probability=probs.round(4),
        priority=[priority(float(p), quantiles) for p in probs],
        model_version=str(model.metadata.get("trained_on")),
        company_response=response,
        days_since_received=[(as_of - d).days for d in received],
        already_closed=response.notna() & (response != "In progress"),
    )
    wh.load_frame(scores, "triage_scores", TRIAGE_SCORES_ARROW)
    drift = drift_report(model.metadata, fresh["product"], probs)
    wh.load_frame(pd.DataFrame(drift).assign(as_of=as_of), "drift_metrics", DRIFT_ARROW)
    return {"scored": int(len(scores)), "already_closed": int(scores["already_closed"].sum()), "drift": drift}
