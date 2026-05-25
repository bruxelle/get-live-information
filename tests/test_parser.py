from __future__ import annotations

from datetime import date

from myojou_sync.models import SourceKind
from myojou_sync.parser import PostParser


def test_initial_announcement_parsing(mock_posts):
    parsed = PostParser().parse_post(mock_posts["180001"])

    assert parsed is not None
    assert parsed.source_kind == SourceKind.INITIAL_ANNOUNCEMENT
    assert parsed.event_date == date(2026, 6, 15)
    assert parsed.event_name == "STARLIGHT LIVE vol.7"
    assert parsed.venue == "渋谷Milkyway"
    assert parsed.open_time == "18:00"
    assert parsed.start_time == "18:30"
    assert parsed.ticket_url == "https://t.livepocket.jp/e/starlight7"
    assert parsed.general_ticket_price == 2500
    assert parsed.priority_ticket_name == "優先チケット"
    assert parsed.priority_ticket_price == 4000
    assert parsed.same_day_ticket_price == 3000
    assert parsed.extraction_confidence >= 0.8


def test_timetable_update_parsing(mock_posts):
    parsed = PostParser().parse_post(mock_posts["180002"])

    assert parsed is not None
    assert parsed.source_kind == SourceKind.TIMETABLE_UPDATE
    assert parsed.event_date == date(2026, 6, 15)
    assert parsed.myojou_performance_time == "19:10-19:35"
    assert parsed.benefit_event_time == "20:00-21:00"


def test_day_before_reminder_classification(mock_posts):
    parsed = PostParser().parse_post(mock_posts["180003"])

    assert parsed is not None
    assert parsed.source_kind == SourceKind.DAY_BEFORE_REMINDER
    assert parsed.event_date == date(2026, 6, 15)


def test_same_day_reminder_classification(mock_posts):
    parsed = PostParser().parse_post(mock_posts["180004"])

    assert parsed is not None
    assert parsed.source_kind == SourceKind.SAME_DAY_REMINDER
    assert parsed.event_date == date(2026, 6, 15)
    assert parsed.ticket_status == "same_day_available"
    assert parsed.myojou_performance_time == "19:10-19:35"


def test_sold_out_classification(mock_posts):
    parsed = PostParser().parse_post(mock_posts["180005"])

    assert parsed is not None
    assert parsed.source_kind == SourceKind.SOLD_OUT
    assert parsed.ticket_status == "sold_out"


def test_correction_classification_and_time_parsing(mock_posts):
    parsed = PostParser().parse_post(mock_posts["180006"])

    assert parsed is not None
    assert parsed.source_kind == SourceKind.CORRECTION
    assert parsed.open_time == "18:15"
    assert parsed.start_time == "18:45"
