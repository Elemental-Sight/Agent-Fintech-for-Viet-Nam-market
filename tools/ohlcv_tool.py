"""Historical OHLCV lookup + summary (requirement #4).

Returns min/max/mean/%change stats plus a downsampled series — the full
raw daily series is never handed to the LLM, keeping tool output small and
bounded in size regardless of the requested date range.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

import pandas as pd

from ._vnstock_client import fetch_history, prepare_ohlcv_frame

_MAX_POINTS_BEFORE_DOWNSAMPLE = 60
_MAX_SERIES_POINTS = 40  # hard cap so very long ranges can't blow up the LLM's answer token budget


def _pick_resample_rule(span_days: int) -> str:
    if span_days <= 190:
        return "W"
    if span_days <= 3 * 365:
        return "M"
    if span_days <= 10 * 365:
        return "Q"
    return "Y"


@dataclass
class OhlcvResult:
    ticker: str
    start: str
    end: str
    found: bool
    stats: dict[str, Any] = field(default_factory=dict)
    series: list[dict] = field(default_factory=list)
    resample_rule: Optional[str] = None
    points_total: int = 0
    points_returned: int = 0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "start": self.start,
            "end": self.end,
            "found": self.found,
            "stats": self.stats,
            "series": self.series,
            "resample_rule": self.resample_rule,
            "points_total": self.points_total,
            "points_returned": self.points_returned,
            "error": self.error,
        }


def get_ohlcv_summary(ticker: str, start: date, end: date, latest_only: bool = False) -> OhlcvResult:
    try:
        raw = fetch_history(ticker, start, end)
    except Exception as exc:  # pragma: no cover - depends on live network/vnstock
        return OhlcvResult(ticker=ticker, start=start.isoformat(), end=end.isoformat(), found=False, error=str(exc))

    if raw is None or raw.empty:
        return OhlcvResult(
            ticker=ticker,
            start=start.isoformat(),
            end=end.isoformat(),
            found=False,
            error="Không có dữ liệu giá trong khoảng thời gian này.",
        )

    df = prepare_ohlcv_frame(raw)
    close = df["close"].astype(float)

    stats = {
        "min": round(float(close.min()), 2),
        "max": round(float(close.max()), 2),
        "mean": round(float(close.mean()), 2),
        "first_close": round(float(close.iloc[0]), 2),
        "last_close": round(float(close.iloc[-1]), 2),
        "pct_change": round(float((close.iloc[-1] / close.iloc[0] - 1) * 100), 2) if close.iloc[0] else None,
    }

    points_total = len(df)
    resample_rule = None
    display_df = df
    if points_total > _MAX_POINTS_BEFORE_DOWNSAMPLE:
        span_days = (end - start).days
        resample_rule = _pick_resample_rule(span_days)
        display_df = (
            df.resample(resample_rule)
            .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
            .dropna(subset=["close"])
        )
        # resample() labels each bucket by the calendar period end (e.g. the
        # next Sunday for "W"), which can be a date with no real trading --
        # relabel with the actual last trading date observed in that bucket.
        actual_last_date = df.index.to_series().resample(resample_rule).max()
        display_df.index = actual_last_date.loc[display_df.index]

        # Even at the coarsest rule ("Y"), an extremely long range could still
        # exceed the cap -- evenly sample it down as a final safety net.
        if len(display_df) > _MAX_SERIES_POINTS:
            step = -(-len(display_df) // _MAX_SERIES_POINTS)  # ceil division
            display_df = display_df.iloc[::step]

    series = [
        {
            "date": idx.date().isoformat(),
            "open": round(float(row["open"]), 2),
            "high": round(float(row["high"]), 2),
            "low": round(float(row["low"]), 2),
            "close": round(float(row["close"]), 2),
            "volume": int(row["volume"]) if pd.notna(row["volume"]) else None,
        }
        for idx, row in display_df.iterrows()
    ]

    result_start, result_end = start, end
    if latest_only:
        # "current price" style question -- the caller only wants the most
        # recent trading day, not a range summary/table. `start`/`end` here
        # are just an internal lookback buffer wide enough to survive
        # weekends/holidays -- citing that padded window back to the user
        # ("giá hiện tại ... trong khoảng thời gian từ ... đến ...") reads as
        # a contradiction, so report the single actual trading date instead.
        series = series[-1:]
        stats = {"last_close": stats["last_close"]}
        if series:
            latest_date = date.fromisoformat(series[0]["date"])
            result_start = result_end = latest_date

    return OhlcvResult(
        ticker=ticker,
        start=result_start.isoformat(),
        end=result_end.isoformat(),
        found=True,
        stats=stats,
        series=series,
        resample_rule=resample_rule,
        points_total=points_total,
        points_returned=len(series),
    )
