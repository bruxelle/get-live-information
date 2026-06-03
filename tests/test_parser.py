from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from myojou_sync.models import SourceKind
from myojou_sync.models import CanonicalEvent
from myojou_sync.models import PostClassification
from myojou_sync.models import TicketSalePeriod
from myojou_sync.models import XPost
from myojou_sync.parser import PostParser
from myojou_sync.real_samples import evaluate_real_samples


JST = timezone(timedelta(hours=9))


def test_ticket_sale_period_model_accepts_required_fields():
    period = TicketSalePeriod(
        sale_type="抽選",
        ticket_name="優先チケット",
        ticket_tier="優先",
        price=4000,
        start_at=datetime(2026, 5, 1, 20, 0, tzinfo=JST),
        deadline_at=datetime(2026, 5, 10, 23, 59, tzinfo=JST),
        result_at=datetime(2026, 5, 11, 18, 0, tzinfo=JST),
        payment_deadline_at=datetime(2026, 5, 13, 23, 59, tzinfo=JST),
        status="販売中",
        source_url="https://x.com/info_myojou/status/period001",
        source_post_id="period001",
        notes="manual fixture",
    )

    assert period.sale_type == "抽選"
    assert period.ticket_tier == "優先"
    assert period.price == 4000


def test_canonical_event_includes_ticket_sales():
    period = TicketSalePeriod(sale_type="一般", ticket_tier="一般", price=2500)
    event = CanonicalEvent(event_name="Ticket Sales Event", ticket_sales=[period])

    assert event.ticket_sales == [period]


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
    assert parsed.ticket_application_start_at == datetime(2026, 5, 25, 20, 0, tzinfo=JST)
    assert parsed.ticket_application_deadline_at == datetime(2026, 6, 1, 23, 59, tzinfo=JST)
    assert parsed.lottery_result_at == datetime(2026, 6, 3, 18, 0, tzinfo=JST)
    assert parsed.payment_deadline_at == datetime(2026, 6, 5, 23, 59, tzinfo=JST)
    assert parsed.ticket_sale_type == "抽選"
    assert len(parsed.ticket_sales) == 3
    dated_periods = [period for period in parsed.ticket_sales if period.deadline_at]
    assert {period.ticket_tier for period in dated_periods} == {"一般", "優先"}
    assert all(period.deadline_at == datetime(2026, 6, 1, 23, 59, tzinfo=JST) for period in dated_periods)
    assert any(period.sale_type == "当日券" and period.price == 3000 for period in parsed.ticket_sales)
    assert parsed.extraction_confidence >= 0.8


def test_ticket_deadline_fields_parse_from_labeled_lines():
    parsed = PostParser().parse_post(
        XPost(
            id="deadline001",
            created_at=datetime(2026, 5, 20, 3, 0, tzinfo=timezone.utc),
            text=(
                "【チケット情報】\n"
                "6/15(月)『STARLIGHT LIVE vol.7』\n"
                "受付開始：5/25 20:00\n"
                "受付締切：6/1 23:59\n"
                "当落発表：6/3 18:00\n"
                "入金期限：6/5 23:59\n"
                "抽選受付\n"
                "https://t.livepocket.jp/e/starlight7"
            ),
        )
    )

    assert parsed is not None
    assert parsed.ticket_application_start_at == datetime(2026, 5, 25, 20, 0, tzinfo=JST)
    assert parsed.ticket_application_deadline_at == datetime(2026, 6, 1, 23, 59, tzinfo=JST)
    assert parsed.lottery_result_at == datetime(2026, 6, 3, 18, 0, tzinfo=JST)
    assert parsed.payment_deadline_at == datetime(2026, 6, 5, 23, 59, tzinfo=JST)
    assert parsed.ticket_sale_type == "抽選"


def test_payment_deadline_parses_shiharai_variant():
    parsed = PostParser().parse_post(
        XPost(
            id="payment-variant",
            created_at=datetime(2026, 5, 1, 3, 0, tzinfo=JST),
            text=(
                "【ライブ出演情報】\n"
                "5/30(土)『PAYMENT VARIANT LIVE』\n"
                "会場：渋谷DESEO\n"
                "抽選受付：5/1 20:00〜5/10 23:59\n"
                "支払い期限：5/13 23:59\n"
                "チケット：https://t.livepocket.jp/e/payment-variant"
            ),
        )
    )

    assert parsed is not None
    assert parsed.payment_deadline_at == datetime(2026, 5, 13, 23, 59, tzinfo=JST)
    assert parsed.ticket_sales[0].payment_deadline_at == datetime(2026, 5, 13, 23, 59, tzinfo=JST)


