"""Complaint Radar scoring API.

GET  /health   service and model status
POST /score    relief probability, priority and top reasons for up to 1,000 complaints
GET  /topics   what customers typically describe for a product + issue (from the narrative archive)
GET  /alerts   latest emerging-issue alerts (from the serving file written by the daily job)
"""

import json
import os
from datetime import date
from functools import lru_cache
from importlib import resources
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from complaint_radar.summarize.enrich import topic_lookup
from complaint_radar.triage.model import TriageModel

DEFAULT_MODEL = resources.files("complaint_radar") / "data" / "triage_model.joblib"


class Complaint(BaseModel):
    date_received: date
    product: str
    issue: str
    company: str
    sub_product: str | None = None
    sub_issue: str | None = None
    state: str | None = None
    submitted_via: str | None = None
    tags: str | None = None


class ScoreRequest(BaseModel):
    complaints: list[Complaint] = Field(min_length=1, max_length=1000)


class Reason(BaseModel):
    feature: str
    value: str
    effect: float


class Score(BaseModel):
    relief_probability: float
    priority: str
    reasons: list[Reason]


class ScoreResponse(BaseModel):
    model_version: str
    scores: list[Score]


def _priority(p: float, quantiles: list[float]) -> str:
    """High = top 10% of the validation-period score distribution, medium = next 20%."""
    if not quantiles:
        return "unknown"
    return "high" if p >= quantiles[9] else "medium" if p >= quantiles[7] else "low"


def create_app(model_path: Path | None = None, alerts_path: Path | None = None, lookup: dict | None = None) -> FastAPI:
    model_path = Path(model_path or os.environ.get("CR_TRIAGE_MODEL", str(DEFAULT_MODEL)))
    alerts_path = Path(alerts_path or os.environ.get("CR_ALERTS_PATH", "data/serving/alerts.json"))
    app = FastAPI(title="Complaint Radar API", version="1.0")

    @lru_cache(maxsize=1)
    def model() -> TriageModel | None:
        return TriageModel.load(model_path) if model_path.is_file() else None

    def topics() -> dict:
        return topic_lookup() if lookup is None else lookup

    @app.get("/health")
    def health() -> dict:
        m = model()
        return {
            "status": "ok",
            "model_loaded": m is not None,
            "model_trained_on": m.metadata.get("trained_on") if m else None,
            "topic_lookup_pairs": len(topics()),
        }

    @app.post("/score", response_model=ScoreResponse)
    def score(req: ScoreRequest) -> ScoreResponse:
        m = model()
        if m is None:
            raise HTTPException(status_code=503, detail="triage model not available")
        df = pd.DataFrame([c.model_dump() for c in req.complaints])
        probs, reasons = m.predict(df), m.reasons(df)
        quantiles = m.metadata.get("reference_score_quantiles", [])
        return ScoreResponse(
            model_version=str(m.metadata.get("trained_on")),
            scores=[
                Score(relief_probability=round(float(p), 4), priority=_priority(float(p), quantiles), reasons=r)
                for p, r in zip(probs, reasons, strict=True)
            ],
        )

    @app.get("/topics")
    def topics_for(product: str = Query(...), issue: str = Query(...)) -> dict:
        entry = topics().get(f"{product}||{issue}")
        if entry is None:
            raise HTTPException(status_code=404, detail="no archived narratives for this product and issue")
        return entry

    @app.get("/alerts")
    def alerts(limit: int = Query(50, ge=1, le=500)) -> list[dict]:
        if not alerts_path.is_file():
            return []
        return json.loads(alerts_path.read_text(encoding="utf-8"))[:limit]

    return app


app = create_app()
