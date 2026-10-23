"""Match enforcement-action company names to CFPB complaint company names.

Names differ in legal form and wording ("Capital One, N.A." vs "CAPITAL ONE FINANCIAL CORPORATION"). The match is:
1. a reviewed override file (action URL -> complaint company), which always wins;
2. an exact match after normalisation (lowercase, punctuation and legal suffixes removed, "&" -> "and");
3. otherwise the closest name sharing the first normalised word, accepted at similarity >= 0.90 and flagged for
   review between 0.80 and 0.90.
Many actions target individuals or companies with no complaint history; those stay unmatched.
"""

import re
from difflib import SequenceMatcher

import pandas as pd

ACCEPT, REVIEW = 0.90, 0.80
_SUFFIXES = {
    "inc", "incorporated", "llc", "l", "c", "corp", "corporation", "co", "company", "ltd", "limited", "lp", "llp",
    "plc", "na", "n", "a", "pllc", "pc", "the", "holdings", "holding", "group", "financial", "services",
    "national", "association", "usa", "us",
}  # fmt: skip
_DBA = re.compile(r"\b(d/?b/?a|f/?k/?a|a/?k/?a|formerly known as|doing business as)\b", re.I)


def normalize(name: str) -> str:
    if not isinstance(name, str):
        return ""
    name = _DBA.split(name)[0]  # keep the legal name before any "d/b/a ..."
    name = name.lower().replace("&", " and ")
    tokens = re.findall(r"[a-z0-9]+", name)
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    tokens = [t for t in tokens if t not in {"the"}]
    return " ".join(tokens)


def match_companies(
    actions: pd.DataFrame, companies: list[str], overrides: dict[str, str] | None = None
) -> pd.DataFrame:
    """Add matched_company, match_score and match_method (override | exact | fuzzy | review | none)."""
    overrides = overrides or {}
    norm_to_company: dict[str, str] = {}
    for c in companies:
        norm_to_company.setdefault(normalize(c), c)
    by_first: dict[str, list[str]] = {}
    for n in norm_to_company:
        if n:
            by_first.setdefault(n.split()[0], []).append(n)

    out = []
    for row in actions.itertuples():
        if row.url in overrides:
            target = overrides[row.url]
            out.append((target or None, 1.0, "override"))
            continue
        n = normalize(row.company)
        if n and n in norm_to_company:
            out.append((norm_to_company[n], 1.0, "exact"))
            continue
        best, score = None, 0.0
        for cand in by_first.get(n.split()[0], []) if n else []:
            s = SequenceMatcher(None, n, cand).ratio()
            if s > score:
                best, score = cand, s
        if best and score >= ACCEPT:
            out.append((norm_to_company[best], round(score, 3), "fuzzy"))
        elif best and score >= REVIEW:
            out.append((norm_to_company[best], round(score, 3), "review"))
        else:
            out.append((None, round(score, 3), "none"))
    result = actions.copy()
    result[["matched_company", "match_score", "match_method"]] = pd.DataFrame(out, index=actions.index)
    return result


def accepted(matches: pd.DataFrame) -> pd.DataFrame:
    """Actions usable in the study: overrides with a target, exact and fuzzy matches (not 'review' or 'none')."""
    ok = matches["match_method"].isin(["override", "exact", "fuzzy"]) & matches["matched_company"].notna()
    return matches[ok]
