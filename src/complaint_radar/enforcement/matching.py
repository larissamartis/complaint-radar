"""Match enforcement-action company names to CFPB complaint company names.

Enforcement actions often name several entities ("Navient Corporation, Navient Solutions, Inc. and Pioneer Credit
Recovery, Inc.") and use a bank's legal name where complaints use its parent ("Regions Bank" vs "REGIONS FINANCIAL
CORPORATION"). Each action is split into its parties, and each party is tried against the complaint companies with
rules from strictest to loosest:

  override     a reviewed mapping (action URL -> complaint company; blank = reject), always wins
  exact        identical after normalisation (lowercase, punctuation and legal suffixes removed)
  alias        a short documented list of known name differences (e.g. "U.S. Bank" -> "U.S. Bancorp")
  prefix       one name is a word-prefix of the other (same brand); only for parties that look like companies
  first_token  a distinctive first word shared by both (e.g. "USAA"); only for company-like parties
  fuzzy        close spelling within the same first word (similarity >= 0.90); 0.80-0.90 is flagged "review"

When a rule finds several companies, the one with the most complaints wins. People named in actions do not look
like companies (no legal or business words), so the brand rules never apply to them.
"""

import re
from difflib import SequenceMatcher

import pandas as pd

ACCEPT, REVIEW = 0.90, 0.80
ACCEPTED_METHODS = ("override", "exact", "alias", "prefix", "first_token", "fuzzy")
_RANK = {m: i for i, m in enumerate(["exact", "alias", "prefix", "first_token", "fuzzy", "review", "none"])}

_SUFFIXES = {
    "inc", "incorporated", "llc", "l", "c", "corp", "corporation", "co", "company", "ltd", "limited", "lp", "llp",
    "plc", "na", "n", "a", "pllc", "pc", "the", "holdings", "holding", "group", "financial", "services",
    "national", "association", "usa", "us",
}  # fmt: skip
# Normalised action name -> normalised complaint name, for brands whose names differ beyond the rules above.
ALIASES = {
    "u s bank": "u s bancorp",
    "chase bank": "jpmorgan chase and",
    "chase": "jpmorgan chase and",
}
_GENERIC_FIRST = {
    "first", "american", "national", "united", "citizens", "community", "bank", "new", "great", "southern",
    "northern", "western", "eastern", "central", "capital", "credit", "home", "u", "global", "premier", "pacific",
    "atlantic", "midwest", "security", "peoples", "farmers", "state", "city", "federal", "mutual", "advance",
    "consumer", "fidelity", "guaranty", "heritage", "liberty", "mid", "north", "south", "west", "east", "one",
    "america", "main", "old", "union", "pioneer", "summit", "integrity", "alliance", "student", "auto", "car",
    "mortgage", "financial", "loan", "loans", "debt", "legal", "law", "tax", "payday", "cash", "money", "check",
    "title", "lending", "rent", "rental", "secure", "direct", "express", "prime", "smart", "best", "total",
}  # fmt: skip
_DBA = re.compile(r"\b(d/?b/?a|f/?k/?a|n/?k/?a|a/?k/?a|formerly known as|doing business as|formerly)\b", re.I)
_LEGAL_AFTER_COMMA = r"\s*(inc|llc|l\.?l\.?c|corp|corporation|ltd|n\.?\s?a|lp|l\.?p|llp|plc|fsb|f\.?s\.?b|co)\b"
_SPLIT = re.compile(rf";|\band\b|,(?!{_LEGAL_AFTER_COMMA})", re.I)
_COMPANY_WORDS = re.compile(
    r"\b(inc|llc|l\.l\.c|corp|corporation|company|co|bank|bancorp|n\.a|fsb|lp|llp|plc|ltd|financial|services|group|"
    r"holdings|credit|capital|mortgage|loans?|funding|card|express|savings|trust|union|association|interactive|"
    r"servicing|acceptance|finance|lending|payments?)\b",
    re.I,
)


