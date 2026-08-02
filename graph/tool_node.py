"""Tool node (requirement #6, second stage): calls the tool matching the
resolved intent, using only the deterministically resolved ticker/date
range produced by router_node. Never asks the LLM to pick a tool."""
from __future__ import annotations

from datetime import date, timedelta

from resolvers import current_price_range
from tools import (
    get_company_profile,
    get_financial_metric_for_question,
    get_indicator,
    get_news_by_industry,
    get_news_by_ticker,
    get_ohlcv_summary,
)

from .state import AgentState

_DEFAULT_LOOKBACK_DAYS = 90
_DEFAULT_WINDOW = {"SMA": 20, "RSI": 14}
_MAX_COMPARE_ENTITIES = 5
# Only intents backed by a single-ticker tool that returns flat/scalar-ish
# data are comparable -- news (articles + sentiment per ticker) and "other"
# (unsupported metrics) don't have a sane side-by-side table representation.
_COMPARABLE_INTENTS = {"company_profile", "price_history", "indicator", "financial_statement"}


def _date_bounds(date_range: dict | None) -> tuple[date, date]:
    if date_range:
        return date.fromisoformat(date_range["start"]), date.fromisoformat(date_range["end"])
    end = date.today()
    start = end - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
    return start, end


def _compare_entities(
    intent: str,
    entities: list[dict],
    date_range: dict | None,
    indicator_type: str | None,
    window_size: int | None,
    financial_metric: str | None = None,
    financial_date_range: dict | None = None,
) -> dict | None:
    """Sequentially calls the same single-ticker tool once per entity and
    flattens the results into one comparison table -- no new tool/data
    source, just the existing deterministic tools called more than once so
    the LLM still never invents a number to fill in a comparison row."""
    if intent not in _COMPARABLE_INTENTS:
        return None

    if intent == "financial_statement":
        if not financial_metric:
            return {
                "comparison": True, "intent": intent,
                "results": [{"ticker": e["ticker"], "name": e.get("name") or e["ticker"], "found": False,
                              "error": "Chưa xác định được chỉ số BCTC cần so sánh."}
                             for e in entities[:_MAX_COMPARE_ENTITIES]],
            }
        results = []
        for entity in entities[:_MAX_COMPARE_ENTITIES]:
            ticker = entity["ticker"]
            name = entity.get("name") or ticker
            result = get_financial_metric_for_question(ticker, financial_metric, financial_date_range)
            if not result.found:
                results.append({"ticker": ticker, "name": name, "found": False, "error": result.error})
                continue
            for p in result.periods:
                results.append(
                    {"ticker": ticker, "name": name, "found": True, "period": p["period_label"],
                     "value": p["value"], "unit": result.unit}
                )
        return {"comparison": True, "intent": intent, "metric": financial_metric, "results": results}

    if intent == "price_history" and not date_range:
        # "So sánh giá X và Y" with no time phrase means "right now", not a
        # multi-month range summary -- comparing min/max over 90 days isn't
        # what a comparison question is usually asking for.
        date_range = current_price_range().as_dict()

    entities = entities[:_MAX_COMPARE_ENTITIES]
    start, end = _date_bounds(date_range)
    latest_only = bool((date_range or {}).get("is_current"))
    results: list[dict] = []

    for entity in entities:
        ticker = entity["ticker"]
        row: dict = {"ticker": ticker, "name": entity.get("name") or ticker}
        if intent == "company_profile":
            result = get_company_profile(ticker)
            row["found"] = result.found
            if result.found:
                row.update({k: v for k, v in result.profile.items() if k != "company_profile_summary"})
            else:
                row["error"] = result.error
        elif intent == "indicator":
            resolved_indicator = indicator_type or "SMA"
            resolved_window = window_size or _DEFAULT_WINDOW.get(resolved_indicator, 14)
            result = get_indicator(ticker, resolved_indicator, resolved_window, start, end)
            row.update(
                {
                    "found": result.found,
                    "indicator": result.indicator,
                    "window_size": result.window_size,
                    "latest_value": result.latest_value,
                    "latest_date": result.latest_date,
                    "error": result.error,
                }
            )
        else:  # price_history
            result = get_ohlcv_summary(ticker, start, end, latest_only=latest_only)
            row["found"] = result.found
            if result.found:
                row.update(result.stats)
                if latest_only:
                    # `result.start`/`.end` collapse to the single real
                    # trading date when latest_only -- report that as this
                    # row's as-of date instead of the padded lookback window
                    # below, which would read as a contradiction next to
                    # "giá hiện tại"/"last_close".
                    row["date"] = result.end
            else:
                row["error"] = result.error
        results.append(row)

    comparison: dict = {"comparison": True, "intent": intent, "results": results}
    if not (intent == "price_history" and latest_only):
        comparison["start"] = start.isoformat()
        comparison["end"] = end.isoformat()
    return comparison


