"""Daily triage scoring of newly arrived complaints, plus drift monitoring of the scores and product mix."""

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
from complaint_radar.triage.model import TriageModel

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
            WHERE c.company NOT IN ({bureaus})
            """,
            [changes_parquet.as_posix(), existing_keys.as_posix()],
        ).df()
    finally:
        con.close()


def _priority(p: float, quantiles: list[float]) -> str:
    return "high" if p >= quantiles[9] else "medium" if p >= quantiles[7] else "low"


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
    quantiles = model.metadata.get("reference_score_quantiles") or [0.0] * 11
    version = str(model.metadata.get("trained_on"))
    scores = fresh[["complaint_id", "date_received", "company", "product", "issue"]].assign(
        as_of=as_of,
        relief_probability=probs.round(4),
        priority=[_priority(float(p), quantiles) for p in probs],
        model_version=version,
    )
    wh.load_frame(scores, "triage_scores", TRIAGE_SCORES_ARROW)
    drift = drift_report(model.metadata, fresh["product"], probs)
    wh.load_frame(pd.DataFrame(drift).assign(as_of=as_of), "drift_metrics", DRIFT_ARROW)
    return {"scored": int(len(scores)), "drift": drift}
