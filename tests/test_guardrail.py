"""Validates the guardrail's number-extraction/matching logic (prompt_v3
requirement #1) -- pure functions, no LLM/network involved. This is the
"regex/exact match" heuristic check itself; the graph wiring (retry loop) is
covered by live testing, not unit tests, since it depends on real Groq
output."""
from graph.guardrail_node import _extract_numbers, _grounded_numbers, _is_grounded


def test_extract_numbers_vn_thousands_and_decimal():
    text = "Doanh thu đạt 118.953.027.893.654,0 VND, tăng so với 32.806.456.479.733 VND."
    numbers = _extract_numbers(text)
    assert 118953027893654.0 in numbers
    assert 32806456479733.0 in numbers


def test_extract_numbers_plain_decimal():
    assert 21.7 in _extract_numbers("Giá đóng cửa là 21.7 nghìn đồng.")


def test_grounded_numbers_walks_nested_structure_and_strings():
    tool_result = {
        "ticker": "HPG",
        "stats": {"last_close": 21.7},
        "series": [{"date": "2026-07-31", "close": 21.7, "volume": 137648000}],
    }
    grounded = _grounded_numbers(tool_result)
    assert 21.7 in grounded
    assert 137648000.0 in grounded
    assert 2026.0 in grounded  # extracted from the date string, not just numeric leaves


def test_is_grounded_exact_match():
    assert _is_grounded(21.7, {21.7, 100.0})


def test_is_grounded_truncated_unit_conversion():
    # "185 nghìn tỷ" for a grounded value of 185056626536000
    assert _is_grounded(185.0, {185056626536000.0})


def test_is_grounded_fabricated_number_is_flagged():
    assert not _is_grounded(999.0, {21.7, 100.0, 2026.0})


def test_is_grounded_empty_grounded_set_never_flags():
    # No tool_result data to check against (e.g. general chat) -- don't
    # false-positive on every number in a normal conversational answer.
    assert _is_grounded(42.0, set())


def test_is_grounded_sign_insensitive():
    # "giảm 12.39%" (Vietnamese conveys direction with words, not a minus
    # sign) must match a grounded pct_change of -12.39. Caught live-testing.
    assert _is_grounded(12.39, {-12.39})


def test_extract_numbers_small_decimal_not_mistaken_for_thousands_grouping():
    # "-0.215" (e.g. a sentiment average_score) must parse as 0.215, not get
    # mangled into 215 by the VN-thousands-separator heuristic (which should
    # only fire for numbers NOT starting with a leading zero). Caught
    # live-testing a company-evaluation answer citing a real sentiment score.
    numbers = _extract_numbers("Điểm sentiment trung bình là -0.215.")
    assert 0.215 in numbers
    assert 215.0 not in numbers
