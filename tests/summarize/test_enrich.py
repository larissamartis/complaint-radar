from datetime import date

import pandas as pd

from complaint_radar.summarize.enrich import MAX_LLM_SUMMARIES, enrich_alerts

LOOKUP = {
    "Student loan||Servicing": {
        "docs": 100,
        "topics": [{"topic": 3, "label": "Payments blocked", "share": 0.6, "examples": ["I cannot make a payment."]}],
    }
}


def alerts(n):
    return pd.DataFrame(
        [
            {
                "company": f"C{i}",
                "product": "Student loan",
                "issue": "Servicing",
                "week_start": date(2026, 10, 5),
                "n": 40 + i,
                "expected": 10.0,
                "score": 4.0 + i,
                "pattern": "single_company",
                "wave_companies": 1,
            }
            for i in range(n)
        ]
    )


class Echo:
    def generate(self, prompt):
        return "Complaints rose."


def test_top_alerts_get_llm_and_rest_get_template():
    out = enrich_alerts(alerts(MAX_LLM_SUMMARIES + 2), llm=Echo(), lookup=LOOKUP)
    assert list(out["summary_method"]).count("llm") == MAX_LLM_SUMMARIES
    assert out["score"].is_monotonic_decreasing
    assert "Payments blocked" in out.loc[0, "typical_topics"]


def test_without_lookup_entry_topics_are_empty():
    out = enrich_alerts(alerts(1), llm=None, lookup={})
    assert out.loc[0, "typical_topics"] == "[]" and out.loc[0, "summary_method"] == "template"
