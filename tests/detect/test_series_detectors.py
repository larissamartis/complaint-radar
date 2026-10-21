from datetime import date, timedelta

import duckdb
import numpy as np
import pandas as pd

from complaint_radar.detect.detectors import DETECTORS, add_baseline_features, alerts, score
from complaint_radar.detect.series import weekly_series

MONDAY = date(2024, 1, 1)  # a Monday


def daily_table(con, rows):
    con.execute(
        "create table daily (date_received date, segment varchar, company varchar, product varchar, "
        "issue varchar, n_complaints bigint)"
    )
    con.executemany("insert into daily values (?, 'other', ?, 'P', 'I', ?)", rows)


def test_weekly_series_zero_fills_and_starts_monday():
    con = duckdb.connect()
    daily_table(con, [(MONDAY + timedelta(days=2), "A", 3), (MONDAY + timedelta(days=22), "A", 5)])
    df = weekly_series(con, "daily", MONDAY, MONDAY + timedelta(days=27))
    assert list(df["week"]) == [pd.Timestamp(MONDAY + timedelta(weeks=k)) for k in range(4)]
    assert list(df["n"]) == [3, 0, 0, 5]
    assert all(pd.Timestamp(w).dayofweek == 0 for w in df["week"])


def synthetic(n_weeks=30, base=10, spike_week=20, spike=60, seed=0):
    rng = np.random.default_rng(seed)
    counts = rng.poisson(base, n_weeks)
    counts[spike_week] = spike
    weeks = pd.date_range("2024-01-01", periods=n_weeks, freq="W-MON")
    return pd.DataFrame({"segment": "other", "company": "A", "product": "P", "issue": "I", "week": weeks, "n": counts})


def test_baseline_excludes_current_week():
    df = add_baseline_features(synthetic())
    row = df.iloc[20]
    assert row["mean_8"] == df["n"].iloc[12:20].mean()  # weeks 12..19 only, never week 20 itself


def test_short_history_has_no_score():
    df = add_baseline_features(synthetic())
    for det in DETECTORS:
        assert score(df, det).iloc[:8].isna().all()


def test_single_spike_is_the_only_alert_for_every_detector():
    df = add_baseline_features(synthetic())
    for det, threshold in {"volume_rule": 2.0, "robust_z": 4.0, "nb_surprise": 4.0}.items():
        hits = alerts(df, det, threshold)
        assert list(hits["week"]) == [df["week"].iloc[20]], det


def test_nb_surprise_monotonic_in_count():
    df = add_baseline_features(synthetic())
    low, high = df.copy(), df.copy()
    low.loc[20, "n"], high.loc[20, "n"] = 25, 80
    assert score(high, "nb_surprise").iloc[20] > score(low, "nb_surprise").iloc[20] > 0
