from datetime import date

from resolvers.time_resolver import TimeResolver

REF = date(2024, 6, 15)  # anchor date used across tests, Q2 2024


def test_last_n_months():
    r = TimeResolver().resolve("3 tháng gần nhất", reference_date=REF)
    assert r is not None
    assert r.end == REF
    assert r.start == date(2024, 3, 16)


def test_last_n_days():
    r = TimeResolver().resolve("10 ngày gần nhất", reference_date=REF)
    assert r.end == REF
    assert r.start == date(2024, 6, 6)


def test_last_n_quarters():
    r = TimeResolver().resolve("2 quý gần nhất", reference_date=REF)
    assert r.end == REF
    assert r.start == date(2023, 12, 16)


def test_explicit_range_iso_format():
    r = TimeResolver().resolve("từ 2023-01-01 đến 2023-06-30", reference_date=REF)
    assert r.start == date(2023, 1, 1)
    assert r.end == date(2023, 6, 30)


def test_explicit_range_slash_format():
    r = TimeResolver().resolve("từ 01/01/2023 đến 30/06/2023", reference_date=REF)
    assert r.start == date(2023, 1, 1)
    assert r.end == date(2023, 6, 30)


def test_quarter_this_clips_end_to_reference_date():
    r = TimeResolver().resolve("quý này", reference_date=REF)
    assert r.start == date(2024, 4, 1)
    assert r.end == REF


def test_quarter_previous():
    r = TimeResolver().resolve("quý trước", reference_date=REF)
    assert r.start == date(2024, 1, 1)
    assert r.end == date(2024, 3, 31)


def test_quarter_previous_crosses_year_boundary():
    ref_q1 = date(2024, 2, 10)
    r = TimeResolver().resolve("quý trước", reference_date=ref_q1)
    assert r.start == date(2023, 10, 1)
    assert r.end == date(2023, 12, 31)


def test_month_this():
    r = TimeResolver().resolve("tháng này", reference_date=REF)
    assert r.start == date(2024, 6, 1)
    assert r.end == REF


def test_month_previous():
    r = TimeResolver().resolve("tháng trước", reference_date=REF)
    assert r.start == date(2024, 5, 1)
    assert r.end == date(2024, 5, 31)


def test_year_this():
    r = TimeResolver().resolve("năm nay", reference_date=REF)
    assert r.start == date(2024, 1, 1)
    assert r.end == REF


def test_year_previous():
    r = TimeResolver().resolve("năm ngoái", reference_date=REF)
    assert r.start == date(2023, 1, 1)
    assert r.end == date(2023, 12, 31)


def test_specific_quarter_and_year():
    r = TimeResolver().resolve("quý 2 năm 2024", reference_date=REF)
    assert r.start == date(2024, 4, 1)
    assert r.end == date(2024, 6, 30)


def test_specific_quarter_slash_year_no_accents():
    r = TimeResolver().resolve("quy 3/2023", reference_date=REF)
    assert r.start == date(2023, 7, 1)
    assert r.end == date(2023, 9, 30)


def test_specific_month_and_year():
    r = TimeResolver().resolve("tháng 3 năm 2024", reference_date=REF)
    assert r.start == date(2024, 3, 1)
    assert r.end == date(2024, 3, 31)


def test_specific_year_only():
    r = TimeResolver().resolve("năm 2022", reference_date=REF)
    assert r.start == date(2022, 1, 1)
    assert r.end == date(2022, 12, 31)


def test_single_explicit_date():
    r = TimeResolver().resolve("ngày 15/03/2024", reference_date=REF)
    assert r.start == date(2024, 3, 15)
    assert r.end == date(2024, 3, 15)


def test_current_price_phrase_resolves_to_short_recent_window():
    r = TimeResolver().resolve("hiện tại", reference_date=REF)
    assert r is not None
    assert r.is_current is True
    assert r.end == REF
    assert r.start == date(2024, 6, 1)  # 14-day lookback


def test_today_phrase_is_current():
    r = TimeResolver().resolve("giá hôm nay", reference_date=REF)
    assert r is not None
    assert r.is_current is True


def test_latest_phrase_is_current():
    r = TimeResolver().resolve("giá mới nhất", reference_date=REF)
    assert r is not None
    assert r.is_current is True


def test_unrecognized_phrase_returns_none():
    assert TimeResolver().resolve("một câu không có nghĩa thời gian", reference_date=REF) is None


def test_empty_phrase_returns_none():
    assert TimeResolver().resolve("", reference_date=REF) is None
    assert TimeResolver().resolve(None, reference_date=REF) is None
