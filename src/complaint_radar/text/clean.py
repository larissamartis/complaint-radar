"""Normalise CFPB complaint narratives before modelling."""

import re

# CFPB redacts personal data as XX, XXXX, XX/XX/XXXX and amounts as {$123.45}.
_REDACTION = re.compile(r"\bX{2,}(?:/X{2,})*\b")
_AMOUNT = re.compile(r"\{\$[\d,.]+\}")
_SPACE = re.compile(r"\s+")
_WORD = re.compile(r"[a-z0-9']+")


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = _AMOUNT.sub(" ", _REDACTION.sub(" ", text))
    return _SPACE.sub(" ", text).strip()


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())
