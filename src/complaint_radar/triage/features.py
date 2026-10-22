"""Features for escalation triage: only fields known when a complaint arrives.

Left out on purpose (known only after the company responds, so using them would leak the outcome):
company_response (the label itself), timely_response, company_public_response, date_sent_to_company.
"""

import pandas as pd

CATEGORICAL = ["product", "sub_product", "issue", "sub_issue", "company", "state", "submitted_via", "tags"]
NUMERIC = ["month", "weekday"]
FEATURES = CATEGORICAL + NUMERIC
TARGET = "relief_given"
MAX_COMPANIES = 300  # remaining companies are grouped as "Other" (decided on training data only)


class CompanyGrouper:
    """Keep the most frequent companies seen in training; map everything else to 'Other'."""

    def __init__(self, max_companies: int = MAX_COMPANIES):
        self.max_companies = max_companies
        self.keep: set[str] = set()

    def fit(self, companies: pd.Series) -> "CompanyGrouper":
        self.keep = set(companies.value_counts().head(self.max_companies).index)
        return self

    def transform(self, companies: pd.Series) -> pd.Series:
        return companies.where(companies.isin(self.keep), "Other")


def build_frame(df: pd.DataFrame, grouper: CompanyGrouper) -> pd.DataFrame:
    """Model input frame: categorical columns as strings ('(missing)' for nulls) plus calendar features."""
    out = pd.DataFrame(index=df.index)
    for col in CATEGORICAL:
        values = df[col] if col in df else pd.Series(None, index=df.index, dtype="object")
        out[col] = values.fillna("(missing)").astype(str)
    out["company"] = grouper.transform(out["company"])
    received = pd.to_datetime(df["date_received"])
    out["month"] = received.dt.month.astype(int)
    out["weekday"] = received.dt.weekday.astype(int)
    return out[FEATURES]
