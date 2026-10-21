import numpy as np
import pandas as pd

from complaint_radar.detect.backtest import evaluate, label_incidents
from complaint_radar.detect.detectors import add_baseline_features, alerts


def series(counts, company="A", start="2023-01-02"):
    weeks = pd.date_range(start, periods=len(counts), freq="W-MON")
    return pd.DataFrame(
        {"segment": "other", "company": company, "product": "P", "issue": "I", "week": weeks, "n": counts}
    )


def rising_incident():
    # 40 quiet weeks (~15/wk), then a 4-week ramp to a peak of 200, then back to normal.
    rng = np.random.default_rng(1)
    counts = list(rng.poisson(15, 40)) + [40, 80, 140, 200] + list(rng.poisson(15, 20))
    return series(counts)


def test_label_incidents_finds_peak_week():
    inc = label_incidents(rising_incident())
    assert len(inc) == 1
    assert inc.iloc[0]["peak_week"] == pd.Timestamp("2023-01-02") + pd.Timedelta(weeks=43)


def test_caught_with_lead_time_and_no_false_alarm():
    weekly = add_baseline_features(rising_incident())
    inc = label_incidents(weekly)
    al = alerts(weekly, "volume_rule", 2.0)
    m = evaluate(al, inc, weekly, pd.Timestamp("2023-01-01"), pd.Timestamp("2025-01-01"))
    assert m["incidents"] == 1 and m["caught"] == 1
    assert m["median_lead_days"] == 21  # first alert on the 40-count week, 3 weeks before the peak
    assert m["false_alarms"] == 0


def test_isolated_spike_is_false_alarm_and_late_alert_is_not_a_catch():
    rng = np.random.default_rng(2)
    quiet = list(rng.poisson(15, 30))
    counts = quiet[:20] + [90] + quiet[20:]  # a single-week blip: not a monthly incident
    weekly = add_baseline_features(series(counts))
    m = evaluate(
        alerts(weekly, "volume_rule", 2.0),
        label_incidents(weekly),
        weekly,
        pd.Timestamp("2023-01-01"),
        pd.Timestamp("2025-01-01"),
    )
    assert m["incidents"] == 0 and m["false_alarms"] == 1
