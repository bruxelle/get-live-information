from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from myojou_sync.merger import EventMerger
from myojou_sync.merger import derive_compatible_ticket_fields
from myojou_sync.models import CanonicalEvent, ExtractedEvent, SourceKind
from myojou_sync.parser import PostParser


JST = timezone(timedelta(hours=9))


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
    assert event.ticket_status == "same_day"
    assert event.latest_source_url == "https://x.com/info_myojou/status/180004"


def test_sold_out_post_updates_ticket_status(mock_posts):
    merger = EventMerger()
    events: list[CanonicalEvent] = []

    merger.merge_into_collection(_parsed("180001", mock_posts), events)
    event, created, _ = merger.merge_into_collection(_parsed("180005", mock_posts), events)

    assert created is False
    assert any(period.ticket_tier == "優先" and period.status == "完売" for period in event.ticket_sales)
    assert event.ticket_status != "sold_out"
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


def test_short_title_alias_merges_on_same_date_venue_and_keeps_richer_name():
    merger = EventMerger()
    events: list[CanonicalEvent] = []
    short = ExtractedEvent(
        event_date=date(2026, 6, 8),
        event_name="明夏",
        venue="Veats Shibuya",
        open_time="18:00",
        start_time="19:00",
        ticket_status="sold_out",
        myojou_performance_time="19:00",
        source_url="https://x.com/info_myojou/status/meika-short",
        source_post_id="meika-short",
        source_posted_at=datetime(2026, 6, 7, 13, 0, tzinfo=JST),
        source_text="⟣price：SOLD OUT",
        source_kind=SourceKind.SOLD_OUT,
        extraction_confidence=0.85,
    )
    rich = ExtractedEvent(
        event_date=date(2026, 6, 8),
        event_name="myojou oneman live 明夏",
        venue="Veats Shibuya",
        open_time="18:00",
        start_time="19:00",
        ticket_url="https://ticketdive.com/event/meika",
        ticket_sales=[
            _period(
                "一般",
                datetime(2026, 5, 1, 20, 0, tzinfo=JST),
                datetime(2026, 6, 8, 12, 0, tzinfo=JST),
                ticket_tier="一般",
                price=3000,
            )
        ],
        source_url="https://x.com/info_myojou/status/meika-rich",
        source_post_id="meika-rich",
        source_posted_at=datetime(2026, 6, 8, 1, 0, tzinfo=JST),
        source_text="myojou oneman live 明夏",
        source_kind=SourceKind.SAME_DAY_REMINDER,
        extraction_confidence=0.95,
    )

    merger.merge_into_collection(short, events)
    event, created, confidence = merger.merge_into_collection(rich, events)

    assert created is False
    assert confidence >= 0.72
    assert len(events) == 1
    assert event.event_name == "myojou oneman live 明夏"
    assert event.ticket_status == "sold_out"
    assert event.myojou_performance_time == "19:00"
    assert event.ticket_url == "https://ticketdive.com/event/meika"
    assert len(event.ticket_sales) == 1
    assert event.source_post_ids == ["meika-short", "meika-rich"]
    assert event.all_source_urls == [
        "https://x.com/info_myojou/status/meika-short",
        "https://x.com/info_myojou/status/meika-rich",
    ]


def test_short_title_same_name_different_date_or_venue_does_not_merge():
    merger = EventMerger()
    different_date_events: list[CanonicalEvent] = []
    first = ExtractedEvent(
        event_date=date(2026, 6, 8),
        event_name="明夏",
        venue="Veats Shibuya",
        source_url="https://x.com/info_myojou/status/meika-1",
        source_post_id="meika-1",
        source_posted_at=datetime(2026, 6, 7, 13, 0, tzinfo=JST),
        source_text="明夏",
        source_kind=SourceKind.INITIAL_ANNOUNCEMENT,
        extraction_confidence=0.8,
    )
    different_date = first.model_copy(
        update={
            "event_date": date(2026, 6, 9),
            "source_url": "https://x.com/info_myojou/status/meika-2",
            "source_post_id": "meika-2",
        }
    )

    merger.merge_into_collection(first, different_date_events)
    _, created_date, _ = merger.merge_into_collection(different_date, different_date_events)

    different_venue_events: list[CanonicalEvent] = []
    different_venue = first.model_copy(
        update={
            "venue": "Spotify O-nest",
            "source_url": "https://x.com/info_myojou/status/meika-3",
            "source_post_id": "meika-3",
        }
    )

    merger.merge_into_collection(first, different_venue_events)
    _, created_venue, _ = merger.merge_into_collection(different_venue, different_venue_events)

    assert created_date is True
    assert len(different_date_events) == 2
    assert created_venue is True
    assert len(different_venue_events) == 2


