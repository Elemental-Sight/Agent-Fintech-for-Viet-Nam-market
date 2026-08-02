"""Thin wrapper around the Groq chat completions API.

Every call is timed and its token usage is logged (both to the standard
logger and, optionally, to a caller-supplied usage_logger callback that
persists the numbers to Postgres) so token usage can be analyzed later.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from groq import Groq

from config import get_settings

logger = logging.getLogger("groq_client")

UsageLogger = Callable[[dict], None]

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_reasoning(content: Optional[str]) -> Optional[str]:
    """Reasoning models (e.g. qwen3) can inline their chain-of-thought as a
    <think>...</think> block in `content` -- callers should never see that,
    even though `reasoning_effort="none"` already asks the model not to."""
    if not content:
        return content
    return _THINK_BLOCK_RE.sub("", content).strip()


@dataclass
class GroqCallResult:
    content: Optional[str]
    tool_calls: list[dict] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    finish_reason: Optional[str] = None
    raw: Any = None


class GroqClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        usage_logger: Optional[UsageLogger] = None,
    ):
        settings = get_settings()
        self._client = Groq(api_key=api_key or settings.groq_api_key)
        self.model = model or settings.groq_model
        self._usage_logger = usage_logger

    def chat(
        self,
        messages: list[dict],
        *,
        node: str,
        thread_id: Optional[str] = None,
        tools: Optional[list[dict]] = None,
        tool_choice: Any = None,
        temperature: float = 0.1,
        reasoning_effort: Optional[str] = "none",
        max_tokens: Optional[int] = None,
    ) -> GroqCallResult:
        kwargs: dict[str, Any] = {}
        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        start = time.perf_counter()
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            **kwargs,
        )
        latency_ms = (time.perf_counter() - start) * 1000

        choice = response.choices[0]
        usage = response.usage
        tokens_in = getattr(usage, "prompt_tokens", 0) or 0
        tokens_out = getattr(usage, "completion_tokens", 0) or 0

        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append(
                    {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
                )

        logger.info(
            "groq_call node=%s model=%s tokens_in=%d tokens_out=%d latency_ms=%.1f finish_reason=%s",
            node,
            self.model,
            tokens_in,
            tokens_out,
            latency_ms,
            choice.finish_reason,
        )
        if choice.finish_reason == "length":
            logger.warning("groq_call node=%s was truncated by max_tokens -- answer may be cut off", node)
        if self._usage_logger:
            self._usage_logger(
                {
                    "thread_id": thread_id,
                    "node": node,
                    "model": self.model,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "latency_ms": latency_ms,
                }
            )

        return GroqCallResult(
            content=_strip_reasoning(choice.message.content),
            tool_calls=tool_calls,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            finish_reason=choice.finish_reason,
            raw=response,
        )