def test_ticket_sale_type_detection():
    parser = PostParser()

    assert parser.extract_ticket_sale_type("チケットは先着販売です") == "先着"
    assert parser.extract_ticket_sale_type("抽選受付 / 当落発表あり") == "抽選"
    assert parser.extract_ticket_sale_type("当日券販売あり") == "当日券"
    assert parser.extract_ticket_sale_type("入場無料イベント") == "無料"


def test_clear_live_announcement_classifies_as_event():
    post = XPost(
        id="class-live",
        created_at=datetime(2026, 5, 30, 3, 0, tzinfo=JST),
        text="【Next Live】\n6/15(月)『STARLIGHT LIVE』\n会場：渋谷Milkyway\n開場18:00 / 開演18:30\nチケット：https://t.livepocket.jp/e/live",
    )

    result = PostParser().classify_post(post)

    assert result.classification == PostClassification.EVENT
    assert result.confidence == "high"


def test_goods_announcement_classifies_as_non_event():
    post = XPost(
        id="class-goods",
        created_at=datetime(2026, 5, 30, 3, 0, tzinfo=JST),
        text="新グッズ通販開始！ランダム写真もあります。",
    )

    result = PostParser().classify_post(post)

    assert result.classification == PostClassification.NON_EVENT


def test_music_release_classifies_as_non_event():
    post = XPost(
        id="class-mv",
        created_at=datetime(2026, 5, 30, 3, 0, tzinfo=JST),
        text="新曲MV公開！楽曲配信とサブスクも開始しました。",
    )

    assert PostParser().classify_post(post).classification == PostClassification.NON_EVENT


def test_thank_you_after_live_classifies_as_non_event():
    post = XPost(
        id="class-thanks",
        created_at=datetime(2026, 5, 30, 3, 0, tzinfo=JST),
        text="本日のライブありがとうございました！またお会いしましょう。",
    )

    assert PostParser().classify_post(post).classification == PostClassification.NON_EVENT


def test_vague_image_dependent_reminder_classifies_as_needs_review():
    post = XPost(
        id="class-review",
        created_at=datetime(2026, 5, 30, 3, 0, tzinfo=JST),
        text="本日はこちら！よろしくお願いします！",
    )

    result = PostParser().classify_post(post)

    assert result.classification == PostClassification.NEEDS_REVIEW
    assert result.source_kind == SourceKind.SAME_DAY_REMINDER


def test_lottery_and_general_sale_periods_parse_from_one_post():
    parsed = PostParser().parse_post(
        XPost(
            id="sales001",
            created_at=datetime(2026, 4, 30, 3, 0, tzinfo=JST),
            text=(
                "【ライブ出演情報】\n"
                "5/30(土)『SALES TEST LIVE』\n"
                "会場：渋谷DESEO\n"
                "開場18:00 / 開演18:30\n"
                "抽選受付：5/1 20:00〜5/10 23:59\n"
                "一般販売：5/11 20:00〜5/30 23:59\n"
                "当落発表：5/11 18:00\n"
                "支払期限：5/13 23:59\n"
                "チケット：https://t.livepocket.jp/e/sales-test"
            ),
        )
    )

    assert parsed is not None
    assert [period.sale_type for period in parsed.ticket_sales] == ["抽選", "一般"]
    assert parsed.ticket_sales[0].start_at == datetime(2026, 5, 1, 20, 0, tzinfo=JST)
    assert parsed.ticket_sales[0].deadline_at == datetime(2026, 5, 10, 23, 59, tzinfo=JST)
    assert parsed.ticket_sales[1].start_at == datetime(2026, 5, 11, 20, 0, tzinfo=JST)
    assert parsed.ticket_sales[1].deadline_at == datetime(2026, 5, 30, 23, 59, tzinfo=JST)


def test_general_release_and_first_come_reception_patterns_parse():
    parsed = PostParser().parse_post(
        XPost(
            id="sales-patterns",
            created_at=datetime(2026, 5, 1, 3, 0, tzinfo=JST),
            text=(
                "【ライブ出演情報】\n"
                "5/30(土)『PATTERN LIVE』\n"
                "会場：渋谷DESEO\n"
                "一般発売：5/11 20:00〜5/20 23:59\n"
                "先着受付：5/21 20:00〜5/30 12:00\n"
                "チケット：https://t.livepocket.jp/e/pattern-live"
            ),
        )
    )

    assert parsed is not None
    assert [period.sale_type for period in parsed.ticket_sales] == ["一般", "先着"]
    assert parsed.ticket_sales[0].deadline_at == datetime(2026, 5, 20, 23, 59, tzinfo=JST)
    assert parsed.ticket_sales[1].deadline_at == datetime(2026, 5, 30, 12, 0, tzinfo=JST)


