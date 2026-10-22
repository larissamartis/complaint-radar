"""Near-duplicate detection with MinHash + LSH, written in NumPy (no extra dependency).

Template and campaign complaints are copies of one text with small edits (a name, an amount, a date).
Two texts are near-duplicates when their sets of word 3-grams overlap strongly (Jaccard similarity).
MinHash compresses each set into a short signature whose agreement rate estimates Jaccard, and
locality-sensitive hashing (LSH) only compares texts that share a band of the signature, so the work
grows roughly linearly with the number of texts instead of with every pair.
"""

import zlib
from collections import defaultdict

import numpy as np

from complaint_radar.text.clean import clean_text, words

NUM_PERM = 100
BANDS, ROWS = 20, 5  # LSH catches pairs above Jaccard ~0.55 with high probability
JACCARD_THRESHOLD = 0.6
SHINGLE = 3
_PRIME = np.uint64(4294967311)  # > 2**32


def _shingle_hashes(text: str) -> np.ndarray:
    toks = words(clean_text(text))
    grams = [" ".join(toks[i : i + SHINGLE]) for i in range(max(1, len(toks) - SHINGLE + 1))] if toks else [""]
    return np.fromiter((zlib.crc32(g.encode("utf-8")) for g in grams), dtype=np.uint64, count=len(grams))


def _signatures(texts: list[str], seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    a = rng.integers(1, 2**31, NUM_PERM, dtype=np.uint64)
    b = rng.integers(0, 2**31, NUM_PERM, dtype=np.uint64)
    sig = np.empty((len(texts), NUM_PERM), dtype=np.uint64)
    for i, t in enumerate(texts):
        x = _shingle_hashes(t)
        sig[i] = ((a[:, None] * x[None, :] + b[:, None]) % _PRIME).min(axis=1)
    return sig


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        ri, rj = self.find(i), self.find(j)
        if ri != rj:
            self.parent[max(ri, rj)] = min(ri, rj)


def near_duplicate_clusters(texts: list[str], seed: int = 0) -> list[int]:
    """Cluster label per text; near-duplicates share a label. Labels are 0..k-1 in order of first appearance."""
    if not texts:
        return []
    # Exact duplicates (after cleaning) are collapsed first: campaigns often submit thousands of copies.
    cleaned = [clean_text(t).lower() for t in texts]
    uniq_index: dict[str, int] = {}
    uniq_of = [uniq_index.setdefault(c, len(uniq_index)) for c in cleaned]
    uniq_texts = list(uniq_index)

    sig = _signatures(uniq_texts, seed)
    uf = _UnionFind(len(uniq_texts))
    for band in range(BANDS):
        buckets: dict[bytes, list[int]] = defaultdict(list)
        for i, key in enumerate(sig[:, band * ROWS : (band + 1) * ROWS]):
            buckets[key.tobytes()].append(i)
        for members in buckets.values():
            head = members[0]
            for other in members[1:]:  # star linking: verify against the bucket head only
                if uf.find(other) != uf.find(head) and (sig[head] == sig[other]).mean() >= JACCARD_THRESHOLD:
                    uf.union(head, other)

    roots: dict[int, int] = {}
    return [roots.setdefault(uf.find(u), len(roots)) for u in uniq_of]


def campaign_share(texts: list[str], min_cluster: int = 5, seed: int = 0) -> float:
    """Share of texts that belong to a near-duplicate cluster with at least `min_cluster` members."""
    if not texts:
        return 0.0
    labels = near_duplicate_clusters(texts, seed)
    counts = np.bincount(labels)
    return float((counts[labels] >= min_cluster).mean())
