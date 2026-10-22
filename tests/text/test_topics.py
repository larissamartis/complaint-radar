import numpy as np
import pandas as pd

from complaint_radar.text.topics import build_lookup, evaluate_distillation, lookup_for

FEES = "they charged me an overdraft fee twice even though my balance was positive and refused a refund "
FRAUD = "someone stole my card and made unauthorized transactions and the bank denied my fraud claim "


FILLER = "my account bank called again week month told said waited still never help please branch online".split()


def toy_docs(n=200, seed=0):
    """Varied (non-template) texts: each mixes topic words with random filler, like organic complaints."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        topic = int(rng.random() < 0.5)
        vocab = (FRAUD if topic else FEES).split()
        words = list(rng.choice(vocab, 8)) + list(rng.choice(FILLER, 25))
        rng.shuffle(words)
        text = " ".join(words) + f" reference {i}"
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


def test_name_topic_accepts_short_llm_name_and_rejects_rambling():
    from complaint_radar.text.build import name_topic

    class Says:
        def __init__(self, reply):
            self.reply = reply

        def generate(self, prompt):
            return self.reply

    kw = ["overdraft", "fee", "charged", "balance", "refund"]
    assert name_topic(kw, ["x"], Says('"Overdraft fees charged twice"')) == ("Overdraft fees charged twice", "llm")
    long = "This topic is about customers who were charged many different kinds of fees by their bank"
    assert name_topic(kw, ["x"], Says(long)) == ("overdraft, fee, charged, balance", "keywords")
    assert name_topic(kw, ["x"], None)[1] == "keywords"


def test_distillation_split_keeps_near_duplicates_together():
    from complaint_radar.text.topics import grouped_split

    texts = ["the same template complaint text about fees " * 3] * 10 + [
        f"organic complaint number {i} " * 5 for i in range(40)
    ]
    train, test = grouped_split(texts, test_size=0.2, seed=0)
    template_idx = set(range(10))
    assert template_idx <= set(train) or template_idx <= set(test)
