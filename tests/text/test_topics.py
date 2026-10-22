import numpy as np
import pandas as pd

from complaint_radar.text.topics import build_lookup, evaluate_distillation, lookup_for

FEES = "they charged me an overdraft fee twice even though my balance was positive and refused a refund "
FRAUD = "someone stole my card and made unauthorized transactions and the bank denied my fraud claim "


def toy_docs(n=200, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        topic = int(rng.random() < 0.5)
        text = (FRAUD if topic else FEES) + f"case {i} " + "x" * 60
        rows.append({"product": "Checking", "issue": "Managing an account", "text": text, "topic": topic})
    return pd.DataFrame(rows)


def test_distillation_beats_product_issue_baseline_on_separable_text():
    docs = toy_docs()
    _, m = evaluate_distillation(docs, docs["topic"].to_numpy())
    assert m["text_classifier"]["accuracy"] > 0.95
    assert m["product_issue_baseline"]["accuracy"] < 0.7  # one product+issue pair cannot separate two topics


def test_lookup_has_top_topics_with_examples():
    docs = toy_docs()
    lk = build_lookup(docs, {0: "Overdraft fees", 1: "Card fraud"})
    entry = lookup_for(lk, "Checking", "Managing an account")
    assert entry["docs"] == 200
    assert {t["label"] for t in entry["topics"]} == {"Overdraft fees", "Card fraud"}
    assert abs(sum(t["share"] for t in entry["topics"]) - 1.0) < 0.01
    assert all(1 <= len(t["examples"]) <= 2 for t in entry["topics"])


def test_small_pairs_are_left_out_of_lookup():
    docs = toy_docs(20)
    assert build_lookup(docs, {}) == {}
