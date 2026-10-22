"""End-to-end topic build: fit on the embedded sample, name topics, distil to the full corpus, write lookups."""

import json
import logging
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from complaint_radar.text.topics import build_lookup, evaluate_distillation, fit_topics, keyword_label, save_lookup

log = logging.getLogger(__name__)

LABEL_PROMPT = """Name this group of customer complaints in 3 to 6 plain words
(for example "Overdraft fees charged twice").
Top keywords: {keywords}
Example complaints:
{examples}
Reply with the name only."""


def name_topic(keywords: list[str], examples: list[str], llm=None) -> tuple[str, str]:
    """(label, method). The LLM's name is accepted only if it is short and single-line."""
    fallback = keyword_label(keywords)
    if llm is None:
        return fallback, "keywords"
    prompt = LABEL_PROMPT.format(
        keywords=", ".join(keywords[:10]), examples="\n".join(f"- {e[:300]}" for e in examples)
    )
    try:
        name = llm.generate(prompt).strip().strip('"').strip("*").strip()
    except Exception:
        return fallback, "keywords"
    if not name or "\n" in name or len(name.split()) > 8:
        return fallback, "keywords"
    return name, "llm"


def run_build(text_dir: Path, lookup_path: Path, results_path: Path, llm=None) -> dict:
    t0 = time.time()
    sample = pd.read_parquet(text_dir / "sample.parquet")
    emb = np.load(text_dir / "sample_embeddings.npy")
    model, labels = fit_topics(sample["text"].tolist(), emb)
    log.info("topics fitted: %d topics in %.0fs", len(set(labels)), time.time() - t0)

    names, methods = {}, Counter()
    for tid in sorted(set(labels)):
        words = [w for w, _ in model.get_topic(tid)][:10]
        docs = sample.loc[labels == tid, "text"].head(3).tolist()
        names[int(tid)], m = name_topic(words, docs, llm)
        methods[m] += 1

    clf, metrics = evaluate_distillation(sample, labels)
    log.info("distillation: %s", metrics)

    corpus = pd.read_parquet(text_dir / "corpus.parquet")
    preds = []
    for start in range(0, len(corpus), 100_000):
        preds.append(clf.predict(corpus["text"].iloc[start : start + 100_000].tolist()))
    corpus["topic"] = np.concatenate(preds)
    corpus[
        ["narrative_hash", "complaint_id", "date_received", "company", "product", "issue", "topic", "copies"]
    ].to_parquet(text_dir / "corpus_topics.parquet")

    lookup = build_lookup(corpus, names)
    save_lookup(lookup, lookup_path)

    sizes = corpus.groupby("topic")["copies"].sum().sort_values(ascending=False)
    topics_out = [
        {
            "topic": int(t),
            "label": names[int(t)],
            "keywords": [w for w, _ in model.get_topic(int(t))][:8],
            "complaints_in_corpus": int(n),
            "sample_docs": int((labels == t).sum()),
        }
        for t, n in sizes.items()
    ]
    results = {
        "sample_docs": int(len(sample)),
        "corpus_docs": int(len(corpus)),
        "topics": int(len(names)),
        "topic_names": dict(methods),
        "distillation": metrics,
        "lookup_pairs": len(lookup),
        "minutes": round((time.time() - t0) / 60, 1),
        "topic_list": topics_out,
    }
    results_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results
