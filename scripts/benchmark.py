"""Benchmark: tokens/query, latency p50/p95, cache hit rate, fast-path rate
(prompt_v1 evaluation requirement).

Runs a fixed query set against the live backend TWICE:
  - "cold" pass: cache is empty for these questions, so it measures the
    fast-path (rule-based router) improvement in isolation.
  - "warm" pass: same questions again, now the semantic cache from the cold
    pass can hit, so it measures the combined fast-path + cache improvement.

Usage (run from inside the app container, where BACKEND_URL defaults to the
local FastAPI server and DB access is already configured):
    docker compose exec app python scripts/benchmark.py
"""
from __future__ import annotations

import os
import statistics
import sys
import time
import uuid
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_settings  # noqa: E402

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

# Mix of simple explicit-ticker lookups (fast-path eligible) and
# comparison/vague questions (always go through the full Groq router).
QUERIES = [
    "gia VCB hien tai",
    "RSI 14 cua HPG",
    "ho so doanh nghiep FPT",
    "gia VNM 3 thang gan nhat",
    "SMA 20 cua MWG",
    "tin tuc ve HPG gan day",
    "so sanh HPG va HSG",  # always full router (multi-entity)
    "P/E cua SSI la bao nhieu",  # always full router (unsupported metric)
]


def _new_thread() -> str:
    resp = requests.post(f"{BACKEND_URL}/sessions", timeout=10)
    resp.raise_for_status()
    return resp.json()["thread_id"]


def _run_pass(label: str) -> list[dict]:
    results = []
    for question in QUERIES:
        thread_id = _new_thread()  # fresh thread per query -- isolates each question, no cross-turn context
        start = time.perf_counter()
        try:
            resp = requests.post(
                f"{BACKEND_URL}/chat", json={"thread_id": thread_id, "message": question}, timeout=90
            )
            resp.raise_for_status()
            data = resp.json()
            ok = True
        except requests.RequestException as exc:
            data, ok = {}, False
            print(f"  [{label}] lỗi với câu hỏi {question!r}: {exc}")
        latency_ms = (time.perf_counter() - start) * 1000
        results.append(
            {
                "question": question,
                "thread_id": thread_id,
                "ok": ok,
                "latency_ms": latency_ms,
                "used_fast_path": data.get("used_fast_path"),
                "cache_hit": data.get("cache_hit"),
            }
        )
    return results


def _usage_for_threads(thread_ids: list[str]) -> tuple[int, int, int]:
    """Returns (calls, tokens_in, tokens_out) summed across threads by
    querying groq_usage_log directly."""
    import psycopg

    settings = get_settings()
    placeholders = ",".join(["%s"] * len(thread_ids))
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT count(*), coalesce(sum(tokens_in),0), coalesce(sum(tokens_out),0) "
                f"FROM groq_usage_log WHERE thread_id IN ({placeholders})",
                thread_ids,
            )
            return cur.fetchone()


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(len(values) - 1, int(round(pct / 100 * (len(values) - 1))))
    return values[idx]


def _summarize(label: str, results: list[dict]) -> dict:
    latencies = [r["latency_ms"] for r in results if r["ok"]]
    thread_ids = [r["thread_id"] for r in results]
    calls, tokens_in, tokens_out = _usage_for_threads(thread_ids)
    fast_path_hits = sum(1 for r in results if r.get("used_fast_path"))
    cache_hits = sum(1 for r in results if r.get("cache_hit"))
    n = len(results)

    summary = {
        "label": label,
        "queries": n,
        "groq_calls": calls,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_per_query": round((tokens_in + tokens_out) / n, 1) if n else 0,
        "latency_p50_ms": round(_percentile(latencies, 50), 1),
        "latency_p95_ms": round(_percentile(latencies, 95), 1),
        "fast_path_rate": round(fast_path_hits / n * 100, 1) if n else 0,
        "cache_hit_rate": round(cache_hits / n * 100, 1) if n else 0,
    }
    return summary


def _print_table(rows: list[dict]) -> None:
    columns = [
        ("label", "Pass"),
        ("queries", "Queries"),
        ("groq_calls", "Groq calls"),
        ("tokens_per_query", "Tokens/query"),
        ("latency_p50_ms", "p50 (ms)"),
        ("latency_p95_ms", "p95 (ms)"),
        ("fast_path_rate", "Fast-path %"),
        ("cache_hit_rate", "Cache-hit %"),
    ]
    header = " | ".join(f"{label:>13}" for _, label in columns)
    print(header)
    print("-" * len(header))
    for row in rows:
        print(" | ".join(f"{str(row[key]):>13}" for key, _ in columns))


def main() -> None:
    print(f"Backend: {BACKEND_URL}\nSố câu hỏi: {len(QUERIES)}\n")

    print("=== Pass 1/2: cache lạnh (cold) -- đo cải thiện từ fast-path router ===")
    cold_results = _run_pass("cold")

    print("=== Pass 2/2: cache ấm (warm) -- lặp lại đúng các câu hỏi trên ===")
    warm_results = _run_pass("warm")

    cold_summary = _summarize("cold (before cache)", cold_results)
    warm_summary = _summarize("warm (after cache)", warm_results)

    print("\n=== Kết quả so sánh ===")
    _print_table([cold_summary, warm_summary])


if __name__ == "__main__":
    main()
