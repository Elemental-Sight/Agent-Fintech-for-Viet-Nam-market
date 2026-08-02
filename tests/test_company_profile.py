"""Validates deterministic chairman/CEO extraction from vnstock's officer
list -- must never fall back to the LLM's own (possibly stale) knowledge."""
import pandas as pd

from tools.company_profile_tool import _extract_leadership


def _officers(rows: list[tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame([{"officer_name": name, "officer_position": position} for name, position in rows])


def test_extracts_chairman_and_ceo():
    df = _officers(
        [
            ("Trần Đình Long", "Chủ tịch Hội đồng Quản trị"),
            ("Trần Tuấn Dương", "Phó Chủ tịch Hội đồng Quản trị"),
            ("Nguyễn Việt Thắng", "Thành viên Hội đồng Quản trị/Tổng Giám đốc"),
            ("Nguyễn Thị Thảo Nguyên", "Phó Tổng Giám đốc"),
        ]
    )
    leadership = _extract_leadership(df)
    assert leadership == {"chairman": "Trần Đình Long", "ceo": "Nguyễn Việt Thắng"}


def test_does_not_confuse_vice_chairman_or_vice_ceo():
    df = _officers(
        [
            ("Phó Chủ Nhân", "Phó Chủ tịch Hội đồng Quản trị"),
            ("Phó Giám Đốc", "Phó Tổng Giám đốc"),
        ]
    )
    assert _extract_leadership(df) == {}


def test_empty_or_missing_officers_returns_empty_dict():
    assert _extract_leadership(pd.DataFrame()) == {}
    assert _extract_leadership(None) == {}
