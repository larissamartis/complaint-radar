from pathlib import Path

import pandas as pd

from complaint_radar.enforcement.actions import parse_list_page, scrape_actions
from complaint_radar.enforcement.matching import accepted, match_companies, normalize

FIX = Path(__file__).parents[1] / "fixtures" / "enforcement_page.html"


def test_parse_list_page_reads_company_date_url():
    rows = parse_list_page(FIX.read_text(encoding="utf-8"))
    assert [r["company"] for r in rows] == [
        "Synapse Financial Technologies, Inc.",
        "Wise US Inc.",
        "American Honda Finance Corporation",
    ]
    assert rows[0]["date_filed"] == "2025-08-21"
    assert rows[0]["url"] == "https://www.consumerfinance.gov/enforcement/actions/synapse-financial-technologies-inc/"
    assert rows[0]["description"].startswith("On August 21, 2025")


class Resp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class Session:
    """Page 1 and 2 have actions; page 3 repeats page 2 (as the real site does past the end)."""

    def __init__(self):
        page = FIX.read_text(encoding="utf-8")
        self.pages = {1: page, 2: page.replace("wise-us-inc", "other-co").replace("Wise US Inc.", "Other Co")}
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append(params["page"])
        return Resp(self.pages.get(params["page"], self.pages[2]))


def test_scrape_stops_when_no_new_actions():
    s = Session()
    df = scrape_actions(session=s, pause=0)
    assert s.calls == [1, 2, 3]
    assert len(df) == 4 and df["url"].is_unique and df["date_filed"].is_monotonic_increasing


def test_normalize_strips_legal_forms_and_dba():
    assert normalize("Capital One, N.A.") == "capital one"
    assert normalize("CAPITAL ONE FINANCIAL CORPORATION") == "capital one"
    assert normalize("Wells Fargo Bank, N.A.") == "wells fargo bank"
    assert normalize("Block, Inc. d/b/a Cash App") == "block"
    assert (
        normalize("Ocwen Financial Corp. & Ocwen Loan Servicing, LLC")
        == "ocwen financial corp and ocwen loan servicing"
    )


def test_match_companies_methods():
    actions = pd.DataFrame(
        {
            "company": ["Capital One, N.A.", "Navient Corporation", "John Doe", "Experian Information Solutions, Inc."],
            "url": ["u1", "u2", "u3", "u4"],
            "date_filed": ["2025-01-14"] * 4,
        }
    )
    companies = ["CAPITAL ONE FINANCIAL CORPORATION", "Navient Solutions, LLC.", "Experian Information Solutions Inc."]
    m = match_companies(actions, companies, overrides={"u2": "Navient Solutions, LLC."})
    assert list(m["match_method"]) == ["exact", "override", "none", "exact"]
    assert m.loc[0, "matched_company"] == "CAPITAL ONE FINANCIAL CORPORATION"
    assert list(accepted(m)["url"]) == ["u1", "u2", "u4"]


def test_override_to_blank_rejects_a_wrong_automatic_match():
    actions = pd.DataFrame({"company": ["Capital One, N.A."], "url": ["u1"], "date_filed": ["2025-01-14"]})
    m = match_companies(actions, ["CAPITAL ONE FINANCIAL CORPORATION"], overrides={"u1": ""})
    assert m.loc[0, "match_method"] == "override" and accepted(m).empty
