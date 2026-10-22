import numpy as np
import pandas as pd

from complaint_radar.monitor.drift import drift_report, psi, score_psi, status


def test_psi_zero_for_identical_and_large_for_shifted():
    mix = {"Credit card": 0.5, "Mortgage": 0.3, "Debt collection": 0.2}
    assert abs(psi(mix, mix)) < 1e-9
    assert psi(mix, {"Credit card": 0.1, "Mortgage": 0.1, "Debt collection": 0.8}) > 0.25


def test_score_psi_against_reference_deciles():
    rng = np.random.default_rng(0)
    ref = rng.beta(2, 5, 50_000)
    q = np.quantile(ref, np.linspace(0, 1, 11)).tolist()
    assert score_psi(q, rng.beta(2, 5, 5_000)) < 0.05  # same distribution
    assert score_psi(q, rng.beta(5, 2, 5_000)) > 0.25  # scores shifted upward


def test_status_bands():
    assert status(0.05) == "stable" and status(0.2) == "moderate" and status(0.4) == "significant"
    assert status(float("nan")) == "insufficient_data"


def test_drift_report_needs_enough_rows():
    meta = {"reference_product_mix": {"A": 1.0}, "reference_score_quantiles": [i / 10 for i in range(11)]}
    small = drift_report(meta, pd.Series(["A"] * 10), np.full(10, 0.5))
    assert {r["status"] for r in small} == {"insufficient_data"}
    big = drift_report(meta, pd.Series(["A"] * 500), np.linspace(0, 1, 500))
    assert [r["metric"] for r in big] == ["product_mix_psi", "score_psi"]
    assert all(r["status"] == "stable" for r in big)
