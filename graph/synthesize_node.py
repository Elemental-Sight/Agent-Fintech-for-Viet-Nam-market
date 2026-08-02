"""Synthesize node (requirement #6, third stage): composes the final
Vietnamese answer strictly from tool_result JSON, always citing the data
source and the as-of date/range (requirement: no number may be invented)."""
from __future__ import annotations

import logging
from datetime import date

from db import log_usage
from llm import GroqClient

from ._utils import DISCLAIMER, last_human_text
from .context_trim import build_context_messages
from .state import AgentState

logger = logging.getLogger("graph.synthesize")


def _compact_serialize(tool_result: dict) -> str:
    """Serialize tool_result as compact key:value lines + TSV tables for any
    list-of-dict fields (series/articles), instead of full JSON -- cuts
    prompt tokens noticeably for OHLCV/indicator/news answers with many rows
    (prompt_v1 requirement #4: "serialize dạng bảng gọn thay vì JSON đầy đủ")."""
    lines: list[str] = []
    table_fields: dict[str, list[dict]] = {}

    for key, value in tool_result.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            table_fields[key] = value
        elif isinstance(value, dict):
            lines.append(f"{key}: " + ", ".join(f"{k}={v}" for k, v in value.items()))
        else:
            lines.append(f"{key}: {value}")

    for field_name, rows in table_fields.items():
        columns = list(rows[0].keys())
        lines.append(f"\n{field_name} (TSV, {len(rows)} dòng):")
        lines.append("\t".join(columns))
        for row in rows:
            lines.append("\t".join(str(row.get(c, "")) for c in columns))

    return "\n".join(lines)


_FINANCIAL_SYSTEM_PROMPT = (
    "Bạn là trợ lý phân tích chứng khoán Việt Nam. Bạn PHẢI trả lời bằng tiếng Việt.\n"
    "Chỉ được dùng các con số có trong JSON 'tool_result' được cung cấp -- KHÔNG được tự bịa, "
    "tự tính, hay tự suy diễn bất kỳ con số nào ngoài JSON đó.\n"
    "Luôn trích dẫn rõ nguồn số liệu (ví dụ: dữ liệu giá/chỉ báo từ vnstock) và ngày hoặc khoảng "
    "thời gian mà số liệu được tính.\n"
    "User prompt sẽ kèm 'Ngày hệ thống hiện tại' (deterministic, không phải do bạn tự đoán). Khi trả lời "
    "câu hỏi kiểu 'giá/chỉ số hiện tại/hôm nay', nếu ngày dữ liệu mới nhất trong tool_result KHÁC ngày hệ "
    "thống hiện tại, TUYỆT ĐỐI không gọi số liệu đó là 'hôm nay' -- hãy gọi là 'phiên giao dịch gần nhất "
    "(ngày cụ thể)' và có thể giải thích ngắn gọn lý do thường gặp (cuối tuần/ngày lễ thị trường không "
    "giao dịch) nếu phù hợp. Chỉ dùng 'hôm nay' khi 2 ngày đó trùng nhau.\n"
    "Nếu tool_result có field 'series' (chuỗi giá hoặc chuỗi chỉ báo theo ngày), LUÔN trình bày "
    "chuỗi đó dưới dạng bảng markdown (cú pháp | cột | cột |), không liệt kê dạng gạch đầu dòng.\n"
    "Nếu tool_result là hồ sơ doanh nghiệp (company_profile), chỉ nêu các thông tin nổi bật nhất "
    "(tên công ty, ngành, giá hiện tại, vốn hóa, khuyến nghị/giá mục tiêu nếu có, mô tả ngắn gọn) -- "
    "KHÔNG liệt kê hết toàn bộ trường dữ liệu, giữ câu trả lời ngắn gọn súc tích. Nếu profile có field "
    "'chairman'/'ceo', đó là Chủ tịch HĐQT/Tổng Giám đốc lấy từ dữ liệu thật -- chỉ trả lời tên đó, TUYỆT "
    "ĐỐI không tự lấy tên lãnh đạo từ kiến thức nền của bạn nếu field này không có trong tool_result.\n"
    "Nếu tool_result có 'comparison': true và field 'results' (danh sách nhiều mã), đây là câu hỏi so "
    "sánh nhiều mã -- trình bày 'results' dưới dạng 1 bảng markdown duy nhất (mỗi hàng là 1 mã) rồi nêu "
    "ngắn gọn điểm khác biệt chính giữa các mã, dựa đúng số liệu trong bảng đó.\n"
    "Nếu tool_result là số liệu BCTC (có field 'metric_key' và 'periods'), trình bày 'periods' dưới dạng "
    "bảng markdown (Kỳ | Giá trị), ghi rõ đơn vị theo field 'unit' (VND/%/x), và trích nguồn 'theo BCTC/"
    "vnstock'. Nếu 'found': false, hãy nói rõ lý do trong 'error' (thường là do vnstock chỉ cung cấp ~4 kỳ "
    "gần nhất) -- TUYỆT ĐỐI không tự ước tính hay suy ra con số ngoài phạm vi kỳ đã có.\n"
    "Nếu tool_result là tin tức (có 'articles' và 'sentiment_summary'), trình bày danh sách tin dưới dạng "
    "bảng markdown (Ngày | Tiêu đề | Cảm xúc), sau đó nêu điểm sentiment tổng hợp (tích cực/tiêu cực/trung "
    "tính, số lượng mỗi loại) đúng theo 'sentiment_summary' -- không tự đánh giá cảm xúc khác với nhãn đã cho.\n"
    "Nếu tool_result có 'found': false hoặc có 'error', hãy nói rõ là không tra được dữ liệu và nêu lý do, "
    "không suy diễn thêm.\n"
    "Nếu người dùng hỏi về 1 chỉ số cụ thể (P/E, EPS, ROE, cổ tức, biên lợi nhuận...) mà KHÔNG có trong "
    "tool_result, hãy nói rõ hệ thống hiện chưa hỗ trợ tra cứu chỉ số đó -- đừng lờ đi câu hỏi hay chỉ "
    "trả lời chung chung sang thông tin khác.\n"
    f"Luôn kết thúc câu trả lời bằng đúng câu: '{DISCLAIMER}'"
)

