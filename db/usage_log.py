"""Persists + queries Groq token-usage records (see llm/groq_client.py)."""
from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from config import get_settings


def log_usage(record: dict) -> None:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO groq_usage_log (thread_id, node, model, tokens_in, tokens_out, latency_ms) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    record.get("thread_id"),
                    record["node"],
                    record["model"],
                    record["tokens_in"],
                    record["tokens_out"],
                    record["latency_ms"],
                ),
            )


def get_usage_summary(thread_id: str) -> dict:
    """Aggregate token usage for one thread -- powers the Streamlit usage
    sidebar (prompt_v1 requirement #4)."""
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    count(*) AS calls,
                    coalesce(sum(tokens_in), 0) AS tokens_in,
                    coalesce(sum(tokens_out), 0) AS tokens_out,
                    coalesce(avg(latency_ms), 0) AS avg_latency_ms
                FROM groq_usage_log
                WHERE thread_id = %s
                """,
                (thread_id,),
            )
            return cur.fetchone()
