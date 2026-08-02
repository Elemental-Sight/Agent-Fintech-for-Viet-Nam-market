"""Guardrail node (prompt_v3 requirement #1): after synthesize/evaluate,
cross-checks the numbers in the final answer against the numbers actually
present in `tool_result`. This is the "regex/exact match" heuristic check
the spec asks for -- a SECOND, best-effort line of defense, not the primary
one (the primary defense is still the deterministic `unsupported_metric`
routing in tool_node.py that keeps ungrounded questions away from free-form
LLM answering in the first place -- see #7 in PROJECT_CONTEXT.md).

Deliberately tolerant on small numbers (< 10): dates, list positions, and
percentages are common, hard to verify reliably by pure numeric matching,
and flagging them generates far more false positives than genuine catches.
The numbers this guardrail actually protects against -- a fabricated
revenue/price/ratio figure -- are large and distinctive enough that requiring
an approximate match against real tool_result values is a meaningful check
without that noise.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from .state import AgentState

logger = logging.getLogger("graph.guardrail")

_MAX_RETRIES = 1
_MIN_CHECKED_VALUE = 10.0
_TOLERANCE = 0.01

_NUMBER_RE = re.compile(r"\d[\d.,]*\d|\d")


def _normalize_number(raw: str) -> Optional[float]:
    """Vietnamese formatting uses '.' as a thousands separator and ',' as
    the decimal point (e.g. "185.056.626.536.000,0") -- but numbers copied
    verbatim from tool_result's own JSON-ish serialization use plain '.'
    decimals too, so both conventions have to be tolerated."""
    text = raw.strip()
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    elif text.count(".") > 1:
        text = text.replace(".", "")
    # Leading digit must be 1-9 (not 0) -- "0.215" (a plain decimal, e.g. a
    # sentiment score) must NOT be treated as VN thousands-grouping, or it
    # gets mangled into 215. Nobody writes a thousands-separated number
    # starting with "0" (caught live-testing: "-0.215" flagged as ungrounded
    # because it got parsed as 215).
    elif re.fullmatch(r"[1-9]\d{0,2}(\.\d{3})+", text):
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def _extract_numbers(text: str) -> list[float]:
    numbers = []
    for match in _NUMBER_RE.finditer(text):
        n = _normalize_number(match.group(0))
        if n is not None:
            numbers.append(n)
    return numbers


def _grounded_numbers(data) -> set[float]:
    """Recursively collects every number in a tool_result-shaped structure
    -- both real numeric leaves AND numbers embedded in string fields (e.g.
    "2026" inside a period_label like "2026-Q2", or a date string), since
    the LLM restating a period/date is not a fabrication."""
    found: set[float] = set()
    if isinstance(data, dict):
        for v in data.values():
            found |= _grounded_numbers(v)
    elif isinstance(data, list):
        for v in data:
            found |= _grounded_numbers(v)
    elif isinstance(data, bool):
        pass
    elif isinstance(data, (int, float)):
        found.add(float(data))
    elif isinstance(data, str):
        found |= set(_extract_numbers(data))
    return found


def _is_grounded(number: float, grounded: set[float], tolerance: float = _TOLERANCE) -> bool:
    if not grounded:
        return True  # nothing to check against (e.g. general chat) -- don't false-flag
    # Compared by magnitude, not sign: `_NUMBER_RE` doesn't capture a leading
    # "-", and Vietnamese financial writing conventionally expresses
    # direction with words ("giảm 12.39%") rather than a minus sign, so a
    # negative grounded value (e.g. pct_change=-12.39) legitimately shows up
    # in the answer as a bare positive "12.39" (caught live-testing).
    number = abs(number)
    n_str = str(int(number)) if number == int(number) else None
    for g in grounded:
        g = abs(g)
        if g == 0:
            if number < 1e-9:
                return True
            continue
        if abs(number - g) / g <= tolerance:
            return True
        # Truncated/rounded restatement, e.g. answer says "185" (as in "185
        # nghìn tỷ") for a grounded value of 185056626536000.
        g_str = str(int(g)) if g == int(g) else None
        if g_str and n_str and len(n_str) >= 2 and g_str.startswith(n_str):
            return True
    return False


def guardrail_node(state: AgentState) -> dict:
    tool_result = state.get("tool_result") or {}
    if tool_result.get("clarification_needed"):
        # synthesize_node committed this straight to `messages` itself
        # (deterministic template, never went through the LLM) -- nothing
        # for guardrail to check or commit.
        return {"guardrail_needs_retry": False}

    answer = state.get("draft_answer")
    if not answer:
        return {"guardrail_needs_retry": False}

    if tool_result.get("general_question"):
        # Unconstrained general chat has no grounded tool_result to check
        # numbers against -- just commit the draft as-is.
        return {"guardrail_needs_retry": False, "messages": [{"role": "assistant", "content": answer}]}

    grounded = _grounded_numbers(tool_result)
    answer_numbers = [n for n in _extract_numbers(answer) if abs(n) >= _MIN_CHECKED_VALUE]
    unverified = [n for n in answer_numbers if not _is_grounded(n, grounded)]

    retry_count = state.get("guardrail_retry_count") or 0
    if unverified and retry_count < _MAX_RETRIES:
        logger.warning(
            "guardrail: %d unverified number(s) in answer (retry %d/%d): %s",
            len(unverified), retry_count + 1, _MAX_RETRIES, unverified,
        )
        return {
            "guardrail_retry_count": retry_count + 1,
            "guardrail_needs_retry": True,
            "guardrail_feedback": [f"{n:g}" for n in unverified],
        }

    if unverified:
        logger.warning(
            "guardrail: %d unverified number(s) remain after retry budget exhausted, "
            "letting answer through as-is: %s", len(unverified), unverified,
        )
    return {
        "guardrail_needs_retry": False,
        "guardrail_feedback": None,
        "messages": [{"role": "assistant", "content": answer}],
    }


def route_after_guardrail(state: AgentState) -> str:
    if state.get("guardrail_needs_retry"):
        return "evaluate" if state.get("intent") == "company_evaluation" else "synthesize"
    return "cache_write"
