"""Vietnamese news sentiment classification (prompt_v1 requirement #1).

Runs locally via a small pretrained PhoBERT sentiment model instead of
calling Groq per article -- classifying a page of news headlines this way
costs zero LLM tokens and is much faster than an API round-trip each time.

Note: this model is diacritic-sensitive (like most Vietnamese NLP models) --
only feed it properly accented Vietnamese text. Real vnstock news titles
always are, so this is a non-issue for the news tool.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

SentimentLabel = Literal["positive", "negative", "neutral"]

_MODEL_NAME = "wonrax/phobert-base-vietnamese-sentiment"
_LABEL_MAP: dict[str, SentimentLabel] = {"POS": "positive", "NEG": "negative", "NEU": "neutral"}


@dataclass
class SentimentResult:
    label: SentimentLabel
    score: float  # confidence of the winning label, 0..1


@lru_cache(maxsize=1)
def _get_pipeline():
    from transformers import pipeline

    return pipeline("sentiment-analysis", model=_MODEL_NAME, tokenizer=_MODEL_NAME)


def classify_sentiment(text: str) -> SentimentResult:
    if not text or not text.strip():
        return SentimentResult(label="neutral", score=0.0)
    pipe = _get_pipeline()
    result = pipe(text[:512])[0]  # PhoBERT's max sequence length is well under 512 tokens
    label = _LABEL_MAP.get(result["label"], "neutral")
    return SentimentResult(label=label, score=round(float(result["score"]), 3))
