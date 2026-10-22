"""Attach pattern labels, typical topics and a summary to each new alert."""

import json
from functools import lru_cache
from importlib import resources

import pandas as pd

from complaint_radar.summarize.explain import explain, template_summary

MAX_LLM_SUMMARIES = 10  # CPU budget per daily run; remaining alerts get the template summary


@lru_cache(maxsize=1)
def topic_lookup() -> dict:
    """Topic lookup built from the narrative archive (src/complaint_radar/data/topic_lookup.json)."""
    path = resources.files("complaint_radar") / "data" / "topic_lookup.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def enrich_alerts(alerts: pd.DataFrame, llm=None, lookup: dict | None = None) -> pd.DataFrame:
    lookup = topic_lookup() if lookup is None else lookup
    out = alerts.sort_values("score", ascending=False).reset_index(drop=True)
    summaries, methods, topics = [], [], []
    for i, row in enumerate(out.to_dict("records")):
        issue = row["issue"] if isinstance(row["issue"], str) and row["issue"] else "(none)"
        entry = lookup.get(f"{row['product']}||{issue}") or {"topics": []}
        examples = [e for t in entry["topics"] for e in t["examples"]]
        topics.append(json.dumps([{"label": t["label"], "share": t["share"]} for t in entry["topics"]]))
        if i < MAX_LLM_SUMMARIES:
            res = explain(row, examples, client=llm)
            summaries.append(res["summary"])
            methods.append(res["method"])
        else:
            summaries.append(template_summary(row))
            methods.append("template")
    return out.assign(summary=summaries, summary_method=methods, typical_topics=topics)
