"""SQL-backed cache/query layer for financial statement metrics (prompt_v2
requirement #1). Deliberately plain SQL, no embedding/similarity involved --
BCTC numbers must be exact-match queryable, never approximated by semantic
search (that's what distinguishes this from db/cache_store.py's semantic
answer cache).

TTL is long (financial statements update quarterly, not intraday) so a
repeated question doesn't re-hit vnstock every time.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg
from psycopg.rows import dict_row

from config import get_settings

_TTL = timedelta(hours=24)


def is_fresh(ticker: str, period_type: str, metric_key: str) -> bool:
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - _TTL
    with psycopg.connect(settings.database_url, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM financial_metrics
                WHERE ticker = %s AND period_type = %s AND metric_key = %s AND fetched_at > %s
                LIMIT 1
                """,
                (ticker, period_type, metric_key, cutoff),
            )
            return cur.fetchone() is not None


def upsert_metrics(ticker: str, period_type: str, rows: list[dict]) -> None:
    """`rows`: [{"period_label": ..., "metric_key": ..., "metric_value": ...}, ...]"""
    if not rows:
        return
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO financial_metrics (ticker, period_type, period_label, metric_key, metric_value, fetched_at)
                VALUES (%s, %s, %s, %s, %s, now())
                ON CONFLICT (ticker, period_type, period_label, metric_key)
                DO UPDATE SET metric_value = EXCLUDED.metric_value, fetched_at = now()
                """,
                [(ticker, period_type, r["period_label"], r["metric_key"], r["metric_value"]) for r in rows],
            )


def query_metrics(
    ticker: str,
    period_type: str,
    metric_key: str,
    period_labels: Optional[list[str]] = None,
) -> list[dict]:
    """Returns rows sorted by period_label descending (newest first). If
    `period_labels` is None, returns every cached period for this metric --
    which, given vnstock's own ~4-period cap, is "everything we have"."""
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            if period_labels:
                cur.execute(
                    """
                    SELECT period_label, metric_value FROM financial_metrics
                    WHERE ticker = %s AND period_type = %s AND metric_key = %s AND period_label = ANY(%s)
                    ORDER BY period_label DESC
                    """,
                    (ticker, period_type, metric_key, period_labels),
                )
            else:
                cur.execute(
                    """
                    SELECT period_label, metric_value FROM financial_metrics
                    WHERE ticker = %s AND period_type = %s AND metric_key = %s
                    ORDER BY period_label DESC
                    """,
                    (ticker, period_type, metric_key),
                )
            return cur.fetchall()