def tool_node(state: AgentState) -> dict:
    intent = state.get("intent")
    ticker = state.get("resolved_ticker")
    ambiguous = state.get("ambiguous_candidates") or []
    multi_entity = state.get("multi_entity_candidates") or []

    if multi_entity:
        comparison = _compare_entities(
            intent,
            multi_entity,
            state.get("resolved_date_range"),
            state.get("indicator_type"),
            state.get("window_size"),
            financial_metric=state.get("financial_metric"),
            # Ignore a date_range merely carried over from a PRIOR turn's
            # different intent (e.g. a price "hiện tại" window) -- reusing
            # that for BCTC period inference would silently restrict results
            # to an unrelated period. Only trust it when this turn actually
            # gave a time phrase (matches the single-ticker branch below).
            financial_date_range=state.get("resolved_date_range") if state.get("time_phrase") else None,
        )
        if comparison:
            return {"tool_result": comparison, "tool_name": f"compare_{intent}"}
        # News/"other" comparisons don't have a sane grounded table to build
        # (unsupported metrics especially -- letting the LLM free-answer a
        # comparison of numbers we never fetched is exactly the fabrication
        # bug this system is designed to avoid), so decline deterministically.
        return {
            "tool_result": {"clarification_needed": True, "reason": "multi_entity_not_supported", "candidates": multi_entity},
            "tool_name": "none",
        }

    if intent == "foreign_stock":
        # Deterministic decline, same principle as unsupported_metric: the
        # router recognized this as a real financial question, just about a
        # company outside the only data source this system has (vnstock,
        # VN-listed only) -- never let the LLM free-answer with its own
        # ungrounded general knowledge about a foreign ticker/price/metric.
        return {
            "tool_result": {"clarification_needed": True, "reason": "foreign_market_not_supported"},
            "tool_name": "none",
        }

    if intent == "other":
        if ticker:
            # The router couldn't classify this into company_profile/price/
            # indicator, but a real ticker WAS resolved -- this is an on-topic
            # finance question about something we don't have a tool for (P/E,
            # beta, MACD, VN30 membership...), not small talk. Routing it to
            # the unconstrained general-chat prompt let the LLM confidently
            # fabricate numbers (e.g. an invented "Beta: 1.35" citing vnstock
            # data that was never fetched) -- ground it instead.
            return {
                "tool_result": {"clarification_needed": True, "reason": "unsupported_metric", "ticker": ticker},
                "tool_name": "none",
            }
        # No ticker resolved either -- genuinely general/off-topic chat.
        return {"tool_result": {"general_question": True}, "tool_name": "general"}

    if ambiguous:
        return {
            "tool_result": {"clarification_needed": True, "reason": "ambiguous_company", "candidates": ambiguous},
            "tool_name": "none",
        }

    if intent == "news":
        industry_mention = state.get("industry_mention")
        if industry_mention and not ticker:
            result = get_news_by_industry(industry_mention)
            return {"tool_result": result.to_dict(), "tool_name": "news"}
        if not ticker:
            return {"tool_result": {"clarification_needed": True, "reason": "missing_ticker"}, "tool_name": "none"}
        result = get_news_by_ticker(ticker)
        return {"tool_result": result.to_dict(), "tool_name": "news", "last_ticker": ticker}

    if not ticker:
        return {
            "tool_result": {"clarification_needed": True, "reason": "missing_ticker"},
            "tool_name": "none",
        }

    if intent == "company_evaluation":
        # Should already have been fanned out to the parallel evaluate path
        # by build_graph.py's routing (see route_after_cache_miss) whenever
        # the ticker resolves cleanly -- reaching here with a valid ticker
        # means that routing didn't fire, which is a bug elsewhere. Decline
        # safely rather than silently answer as if this were a price lookup.
        return {
            "tool_result": {"clarification_needed": True, "reason": "unsupported_metric", "ticker": ticker},
            "tool_name": "none",
        }

    if intent == "company_profile":
        result = get_company_profile(ticker)
        return {"tool_result": result.to_dict(), "tool_name": "company_profile", "last_ticker": ticker}

    if intent == "financial_statement":
        financial_metric = state.get("financial_metric")
        if not financial_metric:
            # Same grounding as intent="other" + resolved ticker: a real BCTC
            # question the router couldn't map to a supported metric must
            # decline deterministically, never fall through to free-form LLM
            # answering (that's exactly how the MACD/beta hallucination bug
            # happened before -- see #7 in PROJECT_CONTEXT.md).
            return {
                "tool_result": {"clarification_needed": True, "reason": "unsupported_metric", "ticker": ticker},
                "tool_name": "none",
            }
        # Ignore a date_range merely carried over from a prior turn's
        # different intent -- only trust it when this turn gave a time phrase.
        financial_date_range = state.get("resolved_date_range") if state.get("time_phrase") else None
        result = get_financial_metric_for_question(ticker, financial_metric, financial_date_range)
        return {"tool_result": result.to_dict(), "tool_name": "financial_statement", "last_ticker": ticker}

    date_range = state.get("resolved_date_range")
    start, end = _date_bounds(date_range)
    resolved_range = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "label": (date_range or {}).get("label", ""),
        # Must survive into `last_date_range` so a same-turn-less follow-up
        # ("còn FPT thì sao") that reuses this carried-over range still gets
        # treated as a current-price question instead of silently reverting
        # to the padded lookback window (see #21/#22 in PROJECT_CONTEXT.md).
        "is_current": bool((date_range or {}).get("is_current")),
    }

    if intent == "indicator":
        indicator_type = state.get("indicator_type") or "SMA"
        window_size = state.get("window_size") or _DEFAULT_WINDOW.get(indicator_type, 14)
        result = get_indicator(ticker, indicator_type, window_size, start, end)
        return {
            "tool_result": result.to_dict(),
            "tool_name": "indicator",
            "last_ticker": ticker,
            "last_date_range": resolved_range,
        }

    result = get_ohlcv_summary(ticker, start, end, latest_only=bool((date_range or {}).get("is_current")))
    return {
        "tool_result": result.to_dict(),
        "tool_name": "ohlcv",
        "last_ticker": ticker,
        "last_date_range": resolved_range,
    }
