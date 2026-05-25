from __future__ import annotations

from datetime import date

from myojou_sync.merger import EventMerger
from myojou_sync.models import CanonicalEvent, ExtractedEvent, SourceKind
from myojou_sync.parser import PostParser


def _parsed(post_id: str, mock_posts):
    parsed = PostParser().parse_post(mock_posts[post_id])
    assert parsed is not None
    return parsed


def test_initial_announcement_creates_new_event(mock_posts):
    events: list[CanonicalEvent] = []
    event, created, confidence = EventMerger().merge_into_collection(_parsed("180001", mock_posts), events)

    assert created is True
    assert confidence == 0
    assert len(events) == 1
    assert event.event_name == "STARLIGHT LIVE vol.7"
    assert event.primary_source_url == "https://x.com/info_myojou/status/180001"
    assert event.latest_source_url == event.primary_source_url
    assert event.source_summary is not None
    assert event.last_source_kind == SourceKind.INITIAL_ANNOUNCEMENT


def test_timetable_update_updates_existing_event(mock_posts):
    merger = EventMerger()
    events: list[CanonicalEvent] = []

    first, first_created, _ = merger.merge_into_collection(_parsed("180001", mock_posts), events)
    second, second_created, confidence = merger.merge_into_collection(_parsed("180002", mock_posts), events)

    assert first_created is True
    assert second_created is False
    assert confidence >= 0.72
    assert len(events) == 1
    assert first.event_id == second.event_id
    assert second.myojou_performance_time == "19:10-19:35"
    assert second.benefit_event_time == "20:00-21:00"
    assert second.latest_source_url == "https://x.com/info_myojou/status/180002"


def test_day_before_reminder_only_updates_source_fields_without_changed_information(mock_posts):
    merger = EventMerger()
    events: list[CanonicalEvent] = []

    merger.merge_into_collection(_parsed("180001", mock_posts), events)
    event, created, _ = merger.merge_into_collection(_parsed("180003", mock_posts), events)

    assert created is False
    assert len(events) == 1
    assert event.open_time == "18:00"
    assert event.start_time == "18:30"
    assert event.latest_source_url == "https://x.com/info_myojou/status/180003"
    assert "day_before_reminder" in (event.source_summary or "")
    assert event.last_source_kind == SourceKind.DAY_BEFORE_REMINDER


def test_same_day_reminder_updates_ticket_status(mock_posts):
    merger = EventMerger()
    events: list[CanonicalEvent] = []

    merger.merge_into_collection(_parsed("180001", mock_posts), events)
    event, created, _ = merger.merge_into_collection(_parsed("180004", mock_posts), events)

    assert created is False
    assert event.ticket_status == "same_day_available"
    assert event.latest_source_url == "https://x.com/info_myojou/status/180004"


def test_sold_out_post_updates_ticket_status(mock_posts):
    merger = EventMerger()
    events: list[CanonicalEvent] = []

    merger.merge_into_collection(_parsed("180001", mock_posts), events)
    event, created, _ = merger.merge_into_collection(_parsed("180005", mock_posts), events)

    assert created is False
    assert event.ticket_status == "sold_out"
    assert event.last_source_kind == SourceKind.SOLD_OUT


def test_correction_post_updates_canonical_event(mock_posts):
    merger = EventMerger()
    events: list[CanonicalEvent] = []

    merger.merge_into_collection(_parsed("180001", mock_posts), events)
    event, created, _ = merger.merge_into_collection(_parsed("180006", mock_posts), events)

    assert created is False
    assert event.open_time == "18:15"
    assert event.start_time == "18:45"
    assert event.last_source_kind == SourceKind.CORRECTION


def test_two_different_events_on_same_date_do_not_merge(mock_posts):
    merger = EventMerger()
    events: list[CanonicalEvent] = []

    merger.merge_into_collection(_parsed("180001", mock_posts), events)
    second, created, _ = merger.merge_into_collection(_parsed("180010", mock_posts), events)

    assert created is True
    assert len(events) == 2
    assert second.event_name == "SUNRISE IDOL PARK"