def test_global_first_come_deadline_labels_do_not_create_extra_periods():
    parsed = PostParser().parse_post(
        XPost(
            id="global-deadline-labels",
            created_at=datetime(2026, 5, 22, 3, 0, tzinfo=JST),
            text=(
                "【ライブ出演情報】\n"
                "5/29(金)『GLOBAL LABEL LIVE』\n"
                "会場：渋谷DESEO\n"
                "一般：2,800円\n"
                "優先チケット：4,000円\n"
                "販売方式：先着\n"
                "受付開始：5/23 20:00\n"
                "受付締切：5/29 12:00\n"
                "チケット：https://t.livepocket.jp/e/global-label-live"
            ),
        )
    )

    assert parsed is not None
    assert len(parsed.ticket_sales) == 2
    assert {period.ticket_tier for period in parsed.ticket_sales} == {"一般", "優先"}
    assert all(period.start_at == datetime(2026, 5, 23, 20, 0, tzinfo=JST) for period in parsed.ticket_sales)
    assert all(period.deadline_at == datetime(2026, 5, 29, 12, 0, tzinfo=JST) for period in parsed.ticket_sales)


def test_same_day_ticket_period_extracts_price_and_start():
    parsed = PostParser().parse_post(
        XPost(
            id="same-day-period",
            created_at=datetime(2026, 5, 30, 1, 0, tzinfo=JST),
            text=(
                "【本日】\n"
                "本日5/30(土)『SAME DAY LIVE』出演です。\n"
                "会場：渋谷DESEO\n"
                "当日券販売：5/30 10:00〜\n"
                "当日券：3,000円\n"
                "チケット：https://t.livepocket.jp/e/same-day-live"
            ),
        )
    )

    assert parsed is not None
    same_day_periods = [period for period in parsed.ticket_sales if period.sale_type == "当日券"]
    assert len(same_day_periods) == 1
    assert same_day_periods[0].start_at == datetime(2026, 5, 30, 10, 0, tzinfo=JST)
    assert same_day_periods[0].price == 3000


def test_multiple_ticket_tiers_extract_from_price_lines():
    parsed = PostParser().parse_post(
        XPost(
            id="multi-tier",
            created_at=datetime(2026, 5, 1, 3, 0, tzinfo=JST),
            text=(
                "【ライブ出演情報】\n"
                "5/30(土)『MULTI TIER LIVE』\n"
                "会場：渋谷DESEO\n"
                "抽選申込：5/1 20:00〜5/10 23:59\n"
                "一般チケット 2,500円\n"
                "VIP 8,000円\n"
                "SS 8,000円\n"
                "前方 5,000円\n"
                "カメラ 10,000円\n"
                "チケット：https://t.livepocket.jp/e/multi-tier"
            ),
        )
    )

    assert parsed is not None
    tiers = {period.ticket_tier: period.price for period in parsed.ticket_sales}
    assert tiers["一般"] == 2500
    assert tiers["VIP"] == 8000
    assert tiers["SS"] == 8000
    assert tiers["前方"] == 5000
    assert tiers["カメラ"] == 10000


def test_real_sample_fixture_evaluation_helper_passes(mock_posts_dir):
    results = evaluate_real_samples(mock_posts_dir / "real_samples")

    assert results
    assert all(result.passed for result in results)


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
    assert parsed.ticket_status == "same_day"
    assert parsed.myojou_performance_time == "19:10-19:35"


def test_sold_out_classification(mock_posts):
    parsed = PostParser().parse_post(mock_posts["180005"])

    assert parsed is not None
    assert parsed.source_kind == SourceKind.SOLD_OUT
    assert parsed.ticket_status == "sold_out"


def test_ended_ticket_status_parsing():
    parsed = PostParser().parse_post(
        XPost(
            id="ended001",
            created_at=datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc),
            text="【チケット販売終了】\n6/15(月)『STARLIGHT LIVE vol.7』\nチケット販売終了しました。",
        )
    )

    assert parsed is not None
    assert parsed.ticket_status == "ended"


def test_correction_classification_and_time_parsing(mock_posts):
    parsed = PostParser().parse_post(mock_posts["180006"])

    assert parsed is not None
    assert parsed.source_kind == SourceKind.CORRECTION
    assert parsed.open_time == "18:15"
    assert parsed.start_time == "18:45"
