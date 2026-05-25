from __future__ import annotations

from datetime import date

from myojou_sync.normalization import (
    normalize_event_name,
    normalize_price,
    normalize_spaces,
    normalize_time,
    normalize_time_range,
    normalize_venue,
    parse_event_date,
)


def test_normalize_full_width_and_half_width_spaces():
    assert normalize_spaces("渋谷　Milkyway\t  Hall") == "渋谷 Milkyway Hall"


def test_normalize_event_names_and_venues_for_matching():
    assert normalize_event_name("『ＳＴＡＲＬＩＧＨＴ LIVE vol.7』") == "starlightlivevol7"
    assert normalize_venue("渋谷　Milkyway") == "渋谷milkyway"


def test_normalize_yen_prices():
    assert normalize_price("優先：￥４,０００") == 4000
    assert normalize_price("一般 2500円") == 2500


def test_normalize_time_formats():
    assert normalize_time("18:00") == "18:00"
    assert normalize_time("18時") == "18:00"
    assert normalize_time_range("18:00〜18:20") == "18:00-18:20"


def test_parse_supported_date_formats():
    posted = date(2026, 5, 1)

    assert parse_event_date("5/25", posted) == date(2026, 5, 25)
    assert parse_event_date("2026/5/25", posted) == date(2026, 5, 25)
    assert parse_event_date("05.25", posted) == date(2026, 5, 25)
    assert parse_event_date("5月25日", posted) == date(2026, 5, 25)
