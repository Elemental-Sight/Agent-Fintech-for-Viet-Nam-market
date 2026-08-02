"""Company evaluation (prompt_v2 requirement #3 / prompt_v3 requirement #1):
a single ticker -> parallel calls to the BCTC tool and the news/sentiment
tool (both already exist, this just orchestrates them), then one Groq call
that synthesizes a structured strengths/weaknesses/risks summary where every
claim must cite one of the two real data sources.

`bctc_research_node` and `news_sentiment_node` run as parallel graph
branches (see build_graph.py) -- they write to separate state keys
(`research_result`/`news_result`) specifically so LangGraph's default
per-key state merge never has to arbitrate a write conflict between them.

RAG over broker analyst reports (the 3rd source prompt_v2 originally wanted
here) is deferred -- no real report corpus available yet (see
PROJECT_CONTEXT.md). The prompt below only describes the two sources that
actually exist; adding RAG later means adding a 3rd data block + a matching
prompt clause, not restructuring this node.
"""
from __future__ import annotations

import logging

from db import log_usage
from llm import GroqClient
from tools import SUPPORTED_FINANCIAL_METRICS, get_financial_metric_for_question, get_news_by_ticker

from ._utils import DISCLAIMER, last_human_text
from .state import AgentState
from .synthesize_node import _compact_serialize

logger = logging.getLogger("graph.evaluate")

_EVALUATION_SYSTEM_PROMPT = (
    "Bạn là trợ lý phân tích chứng khoán Việt Nam, viết bằng tiếng Việt. Nhiệm vụ: tổng hợp 1 đánh giá "
    "CÓ CẤU TRÚC về 1 công ty dựa CHỈ trên dữ liệu trong 'research_data' (số liệu BCTC) và 'news_data' "
    "(tin tức + sentiment) được cung cấp -- KHÔNG được tự bịa, tự suy diễn, hay dùng kiến thức nền ngoài "
    "2 nguồn này cho bất kỳ con số hay nhận định nào.\n"
    "Trình bày đúng cấu trúc sau (heading markdown):\n"
    "## Điểm mạnh\n"
    "## Điểm yếu\n"
    "## Rủi ro\n"
    "## Số liệu chính\n"
    "Mỗi ý trong Điểm mạnh/Điểm yếu/Rủi ro PHẢI trích rõ nguồn cụ thể ngay trong câu, ví dụ 'theo BCTC "
    "quý 2/2026 (vnstock)' hoặc 'theo tin tức ngày DD/MM/YYYY (vnstock)' -- không viết nhận định chung "
    "chung không có căn cứ. Rủi ro nên dựa trên sentiment tin tức tiêu cực hoặc xu hướng số liệu xấu NẾU "
    "có trong dữ liệu, không tự suy đoán rủi ro không có căn cứ. Mục 'Số liệu chính' trình bày các chỉ số "
    "BCTC hiện có dưới dạng bảng markdown.\n"
    "Nếu 1 nguồn dữ liệu rỗng hoặc 'found': false, hãy nói rõ phần đó hiện chưa có dữ liệu, KHÔNG suy diễn "
    "thay thế.\n"
    "Đây KHÔNG phải khuyến nghị mua/bán/nắm giữ -- chỉ là tổng hợp thông tin có căn cứ.\n"
    f"Luôn kết thúc câu trả lời bằng đúng câu: '{DISCLAIMER}'"
)


def bctc_research_node(state: AgentState) -> dict:
    ticker = state["resolved_ticker"]
    rows: list[dict] = []
    for metric_key in SUPPORTED_FINANCIAL_METRICS:
        result = get_financial_metric_for_question(ticker, metric_key, None)
        if result.found:
            rows.extend(
                {"metric": metric_key, "period": p["period_label"], "value": p["value"], "unit": result.unit}
                for p in result.periods
            )
    research_result = {"ticker": ticker, "found": bool(rows), "metrics": rows}
    if not rows:
        research_result["error"] = "Không tra được số liệu BCTC nào cho mã này."
    return {"research_result": research_result}


def news_sentiment_node(state: AgentState) -> dict:
    ticker = state["resolved_ticker"]
    result = get_news_by_ticker(ticker)
    return {"news_result": result.to_dict()}


def evaluate_node(state: AgentState) -> dict:
    question = last_human_text(state["messages"])
    ticker = state.get("resolved_ticker") or ""
    research_result = state.get("research_result") or {}
    news_result = state.get("news_result") or {}

    user_prompt = (
        f"Câu hỏi của người dùng: {question}\n\n"
        f"research_data (nguồn: BCTC/vnstock, mã {ticker}):\n{_compact_serialize(research_result)}\n\n"
        f"news_data (nguồn: tin tức CBTT + sentiment/vnstock, mã {ticker}):\n{_compact_serialize(news_result)}"
    )
    guardrail_feedback = state.get("guardrail_feedback")
    if guardrail_feedback:
        user_prompt += (
            "\n\nLƯU Ý: bản đánh giá trước đó có các số liệu KHÔNG khớp với research_data/news_data: "
            f"{', '.join(guardrail_feedback)}. Viết lại, chỉ dùng đúng số liệu có trong dữ liệu ở trên."
        )
    messages = [{"role": "system", "content": _EVALUATION_SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}]

    answer = None
    try:
        client = GroqClient(usage_logger=log_usage)
        result = client.chat(
            messages=messages,
            node="evaluate",
            thread_id=state.get("thread_id"),
            temperature=0.2,
            max_tokens=4096,
        )
        answer = result.content
    except Exception:
        logger.exception("evaluate: Groq call failed, falling back to templated answer")

    if not answer:
        answer = f"Xin lỗi, hiện tôi chưa thể tổng hợp đánh giá cho mã {ticker}. {DISCLAIMER}"

    # Nested under `tool_result` (not two separate keys) so guardrail_node's
    # generic number-extraction walk works identically for this path and the
    # normal tool->synthesize path, without needing to know which path it is.
    combined = {"found": bool(research_result.get("found")) or bool(news_result.get("found")),
                "research": research_result, "news": news_result}

    # `draft_answer`, not `messages` -- see synthesize_node.py for why (kept
    # out of permanent chat history until guardrail_node approves it).
    return {
        "draft_answer": answer,
        "tool_result": combined,
        "tool_name": "company_evaluation",
        "last_ticker": ticker,
    }