_GENERAL_SYSTEM_PROMPT = (
    "Bạn là trợ lý hội thoại tiếng Việt, thân thiện và hữu ích, một phần của hệ thống agent chứng "
    "khoán Việt Nam. Câu hỏi này không liên quan đến chứng khoán/tài chính -- hãy trả lời bình thường, "
    "tự nhiên, không cần trích dẫn nguồn số liệu hay thêm disclaimer đầu tư.\n"
    "Ngoại lệ bắt buộc: nếu câu hỏi thực chất vẫn nhắc đến một mã cổ phiếu/công ty Việt Nam cụ thể và "
    "yêu cầu số liệu tài chính hay kỹ thuật (giá, P/E, EPS, beta, MACD, xếp hạng...), TUYỆT ĐỐI KHÔNG "
    "được tự bịa ra con số -- hãy nói rõ bạn không có dữ liệu thật cho yêu cầu đó."
)


def synthesize_node(state: AgentState) -> dict:
    question = last_human_text(state["messages"])
    tool_result = state.get("tool_result") or {}
    tool_name = state.get("tool_name") or "none"
    is_general = tool_name == "general" or tool_result.get("general_question")

    if tool_result.get("clarification_needed"):
        # No synthesis needed here -- it's just "please pick one of these
        # tickers". Skipping the LLM entirely means it can never embellish
        # the candidate list with invented company info (a real hallucination
        # we saw in testing: it added a fabricated "(VPBank)" annotation to
        # an unrelated ticker despite being told not to).
        return {"messages": [{"role": "assistant", "content": _fallback_answer(tool_result)}]}

    if is_general:
        system_prompt = _GENERAL_SYSTEM_PROMPT
        # General chat has no deterministic state (like last_ticker) to carry
        # context across turns, so it needs the actual conversation history
        # replayed -- otherwise follow-ups like "anh ấy giàu thế nào" lose
        # who "anh ấy" refers to.
        messages = [
            {"role": "system", "content": system_prompt},
            *build_context_messages(state.get("thread_id", ""), state["messages"]),
        ]
    else:
        system_prompt = _FINANCIAL_SYSTEM_PROMPT
        user_prompt = (
            f"Ngày hệ thống hiện tại: {date.today().isoformat()}\n\n"
            f"Câu hỏi của người dùng: {question}\n\n"
            f"tool_result (nguồn dữ liệu: {tool_name}):\n"
            f"{_compact_serialize(tool_result)}"
        )
        guardrail_feedback = state.get("guardrail_feedback")
        if guardrail_feedback:
            # Retry from guardrail_node: the previous answer cited numbers
            # that don't appear anywhere in tool_result -- tell the model
            # exactly which ones so the retry isn't just a random resample.
            user_prompt += (
                "\n\nLƯU Ý: câu trả lời trước đó có các số liệu KHÔNG khớp với tool_result: "
                f"{', '.join(guardrail_feedback)}. Viết lại, chỉ dùng đúng số liệu có trong tool_result ở trên."
            )
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

    answer = None
    try:
        client = GroqClient(usage_logger=log_usage)
        result = client.chat(
            messages=messages,
            node="synthesize",
            thread_id=state.get("thread_id"),
            temperature=0.2,
            max_tokens=4096,
        )
        answer = result.content
    except Exception:
        logger.exception("synthesize: Groq call failed, falling back to templated answer")

    if not answer:
        answer = "Xin lỗi, hiện tôi chưa thể trả lời câu hỏi này." if is_general else _fallback_answer(tool_result)

    # Written to `draft_answer`, not `messages` directly -- guardrail_node
    # checks this draft and only commits it to permanent chat history once
    # it passes (or exhausts its retry budget), so a flawed first attempt
    # never lingers in conversation history alongside the corrected retry.
    return {"draft_answer": answer}