def test_lottery_post_followed_by_general_sale_merges_two_periods():
    parser = PostParser()
    merger = EventMerger()
    events: list[CanonicalEvent] = []
    lottery = parser.parse_post(
        _xpost(
            "sales-lottery",
            "【ライブ出演情報】\n5/30(土)『SALES TEST LIVE』\n会場：渋谷DESEO\n"
            "抽選受付：5/1 20:00〜5/10 23:59\nチケット：https://t.livepocket.jp/e/sales-test",
            datetime(2026, 4, 30, 3, 0, tzinfo=JST),
        )
    )
    general = parser.parse_post(
        _xpost(
            "sales-general",
            "【チケット情報】\n5/30(土)『SALES TEST LIVE』\n会場：渋谷DESEO\n"
            "一般販売：5/11 20:00〜5/30 23:59\nチケット：https://t.livepocket.jp/e/sales-test",
            datetime(2026, 5, 10, 3, 0, tzinfo=JST),
        )
    )
    assert lottery is not None
    assert general is not None

    merger.merge_into_collection(lottery, events)
    event, created, _ = merger.merge_into_collection(general, events)

    assert created is False
    assert len(events) == 1
    assert {period.sale_type for period in event.ticket_sales} == {"抽選", "一般"}


def test_derived_deadline_prefers_general_after_lottery_ended():
    event = CanonicalEvent(
        event_name="SALES TEST LIVE",
        ticket_sales=[
            _period("抽選", datetime(2026, 5, 1, 20, 0, tzinfo=JST), datetime(2026, 5, 10, 23, 59, tzinfo=JST)),
            _period("一般", datetime(2026, 5, 11, 20, 0, tzinfo=JST), datetime(2026, 5, 30, 23, 59, tzinfo=JST)),
        ],
    )

    derive_compatible_ticket_fields(event, now=datetime(2026, 5, 20, 12, 0, tzinfo=JST))

    assert event.ticket_sale_type == "一般"
    assert event.ticket_application_deadline_at == datetime(2026, 5, 30, 23, 59, tzinfo=JST)


def test_sold_out_priority_ticket_updates_only_priority_period():
    event = CanonicalEvent(
        event_name="SALES TEST LIVE",
        event_date=date(2026, 5, 30),
        venue="渋谷DESEO",
        priority_ticket_name="優先",
        priority_ticket_price=4000,
        ticket_sales=[
            _period("抽選", datetime(2026, 5, 1, 20, 0, tzinfo=JST), datetime(2026, 5, 10, 23, 59, tzinfo=JST), ticket_tier="優先"),
            _period("一般", datetime(2026, 5, 11, 20, 0, tzinfo=JST), datetime(2026, 5, 30, 23, 59, tzinfo=JST), ticket_tier="一般"),
        ],
    )
    sold_out = ExtractedEvent(
        event_date=date(2026, 5, 30),
        event_name="SALES TEST LIVE",
        venue="渋谷DESEO",
        ticket_status="sold_out",
        priority_ticket_name="優先チケットは完売しました。",
        ticket_sales=[
            _period(
                "不明",
                None,
                None,
                ticket_tier="優先",
                status="完売",
                source_post_id="soldout-priority",
            )
        ],
        source_url="https://x.com/info_myojou/status/soldout-priority",
        source_post_id="soldout-priority",
        source_posted_at=event.created_at,
        source_text="優先チケットは完売しました",
        source_kind=SourceKind.SOLD_OUT,
        extraction_confidence=0.8,
    )

    EventMerger().apply_update(event, sold_out)

    priority = next(period for period in event.ticket_sales if period.ticket_tier == "優先")
    general = next(period for period in event.ticket_sales if period.ticket_tier == "一般")
    assert priority.status == "完売"
    assert general.status != "完売"
    assert event.priority_ticket_name == "優先"
    assert event.priority_ticket_price == 4000
    assert event.ticket_status != "sold_out"


