from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    thread_id: str
    message: str


class ChatResponse(BaseModel):
    thread_id: str
    answer: str
    resolved_ticker: Optional[str] = None
    resolved_date_range: Optional[dict] = None
    tool_name: Optional[str] = None
    used_fast_path: Optional[bool] = None
    cache_hit: Optional[bool] = None


class UsageSummary(BaseModel):
    calls: int
    tokens_in: int
    tokens_out: int
    avg_latency_ms: float


class CreateSessionResponse(BaseModel):
    thread_id: str
    title: str


class SessionOut(BaseModel):
    thread_id: str
    title: str
    pinned: bool
    created_at: str
    updated_at: str


class UpdateSessionRequest(BaseModel):
    title: Optional[str] = None
    pinned: Optional[bool] = None


class MessageOut(BaseModel):
    role: str
    content: str


class ScreenerRequest(BaseModel):
    rsi_min: Optional[float] = None
    rsi_max: Optional[float] = None
    sma_period: Optional[int] = None
    sma_condition: Optional[str] = None  # "above" | "below"
    financial_metric: Optional[str] = None  # REVENUE | NET_PROFIT | EPS | DEBT
    financial_op: Optional[str] = None  # "gt" | "gte" | "lt" | "lte"
    financial_value: Optional[float] = None
