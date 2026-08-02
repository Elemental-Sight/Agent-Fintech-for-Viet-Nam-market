"""News + sentiment tool (prompt_v1 requirement #1).

News comes from vnstock's own news feed (official company disclosures /
CBTT, aggregated by vnstock itself) rather than scraping CafeF/Vietstock
directly -- same trusted data source the rest of the app already relies on,
without the fragility/ToS risk of HTML scraping.

Sentiment is classified locally (nlp.sentiment, a small PhoBERT model) per
headline instead of calling Groq per article, so this tool's cost/latency
doesn't scale with how many articles it returns.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Optional

from rapidfuzz import fuzz, process

from nlp.sentiment import classify_sentiment
from resolvers.text_utils import normalize_text

from ._vnstock_client import fetch_industry_symbol_map, fetch_news

_MAX_ARTICLES_PER_TICKER = 10
_MAX_TICKERS_PER_INDUSTRY = 5
_MAX_ARTICLES_PER_INDUSTRY_TICKER = 4
_INDUSTRY_MATCH_THRESHOLD = 80.0


@dataclass
class NewsResult:
    query: str
    query_type: str  # "ticker" | "industry"
    found: bool
    articles: list[dict] = field(default_factory=list)
    sentiment_summary: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "query_type": self.query_type,
            "found": self.found,
            "articles": self.articles,
            "sentiment_summary": self.sentiment_summary,
            "error": self.error,
        }


def _classify_articles(raw_rows, ticker: str, limit: int) -> list[dict]:
    articles = []
    for _, row in raw_rows.head(limit).iterrows():
        title = str(row.get("news_title") or "").strip()
        if not title:
            continue
        sentiment = classify_sentiment(title)
        articles.append(
            {
                "ticker": ticker,
                "title": title,
                "date": str(row.get("public_date") or "")[:10],
                "sentiment": sentiment.label,
                "sentiment_score": sentiment.score,
            }
        )
    return articles


def _summarize_sentiment(articles: list[dict]) -> dict:
    if not articles:
        return {"positive": 0, "negative": 0, "neutral": 0, "overall": "neutral", "average_score": 0.0}
    counts = {"positive": 0, "negative": 0, "neutral": 0}
    signed_total = 0.0
    for a in articles:
        counts[a["sentiment"]] += 1
        sign = {"positive": 1, "negative": -1, "neutral": 0}[a["sentiment"]]
        signed_total += sign * a["sentiment_score"]
    average = round(signed_total / len(articles), 3)
    overall = "positive" if average > 0.15 else "negative" if average < -0.15 else "neutral"
    return {**counts, "overall": overall, "average_score": average}


def get_news_by_ticker(ticker: str, limit: int = _MAX_ARTICLES_PER_TICKER) -> NewsResult:
    try:
        raw = fetch_news(ticker)
    except Exception as exc:  # pragma: no cover - depends on live network/vnstock
        return NewsResult(query=ticker, query_type="ticker", found=False, error=str(exc))

    if raw is None or raw.empty:
        return NewsResult(query=ticker, query_type="ticker", found=False, error="Không tìm thấy tin tức cho mã này.")

    articles = _classify_articles(raw, ticker, limit)
    return NewsResult(
        query=ticker, query_type="ticker", found=True, articles=articles, sentiment_summary=_summarize_sentiment(articles)
    )


@lru_cache(maxsize=1)
def _industry_choices() -> tuple[list[str], dict]:
    """Unique ICB industry names -> list of tickers. Cached for the process
    lifetime since vnstock's industry classification doesn't change often."""
    df = fetch_industry_symbol_map()
    industry_to_tickers: dict[str, list[str]] = {}
    for _, row in df.iterrows():
        name = str(row.get("icb_name") or "").strip()
        symbol = str(row.get("symbol") or "").strip().upper()
        if not name or not symbol:
            continue
        industry_to_tickers.setdefault(name, [])
        if symbol not in industry_to_tickers[name]:
            industry_to_tickers[name].append(symbol)
    return list(industry_to_tickers.keys()), industry_to_tickers


def _resolve_industry(query: str) -> Optional[tuple[str, list[str]]]:
    names, mapping = _industry_choices()
    normalized_choices = {name: normalize_text(name) for name in names}
    match = process.extractOne(
        normalize_text(query), list(normalized_choices.values()), scorer=fuzz.WRatio
    )
    if not match or match[1] < _INDUSTRY_MATCH_THRESHOLD:
        return None
    matched_normalized = match[0]
    matched_name = next(name for name, norm in normalized_choices.items() if norm == matched_normalized)
    return matched_name, mapping[matched_name]


def get_news_by_industry(
    industry_query: str,
    max_tickers: int = _MAX_TICKERS_PER_INDUSTRY,
    max_articles_per_ticker: int = _MAX_ARTICLES_PER_INDUSTRY_TICKER,
) -> NewsResult:
    resolved = _resolve_industry(industry_query)
    if resolved is None:
        return NewsResult(
            query=industry_query,
            query_type="industry",
            found=False,
            error="Không nhận diện được ngành này trong danh mục ICB.",
        )
    industry_name, tickers = resolved

    all_articles: list[dict] = []
    for ticker in tickers[:max_tickers]:
        try:
            raw = fetch_news(ticker)
        except Exception:  # pragma: no cover - depends on live network/vnstock
            continue
        if raw is None or raw.empty:
            continue
        all_articles.extend(_classify_articles(raw, ticker, max_articles_per_ticker))

    all_articles.sort(key=lambda a: a["date"], reverse=True)
    if not all_articles:
        return NewsResult(
            query=industry_name, query_type="industry", found=False, error="Không tìm thấy tin tức cho ngành này."
        )

    return NewsResult(
        query=industry_name,
        query_type="industry",
        found=True,
        articles=all_articles,
        sentiment_summary=_summarize_sentiment(all_articles),
    )
