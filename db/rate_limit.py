"""Simple per-session/IP rate limiting (prompt_v1 requirement #5) to protect
the Groq free-tier quota when demoing publicly."""
from __future__ import annotations

import psycopg

from config import get_settings

DEFAULT_MAX_EVENTS = 30
DEFAULT_WINDOW_MINUTES = 60


def check_rate_limit(
    client_key: str, max_events: int = DEFAULT_MAX_EVENTS, window_minutes: int = DEFAULT_WINDOW_MINUTES
) -> bool:
    """Records this call as an event and returns True if `client_key` is
    still under `max_events` within the trailing `window_minutes`."""
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) FROM rate_limit_events
                WHERE client_key = %s AND created_at > now() - (%s || ' minutes')::interval
                """,
                (client_key, window_minutes),
            )
            (recent_count,) = cur.fetchone()
            if recent_count >= max_events:
                return False
            cur.execute("INSERT INTO rate_limit_events (client_key) VALUES (%s)", (client_key,))
            return True
