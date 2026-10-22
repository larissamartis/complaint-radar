from datetime import date

import pandas as pd

from complaint_radar.detect.patterns import flag_cross_company_waves


def alerts(rows):
    return pd.DataFrame(rows, columns=["week_start", "company", "product", "issue"])


def test_same_issue_across_many_companies_is_a_wave():
    w = date(2026, 10, 5)
    rows = [(w, f"Lender {i}", "Credit reporting", "Incorrect information on your report") for i in range(6)]
    rows += [(w, "MOHELA", "Student loan", "Dealing with your lender or servicer")]
    out = flag_cross_company_waves(alerts(rows), min_companies=5)
    assert (out.loc[out["company"] != "MOHELA", "pattern"] == "cross_company_wave").all()
    assert out.loc[out["company"] == "MOHELA", "pattern"].item() == "single_company"
    assert out.loc[0, "wave_companies"] == 6


def test_wave_requires_same_week():
    rows = [(date(2026, 10, 5 + 7 * (i % 2)), f"Lender {i}", "P", "I") for i in range(6)]  # 3 per week
    out = flag_cross_company_waves(alerts(rows), min_companies=5)
    assert (out["pattern"] == "single_company").all()


def test_empty_alerts():
    out = flag_cross_company_waves(alerts([]), min_companies=5)
    assert out.empty and "pattern" in out.columns
