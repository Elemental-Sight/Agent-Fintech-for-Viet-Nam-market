"""Validates the pure/deterministic pieces of the BCTC tool: quarter/year
inference from an already-resolved date_range, period-label enumeration, and
DataFrame parsing -- none of this should ever go through the LLM."""
import numpy as np
import pandas as pd

from tools.financial_tool import _infer_period_type, _parse_finance_df, _periods_in_range


def test_infer_period_type_defaults_to_quarter():
    assert _infer_period_type(None) == "quarter"


def test_infer_period_type_year_label():
    assert _infer_period_type({"label": "năm 2023"}) == "year"
    assert _infer_period_type({"label": "4 năm gần nhất"}) == "year"


def test_infer_period_type_quarter_label_wins_over_year_word():
    assert _infer_period_type({"label": "quý 2/2024"}) == "quarter"


def test_infer_period_type_month_label_defaults_to_quarter():
    assert _infer_period_type({"label": "tháng 3/2024"}) == "quarter"


def test_periods_in_range_none_when_no_date_range():
    assert _periods_in_range(None, "quarter") is None


def test_periods_in_range_single_year():
    date_range = {"start": "2023-01-01", "end": "2023-12-31"}
    assert _periods_in_range(date_range, "year") == ["2023"]


def test_periods_in_range_multiple_years():
    date_range = {"start": "2022-06-01", "end": "2023-03-01"}
    assert _periods_in_range(date_range, "year") == ["2022", "2023"]


def test_periods_in_range_single_quarter():
    date_range = {"start": "2024-04-01", "end": "2024-06-30"}
    assert _periods_in_range(date_range, "quarter") == ["2024-Q2"]


def test_periods_in_range_multiple_quarters():
    date_range = {"start": "2024-04-01", "end": "2024-09-30"}
    assert _periods_in_range(date_range, "quarter") == ["2024-Q2", "2024-Q3"]


def test_periods_in_range_quarters_across_year_boundary():
    date_range = {"start": "2023-10-01", "end": "2024-03-31"}
    assert _periods_in_range(date_range, "quarter") == ["2023-Q4", "2024-Q1"]


def _vnstock_shaped_df(rows: dict[str, list]) -> pd.DataFrame:
    """rows: {item_en: [values per period col]} -- mimics the wide,
    row-per-item shape vnstock's Finance.income_statement()/ratio()/
    balance_sheet() actually returns (verified live, see PROJECT_CONTEXT.md)."""
    periods = ["2025-Q4", "2025-Q3"]
    data = {"item": list(rows.keys()), "item_en": list(rows.keys()), "item_id": ["x"] * len(rows)}
    for i, period in enumerate(periods):
        data[period] = [values[i] for values in rows.values()]
    return pd.DataFrame(data)


def test_parse_finance_df_single_item():
    df = _vnstock_shaped_df({"Net sales": [100.0, 90.0], "Cost of sales": [-60.0, -55.0]})
    result = _parse_finance_df(df, ["Net sales"])
    assert {r["period_label"]: r["metric_value"] for r in result} == {"2025-Q4": 100.0, "2025-Q3": 90.0}


def test_parse_finance_df_sums_multiple_items():
    df = _vnstock_shaped_df({"Short-term borrowings": [10.0, 8.0], "Long-term borrowings": [5.0, 4.0]})
    result = _parse_finance_df(df, ["Short-term borrowings", "Long-term borrowings"])
    assert {r["period_label"]: r["metric_value"] for r in result} == {"2025-Q4": 15.0, "2025-Q3": 12.0}


def test_parse_finance_df_all_nan_period_dropped_not_zeroed():
    df = _vnstock_shaped_df({"Net sales": [np.nan, np.nan]})
    result = _parse_finance_df(df, ["Net sales"])
    assert result == []


def test_parse_finance_df_no_matching_item_returns_empty():
    df = _vnstock_shaped_df({"Net sales": [100.0, 90.0]})
    assert _parse_finance_df(df, ["ROE (%)"]) == []
