"""LangGraph Postgres checkpointer, kept as a process-wide singleton pool.

This is what gives the agent per-thread_id conversation memory (requirement
#7): each Streamlit session uses its own thread_id, and LangGraph persists
graph state (messages + our custom state fields) keyed by that id.
"""
from __future__ import annotations

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool

from config import get_settings

_pool: ConnectionPool | None = None
_checkpointer: PostgresSaver | None = None


def get_checkpointer() -> PostgresSaver:
    global _pool, _checkpointer
    if _checkpointer is None:
        settings = get_settings()
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            max_size=10,
            kwargs={"autocommit": True, "prepare_threshold": 0},
        )
        _checkpointer = PostgresSaver(_pool)
        _checkpointer.setup()
    return _checkpointer
