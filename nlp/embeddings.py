"""Sentence embeddings for the semantic cache (prompt_v1 requirement #3).

Runs locally via sentence-transformers -- no Groq call, so checking the
cache costs no LLM tokens. Model is loaded once per process (lru_cache).
"""
from __future__ import annotations

from functools import lru_cache

_MODEL_NAME = "intfloat/multilingual-e5-small"
EMBEDDING_DIM = 384


@lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(_MODEL_NAME)


def embed_text(text: str) -> list[float]:
    """Encode `text` into a unit-normalized embedding vector.

    e5 models expect a "query: " prefix by convention (trained with
    query/passage pairs) -- using it consistently for both cache writes and
    lookups keeps the vectors comparable to each other.
    """
    model = _get_model()
    vector = model.encode(f"query: {text}", normalize_embeddings=True)
    return vector.tolist()
