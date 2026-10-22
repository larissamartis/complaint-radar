"""Plain-English alert summaries from a small local LLM, with a grounded template fallback.

The model only sees the alert's facts and a few real example complaints. Its answer is accepted only if
every number in it appears in those facts or examples; otherwise (and whenever the model is unavailable)
the deterministic template is used. Each summary records which method produced it.
"""

import re

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
MAX_SENTENCES = 3

PROMPT = """You write one short alert note for a bank's complaints team.

Facts (the only numbers you may use):
{facts}

Example complaints from customers (for what people describe; do not quote personal details):
{examples}

Write 2-3 plain sentences: what is rising, by how much, and what customers say is going wrong.
Do not invent numbers, causes, dates or company actions. Do not use bullet points or headings."""


def facts_text(alert: dict) -> str:
    lines = [
        f"Company: {alert['company']}",
        f"Product: {alert['product']}",
        f"Issue: {alert['issue']}",
        f"Week starting: {alert['week_start']}",
        f"Complaints this week: {int(alert['n'])}",
        f"Usually expected: {alert['expected']:.0f}",
        f"Ratio to expected: {alert['score']:.1f}x",
    ]
    if alert.get("pattern") == "cross_company_wave":
        lines.append(f"The same issue rose at {int(alert['wave_companies'])} companies in the same week.")
    return "\n".join(lines)


def template_summary(alert: dict) -> str:
    text = (
        f'{alert["company"]} received {int(alert["n"])} complaints about "{alert["issue"]}" '
        f"({alert['product']}) in the week starting {alert['week_start']}, "
        f"{alert['score']:.1f}x the usual {alert['expected']:.0f}."
    )
    if alert.get("pattern") == "cross_company_wave":
        text += (
            f" The same issue rose at {int(alert['wave_companies'])} companies that week, "
            "which points to a shared cause rather than one company's failure."
        )
    return text


def _numbers(text: str) -> set[float]:
    return {float(n.replace(",", "")) for n in _NUMBER.findall(text)}


def _grounded(reply: str, allowed_text: str) -> set[float]:
    allowed = _numbers(allowed_text)
    allowed |= {float(round(a)) for a in allowed}
    return {n for n in _numbers(reply) if n not in allowed}


def explain(alert: dict, examples: list[str], client=None) -> dict:
    """Return {'summary', 'method' ('llm' | 'template'), 'fallback_reason'}."""
    if client is None:
        return {"summary": template_summary(alert), "method": "template", "fallback_reason": "no model configured"}
    facts = facts_text(alert)
    shown = [e[:600] for e in examples[:3]]
    prompt = PROMPT.format(facts=facts, examples="\n".join(f"- {e}" for e in shown) or "- (none available)")
    try:
        reply = " ".join(client.generate(prompt).split())
        reply = " ".join(_SENTENCE_END.split(reply)[:MAX_SENTENCES])  # small models ignore length limits
    except Exception as exc:  # any model/server failure must not break the pipeline
        return {"summary": template_summary(alert), "method": "template", "fallback_reason": f"{type(exc).__name__}"}
    unsupported = _grounded(reply, facts + " " + " ".join(shown))
    if not reply or unsupported:
        reason = f"unsupported numbers {sorted(unsupported)}" if unsupported else "empty reply"
        return {"summary": template_summary(alert), "method": "template", "fallback_reason": reason}
    return {"summary": reply, "method": "llm", "fallback_reason": None}