def normalize(name: str) -> str:
    if not isinstance(name, str):
        return ""
    name = _DBA.split(name)[0]  # keep the legal name before any "d/b/a ..."
    name = name.lower().replace("&", " and ")
    tokens = re.findall(r"[a-z0-9]+", name)
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    tokens = [t for t in tokens if t != "the"]
    return " ".join(tokens)


def parties(name: str) -> list[tuple[str, bool]]:
    """(normalised party name, looks like a company) for each party named in an action."""
    out = []
    for part in _SPLIT.split(_DBA.split(name)[0] if isinstance(name, str) else ""):
        n = normalize(part)
        if n and len(n) > 1:
            out.append((n, bool(_COMPANY_WORDS.search(part))))
    return out


def _is_word_prefix(short: str, long: str) -> bool:
    return long == short or long.startswith(short + " ")


class _Index:
    def __init__(self, companies: list[str], volumes: dict[str, float]):
        self.by_norm: dict[str, str] = {}
        for c in sorted(companies, key=lambda c: -volumes.get(c, 0)):
            self.by_norm.setdefault(normalize(c), c)  # the largest company keeps a shared normalised name
        self.volume = {n: volumes.get(c, 0) for n, c in self.by_norm.items()}
        self.by_first: dict[str, list[str]] = {}
        for n in self.by_norm:
            if n:
                self.by_first.setdefault(n.split()[0], []).append(n)

    def biggest(self, norms: list[str]) -> str | None:
        return max(norms, key=lambda n: self.volume.get(n, 0)) if norms else None

    def match(self, n: str, company_like: bool) -> tuple[str | None, float, str]:
        if n in self.by_norm:
            return n, 1.0, "exact"
        if n in ALIASES and ALIASES[n] in self.by_norm:
            return ALIASES[n], 1.0, "alias"
        first = n.split()[0]
        if company_like:
            cands = [
                c for c in self.by_first.get(first, [])
                if (_is_word_prefix(c, n) or _is_word_prefix(n, c))
                and (len(c.split()) >= 2 or len(c) >= 5) and (len(n.split()) >= 2 or len(n) >= 5)
            ]  # fmt: skip
            if cands:
                return self.biggest(cands), 0.95, "prefix"
            if len(first) >= 4 and first not in _GENERIC_FIRST and self.by_first.get(first):
                return self.biggest(self.by_first[first]), 0.9, "first_token"
        best, score = None, 0.0
        for cand in self.by_first.get(first, []):
            s = SequenceMatcher(None, n, cand).ratio()
            if s > score:
                best, score = cand, s
        if best and score >= ACCEPT:
            return best, round(score, 3), "fuzzy"
        if best and score >= REVIEW:
            return best, round(score, 3), "review"
        return None, round(score, 3), "none"


def match_companies(
    actions: pd.DataFrame,
    companies: list[str],
    overrides: dict[str, str] | None = None,
    volumes: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Add matched_company, matched_party, match_score and match_method to each action."""
    overrides = overrides or {}
    index = _Index(companies, volumes or {})
    out = []
    for row in actions.itertuples():
        if row.url in overrides:
            out.append((overrides[row.url] or None, None, 1.0, "override"))
            continue
        results = [(*index.match(n, like), n) for n, like in parties(row.company)]
        if not results:
            out.append((None, None, 0.0, "none"))
            continue
        norm, score, method, party = min(results, key=lambda r: (_RANK[r[2]], -index.volume.get(r[0] or "", 0)))
        out.append((index.by_norm.get(norm) if norm else None, party, score, method))
    result = actions.copy()
    cols = ["matched_company", "matched_party", "match_score", "match_method"]
    result[cols] = pd.DataFrame(out, index=actions.index, columns=cols)
    return result


def accepted(matches: pd.DataFrame) -> pd.DataFrame:
    """Actions usable in the study: every accepted method with a target company ('review' and 'none' are not)."""
    ok = matches["match_method"].isin(ACCEPTED_METHODS) & matches["matched_company"].notna()
    return matches[ok]
