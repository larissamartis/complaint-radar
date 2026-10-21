"""Canonical complaint schema shared by the archive backfill and the daily snapshot."""

COLUMN_MAP: dict[str, str] = {
    "Date received": "date_received",
    "Product": "product",
    "Sub-product": "sub_product",
    "Issue": "issue",
    "Sub-issue": "sub_issue",
    "Consumer complaint narrative": "narrative",
    "Company public response": "company_public_response",
    "Company": "company",
    "State": "state",
    "ZIP code": "zip_code",
    "Tags": "tags",
    "Submitted via": "submitted_via",
    "Date sent to company": "date_sent_to_company",
    "Company response to consumer": "company_response",
    "Timely response?": "timely_response",
    "Complaint ID": "complaint_id",
}

CANONICAL_COLUMNS: tuple[str, ...] = (
    "complaint_id",
    "date_received",
    "product",
    "sub_product",
    "issue",
    "sub_issue",
    "narrative",
    "company_public_response",
    "company",
    "state",
    "zip_code",
    "tags",
    "submitted_via",
    "date_sent_to_company",
    "company_response",
    "timely_response",
    "row_hash",
    "source_file",
)

# Structured business columns only: the narrative is excluded so that archive rows and
# live-snapshot rows (which no longer carry text) hash identically.
HASH_COLUMNS: tuple[str, ...] = tuple(
    c for c in CANONICAL_COLUMNS if c not in {"complaint_id", "narrative", "row_hash", "source_file"}
)

DATE_COLUMNS = frozenset({"date_received", "date_sent_to_company"})

# The three nationwide credit bureaus get their own monitoring segment (about 90% of volume, mostly templates).
# Must match dbt/seeds/bureau_companies.csv (a test checks this).
BUREAU_COMPANIES: tuple[str, ...] = (
    "TRANSUNION INTERMEDIATE HOLDINGS, INC.",
    "Experian Information Solutions Inc.",
    "EQUIFAX, INC.",
)
