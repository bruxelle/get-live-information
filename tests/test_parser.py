from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from myojou_sync.models import SourceKind
from myojou_sync.models import PostClassification
from myojou_sync.models import XPost
from myojou_sync.parser import PostParser
from myojou_sync.real_samples import evaluate_real_samples


JST = timezone(timedelta(hours=9))


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
