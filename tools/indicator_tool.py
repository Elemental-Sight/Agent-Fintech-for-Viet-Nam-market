"""Technical indicators SMA / RSI with a configurable window_size
(requirement #5). Values always come from pandas_ta on real OHLCV data —
the LLM is never allowed to compute or restate these numbers itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pandas as pd
import pandas_ta as ta

from ._vnstock_client import fetch_history, prepare_ohlcv_frame

_SUPPORTED = {"SMA", "RSI"}
_MAX_SERIES_POINTS = 30


@dataclass
class IndicatorResult:
    ticker: str
    indicator: str
    window_size: int
    start: str
    end: str
    found: bool
    latest_value: Optional[float] = None
    latest_date: Optional[str] = None
    series: list[dict] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "indicator": self.indicator,
            "window_size": self.window_size,
            "start": self.start,
            "end": self.end,
            "found": self.found,
            "latest_value": self.latest_value,
            "latest_date": self.latest_date,
            "series": self.series,
            "error": self.error,
        }


def compute_indicator_from_close(close: pd.Series, indicator: str, window_size: int) -> pd.Series:
    """Pure computation on a close-price Series — isolated so tests can
    validate it against a hand-computed / plain-pandas formula."""
    indicator = indicator.upper()
    if indicator not in _SUPPORTED:
        raise ValueError(f"Chỉ báo '{indicator}' chưa được hỗ trợ (chỉ hỗ trợ {sorted(_SUPPORTED)}).")
    if indicator == "SMA":
        return ta.sma(close, length=window_size)
    return ta.rsi(close, length=window_size)


def get_indicator(ticker: str, indicator: str, window_size: int, start: date, end: date) -> IndicatorResult:
    indicator = indicator.upper()
    if indicator not in _SUPPORTED:
        return IndicatorResult(
            ticker=ticker,
            indicator=indicator,
            window_size=window_size,
            start=start.isoformat(),
            end=end.isoformat(),
            found=False,
            error=f"Chỉ báo '{indicator}' chưa được hỗ trợ.",
        )

    try:
        raw = fetch_history(ticker, start, end)
    except Exception as exc:  # pragma: no cover - depends on live network/vnstock
        return IndicatorResult(
            ticker=ticker,
            indicator=indicator,
            window_size=window_size,
            start=start.isoformat(),
            end=end.isoformat(),
            found=False,
            error=str(exc),
        )

    if raw is None or raw.empty:
        return IndicatorResult(
            ticker=ticker,
            indicator=indicator,
            window_size=window_size,
            start=start.isoformat(),
            end=end.isoformat(),
            found=False,
            error="Không có dữ liệu giá trong khoảng thời gian này.",
        )

    df = prepare_ohlcv_frame(raw)
    close = df["close"].astype(float)

    if len(close) < window_size:
        return IndicatorResult(
            ticker=ticker,
            indicator=indicator,
            window_size=window_size,
            start=start.isoformat(),
            end=end.isoformat(),
            found=False,
            error=f"Không đủ dữ liệu ({len(close)} phiên) để tính {indicator} với window_size={window_size}.",
        )

    values = compute_indicator_from_close(close, indicator, window_size).dropna()
    if values.empty:
        return IndicatorResult(
            ticker=ticker,
            indicator=indicator,
            window_size=window_size,
            start=start.isoformat(),
            end=end.isoformat(),
            found=False,
            error="Không tính được chỉ báo với dữ liệu hiện có.",
        )

    tail = values.tail(_MAX_SERIES_POINTS)
    series = [{"date": idx.date().isoformat(), "value": round(float(v), 2)} for idx, v in tail.items()]

    return IndicatorResult(
        ticker=ticker,
        indicator=indicator,
        window_size=window_size,
        start=start.isoformat(),
        end=end.isoformat(),
        found=True,
        latest_value=round(float(values.iloc[-1]), 2),
        latest_date=values.index[-1].date().isoformat(),
        series=series,
    )
