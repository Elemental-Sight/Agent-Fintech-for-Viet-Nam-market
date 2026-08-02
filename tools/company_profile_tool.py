"""Company profile lookup by ticker (requirement #3).

`ticker` must already be a resolved, canonical ticker code (see
resolvers.entity_resolver) — this tool never guesses a symbol.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from ._vnstock_client import fetch_company_officers, fetch_company_overview

logger = logging.getLogger("tools.company_profile")


@dataclass
class CompanyProfileResult:
    ticker: str
    found: bool
    profile: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "found": self.found,
            "profile": self.profile,
            "error": self.error,
        }


# vnstock's overview() returns ~35 columns (internal codes, ICB codes, raw
# insight blobs...). Only these are actually useful in a chat answer -- the
# rest just bloats the prompt and makes the LLM's summary rambly.
_KEEP_FIELDS = [
    "symbol",
    "organ_name",
    "organ_short_name",
    "sector",
    "listing",
    "listing_date",
    "current_price",
    "market_cap",
    "highest_price1_year",
    "lowest_price1_year",
    "foreigner_percentage",
    "maximum_foreign_percentage",
    "rating",
    "rating_as_of",
    "target_price",
    "upside_to_target_percent",
    "dividend_per_share_tsr",
    "analyst",
]
_DESCRIPTION_FIELD = "company_profile"
_DESCRIPTION_MAX_CHARS = 400


def _clean(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _curate(row: dict[str, Any]) -> dict[str, Any]:
    curated = {k: _clean(row[k]) for k in _KEEP_FIELDS if k in row}
    description = _clean(row.get(_DESCRIPTION_FIELD))
    if isinstance(description, str) and description:
        curated["company_profile_summary"] = (
            description[:_DESCRIPTION_MAX_CHARS] + "..."
            if len(description) > _DESCRIPTION_MAX_CHARS
            else description
        )
    return curated


def _extract_leadership(officers_df: pd.DataFrame) -> dict[str, str]:
    """Chairman/CEO name, deterministically picked from vnstock's officer
    list by job-title text match -- never left to the LLM to guess/recall
    from its own training data, which could be stale or simply wrong."""
    leadership: dict[str, str] = {}
    if officers_df is None or officers_df.empty:
        return leadership
    for _, row in officers_df.iterrows():
        position = str(row.get("officer_position") or "")
        name = row.get("officer_name")
        if not name:
            continue
        if "chairman" not in leadership and "Chủ tịch" in position and "Phó Chủ tịch" not in position:
            leadership["chairman"] = str(name)
        if "ceo" not in leadership and "Tổng Giám đốc" in position and "Phó Tổng Giám đốc" not in position:
            leadership["ceo"] = str(name)
    return leadership


def get_company_profile(ticker: str) -> CompanyProfileResult:
    try:
        overview_df = fetch_company_overview(ticker)
    except Exception as exc:  # pragma: no cover - depends on live network/vnstock
        return CompanyProfileResult(ticker=ticker, found=False, error=str(exc))

    if overview_df is None or overview_df.empty:
        return CompanyProfileResult(
            ticker=ticker, found=False, error="Không tìm thấy hồ sơ doanh nghiệp cho mã này."
        )

    row = overview_df.iloc[0].to_dict()
    profile = _curate({str(k): v for k, v in row.items()})

    try:
        officers_df = fetch_company_officers(ticker)
        profile.update(_extract_leadership(officers_df))
    except Exception:  # pragma: no cover - depends on live network/vnstock
        # Best-effort: a leadership lookup failure shouldn't fail the whole
        # profile answer -- the rest of the profile is still useful.
        logger.exception("company_profile: officer lookup failed for %s", ticker)

    return CompanyProfileResult(ticker=ticker, found=True, profile=profile)
