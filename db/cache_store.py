"""Semantic answer cache (prompt_v1 requirement #3).

Caches the *final synthesized answer*, keyed by an EXACT match on
(tool_name, resolved_ticker, resolved_date_range, indicator_type,
window_size) -- embedding similarity is only used to detect near-duplicate
PHRASING of a question within that already-resolved, exact key. Ticker
identity is never decided by embedding similarity alone: a semantically
"close" question about a different ticker or date range simply falls under
a different cache_key and can never serve the wrong data.

TTL varies by data type per the spec: real-time-ish price/indicator data
expires fast, slower-moving company profile data lives longer.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from config import get_settings
from nlp.embeddings import embed_text

logger = logging.getLogger("db.cache_store")

SIMILARITY_THRESHOLD = 0.96

# Only these tool outputs are pure functions of (ticker, date range, params)
# -- general chat and clarification answers depend on conversation history
# or are already free (no LLM call), so they're never cached.
_CACHEABLE_TOOLS = {"ohlcv", "indicator", "company_profile", "news", "financial_statement", "company_evaluation"}

_TTL_BY_TOOL = {
    "ohlcv": timedelta(minutes=10),
    "indicator": timedelta(minutes=10),
    "company_profile": timedelta(hours=12),
    "news": timedelta(minutes=30),
    # BCTC updates quarterly, not intraday -- matches the raw-data cache TTL
    # in db/financial_store.py, no point re-synthesizing sooner than that.
    "financial_statement": timedelta(hours=24),
    # Combines BCTC (slow-moving) + news (30 min TTL) -- use the shorter of
    # the two component TTLs so the evaluation never outlives its news half.
    "company_evaluation": timedelta(minutes=30),
}
_DEFAULT_TTL = timedelta(minutes=10)


def is_cacheable(tool_name: Optional[str]) -> bool:
    return tool_name in _CACHEABLE_TOOLS


def _cache_key(
    tool_name: str,
    resolved_ticker: Optional[str],
    resolved_date_range: Optional[dict],
    indicator_type: Optional[str],
    window_size: Optional[int],
    industry: Optional[str] = None,
    financial_metric: Optional[str] = None,
) -> str:
    date_range = resolved_date_range or {}
    parts = [
        tool_name,
        resolved_ticker or "",
        industry or "",  # industry-wide news has no ticker -- must still discriminate by industry
        date_range.get("start", ""),
        date_range.get("end", ""),
        indicator_type or "",
        str(window_size or ""),
        # Without this, two different BCTC metrics for the same ticker/range
        # (e.g. "doanh thu HPG" vs "ROE HPG") would collide on the same key
        # -- same class of bug as the industry-news collision fixed earlier.
        financial_metric or "",
    ]
    return "|".join(parts)


def lookup(
    question: str,
    tool_name: str,
    resolved_ticker: Optional[str],
    resolved_date_range: Optional[dict],
    indicator_type: Optional[str] = None,
    window_size: Optional[int] = None,
    industry: Optional[str] = None,
    financial_metric: Optional[str] = None,
) -> Optional[str]:
    if not is_cacheable(tool_name):
        return None
    key = _cache_key(tool_name, resolved_ticker, resolved_date_range, indicator_type, window_size, industry, financial_metric)
    try:
        embedding = embed_text(question)
    except Exception:
        logger.exception("cache_store: embedding failed, treating as cache miss")
        return None

    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True, row_factory=dict_row) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT answer, 1 - (question_embedding <=> %s::vector) AS similarity
                FROM semantic_cache
                WHERE cache_key = %s AND expires_at > now()
                ORDER BY question_embedding <=> %s::vector
                LIMIT 1
                """,
                (embedding, key, embedding),
            )
            row = cur.fetchone()

    if row and row["similarity"] >= SIMILARITY_THRESHOLD:
        logger.info("cache_store: HIT key=%s similarity=%.4f", key, row["similarity"])
        return row["answer"]
    logger.info("cache_store: MISS key=%s", key)
    return None


def store(
    question: str,
    answer: str,
    tool_name: str,
    resolved_ticker: Optional[str],
    resolved_date_range: Optional[dict],
    indicator_type: Optional[str] = None,
    window_size: Optional[int] = None,
    industry: Optional[str] = None,
    financial_metric: Optional[str] = None,
) -> None:
    if not is_cacheable(tool_name):
        return
    key = _cache_key(tool_name, resolved_ticker, resolved_date_range, indicator_type, window_size, industry, financial_metric)
    try:
        embedding = embed_text(question)
    except Exception:
        logger.exception("cache_store: embedding failed, skipping cache write")
        return

    ttl = _TTL_BY_TOOL.get(tool_name, _DEFAULT_TTL)
    expires_at = datetime.now(timezone.utc) + ttl

    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO semantic_cache
                    (cache_key, question_embedding, question, answer, tool_name,
                     resolved_ticker, resolved_date_range, expires_at)
                VALUES (%s, %s::vector, %s, %s, %s, %s, %s, %s)
                """,
                (
                    key,
                    embedding,
                    question,
                    answer,
                    tool_name,
                    resolved_ticker,
                    json.dumps(resolved_date_range) if resolved_date_range else None,
                    expires_at,
                ),
            )
