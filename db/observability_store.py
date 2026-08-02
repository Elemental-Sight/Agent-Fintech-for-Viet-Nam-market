"""v3 part 3 (observability): logs every /chat request and aggregates
per-request outcomes (cache-hit/fast-path rate, tool popularity) plus the
per-Groq-call token/latency stats already recorded in `groq_usage_log`.

Deliberately no dollar-cost figure anywhere here -- this project has no real
configured Groq pricing, and inventing a rate would violate the same
"never serve a number we can't verify" principle applied everywhere else
(see PROJECT_CONTEXT.md). Token counts are the honest, verifiable metric.
"""
from __future__ import annotations

from typing import Optional

import psycopg
from psycopg.rows import dict_row

from config import get_settings


def log_request(
    thread_id: Optional[str], tool_name: Optional[str], used_fast_path: Optional[bool], cache_hit: Optional[bool]
) -> None:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO request_log (thread_id, tool_name, used_fast_path, cache_hit) VALUES (%s, %s, %s, %s)",
                (thread_id, tool_name, used_fast_path, cache_hit),
            )


def get_observability_summary(limit_recent: int = 20) -> dict:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    count(*) AS total_requests,
                    coalesce(avg(cache_hit::int), 0) AS cache_hit_rate,
                    coalesce(avg(used_fast_path::int), 0) AS fast_path_rate
                FROM request_log
                """
            )
            totals = cur.fetchone()

            cur.execute(
                """
                SELECT coalesce(tool_name, 'none') AS tool_name, count(*) AS calls
                FROM request_log
                GROUP BY tool_name
                ORDER BY calls DESC
                LIMIT 10
                """
            )
            top_tools = cur.fetchall()

            cur.execute(
                """
                SELECT
                    node,
                    count(*) AS calls,
                    coalesce(avg(tokens_in), 0) AS avg_tokens_in,
                    coalesce(avg(tokens_out), 0) AS avg_tokens_out,
                    coalesce(avg(latency_ms), 0) AS avg_latency_ms
                FROM groq_usage_log
                GROUP BY node
                ORDER BY calls DESC
                """
            )
            by_node = cur.fetchall()

            cur.execute(
                """
                SELECT thread_id, tool_name, used_fast_path, cache_hit, created_at
                FROM request_log
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit_recent,),
            )
            recent = cur.fetchall()

    return {
        "total_requests": totals["total_requests"],
        "cache_hit_rate": round(float(totals["cache_hit_rate"]), 4),
        "fast_path_rate": round(float(totals["fast_path_rate"]), 4),
        "top_tools": top_tools,
        "by_node": by_node,
        "recent_requests": [
            {**r, "created_at": r["created_at"].isoformat()} for r in recent
        ],
    }
