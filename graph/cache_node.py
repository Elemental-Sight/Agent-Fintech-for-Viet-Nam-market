"""Semantic cache lookup/write nodes (prompt_v1 requirement #3), wrapping
db.cache_store. Sits between router and tool/synthesize: on a hit, tool_node
and synthesize_node are both skipped (saves the vnstock call AND the Groq
synthesize call); on a miss, the graph proceeds normally and the answer is
written to the cache afterward for next time.
"""
from __future__ import annotations

from langgraph.graph import END

from db import cache_store

from ._utils import last_human_text
from .state import AgentState

_INTENT_TO_TOOL_NAME = {
    "company_profile": "company_profile",
    "indicator": "indicator",
    "price_history": "ohlcv",
    "news": "news",
    "financial_statement": "financial_statement",
    "company_evaluation": "company_evaluation",
}


def cache_lookup_node(state: AgentState) -> dict:
    intent = state.get("intent")
    tool_name = _INTENT_TO_TOOL_NAME.get(intent)
    ticker = state.get("resolved_ticker")
    ambiguous = state.get("ambiguous_candidates") or []
    multi_entity = state.get("multi_entity_candidates") or []

    industry_mention = state.get("industry_mention")
    is_industry_news = intent == "news" and industry_mention and not ticker
    if not tool_name or ambiguous or multi_entity or (not ticker and not is_industry_news):
        return {"cache_hit": False}

    question = last_human_text(state["messages"])
    cached_answer = cache_store.lookup(
        question=question,
        tool_name=tool_name,
        resolved_ticker=ticker,
        resolved_date_range=state.get("resolved_date_range"),
        indicator_type=state.get("indicator_type"),
        window_size=state.get("window_size"),
        industry=industry_mention if is_industry_news else None,
        financial_metric=state.get("financial_metric") if intent == "financial_statement" else None,
    )
    if cached_answer is None:
        return {"cache_hit": False}

    return {
        "cache_hit": True,
        "tool_name": tool_name,
        "messages": [{"role": "assistant", "content": cached_answer}],
    }


def route_after_cache_lookup(state: AgentState) -> str | list[str]:
    if state.get("cache_hit"):
        return END
    # company_evaluation (v2 part 3 / v3 part 1): fan out to the 2 parallel
    # research nodes instead of the single-tool path -- but only once the
    # ticker resolves cleanly (ambiguous/multi-entity/missing goes through
    # the normal "tool" path below, which already has deterministic
    # clarification handling for all 3 cases -- see tool_node.py).
    intent = state.get("intent")
    ticker = state.get("resolved_ticker")
    ambiguous = state.get("ambiguous_candidates") or []
    multi_entity = state.get("multi_entity_candidates") or []
    if intent == "company_evaluation" and ticker and not ambiguous and not multi_entity:
        return ["bctc_research_node", "news_sentiment_node"]
    return "tool"


def cache_write_node(state: AgentState) -> dict:
    tool_name = state.get("tool_name")
    tool_result = state.get("tool_result") or {}
    if not cache_store.is_cacheable(tool_name):
        return {}
    if tool_result.get("clarification_needed") or tool_result.get("found") is False or tool_result.get("error"):
        return {}  # never cache error/clarification responses

    last_message = state["messages"][-1]
    answer = last_message.get("content") if isinstance(last_message, dict) else getattr(last_message, "content", None)
    if not answer:
        return {}

    ticker = state.get("resolved_ticker")
    industry_mention = state.get("industry_mention")
    cache_store.store(
        question=last_human_text(state["messages"]),
        answer=answer,
        tool_name=tool_name,
        resolved_ticker=ticker,
        resolved_date_range=state.get("resolved_date_range"),
        indicator_type=state.get("indicator_type"),
        window_size=state.get("window_size"),
        industry=industry_mention if (tool_name == "news" and industry_mention and not ticker) else None,
        financial_metric=state.get("financial_metric") if tool_name == "financial_statement" else None,
    )
    return {}
