"""LangGraph graph (requirement #6, extended by prompt_v1 #2/#3, prompt_v2
#3, prompt_v3 #1):

router -> cache_lookup -> [HIT: END | MISS: route_after_cache_lookup]

route_after_cache_lookup splits the miss path in two:
  - normal intents (unchanged since v1): tool -> synthesize -> guardrail -> ...
  - company_evaluation (single ticker, resolved cleanly): fans out to
    [bctc_research_node, news_sentiment_node] in parallel -> evaluate ->
    guardrail -> ...

guardrail (v3 #1) is shared by both paths: it checks the draft answer's
numbers against tool_result and, within a retry budget, can loop back to
whichever node produced the draft (synthesize or evaluate) before finally
handing off to cache_write -> END.

router itself tries a rule-based fast path before ever calling Groq (see
fast_router.py); cache_lookup/cache_write add a semantic answer cache on
top so a repeated near-duplicate question skips tool/synthesize entirely.
"""
from __future__ import annotations

from typing import Any, Optional

from langgraph.graph import END, START, StateGraph

from .cache_node import cache_lookup_node, cache_write_node, route_after_cache_lookup
from .evaluate_node import bctc_research_node, evaluate_node, news_sentiment_node
from .guardrail_node import guardrail_node, route_after_guardrail
from .router_node import router_node
from .state import AgentState
from .synthesize_node import synthesize_node
from .tool_node import tool_node


def build_graph(checkpointer: Optional[Any] = None):
    graph = StateGraph(AgentState)
    graph.add_node("router", router_node)
    graph.add_node("cache_lookup", cache_lookup_node)
    graph.add_node("tool", tool_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("bctc_research_node", bctc_research_node)
    graph.add_node("news_sentiment_node", news_sentiment_node)
    graph.add_node("evaluate", evaluate_node)
    graph.add_node("guardrail", guardrail_node)
    graph.add_node("cache_write", cache_write_node)

    graph.add_edge(START, "router")
    graph.add_edge("router", "cache_lookup")
    # route_after_cache_lookup returns END, "tool", or the 2-node fan-out
    # list directly (no path_map needed -- those are already valid node
    # names/END).
    graph.add_conditional_edges("cache_lookup", route_after_cache_lookup)

    graph.add_edge("tool", "synthesize")
    graph.add_edge("synthesize", "guardrail")

    graph.add_edge("bctc_research_node", "evaluate")
    graph.add_edge("news_sentiment_node", "evaluate")
    graph.add_edge("evaluate", "guardrail")

    # route_after_guardrail returns "synthesize"/"evaluate" (retry) or
    # "cache_write" (pass) -- again, literal node names, no path_map needed.
    graph.add_conditional_edges("guardrail", route_after_guardrail)
    graph.add_edge("cache_write", END)

    return graph.compile(checkpointer=checkpointer)
