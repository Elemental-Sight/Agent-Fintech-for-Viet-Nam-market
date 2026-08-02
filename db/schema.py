"""Application-owned tables.

LangGraph's PostgresSaver manages its own checkpoint tables via
`checkpointer.setup()` (see checkpointer.py) — this module only owns the
tables the app itself queries directly: the lightweight `sessions` list
(for the Streamlit sidebar), the Groq token-usage log, the semantic cache,
conversation summaries, and rate-limit tracking.
"""
from __future__ import annotations

import psycopg

from config import get_settings
from nlp.embeddings import EMBEDDING_DIM

_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    thread_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT 'Phiên mới',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# `pinned` was added after the table already existed in deployed DBs -- an
# ALTER TABLE migration (idempotent via IF NOT EXISTS) rather than a column
# in _SESSIONS_TABLE, which only runs on first CREATE.
_SESSIONS_PINNED_COLUMN = """
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS pinned BOOLEAN NOT NULL DEFAULT FALSE;
"""

_USAGE_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS groq_usage_log (
    id BIGSERIAL PRIMARY KEY,
    thread_id TEXT,
    node TEXT NOT NULL,
    model TEXT NOT NULL,
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    latency_ms DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_VECTOR_EXTENSION = "CREATE EXTENSION IF NOT EXISTS vector;"

# No approximate-nearest-neighbor index (ivfflat/hnsw) on purpose -- at this
# app's scale (single demo deployment) a brute-force `<=>` scan over a few
# thousand rows is plenty fast, and skipping the index avoids pgvector
# version/tuning footguns.
_SEMANTIC_CACHE_TABLE = f"""
CREATE TABLE IF NOT EXISTS semantic_cache (
    id BIGSERIAL PRIMARY KEY,
    cache_key TEXT NOT NULL,
    question_embedding vector({EMBEDDING_DIM}) NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    tool_name TEXT,
    resolved_ticker TEXT,
    resolved_date_range JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS semantic_cache_key_idx ON semantic_cache (cache_key, expires_at);
"""

_CONVERSATION_SUMMARIES_TABLE = """
CREATE TABLE IF NOT EXISTS conversation_summaries (
    thread_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    summarized_through_message_count INTEGER NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_RATE_LIMIT_TABLE = """
CREATE TABLE IF NOT EXISTS rate_limit_events (
    id BIGSERIAL PRIMARY KEY,
    client_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rate_limit_events_client_key_idx ON rate_limit_events (client_key, created_at);
"""

# EAV shape (prompt_v2 requirement #1): a curated, small vocabulary of metric
# keys (see tools/financial_tool.py) but period_label grows every quarter --
# EAV lets "1 ticker/N metrics/N periods" and "N tickers/1 metric/1 period"
# (comparison) queries share one SQL pattern without ALTER TABLE churn.
_FINANCIAL_METRICS_TABLE = """
CREATE TABLE IF NOT EXISTS financial_metrics (
    id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    period_type TEXT NOT NULL,
    period_label TEXT NOT NULL,
    metric_key TEXT NOT NULL,
    metric_value DOUBLE PRECISION,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (ticker, period_type, period_label, metric_key)
);
CREATE INDEX IF NOT EXISTS financial_metrics_lookup_idx ON financial_metrics (ticker, period_type, metric_key);
"""

# v3 part 3 (observability): logged for EVERY /chat call regardless of
# whether Groq was ever invoked -- a cache-hit or fast-path turn produces no
# groq_usage_log row at all, so cache-hit-rate/fast-path-rate can't be
# computed from that table alone.
_REQUEST_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS request_log (
    id BIGSERIAL PRIMARY KEY,
    thread_id TEXT,
    tool_name TEXT,
    used_fast_path BOOLEAN,
    cache_hit BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS request_log_created_at_idx ON request_log (created_at);
"""


def init_db() -> None:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(_VECTOR_EXTENSION)
            cur.execute(_SESSIONS_TABLE)
            cur.execute(_SESSIONS_PINNED_COLUMN)
            cur.execute(_USAGE_LOG_TABLE)
            cur.execute(_SEMANTIC_CACHE_TABLE)
            cur.execute(_CONVERSATION_SUMMARIES_TABLE)
            cur.execute(_RATE_LIMIT_TABLE)
            cur.execute(_FINANCIAL_METRICS_TABLE)
            cur.execute(_REQUEST_LOG_TABLE)
