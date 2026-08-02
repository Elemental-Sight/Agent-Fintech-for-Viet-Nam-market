"""Deterministic Vietnamese time-phrase -> concrete date range resolver.

No LLM involved anywhere in this module. If a phrase isn't recognized,
`resolve()` returns None so the caller can decide on a fallback (e.g. reuse
the date range from the previous conversation turn).
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from dateutil.relativedelta import relativedelta

from .text_utils import normalize_text

_DATE_PATTERNS = [
    ("%Y-%m-%d", re.compile(r"\d{4}-\d{1,2}-\d{1,2}")),
    ("%d/%m/%Y", re.compile(r"\d{1,2}/\d{1,2}/\d{4}")),
    ("%d-%m-%Y", re.compile(r"\d{1,2}-\d{1,2}-\d{4}")),
]

_RELATIVE_N_UNITS = re.compile(
    r"\b(\d+)?\s*(ngay|tuan|thang|quy|nam)\s*(gan nhat|gan day|qua|vua qua)\b"
)
_QUARTER_YEAR_RE = re.compile(r"\bquy\s*([1-4])\s*(?:nam\s*)?(\d{4})\b")
_MONTH_YEAR_RE = re.compile(r"\bthang\s*(1[0-2]|[1-9])\s*(?:nam\s*)?(\d{4})\b")
_YEAR_ONLY_RE = re.compile(r"\bnam\s*(\d{4})\b")
# "current price" style phrasing -- no explicit range given, the user just
# wants the latest available trading day, not a multi-month history table.
_CURRENT_PRICE_RE = re.compile(r"\b(hien tai|hom nay|bay gio|moi nhat|gan nhat|gan day)\b")
# Days to look back so the most recent trading day is still found across
# weekends/holidays (Tet can run ~9-10 non-trading days).
_CURRENT_PRICE_LOOKBACK_DAYS = 14


@dataclass
class DateRange:
    start: date
    end: date
    label: str
    is_current: bool = False

    def as_dict(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "label": self.label,
            "is_current": self.is_current,
        }


def _quarter_of(d: date) -> int:
    return (d.month - 1) // 3 + 1


def _quarter_bounds(year: int, quarter: int) -> tuple[date, date]:
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2
    start = date(year, start_month, 1)
    end = date(year, end_month, calendar.monthrange(year, end_month)[1])
    return start, end


def _parse_explicit_date(token: str) -> Optional[date]:
    for fmt, pattern in _DATE_PATTERNS:
        m = pattern.fullmatch(token.strip()) or pattern.search(token)
        if m:
            try:
                return datetime.strptime(m.group(0), fmt).date()
            except ValueError:
                continue
    return None


class TimeResolver:
    def resolve(self, phrase: Optional[str], reference_date: Optional[date] = None) -> Optional[DateRange]:
        if not phrase or not phrase.strip():
            return None
        today = reference_date or date.today()
        text = normalize_text(phrase)

        return (
            self._resolve_explicit_range(text, phrase)
            or self._resolve_relative_n_units(text, today)
            or self._resolve_specific_quarter_or_month_or_year(text)
            or self._resolve_anchored_period(text, today)
            or self._resolve_single_date(phrase)
            or self._resolve_current_price(text, today)
        )

    def _resolve_current_price(self, text: str, today: date) -> Optional[DateRange]:
        if not _CURRENT_PRICE_RE.search(text):
            return None
        return current_price_range(today)

    def _resolve_specific_quarter_or_month_or_year(self, text: str) -> Optional[DateRange]:
        m = _QUARTER_YEAR_RE.search(text)
        if m:
            q, year = int(m.group(1)), int(m.group(2))
            start, end = _quarter_bounds(year, q)
            return DateRange(start=start, end=end, label=f"quý {q}/{year}")

        m = _MONTH_YEAR_RE.search(text)
        if m:
            month, year = int(m.group(1)), int(m.group(2))
            start = date(year, month, 1)
            end = date(year, month, calendar.monthrange(year, month)[1])
            return DateRange(start=start, end=end, label=f"tháng {month}/{year}")

        m = _YEAR_ONLY_RE.search(text)
        if m:
            year = int(m.group(1))
            return DateRange(start=date(year, 1, 1), end=date(year, 12, 31), label=f"năm {year}")

        return None

    def _resolve_single_date(self, original: str) -> Optional[DateRange]:
        """A single standalone date (e.g. "ngày 15/03/2024"), as opposed to
        an explicit "từ X đến Y" range -- treated as a one-day window."""
        dates_found: list[date] = []
        for _fmt, pattern in _DATE_PATTERNS:
            for match in pattern.finditer(original):
                parsed = _parse_explicit_date(match.group(0))
                if parsed:
                    dates_found.append(parsed)
        if len(dates_found) == 1:
            d = dates_found[0]
            return DateRange(start=d, end=d, label=d.isoformat())
        return None

    def _resolve_explicit_range(self, text: str, original: str) -> Optional[DateRange]:
        if not re.search(r"\btu\b.*\bden\b", text):
            return None
        dates_found: list[date] = []
        for _fmt, pattern in _DATE_PATTERNS:
            for match in pattern.finditer(original):
                parsed = _parse_explicit_date(match.group(0))
                if parsed:
                    dates_found.append(parsed)
        if len(dates_found) < 2:
            return None
        start, end = sorted(dates_found[:2])
        return DateRange(start=start, end=end, label=f"{start.isoformat()} đến {end.isoformat()}")

    def _resolve_relative_n_units(self, text: str, today: date) -> Optional[DateRange]:
        m = _RELATIVE_N_UNITS.search(text)
        if not m:
            return None
        # "quý gần nhất" (no leading number) means "1 quý gần nhất" -- without
        # this default, it fell through all the way to _resolve_current_price,
        # whose "gan nhat" alternative wrongly claimed it as a current-PRICE
        # phrase (14-day window) instead of a proper 1-period range. Caught
        # live testing a BCTC comparison ("so sánh ROE ... quý gần nhất").
        n = int(m.group(1)) if m.group(1) else 1
        unit = m.group(2)
        end = today
        if unit == "ngay":
            start = end - timedelta(days=n - 1)
        elif unit == "tuan":
            start = end - timedelta(weeks=n) + timedelta(days=1)
        elif unit == "thang":
            start = end - relativedelta(months=n) + timedelta(days=1)
        elif unit == "quy":
            start = end - relativedelta(months=n * 3) + timedelta(days=1)
        elif unit == "nam":
            start = end - relativedelta(years=n) + timedelta(days=1)
        else:
            return None
        unit_label = {"ngay": "ngày", "tuan": "tuần", "thang": "tháng", "quy": "quý", "nam": "năm"}[unit]
        return DateRange(start=start, end=end, label=f"{n} {unit_label} gần nhất")

    def _resolve_anchored_period(self, text: str, today: date) -> Optional[DateRange]:
        if re.search(r"\bquy nay\b", text):
            q = _quarter_of(today)
            start, end = _quarter_bounds(today.year, q)
            return DateRange(start=start, end=min(end, today), label=f"quý {q}/{today.year}")
        if re.search(r"\bquy (truoc|vua roi)\b", text):
            q, year = _quarter_of(today) - 1, today.year
            if q == 0:
                q, year = 4, year - 1
            start, end = _quarter_bounds(year, q)
            return DateRange(start=start, end=end, label=f"quý {q}/{year}")
        if re.search(r"\bquy sau\b", text):
            q, year = _quarter_of(today) + 1, today.year
            if q == 5:
                q, year = 1, year + 1
            start, end = _quarter_bounds(year, q)
            return DateRange(start=start, end=end, label=f"quý {q}/{year}")

        if re.search(r"\bthang nay\b", text):
            start = today.replace(day=1)
            return DateRange(start=start, end=today, label=f"tháng {today.month}/{today.year}")
        if re.search(r"\bthang (truoc|vua roi)\b", text):
            first_this = today.replace(day=1)
            last_month_end = first_this - timedelta(days=1)
            start = last_month_end.replace(day=1)
            return DateRange(start=start, end=last_month_end, label=f"tháng {start.month}/{start.year}")
        if re.search(r"\bthang sau\b", text):
            next_start = today.replace(day=1) + relativedelta(months=1)
            next_end = next_start + relativedelta(months=1) - timedelta(days=1)
            return DateRange(start=next_start, end=next_end, label=f"tháng {next_start.month}/{next_start.year}")

        if re.search(r"\bnam nay\b", text):
            return DateRange(start=date(today.year, 1, 1), end=today, label=f"năm {today.year}")
        if re.search(r"\bnam (ngoai|truoc)\b", text):
            year = today.year - 1
            return DateRange(start=date(year, 1, 1), end=date(year, 12, 31), label=f"năm {year}")
        if re.search(r"\bnam sau\b", text):
            year = today.year + 1
            return DateRange(start=date(year, 1, 1), end=date(year, 12, 31), label=f"năm {year}")

        return None


def current_price_range(reference_date: Optional[date] = None) -> DateRange:
    """Public, phrase-independent constructor for the same "latest trading
    day" window `TimeResolver._resolve_current_price` builds -- lets callers
    default to the current price without needing a matching text phrase
    (e.g. a multi-ticker comparison with no explicit time_phrase at all)."""
    today = reference_date or date.today()
    start = today - timedelta(days=_CURRENT_PRICE_LOOKBACK_DAYS)
    return DateRange(start=start, end=today, label="hiện tại", is_current=True)
