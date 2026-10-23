"""Do complaint patterns warn of CFPB enforcement actions in advance? A strictly time-split test.

train: company-months 2015-01 .. 2019-12 | test: 2020-01 .. 2024-08 (the last month whose 12-month target window
ends before the action list stops, Aug 2025). Compared on the same test rows:
  baseline   logistic regression on complaint volume only (big companies get more actions)
  logistic   logistic regression on all complaint-pattern features (standardised)
  lightgbm   gradient boosting on all features
The gain over volume is tested with a company-clustered bootstrap, because rows of one company are not
independent.
"""

import json
import logging
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from complaint_radar.enforcement.panel import FEATURES

log = logging.getLogger(__name__)

TRAIN = ("2015-01-01", "2019-12-01")
TEST = ("2020-01-01", "2024-08-01")
LGBM_PARAMS = {
    "objective": "binary",
    "learning_rate": 0.03,
    "num_leaves": 15,
    "min_child_samples": 200,
    "feature_fraction": 0.8,
    "verbose": -1,
    "seed": 7,
}


def _metrics(y: np.ndarray, p: np.ndarray) -> dict:
    k = max(1, int(round(0.01 * len(p))))
    top = np.argsort(-p)[:k]
    return {
        "roc_auc": float(roc_auc_score(y, p)),
        "pr_auc": float(average_precision_score(y, p)),
        "precision_top1pct": float(y[top].mean()),
        "lift_top1pct": float(y[top].mean() / y.mean()) if y.mean() else float("nan"),
    }


def cluster_bootstrap(test: pd.DataFrame, p_a: np.ndarray, p_b: np.ndarray, n: int = 500, seed: int = 0) -> dict:
    """95% interval for PR-AUC(b) - PR-AUC(a), resampling companies with replacement."""
    rng = np.random.default_rng(seed)
    companies = test["company"].unique()
    rows_by_company = test.groupby("company").indices
    y = test["target"].to_numpy()
    diffs = []
    for _ in range(n):
        pick = rng.choice(companies, len(companies), replace=True)
        idx = np.concatenate([rows_by_company[c] for c in pick])
        if y[idx].sum() == 0:
            continue
        diffs.append(average_precision_score(y[idx], p_b[idx]) - average_precision_score(y[idx], p_a[idx]))
    diffs = np.array(diffs)
    return {
        "mean_diff": float(diffs.mean()),
        "ci95": [float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))],
        "share_positive": float((diffs > 0).mean()),
        "resamples": int(len(diffs)),
    }


def run_study(panel: pd.DataFrame, actions_used: int, out_path: Path) -> dict:
    month = pd.to_datetime(panel["month"])
    train = panel[(month >= TRAIN[0]) & (month <= TRAIN[1])].reset_index(drop=True)
    test = panel[(month >= TEST[0]) & (month <= TEST[1])].reset_index(drop=True)
    y_tr, y_te = train["target"].to_numpy(), test["target"].to_numpy()

    base = LogisticRegression(max_iter=1000).fit(train[["log_volume_12m"]], y_tr)
    logit = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=0.5)).fit(train[FEATURES], y_tr)
    booster = lgb.train(LGBM_PARAMS, lgb.Dataset(train[FEATURES], label=y_tr), num_boost_round=300)

    preds = {
        "baseline_volume_only": base.predict_proba(test[["log_volume_12m"]])[:, 1],
        "logistic_all_features": logit.predict_proba(test[FEATURES])[:, 1],
        "lightgbm_all_features": booster.predict(test[FEATURES]),
    }
    best = max(
        ("logistic_all_features", "lightgbm_all_features"), key=lambda k: average_precision_score(y_te, preds[k])
    )
    coefs = logit[-1].coef_[0]
    results = {
        "question": "Do complaint patterns warn of a CFPB enforcement action within the next 12 months?",
        "design": {
            "train_months": TRAIN,
            "test_months": TEST,
            "features_window": "previous 12 months only",
            "excluded": "company-months with an action in the previous 12 months (post-action complaint waves)",
            "min_complaints_12m": 50,
        },
        "data": {
            "actions_matched_and_used": int(actions_used),
            "train_rows": int(len(train)),
            "train_positive_rows": int(y_tr.sum()),
            "test_rows": int(len(test)),
            "test_positive_rows": int(y_te.sum()),
            "test_positive_companies": int(test.loc[test["target"] == 1, "company"].nunique()),
            "test_base_rate": float(y_te.mean()),
        },
        "test": {name: _metrics(y_te, p) for name, p in preds.items()},
        "best_pattern_model": best,
        "gain_over_volume_pr_auc": cluster_bootstrap(test, preds["baseline_volume_only"], preds[best]),
        "logistic_standardised_coefficients": dict(zip(FEATURES, np.round(coefs, 3).tolist(), strict=True)),
        "lightgbm_gain_importance": dict(
            zip(
                FEATURES,
                np.round(
                    booster.feature_importance("gain") / max(booster.feature_importance("gain").sum(), 1), 3
                ).tolist(),
                strict=True,
            )
        ),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results
