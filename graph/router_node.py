"""Router node (requirement #6, first stage).

Uses Groq with forced structured tool-calling to classify the question and
pull out RAW substrings (company mention, time phrase). It never invents a
ticker code or a concrete date itself -- resolvers.EntityResolver and
resolvers.TimeResolver do that deterministically right after extraction.
"""
from __future__ import annotations

import json
import logging
import re

from db import log_usage
from llm import GroqClient
from resolvers import EntityResolver, TimeResolver
from tools import SUPPORTED_FINANCIAL_METRICS

from ._utils import last_human_text
from .fast_router import try_fast_route
from .state import AgentState

logger = logging.getLogger("graph.router")

_entity_resolver = EntityResolver()
_time_resolver = TimeResolver()
_FINANCIAL_METRIC_ENUM = set(SUPPORTED_FINANCIAL_METRICS)

_EXTRACT_TOOL = {
    "type": "function",
    "function": {
        "name": "extract_query_info",
        "description": (
            "Trich xuat thong tin co cau truc tu cau hoi cua nguoi dung ve chung khoan Viet Nam. "
            "KHONG tu suy ra ma ticker hay ngay thang cu the -- chi trich nguyen van cum tu nguoi dung da dung."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": [
                        "company_profile", "price_history", "indicator", "news",
                        "financial_statement", "company_evaluation", "foreign_stock", "other",
                    ],
                    "description": (
                        "Loai cau hoi: ho so doanh nghiep, lich su gia, chi bao ky thuat, tin tuc/sentiment, "
                        "so lieu BCTC (doanh thu/loi nhuan sau thue/EPS/no vay), hoac danh gia/phan tich TONG "
                        "THE 1 cong ty (diem manh/yeu/rui ro, vi du 'danh gia HPG', 'phan tich toan dien VNM') "
                        "-- dung \"company_evaluation\" CHI khi nguoi dung muon 1 nhan dinh tong hop nhieu mat, "
                        "khong phai hoi 1 so lieu cu the. "
                        "QUAN TRONG: neu cong ty duoc hoi la cong ty niem yet o NUOC NGOAI (khong phai san "
                        "chung khoan Viet Nam -- vi du Apple, Tesla, cong ty cua Elon Musk...), LUON dat "
                        "intent=\"foreign_stock\" BAT KE cau hoi la ve gia, chi so, danh gia hay tin tuc -- "
                        "khong dung cac intent khac cho cong ty nuoc ngoai. "
                        "Dung \"other\" cho MOI cau hoi khong lien quan den chung khoan/tai chinh (vi du: "
                        "chao hoi, hoi chuyen, kien thuc tong quat, lap trinh...)."
                    ),
                },
                "company_mention": {
                    "type": "string",
                    "description": "Ten/alias cong ty hoac ma ticker duoc nhac toi nguyen van. Dung chuoi rong \"\" neu khong co (vi du cau hoi noi tiep, hoac khi hoi tin tuc theo NGANH thay vi theo ma).",
                },
                "industry_mention": {
                    "type": "string",
                    "description": "Ten NGANH duoc nhac toi nguyen van, chi dung khi intent=news va cau hoi hoi theo nganh thay vi theo ma cu the (vi du 'nganh ngan hang'). Dung chuoi rong \"\" neu khong co.",
                },
                "time_phrase": {
                    "type": "string",
                    "description": "Cum tu chi thoi gian nguyen van. Dung chuoi rong \"\" neu khong co.",
                },
                "indicator_type": {
                    "type": "string",
                    "enum": ["SMA", "RSI", "NONE"],
                    "description": "Loai chi bao ky thuat duoc hoi, chi khi intent=indicator. Dung \"NONE\" neu khong ap dung.",
                },
                "window_size": {
                    "type": "integer",
                    "description": "Window size cho chi bao (vi du 14). Dung 0 neu nguoi dung khong neu ro.",
                },
                "financial_metric": {
                    "type": "string",
                    "enum": ["REVENUE", "NET_PROFIT", "EPS", "DEBT", "NONE"],
                    "description": (
                        "Chi so BCTC duoc hoi, chi khi intent=financial_statement: REVENUE=doanh thu, "
                        "NET_PROFIT=loi nhuan sau thue/LNST, EPS, DEBT=no vay. Dung \"NONE\" neu khong ap dung, "
                        "khong xac dinh duoc, hoac chi so khac (P/E, ROE, ROA, bien loi nhuan...) chua ho tro."
                    ),
                },
            },
            "required": [
                "intent", "company_mention", "industry_mention", "time_phrase",
                "indicator_type", "window_size", "financial_metric",
            ],
        },
    },
}

