from datetime import date

from graph.fast_router import try_fast_route

REF = date(2024, 6, 15)


def test_explicit_ticker_price_query_fast_paths():
    result = try_fast_route("gia VCB hien tai", reference_date=REF)
    assert result is not None
    assert result.intent == "price_history"
    assert result.ticker == "VCB"


def test_explicit_ticker_indicator_query_fast_paths():
    result = try_fast_route("RSI 14 cua HPG", reference_date=REF)
    assert result is not None
    assert result.intent == "indicator"
    assert result.ticker == "HPG"
    assert result.indicator_type == "RSI"
    assert result.window_size == 14


def test_explicit_ticker_profile_query_fast_paths():
    result = try_fast_route("ho so doanh nghiep FPT", reference_date=REF)
    assert result is not None
    assert result.intent == "company_profile"
    assert result.ticker == "FPT"


def test_explicit_ticker_news_query_fast_paths():
    result = try_fast_route("tin tuc ve HPG gan day", reference_date=REF)
    assert result is not None
    assert result.intent == "news"
    assert result.ticker == "HPG"


def test_comparison_question_defers_to_full_router():
    assert try_fast_route("so sanh HPG va HSG", reference_date=REF) is None


def test_alias_without_explicit_ticker_defers_to_full_router():
    # "Hòa Phát" is a real alias but not a certain all-caps ticker match in
    # context -- the fast path should never fuzzy-guess.
    assert try_fast_route("gia Hoa Phat hom nay", reference_date=REF) is None


def test_unrecognized_intent_defers_to_full_router():
    assert try_fast_route("ban nghi sao ve VCB", reference_date=REF) is None


def test_empty_question_defers():
    assert try_fast_route("", reference_date=REF) is None
    assert try_fast_route(None, reference_date=REF) is None


def test_fast_path_resolves_time_phrase():
    result = try_fast_route("gia VNM 3 thang gan nhat", reference_date=REF)
    assert result is not None
    assert result.resolved_date_range is not None
    assert result.resolved_date_range["end"] == REF.isoformat()
