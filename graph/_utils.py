from __future__ import annotations

_ROLE_MAP = {"human": "user", "ai": "assistant"}
_MAX_HISTORY_MESSAGES = 20

DISCLAIMER = "Lưu ý: đây không phải lời khuyên đầu tư cá nhân hoá."


def _role_and_content(msg) -> tuple[str | None, str | None]:
    if isinstance(msg, dict):
        return msg.get("role"), msg.get("content")
    return getattr(msg, "type", None), getattr(msg, "content", None)


def last_human_text(messages: list) -> str:
    for msg in reversed(messages):
        role, content = _role_and_content(msg)
        if role in ("human", "user"):
            return content or ""
    return ""


def to_groq_messages(messages: list) -> list[dict]:
    """Convert LangGraph state messages to plain Groq-API role/content dicts,
    capped to the most recent turns (no summarization yet -- see prompt_v1
    for that). Needed for general-chat continuity since that path has no
    deterministic state (like last_ticker) to carry context across turns."""
    out = []
    for msg in messages[-_MAX_HISTORY_MESSAGES:]:
        role, content = _role_and_content(msg)
        role = _ROLE_MAP.get(role, role)
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return out