_SYSTEM_PROMPT = (
    "Ban la bo phan loai cau hoi cho he thong agent chung khoan Viet Nam. He thong CHI co du lieu that "
    "cho cong ty niem yet tai Viet Nam -- khong co du lieu gi cho thi truong nuoc ngoai. "
    "Luon goi ham extract_query_info voi thong tin trich xuat duoc, khong tra loi truc tiep. "
    "Khong tu suy doan ma ticker hay ngay thang cu the, chi trich nguyen van. "
    "Neu cau hoi ve 1 cong ty niem yet o nuoc ngoai, dat intent=\"foreign_stock\". "
    "Neu cau hoi khong lien quan den chung khoan/tai chinh, dat intent=\"other\"."
)


_EMPTY_SENTINELS = {"", "none", "null", "n/a", "na", "nan"}


def _clean_str(value) -> str | None:
    """Some Groq tool-calling models emit the literal text "None"/"" instead
    of actually omitting an optional field -- normalize all of that to None."""
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.lower() not in _EMPTY_SENTINELS else None


def _clean_int(value) -> int | None:
    text = _clean_str(value)
    if text is None:
        return None
    try:
        parsed = int(float(text))
    except ValueError:
        return None
    return parsed if parsed > 0 else None  # 0 is the "not specified" sentinel


# The system only calls one tool with one ticker per turn -- it can't
# actually compare "HPG và HSG" in a single call. Detect this so we can tell
# the user clearly instead of feeding a combined, unresolvable mention into
# the entity resolver (which was producing confusing false-ambiguity results).
_MULTI_ENTITY_SPLIT_RE = re.compile(r"\s*(?:,|;|\bvà\b|\bva\b|\bvs\b|\bso với\b|\bso voi\b)\s*", re.IGNORECASE)

# Keyword -> metric mapping for the heuristic fallback (Groq extraction call
# itself failed). Order matters: checked top to bottom, first match wins.
_FINANCIAL_METRIC_KEYWORDS = [
    (("doanh thu",), "REVENUE"),
    (("lợi nhuận sau thuế", "loi nhuan sau thue", "lnst"), "NET_PROFIT"),
    (("eps",), "EPS"),
    (("nợ vay", "no vay"), "DEBT"),
]


def _ticker_with_name(ticker: str) -> dict:
    record = _entity_resolver.get(ticker)
    return {"ticker": ticker, "name": (record.short_name or record.full_name) if record else ticker}


def _resolve_company_mention(mention: str) -> tuple[str | None, list[dict], list[dict]]:
    """Returns (resolved_ticker, ambiguous_candidates, multi_entity_candidates)."""
    parts = [p for p in _MULTI_ENTITY_SPLIT_RE.split(mention) if p.strip()]
    if len(parts) > 1:
        seen: set[str] = set()
        resolved = []
        for part in parts:
            entity = _entity_resolver.resolve(part)
            if entity.is_found and entity.ticker not in seen:
                seen.add(entity.ticker)
                resolved.append(_ticker_with_name(entity.ticker))
        if len(resolved) >= 2:
            return None, [], resolved

    entity = _entity_resolver.resolve(mention)
    if entity.is_found:
        return entity.ticker, [], []
    if entity.is_ambiguous:
        return None, [_ticker_with_name(t) for t in entity.candidates], []
    return None, [], []


