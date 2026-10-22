"""Topic discovery on a sample (BERTopic over MiniLM embeddings) and distillation to the full corpus.

Embedding 1M+ narratives with a transformer would take more than a day on a laptop CPU, so topics are
discovered on a stratified 40k sample. A TF-IDF + logistic-regression classifier is then trained on the
sample's topic labels and applies them to every narrative in minutes. The classifier is evaluated on held-out
sample documents against a baseline that only knows the complaint's product and issue.
"""

import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline

LOOKUP_TOP_TOPICS = 3
LOOKUP_EXAMPLES = 2
LOOKUP_MIN_DOCS = 30


def fit_topics(texts: list[str], embeddings: np.ndarray, min_cluster_size: int = 80, seed: int = 0):
    """Fit BERTopic on precomputed embeddings. Returns (model, topic per doc with outliers reassigned)."""
    from bertopic import BERTopic  # optional dependency group "text"
    from hdbscan import HDBSCAN
    from umap import UMAP

    model = BERTopic(
        embedding_model=None,
        umap_model=UMAP(n_neighbors=15, n_components=5, min_dist=0.0, metric="cosine", random_state=seed),
        hdbscan_model=HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean", prediction_data=True),
        vectorizer_model=CountVectorizer(stop_words="english", ngram_range=(1, 2), min_df=10, max_df=0.5),
        calculate_probabilities=False,
    )
    topics, _ = model.fit_transform(texts, embeddings)
    topics = model.reduce_outliers(texts, topics, strategy="embeddings", embeddings=embeddings)
    model.update_topics(texts, topics=topics, vectorizer_model=model.vectorizer_model)
    return model, np.asarray(topics)


def keyword_label(words: list[str], k: int = 4) -> str:
    return ", ".join(words[:k])


def distill(texts: list[str], labels: np.ndarray, seed: int = 0) -> Pipeline:
    clf = Pipeline(
        [
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=200_000, sublinear_tf=True)),
            ("lr", LogisticRegression(max_iter=1000, C=4.0)),
        ]
    )
    return clf.fit(texts, labels)


def grouped_split(texts: list[str], test_size: float = 0.2, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Train/test indices with every near-duplicate cluster entirely on one side (no template leakage)."""
    from complaint_radar.text.near_dup import near_duplicate_clusters

    groups = near_duplicate_clusters(texts, seed=seed)
    splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
    train, test = next(splitter.split(np.zeros(len(texts)), groups=groups))
    return train, test


def evaluate_distillation(sample: pd.DataFrame, labels: np.ndarray, seed: int = 0) -> tuple[Pipeline, dict]:
    """Held-out accuracy of the text classifier vs a product+issue baseline (most common topic per pair).

    The split keeps near-duplicate clusters together so copies of one template cannot be on both sides.
    """
    idx_train, idx_test = grouped_split(sample["text"].tolist(), test_size=0.2, seed=seed)
    train, test = sample.iloc[idx_train], sample.iloc[idx_test]
    y_train, y_test = labels[idx_train], labels[idx_test]
    clf = distill(train["text"].tolist(), y_train, seed)
    pred = clf.predict(test["text"].tolist())

    keys_train = list(zip(train["product"], train["issue"], strict=True))
    by_key: dict[tuple, Counter] = {}
    for key, y in zip(keys_train, y_train, strict=True):
        by_key.setdefault(key, Counter())[y] += 1
    overall = Counter(y_train).most_common(1)[0][0]
    base = [
        by_key[k].most_common(1)[0][0] if k in by_key else overall
        for k in zip(test["product"], test["issue"], strict=True)
    ]
    metrics = {
        "test_docs": int(len(test)),
        "topics": int(len(set(labels))),
        "text_classifier": {
            "accuracy": float(accuracy_score(y_test, pred)),
            "macro_f1": float(f1_score(y_test, pred, average="macro")),
        },
        "product_issue_baseline": {
            "accuracy": float(accuracy_score(y_test, base)),
            "macro_f1": float(f1_score(y_test, base, average="macro")),
        },
    }
    return distill(sample["text"].tolist(), labels, seed), metrics


def build_lookup(docs: pd.DataFrame, topic_labels: dict[int, str], seed: int = 0) -> dict:
    """For each product||issue: its most common topics with share and short example complaints."""
    rng = np.random.default_rng(seed)
    lookup = {}
    for (product, issue), g in docs.groupby(["product", "issue"], observed=True):
        if len(g) < LOOKUP_MIN_DOCS:
            continue
        shares = g["topic"].value_counts(normalize=True).head(LOOKUP_TOP_TOPICS)
        entries = []
        for topic, share in shares.items():
            pool = g.loc[(g["topic"] == topic) & g["text"].str.len().between(150, 900), "text"].tolist()
            picks = [pool[i] for i in rng.choice(len(pool), min(LOOKUP_EXAMPLES, len(pool)), replace=False)]
            entries.append(
                {
                    "topic": int(topic),
                    "label": topic_labels.get(int(topic), str(topic)),
                    "share": round(float(share), 3),
                    "examples": [p[:500] for p in picks],
                }
            )
        lookup[f"{product}||{issue}"] = {"docs": int(len(g)), "topics": entries}
    return lookup


def save_lookup(lookup: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lookup, indent=1, ensure_ascii=False), encoding="utf-8")


def lookup_for(lookup: dict, product: str, issue: str) -> dict | None:
    return lookup.get(f"{product}||{issue}")
