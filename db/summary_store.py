"""Stores the running conversation summary used to trim long histories
before they're replayed into a Groq prompt (prompt_v1 requirement #4)."""
from __future__ import annotations

from typing import Optional

import psycopg
from psycopg.rows import dict_row

from config import get_settings


def get_summary(thread_id: str) -> Optional[dict]:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT summary, summarized_through_message_count FROM conversation_summaries WHERE thread_id = %s",
                (thread_id,),
            )
            return cur.fetchone()


def save_summary(thread_id: str, summary: str, summarized_through_message_count: int) -> None:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversation_summaries (thread_id, summary, summarized_through_message_count)
                VALUES (%s, %s, %s)
                ON CONFLICT (thread_id) DO UPDATE SET
                    summary = EXCLUDED.summary,
                    summarized_through_message_count = EXCLUDED.summarized_through_message_count,
                    updated_at = now()
                """,
                (thread_id, summary, summarized_through_message_count),
            )