def _heuristic_fallback(question: str) -> dict:
    """Deterministic fallback if the Groq extraction call itself fails, so
    the graph degrades gracefully instead of crashing. Passes the raw question
    through as company_mention -- _resolve_company_mention() can often still
    recover an explicit ticker from it (e.g. via the all-caps-word shortcut),
    which is strictly better than always discarding it."""
    lowered = question.lower()
    base = {
        "company_mention": question,
        "industry_mention": None,
        "time_phrase": None,
        "indicator_type": None,
        "window_size": None,
        "financial_metric": None,
    }
    if any(kw in lowered for kw in ("đánh giá", "danh gia", "phân tích toàn diện", "phan tich toan dien",
                                     "phân tích công ty", "phan tich cong ty", "nhận định về", "nhan dinh ve",
                                     "điểm mạnh điểm yếu", "diem manh diem yeu")):
        return {**base, "intent": "company_evaluation"}
    if "tin tức" in lowered or "tin tuc" in lowered or "sentiment" in lowered:
        return {**base, "intent": "news"}
    if "rsi" in lowered:
        return {**base, "intent": "indicator", "indicator_type": "RSI"}
    if "sma" in lowered or "trung bình động" in lowered or "trung binh dong" in lowered:
        return {**base, "intent": "indicator", "indicator_type": "SMA"}
    for keywords, metric in _FINANCIAL_METRIC_KEYWORDS:
        if any(kw in lowered for kw in keywords):
            return {**base, "intent": "financial_statement", "financial_metric": metric}
    if "hồ sơ" in lowered or "ho so" in lowered or "giới thiệu" in lowered or "ngành" in lowered:
        return {**base, "intent": "company_profile"}
    if any(kw in lowered for kw in ("giá", "gia ", "cổ phiếu", "co phieu", "chứng khoán", "chung khoan")):
        return {**base, "intent": "price_history"}
    return {**base, "intent": "other", "company_mention": None}


# guardrail_node's per-turn scratch fields -- MUST be reset at the start of
# every turn. They're checkpointed via Postgres across the whole thread like
# everything else in AgentState, so without this a retry used up in one turn
# silently eats into a LATER, unrelated turn's retry budget (caught
# live-testing: a company_evaluation answer that needed 1 retry left
# guardrail_retry_count=1 in the persisted state, so the NEXT turn started
# with its budget already exhausted).
_GUARDRAIL_RESET = {
    "guardrail_retry_count": 0,
    "guardrail_needs_retry": False,
    "guardrail_feedback": None,
    "draft_answer": None,
}


