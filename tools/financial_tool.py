"""Financial statement (BCTC) lookup, backed by a real SQL table -- not RAG
(prompt_v2 requirement #1: "truy vấn chính xác bằng SQL, không qua RAG").

Curated vocabulary only (9 metrics) -- vnstock's raw balance_sheet()/
income_statement()/ratio() rows number in the dozens with many near-duplicate
line items across accounting-standard vintages; dumping all of it would both
bloat the DB and make "which row is THE revenue number" ambiguous. Same
curate-don't-dump principle as company_profile_tool.py's _KEEP_FIELDS.

Confirmed live against vnstock (see PROJECT_CONTEXT.md): community tier caps
every statement call at ~4 periods. `Finance(..., source="vci").ratio()` is
UNRELIABLE regardless of period type -- it consistently returns stale/wrong
2018 data instead of the requested recent periods (confirmed reproducible,
not a parsing bug on our side: the raw "Năm" data row itself says 2018).
ROE/ROA/GROSS_MARGIN/PE/PB were dropped from the supported vocabulary
entirely rather than ship unverified numbers -- only income_statement() and
balance_sheet() (REVENUE/NET_PROFIT/EPS/DEBT) were confirmed to return
correct, current data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

import pandas as pd

from db import financial_store

from ._vnstock_client import fetch_financial_statement

_METADATA_COLS = {"item", "item_en", "item_id"}

# Public: single source of truth for the router's financial_metric enum too
# (see graph/router_node.py) -- avoids the vocabulary drifting out of sync
# between where it's validated and where it's actually used.
#
# ROE/ROA/GROSS_MARGIN/PE/PB (all ratio()-sourced) are deliberately NOT here
# -- see module docstring. `year_ok` is kept for when/if a reliable ratio()
# source is found; every metric currently listed happens to be True.
_METRIC_SPEC: dict[str, dict[str, Any]] = {
    "REVENUE": {"statement": "income_statement", "items": ["Net sales"], "unit": "VND", "year_ok": True},
    "NET_PROFIT": {"statement": "income_statement", "items": ["Net profit/(loss) after tax"], "unit": "VND", "year_ok": True},
    "EPS": {"statement": "income_statement", "items": ["EPS basic (VND)"], "unit": "VND", "year_ok": True},
    "DEBT": {"statement": "balance_sheet", "items": ["Short-term borrowings", "Long-term borrowings"], "unit": "VND", "year_ok": True},
}

SUPPORTED_FINANCIAL_METRICS = tuple(_METRIC_SPEC.keys())


@dataclass
class FinancialMetricResult:
    ticker: str
    metric_key: str
    period_type: str
    found: bool
    periods: list[dict] = field(default_factory=list)
    unit: str = ""
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "metric_key": self.metric_key,
            "period_type": self.period_type,
            "found": self.found,
            "periods": self.periods,
            "unit": self.unit,
            "error": self.error,
        }


def _infer_period_type(date_range: Optional[dict]) -> str:
    """Quarter is the default (matches the spec's primary example, "4 quý
    gần nhất") -- only switch to year when the resolved label is explicitly
    year-level and not quarter-level (TimeResolver always includes the
    literal word "năm" in purely-yearly labels, see resolvers/time_resolver.py)."""
    if not date_range:
        return "quarter"
    label = (date_range.get("label") or "").lower()
    if "năm" in label and "quý" not in label:
        return "year"
    return "quarter"


def _periods_in_range(date_range: Optional[dict], period_type: str) -> Optional[list[str]]:
    """None means "no explicit range -- return whatever's cached/available"
    (which, given vnstock's own ~4-period cap, is already "the recent periods")."""
    if not date_range:
        return None
    start = date.fromisoformat(date_range["start"])
    end = date.fromisoformat(date_range["end"])
    if period_type == "year":
        return [str(y) for y in range(start.year, end.year + 1)]

    def _quarter_index(d: date) -> int:
        return d.year * 4 + (d.month - 1) // 3

    labels = []
    for qi in range(_quarter_index(start), _quarter_index(end) + 1):
        year, quarter = divmod(qi, 4)
        labels.append(f"{year}-Q{quarter + 1}")
    return labels


def _parse_finance_df(df: pd.DataFrame, items: list[str]) -> list[dict]:
    """Sums the given item_en rows per period column (only DEBT has >1 item,
    for the rest this is a 1-row sum, i.e. a passthrough). `min_count=1` so a
    period with genuinely no data for these rows yields NaN (dropped), not a
    misleading 0."""
    period_cols = [c for c in df.columns if c not in _METADATA_COLS]
    subset = df.loc[df["item_en"].isin(items), period_cols]
    if subset.empty:
        return []
    summed = subset.apply(pd.to_numeric, errors="coerce").sum(axis=0, skipna=True, min_count=1)
    return [
        {"period_label": str(period_label), "metric_value": float(value)}
        for period_label, value in summed.items()
        if pd.notna(value)
    ]


def get_financial_metric(
    ticker: str,
    metric_key: str,
    period_type: str,
    period_labels: Optional[list[str]] = None,
) -> FinancialMetricResult:
    spec = _METRIC_SPEC.get(metric_key)
    if spec is None:
        return FinancialMetricResult(
            ticker=ticker, metric_key=metric_key, period_type=period_type, found=False,
            error=f"Chỉ số '{metric_key}' chưa được hỗ trợ.",
        )
    if period_type == "year" and not spec["year_ok"]:
        return FinancialMetricResult(
            ticker=ticker, metric_key=metric_key, period_type=period_type, found=False,
            error=f"Chỉ số {metric_key} hiện chỉ hỗ trợ theo quý, chưa hỗ trợ theo năm (giới hạn dữ liệu nguồn).",
        )

    if not financial_store.is_fresh(ticker, period_type, metric_key):
        try:
            df = fetch_financial_statement(ticker, spec["statement"], period_type)
        except Exception as exc:  # pragma: no cover - depends on live network/vnstock
            return FinancialMetricResult(
                ticker=ticker, metric_key=metric_key, period_type=period_type, found=False, error=str(exc),
            )
        if df is None or df.empty:
            return FinancialMetricResult(
                ticker=ticker, metric_key=metric_key, period_type=period_type, found=False,
                error="Không có dữ liệu BCTC cho mã này.",
            )
        parsed = _parse_finance_df(df, spec["items"])
        financial_store.upsert_metrics(
            ticker, period_type,
            [{"period_label": r["period_label"], "metric_key": metric_key, "metric_value": r["metric_value"]} for r in parsed],
        )

    cached = financial_store.query_metrics(ticker, period_type, metric_key, period_labels)
    if not cached:
        return FinancialMetricResult(
            ticker=ticker, metric_key=metric_key, period_type=period_type, found=False,
            error="Không có dữ liệu cho mã/kỳ này (có thể ngoài giới hạn ~4 kỳ gần nhất mà vnstock cung cấp).",
        )

    periods = [{"period_label": r["period_label"], "value": r["metric_value"]} for r in cached]
    return FinancialMetricResult(
        ticker=ticker, metric_key=metric_key, period_type=period_type, found=True, periods=periods, unit=spec["unit"],
    )


def get_financial_metric_for_question(ticker: str, metric_key: str, date_range: Optional[dict]) -> FinancialMetricResult:
    """Convenience wrapper for graph/tool_node.py -- derives period_type and
    the target period labels from an already-resolved date_range (or None,
    meaning no explicit time phrase this turn) so callers never need to know
    about quarter/year inference or vnstock's ratio()-year bug directly."""
    period_type = _infer_period_type(date_range)
    period_labels = _periods_in_range(date_range, period_type)
    return get_financial_metric(ticker, metric_key, period_type, period_labels)
