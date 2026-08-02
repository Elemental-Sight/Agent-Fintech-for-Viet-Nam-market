"""Small text-normalization helpers shared by the deterministic resolvers."""
from __future__ import annotations

import re
import unicodedata


def strip_diacritics(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn").replace("đ", "d").replace("Đ", "D")


def normalize_text(text: str) -> str:
    """Lowercase, strip Vietnamese diacritics, collapse to plain ascii words.

    Used for keyword/pattern matching where diacritics may be typed
    inconsistently by users (e.g. "quy truoc" vs "quý trước").
    """
    text = strip_diacritics(text.lower())
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# Nearly every Vietnamese company full name starts with one of these
# legal-entity boilerplate phrases. Left in, they dominate fuzzy-match token
# overlap scores -- almost ANY query containing "công ty" would then score
# highly against almost every record, causing false-positive matches on
# garbage input. Stripped before a name is used as a fuzzy search term.
_LEGAL_PREFIXES = [
    r"^công ty cổ phần\s+",
    r"^công ty cp\s+",
    r"^ctcp\s+",
    r"^tổng công ty cổ phần\s+",
    r"^tổng công ty\s+",
    r"^tập đoàn\s+",
    r"^ngân hàng tmcp\s+",
    r"^ngân hàng thương mại cổ phần\s+",
    r"^ngân hàng\s+",
]


def strip_legal_prefix(name: str) -> str:
    stripped = name.strip()
    for pattern in _LEGAL_PREFIXES:
        stripped = re.sub(pattern, "", stripped, flags=re.IGNORECASE)
    return stripped.strip(" -")
