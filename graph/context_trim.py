"""Conversation history trimming for long threads (prompt_v1 requirement #4).

Only the general-chat path replays raw message history (financial Q&A turns
use deterministic ticker/date-range state instead, never raw history) --
so this is where an ever-growing thread would otherwise bloat every Groq
call. Once a thread passes _SUMMARY_TRIGGER messages, a running summary (1
Groq call, refreshed periodically) replaces the older turns; only the most
recent messages are still replayed verbatim.
"""
from __future__ import annotations

import logging

from db import get_summary, log_usage, save_summary
from llm import GroqClient

from ._utils import to_groq_messages

logger = logging.getLogger("graph.context_trim")

_SUMMARY_TRIGGER = 20  # start summarizing once history exceeds this many messages
_KEEP_RECENT = 8  # always replay this many most-recent messages verbatim
_RESUMMARIZE_EVERY = 10  # regenerate the summary every N additional older messages

_SUMMARY_SYSTEM_PROMPT = (
    "Tóm tắt ngắn gọn (dưới 150 từ) nội dung chính của đoạn hội thoại sau bằng tiếng Việt, giữ lại "
    "các thông tin quan trọng (mã cổ phiếu đã hỏi, chủ đề đã thảo luận) để dùng làm ngữ cảnh cho các "
    "câu hỏi tiếp theo."
)


def build_context_messages(thread_id: str, messages: list) -> list[dict]:
    """Message list to actually send to Groq: full (capped) history, or
    [summary] + recent messages once the thread is long enough."""
    if len(messages) <= _SUMMARY_TRIGGER:
        return to_groq_messages(messages)

    older = messages[:-_KEEP_RECENT]
    stored = get_summary(thread_id)
    already_summarized = stored["summarized_through_message_count"] if stored else 0
    need_refresh = stored is None or (len(older) - already_summarized) >= _RESUMMARIZE_EVERY

    if need_refresh:
        # Only summarize the NEW increment since last time, folded into the
        # prior summary text -- re-summarizing the whole "older" slice every
        # time would reprocess (and re-bill) the same messages repeatedly.
        newly_covered = older[already_summarized:]
        summary_text = _summarize(thread_id, newly_covered, stored)
        save_summary(thread_id, summary_text, len(older))
    else:
        summary_text = stored["summary"]

    recent = to_groq_messages(messages[-_KEEP_RECENT:])
    return [{"role": "system", "content": f"Tóm tắt hội thoại trước đó: {summary_text}"}, *recent]


def _summarize(thread_id: str, messages_to_summarize: list, stored: dict | None) -> str:
    prior_summary = stored["summary"] if stored else None
    convo_text = "\n".join(f"{m['role']}: {m['content']}" for m in to_groq_messages(messages_to_summarize))
    user_prompt = (
        convo_text
        if not prior_summary
        else f"Tóm tắt trước đó: {prior_summary}\n\nHội thoại tiếp theo:\n{convo_text}"
    )
    try:
        client = GroqClient(usage_logger=log_usage)
        result = client.chat(
            messages=[
                {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            node="summarize",
            thread_id=thread_id,
            temperature=0.2,
            max_tokens=400,
        )
        return result.content or (prior_summary or "")
    except Exception:
        logger.exception("context_trim: summarization call failed, reusing prior summary")
        return prior_summary or ""
