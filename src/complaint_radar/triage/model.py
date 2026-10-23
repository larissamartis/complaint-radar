"""Escalation-triage model: will this complaint end with the company giving relief?

Serving model = LightGBM on intake-time structured fields, calibrated with isotonic regression on a later
validation period, so a score of 0.30 means "about 30% of such complaints got relief".
"""

from dataclasses import dataclass, field
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from complaint_radar.triage.features import CATEGORICAL, FEATURES, CompanyGrouper, build_frame

LGBM_PARAMS = {
    "objective": "binary",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_child_samples": 100,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "cat_smooth": 20,
    "verbose": -1,
    "seed": 7,
}


def priority(p: float, quantiles: list[float]) -> str:
    """'high' = top 10% of validation-period scores (>= q90), 'medium' = next 20% (>= q70), else 'low'.

    Isotonic calibration produces plateaus, so ties at the cut-off can make 'high' a little more than 10%.
    """
    if len(quantiles) != 11:
        return "unknown"
    return "high" if p >= quantiles[9] else "medium" if p >= quantiles[7] else "low"


def _as_categories(frame: pd.DataFrame, categories: dict[str, list[str]]) -> pd.DataFrame:
    out = frame.copy()
    for col in CATEGORICAL:
        cats = categories[col]
        # Values never seen in training become missing explicitly (pandas will stop doing this implicitly).
        out[col] = pd.Categorical(out[col].where(out[col].isin(cats)), categories=cats)
    return out


@dataclass
class TriageModel:
    grouper: CompanyGrouper
    categories: dict[str, list[str]]
    booster: lgb.Booster
    calibrator: IsotonicRegression | None = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def fit(cls, train: pd.DataFrame, y_train: np.ndarray, rounds: int = 400) -> "TriageModel":
        grouper = CompanyGrouper().fit(train["company"].fillna("(missing)"))
        frame = build_frame(train, grouper)
        categories = {c: sorted(frame[c].unique().tolist()) for c in CATEGORICAL}
        data = lgb.Dataset(_as_categories(frame, categories), label=y_train, categorical_feature=CATEGORICAL)
        booster = lgb.train(LGBM_PARAMS, data, num_boost_round=rounds)
        return cls(grouper, categories, booster)

    def raw_scores(self, df: pd.DataFrame) -> np.ndarray:
        return self.booster.predict(_as_categories(build_frame(df, self.grouper), self.categories))

    def calibrate(self, valid: pd.DataFrame, y_valid: np.ndarray) -> "TriageModel":
        self.calibrator = IsotonicRegression(out_of_bounds="clip").fit(self.raw_scores(valid), y_valid)
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        raw = self.raw_scores(df)
        return self.calibrator.predict(raw) if self.calibrator is not None else raw

    def reasons(self, df: pd.DataFrame, top: int = 3) -> list[list[dict]]:
        """Top features pushing each score up or down (LightGBM's built-in SHAP values).

        `effect` is in log-odds of the uncalibrated model: the sign shows direction (calibration is monotone),
        the size is relative, not a probability. Categories unseen in training show their raw value but were
        treated as missing by the model.
        """
        frame = build_frame(df, self.grouper)
        contrib = self.booster.predict(_as_categories(frame, self.categories), pred_contrib=True)[:, :-1]
        out = []
        for i, row in enumerate(contrib):
            order = np.argsort(-np.abs(row))[:top]
            out.append(
                [
                    {
                        "feature": FEATURES[j],
                        "value": str(frame.iloc[i][FEATURES[j]]),
                        "effect": round(float(row[j]), 3),
                    }
                    for j in order
                ]
            )
        return out

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "grouper_keep": sorted(self.grouper.keep),
                "categories": self.categories,
                "booster": self.booster.model_to_string(),
                "calibrator": self.calibrator,
                "metadata": self.metadata,
            },
            path,
            compress=3,
        )

    @classmethod
    def load(cls, path: Path) -> "TriageModel":
        blob = joblib.load(path)
        grouper = CompanyGrouper()
        grouper.keep = set(blob["grouper_keep"])
        booster = lgb.Booster(model_str=blob["booster"])
        return cls(grouper, blob["categories"], booster, blob["calibrator"], blob["metadata"])
