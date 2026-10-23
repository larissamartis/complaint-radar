import numpy as np
import pandas as pd

from complaint_radar.enforcement.panel import FEATURES, build_panel
from complaint_radar.enforcement.study import cluster_bootstrap, run_study


def monthly_rows(company, months, counts, issue="I", segment="other"):
    return pd.DataFrame(
        {
            "company": company,
            "segment": segment,
            "month": months,
            "issue": issue,
            "n": counts,
            "relief": 0,
            "untimely": 0,
        }
    )


def test_features_use_only_previous_months():
    months = pd.date_range("2020-01-01", periods=24, freq="MS")
    counts = [10] * 23 + [10_000]  # a huge spike in the last month
    panel = build_panel(
        monthly_rows("A", months, counts),
        pd.DataFrame(columns=["company", "date_filed"]),
        "2021-01",
        "2021-12",
        min_volume=1,
    )
    last = panel[panel["month"] == "2021-12-01"].iloc[0]
    assert last["log_volume_12m"] == np.log1p(120)  # months 2020-12 .. 2021-11, the spike month is not included


def test_target_window_and_post_action_exclusion():
    months = pd.date_range("2018-01-01", periods=48, freq="MS")
    actions = pd.DataFrame({"company": ["A"], "date_filed": ["2020-06-15"]})
    panel = build_panel(monthly_rows("A", months, [20] * 48), actions, "2019-01", "2021-12", min_volume=1)
    by_month = panel.set_index("month")["target"]
    assert by_month[pd.Timestamp("2019-07-01")] == 1  # action within the next 12 months (Jul 2019 .. Jun 2020)
    assert by_month[pd.Timestamp("2019-06-01")] == 0  # window Jun 2019 .. May 2020 ends before the action
    assert by_month[pd.Timestamp("2020-06-01")] == 1  # action in the current month counts
    # Jul 2020 .. Jun 2021 come right after the action: excluded to avoid post-action waves
    assert not ((panel["month"] >= "2020-07-01") & (panel["month"] <= "2021-06-01")).any()
    assert pd.Timestamp("2021-07-01") in by_month.index


def test_min_volume_and_issue_shift():
    months = pd.date_range("2019-01-01", periods=24, freq="MS")
    a = pd.concat(
        [
            monthly_rows("A", months[:20], [30] * 20, issue="Fees"),
            monthly_rows("A", months[20:], [30] * 4, issue="Fraud"),
        ]
    )
    tiny = monthly_rows("Tiny", months, [1] * 24)
    panel = build_panel(pd.concat([a, tiny]), pd.DataFrame(columns=["company", "date_filed"]), "2020-12", "2020-12")
    assert set(panel["company"]) == {"A"}  # Tiny has 12 complaints < 50
    assert panel.iloc[0]["issue_shift_jsd"] > 0.9  # last 3 months all "Fraud" vs "Fees" before
    assert set(FEATURES) <= set(panel.columns)


def synthetic_panel(seed=0):
    """Companies whose complaints grow fast and shift issues before an action; volume alone is uninformative."""
    rng = np.random.default_rng(seed)
    rows = []
    months = pd.date_range("2015-01-01", "2024-08-01", freq="MS")
    for c in range(300):
        risky = rng.random() < 0.2
        for m in months:
            signal = risky and rng.random() < 0.3
            rows.append(
                {
                    "company": f"C{c}",
                    "month": m,
                    "log_volume_12m": rng.normal(6, 1),
                    "growth_3m_vs_prior": rng.normal(0.8 if signal else 0, 0.3),
                    "relief_rate_12m": rng.random() * 0.3,
                    "untimely_rate_12m": rng.random() * 0.05,
                    "issue_shift_jsd": rng.random() * (0.8 if signal else 0.3),
                    "n_issues_12m": rng.integers(1, 20),
                    "top_issue_share_12m": rng.random(),
                    "log_months_active": rng.normal(4, 1),
                    "is_bureau": 0,
                    "target": int(signal and rng.random() < 0.6),
                }
            )
    return pd.DataFrame(rows)


def test_study_end_to_end_and_bootstrap(tmp_path):
    res = run_study(synthetic_panel(), actions_used=50, out_path=tmp_path / "enf.json")
    assert (tmp_path / "enf.json").exists()
    t = res["test"]
    assert t["lightgbm_all_features"]["pr_auc"] > t["baseline_volume_only"]["pr_auc"]
    ci = res["gain_over_volume_pr_auc"]["ci95"]
    assert ci[0] > 0  # the planted signal is detected with confidence
    assert set(res["logistic_standardised_coefficients"]) == set(FEATURES)


def test_bootstrap_interval_spans_zero_when_models_are_equal():
    rng = np.random.default_rng(1)
    test = pd.DataFrame({"company": np.repeat([f"C{i}" for i in range(100)], 10), "target": rng.random(1000) < 0.05})
    test["target"] = test["target"].astype(int)
    p = rng.random(1000)
    ci = cluster_bootstrap(test, p, p + rng.normal(0, 1e-9, 1000), n=200)["ci95"]
    assert ci[0] <= 0 <= ci[1]
