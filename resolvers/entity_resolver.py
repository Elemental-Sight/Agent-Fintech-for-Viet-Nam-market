"""Deterministic company-name/alias -> ticker resolver.

The LLM is never allowed to invent a ticker code. This module matches user
text against a mapping file (ticker, full name, short name, aliases) using
exact ticker matching first, then fuzzy string matching. If several tickers
are equally plausible, it reports the ambiguity instead of guessing.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz, process

from .text_utils import normalize_text, strip_legal_prefix

_DEFAULT_MAPPING_PATH = Path(__file__).resolve().parent.parent / "data" / "tickers.json"

_WORD_RE = re.compile(r"[A-Za-z]+")

# Same boilerplate as text_utils.strip_legal_prefix, but ascii/diacritic-free
# so it still matches after normalize_text() -- users often type Vietnamese
# without accents (e.g. "cong ty co phan" instead of "công ty cổ phần"), and
# re.IGNORECASE alone doesn't make "công" match "cong".
_ASCII_LEGAL_PREFIXES = [
    r"^cong ty co phan\s+",
    r"^cong ty cp\s+",
    r"^ctcp\s+",
    r"^tong cong ty co phan\s+",
    r"^tong cong ty\s+",
    r"^tap doan\s+",
    r"^ngan hang tmcp\s+",
    r"^ngan hang thuong mai co phan\s+",
    r"^ngan hang\s+",
    r"^cong ty\s+",  # bare "công ty X", common in casual queries even though official names always add "cổ phần"
]


def _strip_normalized_prefix(normalized_text: str) -> str:
    stripped = normalized_text
    for pattern in _ASCII_LEGAL_PREFIXES:
        stripped = re.sub(pattern, "", stripped)
    return stripped.strip()


@dataclass
class TickerRecord:
    ticker: str
    full_name: str
    short_name: str
    exchange: str = ""
    aliases: list[str] = field(default_factory=list)

    def search_terms(self) -> list[str]:
        # Deliberately excludes `self.ticker`: bare 3-4 letter codes are
        # exact-matched separately (see resolve()). Fuzzy-matching short
        # strings against thousands of other short codes causes false
        # positives (rapidfuzz.WRatio falls back to partial_ratio on
        # length-mismatched strings, which scores unrelated codes highly).
        terms = [strip_legal_prefix(self.full_name), strip_legal_prefix(self.short_name), *self.aliases]
        return [t for t in terms if t]


@dataclass
class ResolvedEntity:
    ticker: Optional[str]
    matched_term: Optional[str] = None
    score: float = 0.0
    candidates: list[str] = field(default_factory=list)

    @property
    def is_ambiguous(self) -> bool:
        return self.ticker is None and len(self.candidates) > 1

    @property
    def is_found(self) -> bool:
        return self.ticker is not None


class EntityResolver:
    MATCH_SCORE_THRESHOLD = 88.0
    AMBIGUOUS_MARGIN = 5.0

    def __init__(self, mapping_path: str | Path | None = None):
        self.mapping_path = Path(mapping_path) if mapping_path else _DEFAULT_MAPPING_PATH
        self.records: list[TickerRecord] = self._load(self.mapping_path)
        self._ticker_index = {r.ticker.upper(): r for r in self.records}

        self._term_index: list[tuple[str, TickerRecord]] = []
        for record in self.records:
            for term in record.search_terms():
                normalized = _strip_normalized_prefix(normalize_text(term))
                if normalized:
                    self._term_index.append((normalized, record))
        self._choices = [term for term, _ in self._term_index]

    @staticmethod
    def _load(path: Path) -> list[TickerRecord]:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return [
            TickerRecord(
                ticker=item["ticker"].upper(),
                full_name=item.get("full_name", ""),
                short_name=item.get("short_name", ""),
                exchange=item.get("exchange", ""),
                aliases=list(item.get("aliases", [])),
            )
            for item in raw
        ]

    def all_tickers(self) -> list[str]:
        return sorted(self._ticker_index)

    def get(self, ticker: str) -> Optional[TickerRecord]:
        return self._ticker_index.get(ticker.upper())

    def resolve(self, mention: str) -> ResolvedEntity:
        if not mention or not mention.strip():
            return ResolvedEntity(ticker=None)

        upper = mention.strip().upper()
        if upper in self._ticker_index:
            return ResolvedEntity(ticker=upper, matched_term=upper, score=100.0)

        # A whole mention like "VCB hiện tại" won't hit the exact match above,
        # but if one of its words was written in ALL CAPS and is a real ticker
        # code, that's a strong deterministic signal -- people/LLMs capitalize
        # tickers, not surrounding filler words.
        capitalized_tickers = {
            w for w in _WORD_RE.findall(mention) if w.isupper() and len(w) >= 3 and w in self._ticker_index
        }
        if len(capitalized_tickers) == 1:
            (only,) = capitalized_tickers
            return ResolvedEntity(ticker=only, matched_term=only, score=100.0)

        # Strip the same legal-entity boilerplate from the query as from the
        # pool terms (symmetric) -- otherwise a query like "công ty cổ phần
        # sữa việt nam" carries extra tokens the stored term doesn't have.
        # Applied both before AND after normalize_text() since the user may
        # or may not have typed the accents (strip_legal_prefix needs them,
        # _strip_normalized_prefix works on the accent-stripped form).
        normalized_mention = _strip_normalized_prefix(normalize_text(strip_legal_prefix(mention)))
        if not normalized_mention or not self._choices:
            return ResolvedEntity(ticker=None)

        matches = process.extract(
            normalized_mention, self._choices, scorer=fuzz.WRatio, limit=5
        )
        if not matches:
            return ResolvedEntity(ticker=None)

        best_term, best_score, best_idx = matches[0]
        if best_score < self.MATCH_SCORE_THRESHOLD:
            return ResolvedEntity(ticker=None, score=best_score)

        top_tickers: dict[str, float] = {}
        for term, score, idx in matches:
            if score >= best_score - self.AMBIGUOUS_MARGIN:
                record = self._term_index[idx][1]
                top_tickers[record.ticker] = max(top_tickers.get(record.ticker, 0.0), score)

        if len(top_tickers) > 1:
            ranked = sorted(top_tickers, key=lambda t: -top_tickers[t])
            return ResolvedEntity(ticker=None, matched_term=best_term, score=best_score, candidates=ranked)

        best_record = self._term_index[best_idx][1]
        return ResolvedEntity(ticker=best_record.ticker, matched_term=best_term, score=best_score)
