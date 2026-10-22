from datetime import date

import duckdb
import numpy as np

from complaint_radar.triage.model import TriageModel
from complaint_radar.triage.scoring import new_complaints, score_new_complaints
from tests.triage.test_triage import synthetic


class Wh:
    def __init__(self):
        self.frames = {}

    def load_frame(self, df, table, arrow):
        self.frames[table] = df.to_dict("records")
        return len(df)


def write(tmp_path, name, sql):
    path = tmp_path / name
    duckdb.sql(f"COPY ({sql}) TO '{path.as_posix()}' (FORMAT parquet)")
    return path


def model():
    df = synthetic(3000)
    m = TriageModel.fit(df, df["relief_given"].astype(int).to_numpy(), rounds=20)
    m.metadata = {
        "trained_on": ["2019-01-01", "2023-12-31"],
        "reference_score_quantiles": np.linspace(0, 1, 11).tolist(),
        "reference_product_mix": {"Credit card": 0.5, "Mortgage": 0.5},
    }
    return m


def changes(tmp_path):
    return write(
        tmp_path,
        "changes.parquet",
        "SELECT * FROM (VALUES "
        "(1, DATE '2026-10-20', 'Credit card', 'Fees', 'Bank B'),"
        "(2, DATE '2026-10-20', 'Mortgage', 'Billing', 'EQUIFAX, INC.'),"
        "(3, DATE '2026-10-01', 'Mortgage', 'Billing', 'Bank A')"
        ") t(complaint_id, date_received, product, issue, company)",
    )


def test_new_complaints_skips_bureaus_and_already_loaded(tmp_path):
    keys = write(tmp_path, "keys.parquet", "SELECT 3::BIGINT AS complaint_id, 'h' AS row_hash")
    fresh = new_complaints(changes(tmp_path), keys)
    assert list(fresh["complaint_id"]) == [1]  # 2 is a bureau, 3 was loaded before (a status change, not new)


def test_score_new_complaints_loads_scores_and_drift(tmp_path):
    keys = write(tmp_path, "keys.parquet", "SELECT NULL::BIGINT AS complaint_id, NULL AS row_hash WHERE false")
    wh = Wh()
    out = score_new_complaints(changes(tmp_path), keys, date(2026, 10, 21), wh, model=model())
    assert out["scored"] == 2
    scores = wh.frames["triage_scores"]
    assert {r["complaint_id"] for r in scores} == {1, 3}
    assert all(0 <= r["relief_probability"] <= 1 and r["priority"] in {"high", "medium", "low"} for r in scores)
    assert {r["metric"] for r in wh.frames["drift_metrics"]} == {"product_mix_psi", "score_psi"}
    assert all(r["status"] == "insufficient_data" for r in wh.frames["drift_metrics"])  # only 2 rows today


def test_no_model_means_no_scoring(tmp_path, monkeypatch):
    import complaint_radar.triage.scoring as scoring

    monkeypatch.setattr(scoring, "load_triage_model", lambda: None)
    keys = write(tmp_path, "keys.parquet", "SELECT 1::BIGINT AS complaint_id, 'h' AS row_hash")
    assert score_new_complaints(changes(tmp_path), keys, date(2026, 10, 21), Wh()) is None
