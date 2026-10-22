"""Build the text corpus and cache sentence embeddings for topic discovery."""

import logging
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from complaint_radar.text.clean import clean_text

log = logging.getLogger(__name__)

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
MAX_SEQ_LENGTH = 128  # ~100 words: enough for the "what happened" core, and 2x faster than 256 on CPU

CORPUS_SQL = """
    SELECT any_value(complaint_id) AS complaint_id, any_value(date_received) AS date_received,
           any_value(company) AS company, any_value(product) AS product,
           any_value(coalesce(issue, '(none)')) AS issue, any_value(narrative) AS narrative,
           narrative_hash, count(*) AS copies
    FROM stg_complaints
    WHERE segment = 'other' AND has_narrative AND date_received BETWEEN ? AND ?
    GROUP BY narrative_hash
"""


def load_corpus(con: duckdb.DuckDBPyConnection, start: str = "2019-01-01", end: str = "2025-12-31") -> pd.DataFrame:
    """Unique non-bureau narratives (exact copies collapsed; `copies` keeps their count)."""
    df = con.execute(CORPUS_SQL, [start, end]).df()
    df["text"] = [clean_text(t) for t in df["narrative"]]
    df["year"] = pd.to_datetime(df["date_received"]).dt.year
    return df.drop(columns="narrative")


def stratified_sample(df: pd.DataFrame, n: int, seed: int = 0) -> pd.DataFrame:
    """Sample proportional to product x year volume, with a floor so small products are still represented."""
    groups = df.groupby(["product", "year"], observed=True)
    sizes = groups.size()
    alloc = np.maximum((sizes / sizes.sum() * n).round().astype(int), np.minimum(sizes, 30))
    parts = [g.sample(min(len(g), int(alloc[k])), random_state=seed) for k, g in groups]
    return pd.concat(parts, ignore_index=True)


def embed(texts: list[str], cache: Path | None = None, batch_size: int = 32) -> np.ndarray:
    """Normalised MiniLM embeddings, cached to `cache` (.npy) so the slow CPU step runs once."""
    if cache is not None and cache.exists():
        emb = np.load(cache)
        if len(emb) == len(texts):
            return emb
    from sentence_transformers import SentenceTransformer  # optional dependency group "text"

    model = SentenceTransformer(EMBEDDING_MODEL, device="cpu")
    model.max_seq_length = MAX_SEQ_LENGTH
    emb = model.encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=True)
    emb = emb.astype(np.float32)
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.save(cache, emb)
    return emb
