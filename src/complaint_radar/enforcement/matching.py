"""Match enforcement-action company names to CFPB complaint company names.

Enforcement actions often name several entities ("Navient Corporation, Navient Solutions, Inc. and Pioneer Credit
Recovery, Inc.") and use a bank's legal name where complaints use its parent ("Regions Bank" vs "REGIONS FINANCIAL
CORPORATION"). Each action is split into its parties, and each party is tried against the complaint companies with
rules from strictest to loosest:

  override     a reviewed mapping (action URL -> complaint company; blank = reject), always wins
  exact        identical after normalisation (lowercase, punctuation and legal suffixes removed)
  alias        a short documented list of known brand names (e.g. "U.S. Bank" -> "U.S. Bancorp"); the alias may
               be followed by any words ("American Express Centurion Bank")
  prefix       one name is a word-prefix of the other, and the extra words are only institution words
               ("Regions" + "Bank") or the shared part is two+ words with a distinctive one ("Colony Ridge")
  first_token  a distinctive first word shared by both, the rest of both names only institution words
               ("SunTrust Mortgage" vs "SunTrust Banks"), and one company holds >= 90% of that brand's complaints
  fuzzy        close spelling within the same first word (similarity >= 0.90); 0.80-0.90 is flagged "review"

A shared distinctive first word that fails these checks is flagged "review", never accepted: "Rocket Homes Real
Estate" is not "Rocket Mortgage", and "Phoenix Title Loans" is not "Phoenix Financial Services".
When a rule finds several companies, the one with the most complaints wins. People named in actions do not look
like companies (no legal or business words), so the brand rules never apply to them.
"""

import re
from difflib import SequenceMatcher

import pandas as pd

ACCEPT, REVIEW = 0.90, 0.80
DOMINANT_SHARE = 0.90  # share of the brand's complaint volume the largest company must hold for a first-word match
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
    "chase": "jpmorgan chase",
    "american express": "american express",
}
# Words that describe the kind of institution rather than the brand ("SunTrust" + "Mortgage").
_INSTITUTION_WORDS = {
    "bank", "banks", "bankshares", "bancorp", "mortgage", "savings", "federal", "national", "fsb", "f", "s", "b",
    "interactive", "intermediate", "rental", "screening", "solutions", "consumer", "trust", "card", "cards",
    "bankcard", "servicing", "insurance", "loan", "loans", "lending", "finance", "credit", "payment", "payments",
    "systems", "worldwide", "technologies", "digital", "acceptance", "funding", "automotive", "business",
    "education", "and", "of", "america",
}  # fmt: skip
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
    while tokens and (tokens[-1] in _SUFFIXES or tokens[-1] == "and"):  # "Wells Fargo & Company" -> "wells fargo"
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


def _brand_like(norm: str) -> bool:
    """Two or more words, or one distinctive word of 5+ letters (not "american", "first", ...)."""
    words = norm.split()
    return len(words) >= 2 or (len(norm) >= 5 and norm not in _GENERIC_FIRST)


def _institution_only(words: list[str]) -> bool:
    return all(w in _INSTITUTION_WORDS for w in words)


def _same_brand_prefix(short: str, long: str) -> bool:
    """`short` is a word-prefix of `long` and the difference is not a different business."""
    if not _is_word_prefix(short, long) or not (_brand_like(short) and _brand_like(long)):
        return False
    shared, extra = short.split(), long.split()[len(short.split()) :]
    return _institution_only(extra) or (len(shared) >= 2 and any(w not in _GENERIC_FIRST for w in shared))


def _alias(n: str) -> str | None:
    for key, target in ALIASES.items():
        if _is_word_prefix(key, n):
            return target
    return None


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
        target = _alias(n)
        if target in self.by_norm:
            return target, 1.0, "alias"
        first = n.split()[0]
        if company_like:
            same_first = self.by_first.get(first, [])
            cands = [c for c in same_first if _same_brand_prefix(c, n) or _same_brand_prefix(n, c)]
            if cands:
                return self.biggest(cands), 0.95, "prefix"
            if len(first) >= 4 and first not in _GENERIC_FIRST and same_first:
                rest = n.split()[1:]
                brand = [c for c in same_first if _institution_only(rest) and _institution_only(c.split()[1:])]
                top = self.biggest(brand or same_first)
                total = sum(self.volume.get(c, 0) for c in same_first)
                # Only accept when one company clearly owns the brand ("TransUnion"); with several sizeable
                # companies sharing the word ("Freedom Mortgage" vs "Freedom Financial") send it to review.
                if brand and (total == 0 or self.volume.get(top, 0) >= DOMINANT_SHARE * total):
                    return top, 0.9, "first_token"
                return top, 0.85, "review"
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
    """Add the best match (matched_company, matched_party, match_score, match_method) and every accepted
    company named in the action (matched_companies, "|"-separated): one action can sanction several firms."""
    overrides = overrides or {}
    index = _Index(companies, volumes or {})
    out = []
    for row in actions.itertuples():
        if row.url in overrides:
            target = overrides[row.url] or None
            out.append((target.split("|")[0] if target else None, None, 1.0, "override", target))
            continue
        results = [(*index.match(n, like), n) for n, like in parties(row.company)]
        if not results:
            out.append((None, None, 0.0, "none", None))
            continue
        norm, score, method, party = min(results, key=lambda r: (_RANK[r[2]], -index.volume.get(r[0] or "", 0)))
        all_ok = sorted({index.by_norm[r[0]] for r in results if r[0] and r[2] in ACCEPTED_METHODS})
        out.append((index.by_norm.get(norm) if norm else None, party, score, method, "|".join(all_ok) or None))
    result = actions.copy()
    cols = ["matched_company", "matched_party", "match_score", "match_method", "matched_companies"]
    result[cols] = pd.DataFrame(out, index=actions.index, columns=cols)
    return result


def accepted(matches: pd.DataFrame) -> pd.DataFrame:
    """One row per (action, sanctioned company) with an accepted match; 'review' and 'none' are left out."""
    ok = matches[matches["match_method"].isin(ACCEPTED_METHODS) & matches["matched_companies"].notna()].copy()
    ok["matched_company"] = ok["matched_companies"].str.split("|")
    return ok.explode("matched_company").drop_duplicates(["url", "matched_company"]).reset_index(drop=True)
