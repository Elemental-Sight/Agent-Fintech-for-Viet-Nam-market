"""Thin, shared wrapper around vnstock so tool modules don't each re-implement
symbol lookup. Isolated in one place so the vnstock API surface only needs
to be adapted here if the library's interface changes.

Imports are at module load time (not lazily inside each function) on
purpose: FastAPI runs sync route handlers in a thread pool, so concurrent
requests can trigger concurrent first-time imports of the same vnstock
submodule -- which hit a real `_ModuleLock` deadlock in testing. Importing
once, sequentially, at process startup avoids that race entirely.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from vnstock.api.company import Company
from vnstock.api.financial import Finance
from vnstock.api.listing import Listing
from vnstock.api.quote import Quote


def fetch_history(ticker: str, start: date, end: date) -> pd.DataFrame:
    quote = Quote(symbol=ticker, source="vci")
    return quote.history(start=start.isoformat(), end=end.isoformat(), interval="1D")


def fetch_company_overview(ticker: str) -> pd.DataFrame:
    company = Company(symbol=ticker, source="vci")
    return company.overview()


def fetch_company_officers(ticker: str) -> pd.DataFrame:
    company = Company(symbol=ticker, source="vci")
    return company.officers()


def fetch_financial_statement(ticker: str, statement: str, period_type: str) -> pd.DataFrame:
    """`statement` in {"income_statement", "balance_sheet", "ratio"}, `period_type`
    in {"quarter", "year"}. vnstock's community tier caps this at ~4 periods
    per call (see PROJECT_CONTEXT.md) -- callers must not assume more."""
    finance = Finance(symbol=ticker, source="vci")
    return getattr(finance, statement)(period=period_type)


def prepare_ohlcv_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names to lowercase and set a sorted datetime index."""
    df = df.rename(columns={c: str(c).lower() for c in df.columns})
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"])
        df = df.set_index("time")
    return df.sort_index()


def fetch_news(ticker: str) -> pd.DataFrame:
    company = Company(symbol=ticker, source="vci")
    return company.news()


def fetch_industry_symbol_map() -> pd.DataFrame:
    """symbol/organ_name/icb_level/icb_code/icb_name for every listed ticker,
    across all 4 ICB hierarchy levels -- used to resolve an industry mention
    to a concrete set of tickers (see tools/news_tool.py)."""
    return Listing(source="vci").symbols_by_industries()
