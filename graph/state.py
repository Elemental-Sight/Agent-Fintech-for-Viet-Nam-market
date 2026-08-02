"""LangGraph state schema.

`last_ticker` / `last_date_range` are what let a follow-up question like
"còn RSI của nó thì sao" resolve without the user repeating the ticker --
they persist across turns via the Postgres checkpointer (keyed by thread_id).
"""
from __future__ import annotations

from typing import Annotated, Optional, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    thread_id: str

    # produced by router_node from the raw question (LLM extraction, no guessing of tickers/dates)
    intent: Optional[str]
    ticker_mention: Optional[str]
    industry_mention: Optional[str]
    time_phrase: Optional[str]
    indicator_type: Optional[str]
    window_size: Optional[int]
    financial_metric: Optional[str]

    # resolved deterministically by resolvers/, never by the LLM
    resolved_ticker: Optional[str]
    resolved_date_range: Optional[dict]
    ambiguous_candidates: Optional[list[dict]]
    multi_entity_candidates: Optional[list[dict]]

    # carried across turns for follow-up questions
    last_ticker: Optional[str]
    last_date_range: Optional[dict]

    # tool_node output, consumed by synthesize_node
    tool_result: Optional[dict]
    tool_name: Optional[str]

    # synthesize_node/evaluate_node write here (NOT `messages`) so a draft
    # guardrail_node later rejects never lingers in permanent chat history --
    # only the version that passes (or exhausts retries) gets committed.
    draft_answer: Optional[str]

    # company_evaluation path only (v2 part 3 / v3 part 1): bctc_research_node
    # and news_sentiment_node write to separate keys so they can run as
    # parallel graph branches without a reducer conflict, then evaluate_node
    # (the join) reads both.
    research_result: Optional[dict]
    news_result: Optional[dict]

    # guardrail_node (v3 part 1): caps the synthesize/evaluate retry loop so
    # an ungrounded-number finding can't loop forever burning Groq calls.
    guardrail_retry_count: Optional[int]
    guardrail_needs_retry: Optional[bool]
    guardrail_feedback: Optional[list[str]]

    # observability / benchmarking (prompt_v1 requirement #2, #3, #6)
    used_fast_path: Optional[bool]
    cache_hit: Optional[bool]