def _fallback_answer(tool_result: dict) -> str:
    if tool_result.get("clarification_needed"):
        candidates = tool_result.get("candidates") or []
        reason = tool_result.get("reason")
        if reason == "unsupported_metric":
            ticker = tool_result.get("ticker", "")
            return (
                f"Xin lỗi, hệ thống hiện chưa hỗ trợ tra cứu chỉ số này cho mã {ticker}. "
                "Hiện tại chỉ hỗ trợ: hồ sơ doanh nghiệp, giá lịch sử OHLCV, chỉ báo kỹ thuật SMA/RSI, và "
                "một số số liệu BCTC (doanh thu, lợi nhuận sau thuế, EPS, nợ vay) -- CHƯA hỗ trợ P/E, P/B, "
                "ROE, ROA, biên lợi nhuận (dữ liệu nguồn không đáng tin cậy). "
                f"{DISCLAIMER}"
            )
        if reason == "foreign_market_not_supported":
            return (
                "Xin lỗi, hệ thống hiện chỉ hỗ trợ chứng khoán niêm yết tại Việt Nam (HOSE/HNX/UPCoM), "
                "chưa hỗ trợ dữ liệu công ty/cổ phiếu nước ngoài. "
                f"{DISCLAIMER}"
            )
        if reason == "multi_entity_not_supported" and candidates:
            listed = ", ".join(f"{c['ticker']} ({c['name']})" for c in candidates)
            first_ticker = candidates[0]["ticker"]
            return (
                f"Hệ thống chưa hỗ trợ so sánh nhiều mã cho loại câu hỏi này. Bạn đang hỏi về: {listed}. "
                "Hệ thống có thể so sánh giá, hồ sơ doanh nghiệp, chỉ báo SMA/RSI, hoặc số liệu BCTC giữa "
                f"nhiều mã -- hãy hỏi lại theo 1 trong các dạng đó, hoặc hỏi lần lượt từng mã (vd {first_ticker}) "
                f"cho loại thông tin này. {DISCLAIMER}"
            )
        if candidates:
            listed = ", ".join(
                f"{c['ticker']} ({c['name']})" if isinstance(c, dict) else str(c) for c in candidates
            )
            return f"Bạn muốn hỏi về mã nào trong số: {listed}? {DISCLAIMER}"
        return f"Bạn vui lòng cho biết rõ mã cổ phiếu hoặc tên công ty bạn muốn hỏi. {DISCLAIMER}"
    if tool_result.get("error") or tool_result.get("found") is False:
        reason = tool_result.get("error", "không rõ nguyên nhân")
        return f"Không tra được dữ liệu: {reason}. {DISCLAIMER}"
    return f"Đã có dữ liệu nhưng không tạo được câu trả lời tự động, vui lòng thử lại. {DISCLAIMER}"