def test_duplicate_sale_periods_are_not_added():
    parser = PostParser()
    merger = EventMerger()
    events: list[CanonicalEvent] = []
    first = parser.parse_post(
        _xpost(
            "general-1",
            "【ライブ出演情報】\n5/30(土)『DUPLICATE PERIOD LIVE』\n会場：渋谷DESEO\n"
            "一般販売：5/11 20:00〜5/30 23:59\nチケット：https://t.livepocket.jp/e/duplicate-period",
            datetime(2026, 5, 10, 3, 0, tzinfo=JST),
        )
    )
    duplicate = parser.parse_post(
        _xpost(
            "general-2",
            "【一般販売のお知らせ】\n5/30(土)『DUPLICATE PERIOD LIVE』\n会場：渋谷DESEO\n"
            "一般販売：5/11 20:00〜5/30 23:59\nチケット：https://t.livepocket.jp/e/duplicate-period",
            datetime(2026, 5, 11, 3, 0, tzinfo=JST),
        )
    )
    assert first is not None
    assert duplicate is not None

    merger.merge_into_collection(first, events)
    event, created, _ = merger.merge_into_collection(duplicate, events)

    assert created is False
    assert len(event.ticket_sales) == 1
    assert event.ticket_sales[0].source_post_id == "general-2"


def test_unclear_sold_out_sets_event_status_and_needs_review():
    event = CanonicalEvent(
        event_name="SALES TEST LIVE",
        event_date=date(2026, 5, 30),
        venue="渋谷DESEO",
        ticket_sales=[
            _period("抽選", datetime(2026, 5, 1, 20, 0, tzinfo=JST), datetime(2026, 5, 10, 23, 59, tzinfo=JST), ticket_tier="優先"),
            _period("一般", datetime(2026, 5, 11, 20, 0, tzinfo=JST), datetime(2026, 5, 30, 23, 59, tzinfo=JST), ticket_tier="一般"),
        ],
    )
    sold_out = ExtractedEvent(
        event_date=date(2026, 5, 30),
        event_name="SALES TEST LIVE",
        venue="渋谷DESEO",
        ticket_status="sold_out",
        source_url="https://x.com/info_myojou/status/soldout-unclear",
        source_post_id="soldout-unclear",
        source_posted_at=event.created_at,
        source_text="チケットは完売しました",
        source_kind=SourceKind.SOLD_OUT,
        extraction_confidence=0.8,
    )

    EventMerger().apply_update(event, sold_out)

    assert event.ticket_status == "sold_out"
    assert event.needs_review is True
    assert all(period.status != "完売" for period in event.ticket_sales)


def test_clear_event_level_sold_out_does_not_force_review():
    event = CanonicalEvent(
        event_name="明夏",
        event_date=date(2026, 6, 8),
        venue="Veats Shibuya",
        open_time="18:00",
        start_time="19:00",
    )
    sold_out = ExtractedEvent(
        event_date=date(2026, 6, 8),
        event_name="明夏",
        venue="Veats Shibuya",
        open_time="18:00",
        start_time="19:00",
        ticket_status="sold_out",
        source_url="https://x.com/info_myojou/status/soldout-clear",
        source_post_id="soldout-clear",
        source_posted_at=event.created_at,
        source_text="⟣price：SOLD OUT",
        source_kind=SourceKind.SOLD_OUT,
        extraction_confidence=0.8,
    )

    EventMerger().apply_update(event, sold_out)

    assert event.ticket_status == "sold_out"
    assert event.needs_review is False


def test_unclear_sales_ended_sets_event_status_and_needs_review():
    event = CanonicalEvent(
        event_name="SALES TEST LIVE",
        event_date=date(2026, 5, 30),
        venue="渋谷DESEO",
        ticket_sales=[_period("一般", datetime(2026, 5, 11, 20, 0, tzinfo=JST), datetime(2026, 5, 30, 23, 59, tzinfo=JST))],
    )
    ended = ExtractedEvent(
        event_date=date(2026, 5, 30),
        event_name="SALES TEST LIVE",
        venue="渋谷DESEO",
        ticket_status="ended",
        source_url="https://x.com/info_myojou/status/ended-unclear",
        source_post_id="ended-unclear",
        source_posted_at=event.created_at,
        source_text="チケット販売終了しました",
        source_kind=SourceKind.TICKET_UPDATE,
        extraction_confidence=0.8,
    )

    EventMerger().apply_update(event, ended)

    assert event.ticket_status == "ended"
    assert event.needs_review is True
    assert event.ticket_sales[0].status != "販売終了"


