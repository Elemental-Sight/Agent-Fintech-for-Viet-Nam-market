"""Validates the SMA/RSI tool against hand-written pandas formulas
(requirement #10) -- not just against pandas_ta calling itself."""
import numpy as np
import pandas as pd
import pytest

from tools.indicator_tool import compute_indicator_from_close


def _synthetic_close(n: int = 60, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    steps = rng.normal(loc=0.0, scale=1.0, size=n)
    prices = 100 + np.cumsum(steps)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.Series(prices, index=dates, name="close")


def _manual_sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window=window).mean()


def _manual_rsi(close: pd.Series, window: int) -> pd.Series:
    """Same construction pandas_ta uses internally (Wilder's RMA via
    ewm(alpha=1/window, adjust=False)), written independently here."""
    delta = close.diff()
    positive = delta.clip(lower=0)
    negative = delta.clip(upper=0)
    positive_avg = positive.ewm(alpha=1 / window, adjust=False).mean()
    negative_avg = negative.ewm(alpha=1 / window, adjust=False).mean()
    return 100 * positive_avg / (positive_avg + negative_avg.abs())


def test_sma_matches_manual_rolling_mean():
    close = _synthetic_close()
    window = 20
    tool_values = compute_indicator_from_close(close, "SMA", window).dropna()
    manual_values = _manual_sma(close, window).dropna()
    pd.testing.assert_series_equal(tool_values, manual_values, check_names=False, rtol=1e-6)


def test_rsi_matches_manual_wilder_rma_formula():
    close = _synthetic_close()
    window = 14
    tool_values = compute_indicator_from_close(close, "RSI", window).dropna()
    manual_values = _manual_rsi(close, window).dropna()
    pd.testing.assert_series_equal(tool_values, manual_values, check_names=False, rtol=1e-6)


def test_rsi_stays_within_0_100():
    close = _synthetic_close(n=120, seed=7)
    values = compute_indicator_from_close(close, "RSI", 14).dropna()
    assert (values >= 0).all()
    assert (values <= 100).all()


def test_unsupported_indicator_raises_value_error():
    close = _synthetic_close()
    with pytest.raises(ValueError):
        compute_indicator_from_close(close, "MACD", 12)