def router_node(state: AgentState) -> dict:
    question = last_human_text(state["messages"])

    # Tier-1 fast path (prompt_v1 requirement #2): explicit-ticker simple
    # lookups skip the Groq call entirely. Deferred to the full router below
    # whenever it isn't 100% confident (comparisons, aliases, unclear intent).
    fast = try_fast_route(question, last_date_range=state.get("last_date_range"))
    if fast is not None:
        return {
            **_GUARDRAIL_RESET,
            "intent": fast.intent,
            "ticker_mention": fast.ticker,
            "industry_mention": None,
            "time_phrase": None,
            "indicator_type": fast.indicator_type,
            "window_size": fast.window_size,
            "financial_metric": None,
            "resolved_ticker": fast.ticker,
            "resolved_date_range": fast.resolved_date_range,
            "ambiguous_candidates": [],
            "multi_entity_candidates": [],
            "used_fast_path": True,
        }

    extracted = None
    try:
        client = GroqClient(usage_logger=log_usage)
        result = client.chat(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            node="router",
            thread_id=state.get("thread_id"),
            tools=[_EXTRACT_TOOL],
            tool_choice={"type": "function", "function": {"name": "extract_query_info"}},
        )
        if result.tool_calls:
            extracted = json.loads(result.tool_calls[0]["arguments"])
    except Exception:
        logger.exception("router: Groq extraction failed, falling back to heuristic")

    if not extracted:
        extracted = _heuristic_fallback(question)

    intent = _clean_str(extracted.get("intent")) or "other"
    company_mention = _clean_str(extracted.get("company_mention"))
    industry_mention = _clean_str(extracted.get("industry_mention"))
    time_phrase = _clean_str(extracted.get("time_phrase"))
    indicator_type = _clean_str(extracted.get("indicator_type"))
    if indicator_type is not None:
        indicator_type = indicator_type.upper()
        if indicator_type not in ("SMA", "RSI"):
            indicator_type = None
    window_size = _clean_int(extracted.get("window_size"))
    financial_metric = _clean_str(extracted.get("financial_metric"))
    if financial_metric is not None:
        financial_metric = financial_metric.upper()
        if financial_metric not in _FINANCIAL_METRIC_ENUM:
            financial_metric = None

    # company_evaluation, "other" and "foreign_stock" never inherit last_ticker.
    # company_evaluation: it's a standalone report request each time, not a
    # "same subject, different metric" follow-up like price/RSI questions
    # are. Silently reusing a stale ticker here produced a real bug (caught
    # live-testing): "Đánh giá công ty ngân hàng" (no resolvable
    # company_mention) reused the PREVIOUS turn's ticker and confidently
    # generated a full report about the wrong company instead of asking for
    # clarification.
    # "other": tool_node treats intent="other" + a resolved ticker as an
    # on-topic-but-unsupported-metric question (e.g. "MWG beta bao nhieu")
    # and declines deterministically instead of answering freely -- correct
    # when the ticker came from THIS turn's company_mention, but wrong when
    # it's only inherited from a past turn: genuinely unrelated small talk
    # ("bạn là ai") right after a price lookup was inheriting the previous
    # last_ticker and got misreported as "chưa hỗ trợ tra cứu chỉ số này cho
    # mã MWG" instead of being answered as general chat (caught live-testing).
    # "foreign_stock": a VN ticker from a PAST turn has no bearing on a
    # question about a foreign company this turn -- e.g. asking about MWG
    # then "cổ phiếu Tesla giá bao nhiêu" must not carry MWG forward.
    resolved_ticker = None if intent in ("company_evaluation", "other", "foreign_stock") else state.get("last_ticker")
    ambiguous_candidates: list[dict] = []
    multi_entity_candidates: list[dict] = []
    # Skip VN entity resolution for foreign_stock -- company_mention here is a
    # foreign company name that will never legitimately match data/tickers.json
    # (VN-only), so attempting it only risks a spurious fuzzy-match false
    # positive against an unrelated VN ticker.
    if company_mention and intent != "foreign_stock":
        # Enrichment with real registered names (via _ticker_with_name) means
        # synthesize_node always has grounded data to cite -- it's never left
        # with bare ticker codes it might otherwise invent company info for.
        resolved_ticker, ambiguous_candidates, multi_entity_candidates = _resolve_company_mention(company_mention)

    resolved_date_range = state.get("last_date_range")
    if time_phrase:
        date_range = _time_resolver.resolve(time_phrase)
        if date_range:
            resolved_date_range = date_range.as_dict()

    return {
        **_GUARDRAIL_RESET,
        "intent": intent,
        "ticker_mention": company_mention,
        "industry_mention": industry_mention if intent == "news" else None,
        "time_phrase": time_phrase,
        "indicator_type": indicator_type,
        "window_size": window_size,
        "financial_metric": financial_metric,
        "resolved_ticker": resolved_ticker,
        "resolved_date_range": resolved_date_range,
        "ambiguous_candidates": ambiguous_candidates,
        "multi_entity_candidates": multi_entity_candidates,
        "used_fast_path": False,
    }
