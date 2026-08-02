"""FastAPI backend hosting the LangGraph agent (requirement #6-#9).

The Streamlit UI is a thin HTTP client of this service -- all agent logic,
tool calls, resolvers and Postgres access live here.
"""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException

from config import get_settings
from db import (
    check_rate_limit,
    create_session,
    delete_session,
    get_checkpointer,
    get_observability_summary,
    get_session,
    get_usage_summary,
    init_db,
    list_sessions,
    log_request,
    log_usage,
    touch_session,
    update_session,
)
from graph import build_graph
from llm import GroqClient
from tools import screen_stocks

from .schemas import (
    ChatRequest,
    ChatResponse,
    CreateSessionResponse,
    MessageOut,
    ScreenerRequest,
    SessionOut,
    UpdateSessionRequest,
    UsageSummary,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

_graph = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    checkpointer = get_checkpointer()
    global _graph
    _graph = build_graph(checkpointer=checkpointer)
    yield


app = FastAPI(title="VN Stock Agent API", lifespan=lifespan)


def _generate_title(message: str) -> str:
    """Short Groq call to title a new session from its first message
    (prompt_v1 requirement #5) -- falls back to plain truncation if the
    call fails, so a flaky/slow title generation never breaks the chat."""
    fallback = message.strip()[:40] or "Phiên mới"
    try:
        client = GroqClient(usage_logger=log_usage)
        result = client.chat(
            messages=[
                {
                    "role": "system",
                    "content": "Đặt tiêu đề ngắn gọn (dưới 6 từ, tiếng Việt, không dấu ngoặc kép) cho phiên "
                    "hội thoại dựa trên tin nhắn đầu tiên của người dùng. PHẢI giữ đúng chủ đề, mã cổ phiếu "
                    "hoặc tên công ty được nhắc trong tin nhắn -- KHÔNG tự đổi sang chủ đề khác. "
                    "Chỉ trả về tiêu đề, không giải thích.",
                },
                {"role": "user", "content": message},
            ],
            node="title",
            temperature=0.1,
            max_tokens=30,
        )
        title = (result.content or "").strip().strip('"').strip("'")
        return title[:60] if title else fallback
    except Exception:
        logger.exception("title generation failed, falling back to truncation")
        return fallback


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/sessions", response_model=CreateSessionResponse)
def create_new_session():
    thread_id = str(uuid.uuid4())
    create_session(thread_id)
    return CreateSessionResponse(thread_id=thread_id, title="Phiên mới")


@app.get("/sessions", response_model=list[SessionOut])
def get_sessions():
    rows = list_sessions()
    return [
        SessionOut(
            thread_id=r["thread_id"],
            title=r["title"],
            pinned=r["pinned"],
            created_at=r["created_at"].isoformat(),
            updated_at=r["updated_at"].isoformat(),
        )
        for r in rows
    ]


@app.patch("/sessions/{thread_id}", response_model=SessionOut)
def update_session_endpoint(thread_id: str, req: UpdateSessionRequest):
    if get_session(thread_id) is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên")
    update_session(thread_id, title=req.title, pinned=req.pinned)
    row = get_session(thread_id)
    return SessionOut(
        thread_id=row["thread_id"],
        title=row["title"],
        pinned=row["pinned"],
        created_at=row["created_at"].isoformat(),
        updated_at=row["updated_at"].isoformat(),
    )


@app.delete("/sessions/{thread_id}")
def delete_session_endpoint(thread_id: str):
    if _graph is None:
        raise HTTPException(status_code=503, detail="Graph chưa sẵn sàng")
    get_checkpointer().delete_thread(thread_id)
    delete_session(thread_id)
    return {"deleted": True, "thread_id": thread_id}


@app.get("/sessions/{thread_id}/history", response_model=list[MessageOut])
def get_history(thread_id: str):
    if _graph is None:
        raise HTTPException(status_code=503, detail="Graph chưa sẵn sàng")

    config = {"configurable": {"thread_id": thread_id}}
    snapshot = _graph.get_state(config)
    messages = (snapshot.values.get("messages") if snapshot and snapshot.values else None) or []

    out = []
    for msg in messages:
        if isinstance(msg, dict):
            role, content = msg.get("role"), msg.get("content")
        else:
            role, content = getattr(msg, "type", None), getattr(msg, "content", None)
        role = {"human": "user", "ai": "assistant"}.get(role, role)
        if role in ("user", "assistant") and content:
            out.append(MessageOut(role=role, content=content))
    return out


@app.get("/usage/{thread_id}", response_model=UsageSummary)
def get_usage(thread_id: str):
    return UsageSummary(**get_usage_summary(thread_id))


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if _graph is None:
        raise HTTPException(status_code=503, detail="Graph chưa sẵn sàng")

    settings = get_settings()
    if not settings.groq_api_key:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY chưa được cấu hình.")

    # Simple per-session rate limit (prompt_v1 requirement #5) to protect the
    # Groq free-tier quota when demoing publicly.
    if not check_rate_limit(req.thread_id):
        raise HTTPException(
            status_code=429, detail="Bạn đã gửi quá nhiều tin nhắn trong 1 giờ qua, vui lòng thử lại sau."
        )

    config = {"configurable": {"thread_id": req.thread_id}}
    result = _graph.invoke(
        {"messages": [{"role": "user", "content": req.message}], "thread_id": req.thread_id},
        config=config,
    )

    session_row = get_session(req.thread_id)
    if session_row and session_row["title"] == "Phiên mới":
        touch_session(req.thread_id, title=_generate_title(req.message))
    else:
        touch_session(req.thread_id)

    last_message = result["messages"][-1]
    answer: Optional[str] = (
        last_message.get("content") if isinstance(last_message, dict) else getattr(last_message, "content", None)
    )

    # v3 part 3 (observability): logged for every request regardless of
    # cache_hit/fast_path, since those paths produce no groq_usage_log row.
    log_request(
        thread_id=req.thread_id,
        tool_name=result.get("tool_name"),
        used_fast_path=result.get("used_fast_path"),
        cache_hit=result.get("cache_hit"),
    )

    return ChatResponse(
        thread_id=req.thread_id,
        answer=answer or "",
        resolved_ticker=result.get("resolved_ticker"),
        resolved_date_range=result.get("resolved_date_range"),
        tool_name=result.get("tool_name"),
        used_fast_path=result.get("used_fast_path"),
        cache_hit=result.get("cache_hit"),
    )


@app.get("/observability")
def observability():
    return get_observability_summary()


@app.post("/screener")
def screener(req: ScreenerRequest):
    result = screen_stocks(
        rsi_min=req.rsi_min,
        rsi_max=req.rsi_max,
        sma_period=req.sma_period,
        sma_condition=req.sma_condition,
        financial_metric=req.financial_metric,
        financial_op=req.financial_op,
        financial_value=req.financial_value,
    )
    return result.to_dict()
