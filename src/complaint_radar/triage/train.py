"""Train and evaluate escalation-triage models with a strict time split.

train: complaints received 2019-2023 | valid (calibration): 2024 | test (reported): 2025.
Compared on the same 2025 test rows:
  1. baseline        historical relief rate for the complaint's product x issue (training period only)
  2. logreg          one-hot logistic regression on the intake fields
  3. lightgbm        gradient boosting on the intake fields, calibrated on 2024  <- serving model
  4. text + fields   TF-IDF of the narrative + one-hot fields (archive only: live complaints have no text)
"""

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.preprocessing import OneHotEncoder

from complaint_radar.triage.features import CATEGORICAL, TARGET, CompanyGrouper, build_frame
from complaint_radar.triage.model import TriageModel

log = logging.getLogger(__name__)

SPLITS = {
    "train": ("2019-01-01", "2023-12-31"),
    "valid": ("2024-01-01", "2024-12-31"),
    "test": ("2025-01-01", "2025-12-31"),
}
TEXT_TRAIN_ROWS = 300_000  # TF-IDF + logistic regression on a sample keeps the runner's memory in check

QUERY = """
    SELECT complaint_id, date_received, product, sub_product, issue, sub_issue, company, state,
           submitted_via, tags, narrative, relief_given
    FROM stg_complaints
    WHERE segment = 'other' AND relief_given IS NOT NULL AND date_received BETWEEN ? AND ?
"""


def metrics(y: np.ndarray, p: np.ndarray) -> dict:
    y, p = np.asarray(y).astype(int), np.asarray(p, dtype=float)
    k = max(1, int(round(0.1 * len(p))))
    top = np.argsort(-p)[:k]
    base = y.mean()
    deciles = pd.qcut(pd.Series(p).rank(method="first"), 10, labels=False)
    calib = (
        pd.DataFrame({"d": deciles, "p": p, "y": y})
        .groupby("d")
        .agg(mean_score=("p", "mean"), relief_rate=("y", "mean"))
    )
    return {
        "rows": int(len(y)),
        "base_rate": float(base),
        "roc_auc": float(roc_auc_score(y, p)),
        "pr_auc": float(average_precision_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "precision_top10": float(y[top].mean()),
        "lift_top10": float(y[top].mean() / base) if base else float("nan"),
        "calibration_deciles": calib.round(3).to_dict("records"),
    }


def baseline_rates(train: pd.DataFrame, y: np.ndarray, prior_weight: float = 50.0) -> dict:
    """Smoothed relief rate per product x issue (falls back to the overall rate)."""
    g = pd.DataFrame({"k": train["product"].fillna("") + "||" + train["issue"].fillna(""), "y": y}).groupby("k")["y"]
    overall = float(y.mean())
    rates = (g.sum() + prior_weight * overall) / (g.count() + prior_weight)
    return {"overall": overall, "rates": rates.to_dict()}


def baseline_predict(model: dict, df: pd.DataFrame) -> np.ndarray:
    keys = df["product"].fillna("") + "||" + df["issue"].fillna("")
    return keys.map(model["rates"]).fillna(model["overall"]).to_numpy()


def _one_hot() -> ColumnTransformer:
    return ColumnTransformer(
        [("cat", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=50), [*CATEGORICAL, "month"])]
    )


def split(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    d = pd.to_datetime(df["date_received"])
    return {name: df[(d >= lo) & (d <= hi)].reset_index(drop=True) for name, (lo, hi) in SPLITS.items()}


def train_and_evaluate(df: pd.DataFrame, model_path: Path, results_path: Path, seed: int = 0) -> dict:
    parts = split(df)
    del df  # keep only the split copies in memory
    tr, va, te = parts.pop("train"), parts.pop("valid"), parts.pop("test")
    y_tr, y_va, y_te = (p[TARGET].astype(int).to_numpy() for p in (tr, va, te))
    log.info("rows train=%d valid=%d test=%d", len(tr), len(va), len(te))

    # Narratives are only needed for the text model's training sample and the test rows.
    tr_text = tr[tr["narrative"].notna()]
    if len(tr_text) > TEXT_TRAIN_ROWS:
        tr_text = tr_text.sample(TEXT_TRAIN_ROWS, random_state=seed)
    tr, va = tr.drop(columns="narrative"), va.drop(columns="narrative")

    base = baseline_rates(tr, y_tr)
    grouper = CompanyGrouper().fit(tr["company"].fillna("(missing)"))
    ohe = _one_hot()
    x_tr = ohe.fit_transform(build_frame(tr, grouper))
    logreg = LogisticRegression(max_iter=300, C=1.0).fit(x_tr, y_tr)

    lgbm = TriageModel.fit(tr, y_tr).calibrate(va, y_va)

    with_text = te["narrative"].notna().to_numpy()
    tfidf = TfidfVectorizer(ngram_range=(1, 2), min_df=5, max_features=100_000, sublinear_tf=True)
    xt_tr = sparse.hstack(
        [tfidf.fit_transform(tr_text["narrative"]), ohe.transform(build_frame(tr_text, grouper))]
    ).tocsr()
    text_lr = LogisticRegression(max_iter=300, C=1.0).fit(xt_tr, tr_text[TARGET].astype(int))
    te_text = te[with_text]
    xt_te = sparse.hstack([tfidf.transform(te_text["narrative"]), ohe.transform(build_frame(te_text, grouper))]).tocsr()

    preds = {
        "baseline_product_issue_rate": baseline_predict(base, te),
        "logistic_regression_fields": logreg.predict_proba(ohe.transform(build_frame(te, grouper)))[:, 1],
        "lightgbm_fields_calibrated": lgbm.predict(te),
    }
    results = {
        "splits": SPLITS,
        "population": "non-bureau complaints with a known outcome; in-progress and untimely complaints "
        "(no outcome) are excluded from training, calibration and test",
        "features": "intake-time fields only: product, sub-product, issue, sub-issue, company, state, "
        "channel, tags, month, weekday",
        "test_all_rows": {name: metrics(y_te, p) for name, p in preds.items()},
        "test_rows_with_narrative": {
            **{name: metrics(y_te[with_text], p[with_text]) for name, p in preds.items()},
            "text_plus_fields_logistic": metrics(y_te[with_text], text_lr.predict_proba(xt_te)[:, 1]),
        },
    }
    lgbm.metadata = {
        "trained_on": SPLITS["train"],
        "calibrated_on": SPLITS["valid"],
        "test": {
            k: v
            for k, v in results["test_all_rows"]["lightgbm_fields_calibrated"].items()
            if k != "calibration_deciles"
        },
        "reference_score_quantiles": np.quantile(lgbm.predict(va), np.linspace(0, 1, 11)).round(4).tolist(),
        "reference_product_mix": va["product"].value_counts(normalize=True).round(4).to_dict(),
    }
    lgbm.save(model_path)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    return results


def load_training_frame(con) -> pd.DataFrame:
    return con.execute(QUERY, [SPLITS["train"][0], SPLITS["test"][1]]).df()
