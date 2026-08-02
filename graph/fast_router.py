"""Tier-1 rule-based router (prompt_v1 requirement #2).

Handles simple, unambiguous lookups with ZERO LLM calls: an explicit ticker
code (all-caps, e.g. "VCB") combined with a recognizable keyword for price /
one named indicator / company profile. Anything else (aliases needing fuzzy
resolution, comparisons, analysis, unclear intent) intentionally falls
through to the full Groq-based router_node -- the fast path only fires when
the ticker match is already 100% certain (no fuzzy guessing here), keeping
it safe.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from resolvers import EntityResolver, TimeResolver
from resolvers.text_utils import normalize_text

_entity_resolver = EntityResolver()
_time_resolver = TimeResolver()

# Presence of any of these means the question needs the full router's
# multi-entity / comparison / company_evaluation handling -- never
# fast-pathed. The "danh gia"/"phan tich..." entries also fix a real bug:
# "gia " (a _PRICE_KEYWORDS entry) is a substring of "danh GIA" (đánh giá),
# so "Đánh giá công ty HPG" was being mis-fast-pathed to price_history
# before company_evaluation intent existed to compete with it (caught live
# testing).
_DEFER_MARKERS = (
    "so sanh", "so voi", " vs ", " va ", "tuong quan", "khac nhau",
    "danh gia", "phan tich toan dien", "phan tich cong ty", "nhan dinh ve", "diem manh diem yeu",
)

_PROFILE_KEYWORDS = ("ho so", "gioi thieu", "thong tin cong ty", "thong tin doanh nghiep", "profile")
_NEWS_KEYWORDS = ("tin tuc", "tin moi", "sentiment", "cam xuc thi truong")
# "bao nhieu" deliberately excluded -- it's generic enough to appear in any
# "X là bao nhiêu?" question (BCTC metrics included), which was silently
# mis-fast-pathing those to price_history before financial_statement intent
# existed to compete with it (caught live-testing "Biên EBITDA ... bao nhiêu").
_PRICE_KEYWORDS = ("gia ", "gia co phieu", "dien bien gia", "lich su gia")
_INDICATOR_RE = re.compile(r"\b(rsi|sma)\b")
_WINDOW_RE = re.compile(r"\b(\d{1,3})\b")


@dataclass
class FastRouteResult:
    intent: str
    ticker: str
    resolved_date_range: Optional[dict]
    indicator_type: Optional[str]
    window_size: Optional[int]


def try_fast_route(
    question: str, last_date_range: Optional[dict] = None, reference_date=None
) -> Optional[FastRouteResult]:
    if not question or not question.strip():
        return None

    text = normalize_text(question)

    if any(marker in text for marker in _DEFER_MARKERS):
        return None

    entity = _entity_resolver.resolve(question)
    if not entity.is_found:
        # No 100%-certain ticker (exact code or unambiguous all-caps word)
        # -- don't risk a fuzzy guess here, let the full router handle it.
        return None
    ticker = entity.ticker

    resolved_range = last_date_range
    date_range = _time_resolver.resolve(question, reference_date=reference_date)
    if date_range:
        resolved_range = date_range.as_dict()

    indicator_match = _INDICATOR_RE.search(text)
    if indicator_match:
        indicator_type = indicator_match.group(1).upper()
        window_match = _WINDOW_RE.search(text)
        window_size = int(window_match.group(1)) if window_match else None
        return FastRouteResult(
            intent="indicator",
            ticker=ticker,
            resolved_date_range=resolved_range,
            indicator_type=indicator_type,
            window_size=window_size,
        )

    if any(kw in text for kw in _NEWS_KEYWORDS):
        return FastRouteResult(
            intent="news", ticker=ticker, resolved_date_range=resolved_range, indicator_type=None, window_size=None
        )

    if any(kw in text for kw in _PROFILE_KEYWORDS):
        return FastRouteResult(
            intent="company_profile", ticker=ticker, resolved_date_range=resolved_range, indicator_type=None, window_size=None
        )

    if any(kw in text for kw in _PRICE_KEYWORDS):
        return FastRouteResult(
            intent="price_history", ticker=ticker, resolved_date_range=resolved_range, indicator_type=None, window_size=None
        )

    return None
