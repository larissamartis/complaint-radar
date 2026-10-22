import json

import pytest
from fastapi.testclient import TestClient

from complaint_radar.api.app import create_app
from complaint_radar.triage.model import TriageModel
from tests.triage.test_triage import synthetic

LOOKUP = {
    "Credit card||Fees": {
        "docs": 50,
        "topics": [{"topic": 1, "label": "Fees charged twice", "share": 0.7, "examples": []}],
    }
}
COMPLAINT = {
    "date_received": "2026-10-20",
    "product": "Credit card",
    "issue": "Fees",
    "company": "Bank B",
    "tags": "Servicemember",
}


@pytest.fixture(scope="module")
def model_path(tmp_path_factory):
    df = synthetic(3000)
    m = TriageModel.fit(df, df["relief_given"].astype(int).to_numpy(), rounds=30)
    m.calibrate(df, df["relief_given"].astype(int).to_numpy())
    m.metadata = {"trained_on": ["2019-01-01", "2023-12-31"], "reference_score_quantiles": [i / 10 for i in range(11)]}
    path = tmp_path_factory.mktemp("m") / "triage.joblib"
    m.save(path)
    return path


def client(model_path, tmp_path, alerts=None):
    alerts_path = tmp_path / "alerts.json"
    if alerts is not None:
        alerts_path.write_text(json.dumps(alerts), encoding="utf-8")
    return TestClient(create_app(model_path=model_path, alerts_path=alerts_path, lookup=LOOKUP))


def test_health_reports_model_and_lookup(model_path, tmp_path):
    body = client(model_path, tmp_path).get("/health").json()
    assert body["status"] == "ok" and body["model_loaded"] and body["topic_lookup_pairs"] == 1


def test_score_returns_probability_priority_and_reasons(model_path, tmp_path):
    r = client(model_path, tmp_path).post("/score", json={"complaints": [COMPLAINT, COMPLAINT | {"company": "New Co"}]})
    assert r.status_code == 200
    scores = r.json()["scores"]
    assert len(scores) == 2
    assert 0 <= scores[0]["relief_probability"] <= 1
    assert scores[0]["priority"] in {"high", "medium", "low"}
    assert len(scores[0]["reasons"]) == 3


def test_score_validates_input(model_path, tmp_path):
    c = client(model_path, tmp_path)
    assert c.post("/score", json={"complaints": []}).status_code == 422
    assert c.post("/score", json={"complaints": [{"product": "Credit card"}]}).status_code == 422


def test_score_without_model_is_503(tmp_path):
    c = TestClient(create_app(model_path=tmp_path / "missing.joblib", alerts_path=tmp_path / "a.json", lookup={}))
    assert c.post("/score", json={"complaints": [COMPLAINT]}).status_code == 503
    assert c.get("/health").json()["model_loaded"] is False


def test_topics_lookup_and_404(model_path, tmp_path):
    c = client(model_path, tmp_path)
    assert (
        c.get("/topics", params={"product": "Credit card", "issue": "Fees"}).json()["topics"][0]["label"]
        == "Fees charged twice"
    )
    assert c.get("/topics", params={"product": "X", "issue": "Y"}).status_code == 404


def test_alerts_from_serving_file(model_path, tmp_path):
    c = client(model_path, tmp_path, alerts=[{"company": "A"}, {"company": "B"}])
    assert [a["company"] for a in c.get("/alerts", params={"limit": 1}).json()] == ["A"]
    assert client(model_path, tmp_path / "none").get("/alerts").json() == []
