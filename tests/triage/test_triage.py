import numpy as np
import pandas as pd

from complaint_radar.triage.features import FEATURES, CompanyGrouper, build_frame
from complaint_radar.triage.model import TriageModel
from complaint_radar.triage.train import baseline_predict, baseline_rates, metrics, train_and_evaluate

LEAKY = {"company_response", "timely_response", "is_timely", "company_public_response", "date_sent_to_company"}


def synthetic(n=6000, seed=0, start="2019-01-01", end="2025-12-31"):
    """Relief is likelier for credit cards at Bank B and for servicemembers; dates span all three splits."""
    rng = np.random.default_rng(seed)
    days = pd.date_range(start, end, freq="D")
    df = pd.DataFrame(
        {
            "complaint_id": np.arange(n),
            "date_received": rng.choice(days, n),
            "product": rng.choice(["Credit card", "Mortgage", "Debt collection"], n),
            "sub_product": rng.choice(["A", "B", None], n),
            "issue": rng.choice(["Fees", "Fraud", "Billing"], n),
            "sub_issue": None,
            "company": rng.choice(["Bank A", "Bank B", "Bank C", "Tiny Co"], n, p=[0.4, 0.3, 0.29, 0.01]),
            "state": rng.choice(["CA", "TX", "NY"], n),
            "submitted_via": "Web",
            "tags": rng.choice([None, "Servicemember"], n, p=[0.9, 0.1]),
            "narrative": rng.choice([None, "they charged me twice for the same fee", "fraud on my card"], n),
        }
    )
    logit = -1.5 + 1.2 * (df["product"] == "Credit card") + 0.8 * (df["company"] == "Bank B") + 1.0 * df["tags"].notna()
    df["relief_given"] = rng.random(n) < 1 / (1 + np.exp(-logit))
    return df


def test_features_exclude_outcome_fields():
    assert not LEAKY & set(FEATURES)


def test_company_grouper_maps_rare_companies_to_other():
    g = CompanyGrouper(max_companies=2).fit(pd.Series(["A", "A", "B", "B", "C"]))
    assert list(g.transform(pd.Series(["A", "C", "Z"]))) == ["A", "Other", "Other"]


def test_build_frame_handles_missing_columns_and_nulls():
    df = pd.DataFrame({"date_received": ["2025-03-03"], "product": [None], "company": ["X"]})
    frame = build_frame(df, CompanyGrouper().fit(pd.Series(["X"])))
    assert list(frame.columns) == FEATURES
    assert frame.loc[0, "product"] == "(missing)" and frame.loc[0, "tags"] == "(missing)"
    assert frame.loc[0, "month"] == 3 and frame.loc[0, "weekday"] == 0


def test_model_learns_signal_calibrates_and_round_trips(tmp_path):
    df = synthetic()
    tr, va = df.iloc[:4000], df.iloc[4000:]
    m = TriageModel.fit(tr, tr["relief_given"].astype(int).to_numpy(), rounds=60)
    m.calibrate(va, va["relief_given"].astype(int).to_numpy())
    p = m.predict(va)
    assert ((p >= 0) & (p <= 1)).all()
    assert metrics(va["relief_given"], p)["roc_auc"] > 0.65
    m.save(tmp_path / "m.joblib")
    m2 = TriageModel.load(tmp_path / "m.joblib")
    np.testing.assert_allclose(m2.predict(va), p)
    reasons = m2.reasons(va.head(2))
    assert len(reasons) == 2 and len(reasons[0]) == 3 and {"feature", "value", "effect"} <= set(reasons[0][0])


def test_unseen_categories_do_not_crash():
    df = synthetic(2000)
    m = TriageModel.fit(df, df["relief_given"].astype(int).to_numpy(), rounds=20)
    new = df.head(3).assign(product="Brand new product", company="Never seen Inc")
    assert len(m.predict(new)) == 3


def test_baseline_uses_training_rates_with_fallback():
    tr = pd.DataFrame({"product": ["P"] * 4, "issue": ["I"] * 4})
    model = baseline_rates(tr, np.array([1, 1, 1, 0]), prior_weight=0)
    te = pd.DataFrame({"product": ["P", "Q"], "issue": ["I", "J"]})
    np.testing.assert_allclose(baseline_predict(model, te), [0.75, 0.75])


def test_metrics_lift_and_calibration():
    y = np.array([1] * 10 + [0] * 90)
    p = np.linspace(1, 0, 100)
    m = metrics(y, p)
    assert m["precision_top10"] == 1.0 and abs(m["lift_top10"] - 10) < 1e-9
    assert len(m["calibration_deciles"]) == 10


def test_train_and_evaluate_end_to_end(tmp_path):
    res = train_and_evaluate(synthetic(9000), tmp_path / "model.joblib", tmp_path / "triage.json")
    assert (tmp_path / "model.joblib").exists() and (tmp_path / "triage.json").exists()
    allrows = res["test_all_rows"]
    assert set(allrows) == {"baseline_product_issue_rate", "logistic_regression_fields", "lightgbm_fields_calibrated"}
    assert "text_plus_fields_logistic" in res["test_rows_with_narrative"]
    assert allrows["lightgbm_fields_calibrated"]["roc_auc"] > allrows["baseline_product_issue_rate"]["roc_auc"]
    meta = TriageModel.load(tmp_path / "model.joblib").metadata
    assert len(meta["reference_score_quantiles"]) == 11 and meta["reference_product_mix"]
