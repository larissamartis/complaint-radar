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


COMPANIES = [  # (name, complaints) - larger companies are preferred when a rule finds several
    ("AMERICAN EXPRESS COMPANY", 50000), ("U.S. BANCORP", 40000), ("REGIONS FINANCIAL CORPORATION", 20000),
    ("Navient Solutions, LLC.", 40000), ("EQUIFAX, INC.", 4_000_000),
    ("TRANSUNION INTERMEDIATE HOLDINGS, INC.", 4_500_000),
    ("USAA Savings Bank", 30000), ("CITIZENS FINANCIAL GROUP, INC.", 15000), ("Citizens Business Bank", 50),
    ("SYNCHRONY FINANCIAL", 85000), ("Paypal Holdings, Inc", 43000), ("Matthew Mortgage LLC", 20),
]  # fmt: skip


def match_one(name, url="u"):
    actions = pd.DataFrame({"company": [name], "url": [url], "date_filed": ["2020-01-01"]})
    return match_companies(actions, [c for c, _ in COMPANIES], volumes=dict(COMPANIES)).iloc[0]


def test_brand_prefix_rules_match_banks_to_parent_names():
    assert match_one("American Express Centurion Bank")["matched_company"] == "AMERICAN EXPRESS COMPANY"
    assert match_one("Regions Bank")["matched_company"] == "REGIONS FINANCIAL CORPORATION"
    assert match_one("Synchrony Bank, f/k/a GE Capital Retail Bank")["matched_company"] == "SYNCHRONY FINANCIAL"
    # "Citizens" is a generic word shared by unrelated banks, so it is never auto-matched: it needs a reviewed override.
    assert match_one("Citizens Bank, N.A.")["match_method"] in ("review", "none")
    action = pd.DataFrame({"company": ["Citizens Bank, N.A."], "url": ["c"], "date_filed": ["2020-01-30"]})
    over = match_companies(action, [c for c, _ in COMPANIES], overrides={"c": "CITIZENS FINANCIAL GROUP, INC."})
    assert over.loc[0, "matched_company"] == "CITIZENS FINANCIAL GROUP, INC."


def test_multi_party_names_are_split():
    m = match_one("Navient Corporation, Navient Solutions, Inc. and Pioneer Credit Recovery, Inc.")
    assert m["matched_company"] == "Navient Solutions, LLC."
    assert match_one("Equifax Inc. and Equifax Consumer Services LLC")["matched_company"] == "EQUIFAX, INC."
    t = match_one("TransUnion; Trans Union, LLC; TransUnion Interactive, Inc.; and John T. Danaher")
    assert t["matched_company"] == "TRANSUNION INTERMEDIATE HOLDINGS, INC."
    assert match_one("PayPal, Inc. and Bill Me Later, Inc.")["matched_company"] == "Paypal Holdings, Inc"


def test_distinctive_first_word_and_alias():
    assert match_one("USAA Federal Savings Bank")["matched_company"] == "USAA Savings Bank"
    assert match_one("U.S. Bank National Association")["matched_company"] == "U.S. BANCORP"


def test_people_named_in_actions_are_not_matched_to_companies():
    m = match_one("Castle & Cooke Mortgage, LLC; Matthew A. Pineda, individually; and Buck L. Hawkins")
    assert m["matched_company"] != "Matthew Mortgage LLC"


def test_first_word_rule_needs_a_dominant_brand():
    companies = {"FREEDOM MORTGAGE CORPORATION": 30000, "Freedom Financial Network": 25000,
                 "TRANSUNION INTERMEDIATE HOLDINGS, INC.": 4_500_000, "TransUnion Rental Screening": 900}  # fmt: skip
    actions = pd.DataFrame({"company": ["Freedom Debt Relief, LLC", "TransUnion Interactive, Inc."],
                            "url": ["f", "t"], "date_filed": ["2017-11-08"] * 2})  # fmt: skip
    m = match_companies(actions, list(companies), volumes=companies).set_index("url")
    assert m.loc["f", "match_method"] == "review"  # two big "Freedom" brands: not safe to pick one
    assert m.loc["t", "matched_company"] == "TRANSUNION INTERMEDIATE HOLDINGS, INC."


def test_generic_single_word_never_drives_a_prefix_match():
    companies = {"AMERICAN EXPRESS COMPANY": 50000}
    actions = pd.DataFrame(
        {"company": ["American Financial Services, Inc."], "url": ["a"], "date_filed": ["2015-01-01"]}
    )
    m = match_companies(actions, list(companies), volumes=companies)
    assert m.loc[0, "matched_company"] is None or m.loc[0, "match_method"] in ("review", "none")


def test_shared_brand_word_with_a_different_business_is_not_accepted():
    # Wrong matches seen in a real run: same first word, different firm.
    companies = {
        "MORGAN STANLEY & CO. LLC": 1284, "Rocket Mortgage, LLC": 9605, "Phoenix Financial Services LLC": 2913,
        "American Debt Services, LLC": 4, "Certified Services, Inc.": 61, "Conduent Incorporated": 2398,
        "WELLS FARGO & COMPANY": 176909, "JPMORGAN CHASE & CO.": 178410, "SUNTRUST BANKS, INC.": 9634,
    }  # fmt: skip
    names = {
        "m": "Morgan Drexen, Inc. and Walter Ledda",
        "r": "Rocket Homes Real Estate LLC, dba Rocket Homes",
        "p": "Phoenix Title Loans, LLC",
        "a": "American Debt Settlement Solutions, Inc.,and Michael DiPanni",
        "c": "Certified Forensic Loan Auditors, LLC, Andrew Lehman, and Michael Carr",
        "k": "Conduent Business Services, LLC",
        "w": "Wells Fargo Bank, N.A.",
        "j": "JPMorgan Chase Bank, N.A.",
        "s": "SunTrust Mortgage, Inc.",
    }
    actions = pd.DataFrame({"company": list(names.values()), "url": list(names), "date_filed": ["2016-01-01"] * 9})
    used = accepted(match_companies(actions, list(companies), volumes=companies)).set_index("url")["matched_company"]
    assert used.to_dict() == {
        "k": "Conduent Incorporated",
        "w": "WELLS FARGO & COMPANY",
        "j": "JPMORGAN CHASE & CO.",
        "s": "SUNTRUST BANKS, INC.",
    }


def test_every_matched_party_is_labelled():
    companies = {"Navient Solutions, LLC.": 40000, "Pioneer Credit Recovery, Inc.": 3000}
    name = "Navient Corporation, Navient Solutions, Inc. and Pioneer Credit Recovery, Inc."
    actions = pd.DataFrame({"company": [name],
                            "url": ["n"], "date_filed": ["2017-01-18"]})  # fmt: skip
    used = accepted(match_companies(actions, list(companies), volumes=companies))
    assert sorted(used["matched_company"]) == ["Navient Solutions, LLC.", "Pioneer Credit Recovery, Inc."]