def test_general_sales_ended_updates_only_general_period_when_detectable():
    event = CanonicalEvent(
        event_name="SALES TEST LIVE",
        event_date=date(2026, 5, 30),
        venue="渋谷DESEO",
        ticket_sales=[
            _period("抽選", datetime(2026, 5, 1, 20, 0, tzinfo=JST), datetime(2026, 5, 10, 23, 59, tzinfo=JST), ticket_tier="優先"),
            _period("一般", datetime(2026, 5, 11, 20, 0, tzinfo=JST), datetime(2026, 5, 30, 23, 59, tzinfo=JST), ticket_tier="一般"),
        ],
    )
    ended = ExtractedEvent(
        event_date=date(2026, 5, 30),
        event_name="SALES TEST LIVE",
        venue="渋谷DESEO",
        ticket_status="ended",
        ticket_sales=[
            _period(
                "不明",
                None,
                None,
                ticket_tier="一般",
                status="販売終了",
                source_post_id="ended-general",
            )
        ],
        source_url="https://x.com/info_myojou/status/ended-general",
        source_post_id="ended-general",
        source_posted_at=event.created_at,
        source_text="一般チケット販売終了しました",
        source_kind=SourceKind.TICKET_UPDATE,
        extraction_confidence=0.8,
    )

    EventMerger().apply_update(event, ended)

    priority = next(period for period in event.ticket_sales if period.ticket_tier == "優先")
    general = next(period for period in event.ticket_sales if period.ticket_tier == "一般")
    assert general.status == "販売終了"
    assert priority.status != "販売終了"
    assert event.ticket_status != "ended"


def test_derived_backward_compatible_fields_include_prices_and_same_day():
    event = CanonicalEvent(
        event_name="SALES TEST LIVE",
        ticket_sales=[
            _period(
                "抽選",
                datetime(2026, 5, 1, 20, 0, tzinfo=JST),
                datetime(2026, 5, 10, 23, 59, tzinfo=JST),
                ticket_tier="VIP",
                price=8000,
                result_at=datetime(2026, 5, 11, 18, 0, tzinfo=JST),
                payment_deadline_at=datetime(2026, 5, 13, 23, 59, tzinfo=JST),
            ),
            _period("一般", datetime(2026, 5, 11, 20, 0, tzinfo=JST), datetime(2026, 5, 30, 23, 59, tzinfo=JST), price=2500),
            _period("当日券", datetime(2026, 5, 30, 10, 0, tzinfo=JST), None, price=3000),
        ],
    )

    derive_compatible_ticket_fields(event, now=datetime(2026, 5, 5, 12, 0, tzinfo=JST))

    assert event.ticket_sale_type == "抽選"
    assert event.ticket_application_start_at == datetime(2026, 5, 1, 20, 0, tzinfo=JST)
    assert event.ticket_application_deadline_at == datetime(2026, 5, 10, 23, 59, tzinfo=JST)
    assert event.lottery_result_at == datetime(2026, 5, 11, 18, 0, tzinfo=JST)
    assert event.payment_deadline_at == datetime(2026, 5, 13, 23, 59, tzinfo=JST)
    assert event.general_ticket_price == 2500
    assert event.priority_ticket_name == "VIP"
    assert event.priority_ticket_price == 8000
    assert event.same_day_ticket_price == 3000


def test_only_same_day_period_can_drive_compatible_sale_type():
    event = CanonicalEvent(
        event_name="SAME DAY LIVE",
        ticket_sales=[_period("当日券", datetime(2026, 5, 30, 10, 0, tzinfo=JST), None, price=3000)],
    )

    derive_compatible_ticket_fields(event, now=datetime(2026, 5, 30, 9, 0, tzinfo=JST))

    assert event.ticket_sale_type == "当日券"
    assert event.ticket_application_start_at == datetime(2026, 5, 30, 10, 0, tzinfo=JST)
    assert event.ticket_application_deadline_at is None
    assert event.same_day_ticket_price == 3000


def _xpost(post_id: str, text: str, created_at: datetime):
    from myojou_sync.models import XPost

    return XPost(id=post_id, text=text, created_at=created_at)


def _period(
    sale_type: str,
    start_at: datetime | None,
    deadline_at: datetime | None,
    *,
    ticket_tier: str = "一般",
    price: int | None = None,
    status: str = "不明",
    result_at: datetime | None = None,
    payment_deadline_at: datetime | None = None,
    source_post_id: str = "source",
):
    from myojou_sync.models import TicketSalePeriod

    return TicketSalePeriod(
        sale_type=sale_type,
        ticket_tier=ticket_tier,
        ticket_name=ticket_tier,
        price=price,
        start_at=start_at,
        deadline_at=deadline_at,
        result_at=result_at,
        payment_deadline_at=payment_deadline_at,
        status=status,
        source_url=f"https://x.com/info_myojou/status/{source_post_id}",
        source_post_id=source_post_id,
    )
