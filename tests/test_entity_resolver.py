from pathlib import Path

import pytest

from resolvers.entity_resolver import EntityResolver

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "tickers_sample.json"


@pytest.fixture
def resolver() -> EntityResolver:
    return EntityResolver(mapping_path=FIXTURE_PATH)


def test_exact_ticker_match(resolver: EntityResolver):
    result = resolver.resolve("HPG")
    assert result.ticker == "HPG"
    assert result.is_found


def test_exact_ticker_match_case_insensitive(resolver: EntityResolver):
    result = resolver.resolve("hpg")
    assert result.ticker == "HPG"


def test_alias_match(resolver: EntityResolver):
    result = resolver.resolve("Hòa Phát")
    assert result.ticker == "HPG"


def test_full_name_fuzzy_match_ignores_diacritics(resolver: EntityResolver):
    result = resolver.resolve("cong ty co phan sua viet nam")
    assert result.ticker == "VNM"


def test_ambiguous_alias_returns_no_ticker_but_lists_candidates(resolver: EntityResolver):
    result = resolver.resolve("cong ty abc")
    assert result.ticker is None
    assert result.is_ambiguous
    assert set(result.candidates) == {"ABC", "ABD"}


def test_unknown_mention_returns_none(resolver: EntityResolver):
    result = resolver.resolve("khong lien quan gi den chung khoan ca")
    assert result.ticker is None
    assert not result.candidates


def test_empty_mention_returns_none(resolver: EntityResolver):
    result = resolver.resolve("")
    assert result.ticker is None