def test_two_different_events_at_same_venue_same_date_do_not_merge(mock_posts):
    merger = EventMerger()
    events: list[CanonicalEvent] = []

    merger.merge_into_collection(_parsed("180001", mock_posts), events)
    second, created, confidence = merger.merge_into_collection(_parsed("180011", mock_posts), events)

    assert created is True
    assert confidence == 0
    assert len(events) == 2
    assert second.event_name == "MOONLIGHT LIVE vol.1"


def test_weak_match_sets_needs_review():
    event = CanonicalEvent(
        event_date=date(2026, 6, 15),
        event_name="STARLIGHT LIVE vol.7",
        venue="渋谷Milkyway",
        ticket_url="https://t.livepocket.jp/e/starlight7",
    )
    extracted_event = ExtractedEvent(
        event_date=date(2026, 6, 15),
        event_name=None,
        venue=None,
        ticket_url=None,
        source_url="https://x.com/info_myojou/status/999",
        source_post_id="999",
        source_posted_at=event.created_at,
        source_text="本日出演です",
        source_kind="same_day_reminder",
        extraction_confidence=0.4,
    )
    events = [event]

    merged, created, _confidence = EventMerger().merge_into_collection(extracted_event, events)

    assert created is False
    assert merged.needs_review is True


def test_manual_override_protects_human_fields_but_appends_source_tracking(mock_posts):
    merger = EventMerger()
    initial = _parsed("180001", mock_posts)
    correction = _parsed("180006", mock_posts)

    event = CanonicalEvent.from_extracted(initial)
    event.manual_override = True
    event.event_date = date(2026, 6, 16)
    event.event_name = "Human Edited Title"
    event.venue = "Human Edited Venue"
    event.open_time = "17:45"
    event.start_time = "18:10"
    event.myojou_performance_time = "19:00-19:20"
    event.benefit_event_time = "20:00-20:30"
    event.ticket_url = "https://example.com/human-ticket"
    event.general_ticket_price = 9999
    event.priority_ticket_name = "Human Priority"
    event.priority_ticket_price = 8888
    event.same_day_ticket_price = 7777

    merger.apply_update(event, correction)

    assert event.event_date == date(2026, 6, 16)
    assert event.event_name == "Human Edited Title"
    assert event.venue == "Human Edited Venue"
    assert event.open_time == "17:45"
    assert event.start_time == "18:10"
    assert event.myojou_performance_time == "19:00-19:20"
    assert event.benefit_event_time == "20:00-20:30"
    assert event.ticket_url == "https://example.com/human-ticket"
    assert event.general_ticket_price == 9999
    assert event.priority_ticket_name == "Human Priority"
    assert event.priority_ticket_price == 8888
    assert event.same_day_ticket_price == 7777
    assert event.latest_source_url == correction.source_url
    assert correction.source_url in event.all_source_urls
    assert "correction" in (event.source_summary or "")
    assert event.last_source_posted_at == correction.source_posted_at
    assert event.last_source_kind == SourceKind.CORRECTION


def test_source_url_preservation(mock_posts):
    merger = EventMerger()
    events: list[CanonicalEvent] = []

    for post_id in ("180001", "180002", "180003"):
        merger.merge_into_collection(_parsed(post_id, mock_posts), events)

    assert len(events) == 1
    event = events[0]
    assert event.primary_source_url == "https://x.com/info_myojou/status/180001"
    assert event.latest_source_url == "https://x.com/info_myojou/status/180003"
    assert event.all_source_urls == [
        "https://x.com/info_myojou/status/180001",
        "https://x.com/info_myojou/status/180002",
        "https://x.com/info_myojou/status/180003",
    ]
    assert event.source_post_ids == ["180001", "180002", "180003"]
