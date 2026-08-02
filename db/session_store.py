"""CRUD helpers for the `sessions` table.

`list_sessions` is used to populate the Streamlit sidebar. It intentionally
only selects from this small metadata table — it never touches LangGraph's
checkpoint tables, so listing sessions never loads full message history.
"""
from __future__ import annotations

from typing import Optional

import psycopg
from psycopg.rows import dict_row

from config import get_settings


def create_session(thread_id: str, title: str = "Phiên mới") -> None:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sessions (thread_id, title) VALUES (%s, %s) "
                "ON CONFLICT (thread_id) DO NOTHING",
                (thread_id, title),
            )


def touch_session(thread_id: str, title: Optional[str] = None) -> None:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            if title:
                cur.execute(
                    "UPDATE sessions SET title = %s, updated_at = now() WHERE thread_id = %s",
                    (title, thread_id),
                )
            else:
                cur.execute(
                    "UPDATE sessions SET updated_at = now() WHERE thread_id = %s",
                    (thread_id,),
                )


def update_session(thread_id: str, title: Optional[str] = None, pinned: Optional[bool] = None) -> None:
    """Rename and/or pin/unpin a session -- unlike `touch_session`, this never
    bumps `updated_at` on its own, since pinning shouldn't reorder a session
    within its (pinned/unpinned) group."""
    sets: list[str] = []
    params: list = []
    if title is not None:
        sets.append("title = %s")
        params.append(title)
    if pinned is not None:
        sets.append("pinned = %s")
        params.append(pinned)
    if not sets:
        return
    params.append(thread_id)

    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE sessions SET {', '.join(sets)} WHERE thread_id = %s", params)


def delete_session(thread_id: str) -> None:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE thread_id = %s", (thread_id,))


def get_session(thread_id: str) -> Optional[dict]:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT thread_id, title, pinned, created_at, updated_at FROM sessions WHERE thread_id = %s",
                (thread_id,),
            )
            return cur.fetchone()


def list_sessions(limit: int = 50) -> list[dict]:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT thread_id, title, pinned, created_at, updated_at FROM sessions "
                "ORDER BY pinned DESC, updated_at DESC LIMIT %s",
                (limit,),
            )
            return cur.fetchall()
