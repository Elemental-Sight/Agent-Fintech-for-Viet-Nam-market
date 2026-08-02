"""Validates screen_stocks()'s filtering logic in isolation -- the
underlying data (RSI/SMA/OHLCV/BCTC) comes from tools already covered by
their own tests/live-testing, so here we mock those calls and only verify
the threshold/comparison logic and the skip-on-missing-data behavior."""
from unittest.mock import patch

from tools.indicator_tool import IndicatorResult
from tools.ohlcv_tool import OhlcvResult
from tools.financial_tool import FinancialMetricResult
from tools.screener_tool import _UNIVERSE, screen_stocks


def _rsi_result(ticker: str, value: float) -> IndicatorResult:
    return IndicatorResult(ticker=ticker, indicator="RSI", window_size=14, start="", end="", found=True, latest_value=value)


def test_rsi_max_filters_correctly():
    with patch("tools.screener_tool.get_indicator") as mock_indicator:
        mock_indicator.side_effect = lambda ticker, *a, **kw: _rsi_result(ticker, 25.0 if ticker == _UNIVERSE[0] else 60.0)
        result = screen_stocks(rsi_max=30.0)
    tickers = [row["ticker"] for row in result.matched]
    assert tickers == [_UNIVERSE[0]]


def test_rsi_missing_data_is_skipped_not_matched():
    with patch("tools.screener_tool.get_indicator") as mock_indicator:
        mock_indicator.return_value = IndicatorResult(
            ticker="X", indicator="RSI", window_size=14, start="", end="", found=False, error="not enough data"
        )
        result = screen_stocks(rsi_max=30.0)
    assert result.matched == []
    assert len(result.skipped) == len(_UNIVERSE)
    assert all("reason" in s for s in result.skipped)


def test_sma_above_condition():
    with patch("tools.screener_tool.get_indicator") as mock_indicator, \
         patch("tools.screener_tool.get_ohlcv_summary") as mock_ohlcv:
        mock_indicator.return_value = IndicatorResult(
            ticker="X", indicator="SMA", window_size=20, start="", end="", found=True, latest_value=100.0
        )
        mock_ohlcv.side_effect = lambda ticker, *a, **kw: OhlcvResult(
            ticker=ticker, start="", end="", found=True,
            stats={"last_close": 110.0 if ticker == _UNIVERSE[0] else 90.0},
        )
        result = screen_stocks(sma_period=20, sma_condition="above")
    tickers = [row["ticker"] for row in result.matched]
    assert tickers == [_UNIVERSE[0]]


def test_financial_condition_gt():
    with patch("tools.screener_tool.get_financial_metric_for_question") as mock_fin:
        def fake_fin(ticker, metric, date_range):
            value = 2000.0 if ticker == _UNIVERSE[0] else 500.0
            return FinancialMetricResult(
                ticker=ticker, metric_key=metric, period_type="quarter", found=True,
                periods=[{"period_label": "2026-Q2", "value": value}],
            )
        mock_fin.side_effect = fake_fin
        result = screen_stocks(financial_metric="REVENUE", financial_op="gt", financial_value=1000.0)
    tickers = [row["ticker"] for row in result.matched]
    assert tickers == [_UNIVERSE[0]]


def test_no_conditions_matches_entire_universe():
    result = screen_stocks()
    assert len(result.matched) == len(_UNIVERSE)
    assert result.universe_size == len(_UNIVERSE)
