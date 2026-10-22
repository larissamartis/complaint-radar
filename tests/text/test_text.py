from complaint_radar.text.clean import clean_text
from complaint_radar.text.near_dup import campaign_share, near_duplicate_clusters


def test_clean_text_removes_redactions_and_amounts():
    raw = "On XX/XX/XXXX I paid {$500.00} to XXXX   XXXX and\n\nnothing happened."
    assert clean_text(raw) == "On I paid to and nothing happened."


def test_clean_text_handles_none():
    assert clean_text(None) == ""


TEMPLATE = (
    "I am filing this complaint against the company due to inadequate customer service and unfair practices "
    "which violate the consumer financial protection act. The company failed to take timely and effective "
    "measures to prevent and address fraud on their platform leaving my account exposed and unprotected."
)


def variants(n):
    # Near-identical copies: one word changed per copy, as campaign templates usually are.
    words = TEMPLATE.split()
    out = []
    for i in range(n):
        w = list(words)
        w[(i * 7) % len(w)] = f"word{i}"
        out.append(" ".join(w))
    return out


ORGANIC = [
    "My mortgage payment was applied to the wrong month and now I have a late fee on my credit report.",
    "The bank closed my checking account without notice and is holding my paycheck deposit for ten days.",
    "A debt collector keeps calling my workplace about a medical bill that my insurance already paid in full.",
    "I disputed a fraudulent charge on my credit card in March and the dispute is still not resolved.",
    "My student loan servicer transferred my account and lost the record of my income driven repayment plan.",
    "The app froze during a transfer and the money left my account but never arrived at my sister's account.",
]


def test_near_duplicates_cluster_and_organic_texts_do_not():
    texts = variants(8) + ORGANIC
    labels = near_duplicate_clusters(texts, seed=1)
    assert len(set(labels[:8])) == 1  # all template variants in one cluster
    assert len(set(labels[8:])) == len(ORGANIC)  # every organic text is its own cluster
    assert labels[8] != labels[0]


def test_campaign_share():
    assert campaign_share(variants(20) + ORGANIC * 1, min_cluster=5) == 20 / 26
    assert campaign_share(ORGANIC, min_cluster=5) == 0.0
    assert campaign_share([], min_cluster=5) == 0.0
