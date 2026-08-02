"""Stock screener (prompt_v3 requirement #3): filters a curated ticker
universe by technical (RSI/SMA) and/or financial (BCTC) conditions, computed
directly from the existing deterministic tools -- never through the LLM.

Universe is a small, curated list of large-cap tickers already exercised
elsewhere in this project's tests/live-testing (banks, steel, retail, tech,
consumer, real estate) rather than the full ~1700-ticker market: screening
the whole market would mean one vnstock history call per ticker per
request, which is both slow and a real risk of hammering vnstock's rate
limits. Expandable later if a precompute/cache strategy is added.

The spec's own example condition ("ROE > 15%") isn't usable -- ROE is a
`ratio()`-sourced metric dropped from the vocabulary after finding vnstock
returns stale/wrong data for it (see PROJECT_CONTEXT.md #24). Financial
filtering here uses the 4 metrics that ARE reliable: REVENUE, NET_PROFIT,
EPS, DEBT.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from .financial_tool import get_financial_metric_for_question
from .indicator_tool import get_indicator
from .ohlcv_tool import get_ohlcv_summary

_UNIVERSE = [
    "HPG", "VCB", "FPT", "VNM", "VIC", "MWG", "HSG", "VHM", "VRE", "MSN",
    "GAS", "CTG", "BID", "TCB", "MBB", "ACB", "VPB", "SSI", "PNJ", "GVR",
]

_LOOKBACK_DAYS = 90
# Live-tested: vnstock's upstream (trading.vietcap.com.vn) is periodically
# flaky -- individual calls sometimes hit a 30s read-timeout and only
# succeed on an internal retry. That's tolerable for 1 ticker but compounds
# badly across ~20 sequential calls (each flaky one adds ~30s), so a full
# screen that normally takes ~100s occasionally took 10+ minutes during
# testing. This delay does NOT fix that (confirmed: timeouts still occurred
# with it in place) -- it's a separate, cheap precaution against
# self-inflicted rate-limiting from bursty requests, kept because it's
# harmless. There is no code-level fix for upstream flakiness itself; see
# PROJECT_CONTEXT.md.
_INTER_TICKER_DELAY_SECONDS = 0.6
_OPS = {
    "gt": lambda v, x: v > x,
    "gte": lambda v, x: v >= x,
    "lt": lambda v, x: v < x,
    "lte": lambda v, x: v <= x,
}


@dataclass
class ScreenerResult:
    universe_size: int
    matched: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # tickers with missing data for a requested condition

    def to_dict(self) -> dict:
        return {"universe_size": self.universe_size, "matched": self.matched, "skipped": self.skipped}


def screen_stocks(
    rsi_min: Optional[float] = None,
    rsi_max: Optional[float] = None,
    sma_period: Optional[int] = None,
    sma_condition: Optional[str] = None,  # "above" | "below" -- latest close vs the SMA
    financial_metric: Optional[str] = None,
    financial_op: Optional[str] = None,  # "gt" | "gte" | "lt" | "lte"
    financial_value: Optional[float] = None,
) -> ScreenerResult:
    end = date.today()
    start = end - timedelta(days=_LOOKBACK_DAYS)

    matched: list[dict] = []
    skipped: list[dict] = []

    for i, ticker in enumerate(_UNIVERSE):
        if i > 0:
            time.sleep(_INTER_TICKER_DELAY_SECONDS)
        row: dict = {"ticker": ticker}
        ok = True

        if rsi_min is not None or rsi_max is not None:
            rsi = get_indicator(ticker, "RSI", 14, start, end)
            if not rsi.found or rsi.latest_value is None:
                skipped.append({"ticker": ticker, "reason": "Không đủ dữ liệu RSI"})
                continue
            row["rsi"] = rsi.latest_value
            if rsi_min is not None and rsi.latest_value < rsi_min:
                ok = False
            if rsi_max is not None and rsi.latest_value > rsi_max:
                ok = False

        if sma_period and sma_condition:
            sma = get_indicator(ticker, "SMA", sma_period, start, end)
            ohlcv = get_ohlcv_summary(ticker, start, end)
            if not sma.found or sma.latest_value is None or not ohlcv.found:
                skipped.append({"ticker": ticker, "reason": f"Không đủ dữ liệu SMA{sma_period}"})
                continue
            latest_close = ohlcv.stats["last_close"]
            row[f"sma{sma_period}"] = sma.latest_value
            row["latest_close"] = latest_close
            if sma_condition == "above" and not (latest_close > sma.latest_value):
                ok = False
            elif sma_condition == "below" and not (latest_close < sma.latest_value):
                ok = False

        if financial_metric and financial_op and financial_value is not None:
            fin = get_financial_metric_for_question(ticker, financial_metric, None)
            if not fin.found or not fin.periods:
                skipped.append({"ticker": ticker, "reason": f"Không có dữ liệu {financial_metric}"})
                continue
            latest = fin.periods[0]["value"]  # query_metrics sorts period_label DESC -- [0] is most recent
            row[financial_metric.lower()] = latest
            row[f"{financial_metric.lower()}_period"] = fin.periods[0]["period_label"]
            op_fn = _OPS.get(financial_op)
            if op_fn is None or not op_fn(latest, financial_value):
                ok = False

        if ok:
            matched.append(row)

    return ScreenerResult(universe_size=len(_UNIVERSE), matched=matched, skipped=skipped)
