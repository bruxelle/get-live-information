from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from myojou_sync.models import SourceKind
from myojou_sync.models import CanonicalEvent
from myojou_sync.models import PostClassification
from myojou_sync.models import TicketSalePeriod
from myojou_sync.models import XPost
from myojou_sync.parser import PostParser
from myojou_sync.pipeline import SyncPipeline
from myojou_sync.public_output import application_summary, ticket_summary
from myojou_sync.readiness import public_readiness
from myojou_sync.real_samples import evaluate_real_samples
from myojou_sync.sample_capture import needs_review_reasons
from myojou_sync.state import SQLiteStateStore
from myojou_sync.x_client import MockXClient


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


def test_multi_day_event_dates_parse_from_comma_list():
    parsed = PostParser().parse_post(
        XPost(
            id="multi-date-comma",
            created_at=datetime(2026, 5, 10, 12, 0, tzinfo=JST),
            text=(
                "【ライブ出演情報】\n"
                "SPARK 2026 in YAMANAKAKO\n"
                "⟣date：9/21, 9/22, 9/23\n"
                "⟣place : 山中湖交流プラザきらら\n"
                "⟣open/start：9:00/10:00"
            ),
        )
    )

    assert parsed is not None
    assert parsed.event_date == date(2026, 9, 21)
    assert parsed.event_dates == [date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)]


def test_multi_day_event_dates_parse_from_day_only_suffixes():
    parsed = PostParser().parse_post(
        XPost(
            id="multi-date-suffix",
            created_at=datetime(2026, 5, 10, 12, 0, tzinfo=JST),
            text=(
                "【ライブ出演情報】\n"
                "SPARK 2026 in YAMANAKAKO\n"
                "⟣date：9/21（月祝）、22（火祝）、23（水祝）\n"
                "⟣place : 山中湖交流プラザきらら\n"
                "⟣open/start：9:00/10:00"
            ),
        )
    )

    assert parsed is not None
    assert parsed.event_dates == [date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)]


def test_multi_day_event_dates_parse_from_range():
    parsed = PostParser().parse_post(
        XPost(
            id="multi-date-range",
            created_at=datetime(2026, 5, 10, 12, 0, tzinfo=JST),
            text=(
                "【ライブ出演情報】\n"
                "SPARK 2026 in YAMANAKAKO\n"
                "⟣date：9/21-9/23\n"
                "⟣place : 山中湖交流プラザきらら\n"
                "⟣open/start：9:00/10:00"
            ),
        )
    )

    assert parsed is not None
    assert parsed.event_dates == [date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)]


def test_multi_day_event_dates_do_not_use_ticket_sale_ranges():
    parsed = PostParser().parse_post(
        XPost(
            id="multi-date-ticket-window",
            created_at=datetime(2026, 4, 9, 12, 0, tzinfo=JST),
            text=(
                "【ライブ出演情報】\n"
                "IDOL SUMMER JUNGLE GOLDEN\n"
                "⟣date：5/2（土）、5/3（日）\n"
                "⟣place : お台場R地区\n"
                "⟣open/start：9:00/10:00\n"
                "【VIPチケット先行抽選】\n"
                "3/26(木)20:00〜4/13(月)23:59"
            ),
        )
    )

    assert parsed is not None
    assert parsed.event_dates == [date(2026, 5, 2), date(2026, 5, 3)]
    assert date(2026, 3, 26) not in parsed.event_dates
    assert date(2026, 4, 13) not in parsed.event_dates


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


def test_goods_number_kuji_announcement_with_live_context_is_non_event():
    text = (
        "✮••┈┈┈┈••✮••┈┈┈┈••✮\n"
        "     グッズ&ナンバーくじ公開\n"
        "        myojou oneman live\n"
        "                       明夏\n"
        "✮••┈┈┈┈••✮••┈┈┈┈••✮\n\n"
        "⟣明夏Tシャツ ¥2,500\n"
        "⟣myojouユニフォーム（全2種） ¥5,000\n"
        "⟣明夏限定ナンバーくじ ¥1,000/回\n\n"
        "⟣date：2026/6/8(月)\n"
        "⟣place : Veats Shibuya\n"
        "⟣open/start：18:15/19:00\n"
        "⟣price：一般¥2,000（完売間近…！）\n"
        "🔗 https://t-dv.com/myojou_260608\n"
    )
    post = XPost(id="2062856267094528446", created_at=datetime(2026, 6, 5, 20, 17, tzinfo=JST), text=text)
    parser = PostParser()

    classification = parser.classify_post(post)

    assert classification.classification == PostClassification.NON_EVENT
    assert "goods/number lottery" in classification.reason
    assert parser.parse_post(post, classification=classification) is None


def test_limited_tshirt_announcement_with_live_context_is_non_event():
    text = (
        "✮••┈┈┈┈••✮••┈┈┈┈••✮\n"
        "       myojou Summer Vol.03\n"
        "            限定Tシャツ公開\n"
        "✮••┈┈┈┈••✮••┈┈┈┈••✮\n\n"
        "⟣date：7/19（日）\n"
        "⟣place : 渋谷音楽堂\n"
        "⟣open/start：17:30/18:00\n"
        "⟣price：優先¥6,000（限定Tシャツ付き）/一般¥0（各+1D）\n\n"
        "【一般販売】\n"
        "6/21（日）22:00-7/18（土）23:59\n"
        "🔗 https://t-dv.com/myojou_0719\n"
    )
    post = XPost(id="2071494887225323698", created_at=datetime(2026, 6, 29, 23, 31, tzinfo=JST), text=text)
    parser = PostParser()

    classification = parser.classify_post(post)

    assert classification.classification == PostClassification.NON_EVENT
    assert "goods/number lottery" in classification.reason
    assert parser.parse_post(post, classification=classification) is None


def test_live_post_with_incidental_goods_mention_is_still_event():
    post = XPost(
        id="live-with-goods-side-note",
        created_at=datetime(2026, 5, 30, 3, 0, tzinfo=JST),
        text=(
            "【Next Live】\n"
            "6/15(月)『超NATSUZOME 2026』\n"
            "会場：幕張海浜公園Gブロック特設会場\n"
            "開場9:00 / 開演10:00\n"
            "🎙18:30-18:45\n"
            "※ VIP特典：前方VIPエリア入場+VIP限定Tシャツ及びグッズプレゼント\n"
            "チケット：https://l-tike.com/live"
        ),
    )

    result = PostParser().classify_post(post)

    assert result.classification == PostClassification.EVENT


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


def test_needs_review_reasons_include_real_world_extraction_gaps():
    event = CanonicalEvent(
        event_date=date(2026, 6, 15),
        needs_review=True,
        classification_reason="本日/明日 reminder appears image-dependent",
    )

    reasons = needs_review_reasons(event)

    assert "missing event_name" in reasons
    assert "missing venue" in reasons
    assert "missing ticket deadline" in reasons
    assert "likely image-dependent" in reasons


def test_free_events_do_not_report_missing_ticket_deadline_reason():
    event = CanonicalEvent(
        event_name="FREE LIVE",
        venue="渋谷Milkyway",
        general_ticket_price=0,
        ticket_sale_type="無料",
    )

    reasons = needs_review_reasons(event)

    assert "missing ticket deadline" not in reasons


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


def test_generic_sale_period_full_range_with_times_parse():
    parsed = PostParser().parse_post(
        XPost(
            id="generic-sale-period-full-range",
            created_at=datetime(2026, 6, 20, 3, 0, tzinfo=JST),
            text=(
                "✮••┈┈┈••✮\n"
                "蒼夏序章\n"
                "✮••┈┈┈••✮\n\n"
                "⟣date：7/6（月）\n"
                "⟣place : 池袋西口公園野外劇場 グローバルリング シアター\n"
                "⟣open/start：TBA/TBA\n"
                "⟣price：前方¥4,500/一般¥1,000（各+1D）/後方観覧無料\n\n"
                "【販売期間】\n"
                "6/9(火)22:00〜7/5(火)23:59\n"
                "🔗 https://t-dv.com/souka"
            ),
        )
    )

    assert parsed is not None
    dated_periods = [period for period in parsed.ticket_sales if period.deadline_at]
    assert dated_periods
    assert all(period.start_at == datetime(2026, 6, 9, 22, 0, tzinfo=JST) for period in dated_periods)
    assert all(period.deadline_at == datetime(2026, 7, 5, 23, 59, tzinfo=JST) for period in dated_periods)


def test_generic_sale_period_date_only_start_keeps_start_empty_and_parses_deadline():
    parsed = PostParser().parse_post(
        XPost(
            id="generic-sale-period-date-only-start",
            created_at=datetime(2026, 7, 10, 3, 0, tzinfo=JST),
            text=(
                "✮••┈┈┈••✮\n"
                "ッスッゴイライブ\n"
                "✮••┈┈┈••✮\n\n"
                "⟣date：7/18（土）\n"
                "⟣place : 品川インターシティホール\n"
                "⟣open/start：8:30/9:00\n"
                "⟣price：前方¥8,000/一般 ¥3,500（各+1D）\n\n"
                "【販売期間】\n"
                "7/10（金）-7/17（金）23:59\n"
                "🔗 https://t-dv.com/ssuggoi"
            ),
        )
    )

    assert parsed is not None
    dated_periods = [period for period in parsed.ticket_sales if period.deadline_at]
    assert dated_periods
    assert all(period.start_at is None for period in dated_periods)
    assert all(period.deadline_at == datetime(2026, 7, 17, 23, 59, tzinfo=JST) for period in dated_periods)


def test_first_come_end_only_deadline_with_holiday_weekday_parse():
    parsed = PostParser().parse_post(
        XPost(
            id="first-come-end-only-deadline",
            created_at=datetime(2026, 7, 13, 3, 0, tzinfo=JST),
            text=(
                "✮••┈┈┈••✮\n"
                "IDOL STORM\n"
                "✮••┈┈┈••✮\n\n"
                "⟣date：7/20（月祝）\n"
                "⟣place : Spotify O-WEST\n"
                "⟣open/start：TBA/TBA\n"
                "⟣price：前方¥7,000/一般¥2,500\n\n"
                "【先着販売】\n"
                "-7/20（月祝）21:59\n"
                "🔗 https://tiget.net/events/idol-storm"
            ),
        )
    )

    assert parsed is not None
    dated_periods = [period for period in parsed.ticket_sales if period.deadline_at]
    assert dated_periods
    assert {period.sale_type for period in dated_periods} == {"先着"}
    assert all(period.start_at is None for period in dated_periods)
    assert all(period.deadline_at == datetime(2026, 7, 20, 21, 59, tzinfo=JST) for period in dated_periods)


def test_explicit_spaced_weekday_ranges_preserve_start_and_deadline_times():
    parsed = PostParser().parse_post(
        XPost(
            id="explicit-spaced-weekday-ranges",
            created_at=datetime(2026, 6, 18, 3, 0, tzinfo=JST),
            text=(
                "✮••┈┈┈••✮\n"
                "IDOL STORM\n"
                "✮••┈┈┈••✮\n\n"
                "⟣date：8/15（土）\n"
                "⟣place : Music restaurant APEXIA\n"
                "⟣open/start：10:30/10:50\n"
                "⟣price：前方 ¥8,000 / 一般 ¥2,500（各＋1D）\n\n"
                "【先行抽選】\n"
                "6/18 (木) 21:00 - 7/7 (火) 23:59\n"
                "【先着販売】\n"
                "7/8 (水) 21:00 - 8/15 (土) 16:00\n"
                "🔗 https://ticketdive.com/event/idolstorm_0815"
            ),
        )
    )

    assert parsed is not None
    lottery_periods = [period for period in parsed.ticket_sales if period.sale_type == "抽選"]
    first_come_periods = [period for period in parsed.ticket_sales if period.sale_type == "先着"]
    assert lottery_periods
    assert first_come_periods
    assert all(period.start_at == datetime(2026, 6, 18, 21, 0, tzinfo=JST) for period in lottery_periods)
    assert all(period.deadline_at == datetime(2026, 7, 7, 23, 59, tzinfo=JST) for period in lottery_periods)
    assert all(period.start_at == datetime(2026, 7, 8, 21, 0, tzinfo=JST) for period in first_come_periods)
    assert all(period.deadline_at == datetime(2026, 8, 15, 16, 0, tzinfo=JST) for period in first_come_periods)


def test_open_ended_general_sales_are_preserved_with_lottery_period():
    parsed = PostParser().parse_post(
        XPost(
            id="2021543846337818936",
            created_at=datetime(2026, 2, 1, 3, 0, tzinfo=JST),
            raw={"url": "https://x.com/info_myojou/status/2021543846337818936"},
            text=(
                "✮••┈┈┈┈••✮••┈┈┈┈••✮\n"
                "           Appare! ひなまつり\n"
                "✮••┈┈┈┈••✮••┈┈┈┈••✮\n\n"
                "🎙9:15-9:30\n"
                "📸9:40-10:40\n\n"
                "⟣date：2026年3月3日（火）\n"
                "⟣place : 有楽町ヒューリックホール\n"
                "⟣open/start：8:30/9:00（予定）\n"
                "⟣price：ひなまつりチケット¥8,000/一般チケット：¥3,500（各+1D）\n\n"
                "<ひなまつりチケット>\n"
                "抽選受付：2/5(木)20:00〜2/23(月祝)23:59\n"
                "一般発売：2/24(火)20:00〜\n"
                "<一般チケット>\n"
                "一般発売：2/5(木)20:00〜\n"
                "🔗 https://t-dv.com/appare-hinamatsuri"
            ),
        )
    )

    assert parsed is not None
    lottery_periods = [period for period in parsed.ticket_sales if period.sale_type == "抽選"]
    general_periods = [period for period in parsed.ticket_sales if period.sale_type == "一般"]
    assert lottery_periods
    assert len(general_periods) == 2
    assert all(period.start_at == datetime(2026, 2, 5, 20, 0, tzinfo=JST) for period in lottery_periods)
    assert all(period.deadline_at == datetime(2026, 2, 23, 23, 59, tzinfo=JST) for period in lottery_periods)
    assert {period.start_at for period in general_periods} == {
        datetime(2026, 2, 5, 20, 0, tzinfo=JST),
        datetime(2026, 2, 24, 20, 0, tzinfo=JST),
    }
    assert all(period.deadline_at is None for period in general_periods)


def test_ticket_sale_years_are_anchored_to_event_date_not_post_date():
    parsed = PostParser().parse_post(
        XPost(
            id="sale-year-anchor",
            created_at=datetime(2026, 7, 1, 3, 0, tzinfo=JST),
            text=(
                "LEADING SPRING\n"
                "日付：2026/3/21(土)\n"
                "会場：渋谷近未来会館\n"
                "料金：前方 8,000円 / 一般 3,000円\n"
                "【先行抽選】\n"
                "2/16(月) 21:00〜3/9(月) 23:59\n"
                "【一般販売】\n"
                "3/10(火) 21:00〜\n"
                "https://ticketdive.com/event/leading-spring"
            ),
        )
    )

    assert parsed is not None
    lottery_periods = [period for period in parsed.ticket_sales if period.sale_type == "抽選"]
    general_periods = [period for period in parsed.ticket_sales if period.sale_type == "一般"]
    assert lottery_periods
    assert general_periods
    assert all(period.start_at == datetime(2026, 2, 16, 21, 0, tzinfo=JST) for period in lottery_periods)
    assert all(period.deadline_at == datetime(2026, 3, 9, 23, 59, tzinfo=JST) for period in lottery_periods)
    assert all(period.start_at == datetime(2026, 3, 10, 21, 0, tzinfo=JST) for period in general_periods)
    assert {period.start_at.year for period in parsed.ticket_sales if period.start_at} == {2026}
    assert {period.deadline_at.year for period in parsed.ticket_sales if period.deadline_at} == {2026}


def test_multiple_sale_phases_before_summer_event_use_same_event_year():
    parsed = PostParser().parse_post(
        XPost(
            id="2073014604645703697",
            created_at=datetime(2026, 7, 1, 3, 0, tzinfo=JST),
            text=(
                "1YOANI LIVE STATION\n"
                "日付：2026/7/22(水)\n"
                "会場：YOANI Live Station\n"
                "料金：前方 6,000円 / 一般 2,500円\n"
                "【先行抽選】\n"
                "4/22(水)21:00-5/22(金)23:59\n"
                "【一般販売】\n"
                "5/23(土)21:00〜7/21(火)23:59\n"
                "https://t-dv.com/1yoani-live-station"
            ),
        )
    )

    assert parsed is not None
    lottery_periods = [period for period in parsed.ticket_sales if period.sale_type == "抽選"]
    general_periods = [period for period in parsed.ticket_sales if period.sale_type == "一般"]
    assert lottery_periods
    assert general_periods
    assert all(period.start_at == datetime(2026, 4, 22, 21, 0, tzinfo=JST) for period in lottery_periods)
    assert all(period.deadline_at == datetime(2026, 5, 22, 23, 59, tzinfo=JST) for period in lottery_periods)
    assert all(period.start_at == datetime(2026, 5, 23, 21, 0, tzinfo=JST) for period in general_periods)
    assert all(period.deadline_at == datetime(2026, 7, 21, 23, 59, tzinfo=JST) for period in general_periods)


def test_december_to_january_sale_range_uses_previous_year_for_early_event():
    parsed = PostParser().parse_post(
        XPost(
            id="winter-year-crossing-sale",
            created_at=datetime(2026, 6, 1, 3, 0, tzinfo=JST),
            text=(
                "NEW YEAR LIVE\n"
                "日付：2026/1/15(木)\n"
                "会場：Spotify O-nest\n"
                "料金：一般 3,000円\n"
                "【先行抽選】\n"
                "12/20(土) 20:00〜1/10(土) 23:59\n"
                "https://t-dv.com/new-year-live"
            ),
        )
    )

    assert parsed is not None
    dated_periods = [period for period in parsed.ticket_sales if period.deadline_at]
    assert dated_periods
    assert all(period.start_at == datetime(2025, 12, 20, 20, 0, tzinfo=JST) for period in dated_periods)
    assert all(period.deadline_at == datetime(2026, 1, 10, 23, 59, tzinfo=JST) for period in dated_periods)


def test_multi_day_event_anchors_ticket_deadline_to_last_event_date():
    parsed = PostParser().parse_post(
        XPost(
            id="multi-day-sale-anchor",
            created_at=datetime(2026, 7, 4, 21, 0, tzinfo=JST),
            text=(
                "超NATSUZOME 2026 Day2\n"
                "⟣date：7/4(土)、7/5(日)\n"
                "⟣place : 幕張海浜公園Gブロック特設会場\n"
                "⟣price：1Day前売り¥8,000/2Days通し券¥14,000\n"
                "【一般販売】\n"
                "5/22（金）20:30-7/5（日）5:59\n"
                "https://ticketdive.com/event/natsuzome"
            ),
        )
    )

    assert parsed is not None
    assert parsed.event_date == date(2026, 7, 4)
    assert parsed.event_dates == [date(2026, 7, 4), date(2026, 7, 5)]
    dated_periods = [period for period in parsed.ticket_sales if period.deadline_at]
    assert dated_periods
    assert all(period.start_at == datetime(2026, 5, 22, 20, 30, tzinfo=JST) for period in dated_periods)
    assert all(period.deadline_at == datetime(2026, 7, 5, 5, 59, tzinfo=JST) for period in dated_periods)


def test_secondary_first_come_header_preserves_neo_kassen_sale_dates():
    parsed = PostParser().parse_post(
        XPost(
            id="2066430868936380727",
            created_at=datetime(2026, 6, 14, 3, 0, tzinfo=JST),
            text=(
                "NEO JAPONISM主催フェス 「NEO KASSEN2026」\n"
                "date: 8/10（日）\n"
                "place: Spotify O-EAST\n"
                "price：SS¥2,026/一般¥6,500/当日 ¥7,500\n"
                "【二次先行先着】\n"
                "6月15日(月) 17:00 ~ 7月6日(月) 23:59\n"
                "https://ticketdive.com/event/neokassen2026"
            ),
        )
    )

    assert parsed is not None
    dated_periods = [period for period in parsed.ticket_sales if period.deadline_at]
    assert dated_periods
    assert {period.sale_type for period in dated_periods} == {"先着"}
    assert all(period.start_at == datetime(2026, 6, 15, 17, 0, tzinfo=JST) for period in dated_periods)
    assert all(period.deadline_at == datetime(2026, 7, 6, 23, 59, tzinfo=JST) for period in dated_periods)
    assert {(period.ticket_tier, period.price) for period in dated_periods} >= {("SS", 2026), ("一般", 6500)}


def test_general_first_come_header_preserves_neat_meets_premium_dates():
    parsed = PostParser().parse_post(
        XPost(
            id="2042217750677127571",
            created_at=datetime(2026, 4, 6, 3, 0, tzinfo=JST),
            text=(
                "Neat Meets vol.18 -PREMIUM-\n"
                "date：4/25(土)\n"
                "place：Spotify O-WEST\n"
                "price：前方チケット¥8,000/一般チケット¥3,500\n"
                "【一般先着】\n"
                "4/6(月)20:00〜4/24(金)23:59\n"
                "https://t-dv.com/neat18-premium"
            ),
        )
    )

    assert parsed is not None
    dated_periods = [period for period in parsed.ticket_sales if period.deadline_at]
    assert len(dated_periods) == 2
    assert {period.price for period in dated_periods} == {8000, 3500}
    assert all(period.sale_type == "先着" for period in dated_periods)
    assert all(period.start_at == datetime(2026, 4, 6, 20, 0, tzinfo=JST) for period in dated_periods)
    assert all(period.deadline_at == datetime(2026, 4, 24, 23, 59, tzinfo=JST) for period in dated_periods)


def test_selfish_lottery_and_general_first_come_periods_are_preserved():
    parsed = PostParser().parse_post(
        XPost(
            id="2034601219575169118",
            created_at=datetime(2026, 3, 8, 3, 0, tzinfo=JST),
            text=(
                "selfish主催 selfish festival\n"
                "date：3/25(水)\n"
                "place：白金高輪SELENE b2\n"
                "price：前方 ¥6,000 / 一般 ¥2,000\n"
                "【抽選期間】\n"
                "3月9日(月)22:00〜3月13日(金)23:59\n"
                "【一般先着】\n"
                "3月14日(土)22:00〜3月24日(火)23:59\n"
                "https://ticketdive.com/event/selfish"
            ),
        )
    )

    assert parsed is not None
    dated_periods = [period for period in parsed.ticket_sales if period.deadline_at]
    assert len(dated_periods) == 4
    lottery_periods = [period for period in dated_periods if period.sale_type == "抽選"]
    general_periods = [period for period in dated_periods if period.sale_type == "先着"]
    assert len(lottery_periods) == 2
    assert len(general_periods) == 2
    assert all(period.start_at == datetime(2026, 3, 9, 22, 0, tzinfo=JST) for period in lottery_periods)
    assert all(period.deadline_at == datetime(2026, 3, 13, 23, 59, tzinfo=JST) for period in lottery_periods)
    assert all(period.start_at == datetime(2026, 3, 14, 22, 0, tzinfo=JST) for period in general_periods)
    assert all(period.deadline_at == datetime(2026, 3, 24, 23, 59, tzinfo=JST) for period in general_periods)


def test_one_and_only_keeps_lottery_general_and_same_day_ticket_periods():
    parsed = PostParser().parse_post(
        XPost(
            id="one-and-only-sale-phases",
            created_at=datetime(2026, 6, 15, 3, 0, tzinfo=JST),
            text=(
                "ONE AND ONLY 2nd Anniversary day2\n"
                "date：7/16(木)\n"
                "place：Zepp Shinjuku\n"
                "price：前方優先エリア¥11,000/一般¥4,500/女性･学生¥3,500/当日¥5,000\n"
                "【先行（抽選）】\n"
                "6/15(月) 20:30 ~ 6/29(月) 23:59\n"
                "【一般発売】\n"
                "7/4(土) 20:00 ~ 7/15(火) 23:59\n"
                "https://w.pia.jp/t/oneandonly/"
            ),
        )
    )

    assert parsed is not None
    assert len(parsed.ticket_sales) == 5
    lottery_periods = [period for period in parsed.ticket_sales if period.sale_type == "抽選"]
    general_periods = [period for period in parsed.ticket_sales if period.sale_type == "一般"]
    same_day_periods = [period for period in parsed.ticket_sales if period.sale_type == "当日券"]
    assert len(lottery_periods) == 2
    assert len(general_periods) == 2
    assert len(same_day_periods) == 1
    assert all(period.start_at == datetime(2026, 6, 15, 20, 30, tzinfo=JST) for period in lottery_periods)
    assert all(period.deadline_at == datetime(2026, 6, 29, 23, 59, tzinfo=JST) for period in lottery_periods)
    assert all(period.start_at == datetime(2026, 7, 4, 20, 0, tzinfo=JST) for period in general_periods)
    assert all(period.deadline_at == datetime(2026, 7, 15, 23, 59, tzinfo=JST) for period in general_periods)
    assert same_day_periods[0].price == 5000


def test_no_sale_period_text_does_not_fabricate_ticket_deadline():
    parsed = PostParser().parse_post(
        XPost(
            id="no-sale-period",
            created_at=datetime(2026, 7, 10, 3, 0, tzinfo=JST),
            text=(
                "✮••┈┈┈••✮\n"
                "俺フェス！ Vol.2\n"
                "✮••┈┈┈••✮\n\n"
                "⟣date：8/21（金）\n"
                "⟣place : 白金高輪SELENE b2\n"
                "⟣open/start：16:00/16:30\n"
                "⟣price：前方¥5,000/一般¥2,000（各+1D）\n"
                "⟣入場特典：明星カード（サインありチェキ）"
            ),
        )
    )

    assert parsed is not None
    assert parsed.ticket_application_deadline_at is None
    assert all(period.deadline_at is None for period in parsed.ticket_sales)


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


def test_info_myojou_first_fetch_after_benefit_event_is_non_event(mock_posts_dir):
    posts = _real_first_fetch_posts(mock_posts_dir)
    classification = PostParser().classify_post(posts["2064018631219183632"])

    assert classification.classification == PostClassification.NON_EVENT
    assert "benefit-only" in classification.reason
    assert PostParser().parse_post(posts["2064018631219183632"], classification=classification) is None


def test_info_myojou_first_fetch_parses_place_and_open_start_labels(mock_posts_dir):
    posts = _real_first_fetch_posts(mock_posts_dir)
    parsed = PostParser().parse_post(posts["2064321642810294772"])

    assert parsed is not None
    assert parsed.event_name == "A Villa idol festival HOKKAIDO 2026"
    assert parsed.event_date == date(2026, 8, 29)
    assert parsed.venue == "安平町ときわ公園"
    assert parsed.open_time == "09:00"
    assert parsed.start_time == "10:00"
    assert parsed.ticket_url is None


def test_info_myojou_first_fetch_skips_thank_you_photo_post(mock_posts_dir):
    posts = _real_first_fetch_posts(mock_posts_dir)
    classification = PostParser().classify_post(posts["2064336515615121857"])

    assert classification.classification == PostClassification.NON_EVENT
    assert PostParser().parse_post(posts["2064336515615121857"], classification=classification) is None


def test_info_myojou_first_fetch_pipeline_keeps_only_public_live_candidate(tmp_path, mock_posts_dir):
    state = SQLiteStateStore(tmp_path / "state.sqlite")
    pipeline = SyncPipeline(
        fetcher=MockXClient(mock_posts_dir / "real_samples" / "info_myojou_first_fetch.json"),
        state=state,
        parser=PostParser(),
    )

    events, result = pipeline.run_once(max_results=10)

    assert result.fetched_posts == 4
    assert result.parsed_events == 1
    assert result.non_event_skipped == 3
    assert result.created_events == 1
    assert result.updated_events == 0
    assert result.canonical_events == 1
    event = events[0]
    assert event.event_name == "A Villa idol festival HOKKAIDO 2026"
    assert event.venue == "安平町ときわ公園"
    assert event.needs_review is False


def test_note_tweet_audit_lovecall_parses_full_ticket_details(tmp_path, mock_posts_dir):
    posts = _note_tweet_audit_posts(mock_posts_dir, tmp_path)
    post = posts["2063217018032328930"]
    parsed = PostParser().parse_post(post)

    assert post.full_text_source == "note_tweet"
    assert post.api_text is not None
    assert len(post.text) > len(post.api_text)
    assert parsed is not None
    assert parsed.event_name == "ラブコール vol.19"
    assert parsed.event_date == date(2026, 6, 29)
    assert parsed.venue in {"Spotify O-nest", "O-nest"}
    assert parsed.open_time == "19:20"
    assert parsed.start_time == "19:40"
    assert parsed.myojou_performance_time == "19:40-20:05"
    assert parsed.benefit_event_time == "21:00-22:00"
    assert parsed.ticket_url == "https://t-dv.com/lc_vol19"
    assert parsed.priority_ticket_name == "前方"
    assert parsed.priority_ticket_price == 3000
    assert parsed.general_ticket_price == 1000
    assert parsed.same_day_ticket_price == 500
    assert parsed.ticket_application_start_at == datetime(2026, 6, 7, 21, 0, tzinfo=JST)
    assert parsed.ticket_application_deadline_at == datetime(2026, 6, 28, 23, 59, tzinfo=JST)
    assert parsed.ticket_sale_type == "一般"
    assert parsed.notes and "明星カード" in parsed.notes
    assert "各+1D" in parsed.notes
    tiers = {(period.ticket_tier, period.price) for period in parsed.ticket_sales}
    assert ("前方", 3000) in tiers
    assert ("一般", 1000) in tiers


def test_note_tweet_audit_lovecall_public_summaries_and_review_state(tmp_path, mock_posts_dir):
    state = SQLiteStateStore(tmp_path / "note.sqlite")
    pipeline = SyncPipeline(
        fetcher=MockXClient(_note_tweet_audit_path(mock_posts_dir, tmp_path)),
        state=state,
        parser=PostParser(),
    )

    events, result = pipeline.run_once(max_results=100)
    event = next(event for event in events if event.event_name == "ラブコール vol.19")

    assert result.estimated_x_post_read_count == 0
    assert event.needs_review is False
    assert event.ticket_url == "https://t-dv.com/lc_vol19"
    assert ticket_summary(event) == "前方 3,000円 / 一般 1,000円 / 当日各+500円"
    assert application_summary(event) == "一般販売 6/7 21:00〜6/28 23:59"


def test_note_tweet_audit_decorative_title_blocks_parse_event_names(tmp_path, mock_posts_dir):
    posts = _note_tweet_audit_posts(mock_posts_dir, tmp_path)
    tokyo = PostParser().parse_post(posts["2064563144996045102"])
    souka = PostParser().parse_post(posts["2064003608367255700"])

    assert tokyo is not None
    assert tokyo.event_name == "TOKYO GIRLS GIRLS"
    assert souka is not None
    assert souka.event_name == "蒼夏序章"
    assert souka.venue == "池袋西口公園野外劇場 グローバルリング シアター"


def test_note_tweet_audit_live_digest_posts_are_non_events(tmp_path, mock_posts_dir):
    posts = _note_tweet_audit_posts(mock_posts_dir, tmp_path)
    parser = PostParser()

    for post_id in ("2063629163001774232", "2064004974288527729"):
        classification = parser.classify_post(posts[post_id])
        assert classification.classification == PostClassification.NON_EVENT
        assert parser.parse_post(posts[post_id], classification=classification) is None


def test_note_tweet_audit_tiered_free_price_is_not_global_free(tmp_path, mock_posts_dir):
    posts = _note_tweet_audit_posts(mock_posts_dir, tmp_path)
    parsed = PostParser().parse_post(posts["2064003608367255700"])

    assert parsed is not None
    assert parsed.ticket_sale_type != "無料"
    assert parsed.general_ticket_price == 1000
    assert parsed.priority_ticket_name == "前方"
    assert parsed.priority_ticket_price == 4500
    assert any(period.ticket_name == "後方観覧" and period.price == 0 for period in parsed.ticket_sales)
    assert ticket_summary(CanonicalEvent.from_extracted(parsed)) == "一般 1,000円 / 前方 4,500円 / 後方観覧 無料 / 7/5締切"


def test_note_tweet_audit_avilla_named_ticket_tiers_do_not_infer_general_price(tmp_path, mock_posts_dir):
    posts = _note_tweet_audit_posts(mock_posts_dir, tmp_path)
    parsed = PostParser().parse_post(posts["2064321642810294772"])

    assert parsed is not None
    assert parsed.event_name == "A Villa idol festival HOKKAIDO 2026"
    assert parsed.general_ticket_price is None
    assert parsed.priority_ticket_name == "VIPチケット"
    assert parsed.priority_ticket_price == 15000
    assert parsed.ticket_sale_type != "無料"
    assert parsed.ticket_url == "https://l-tike.com/avilla-idol-fes/"
    tier_prices = {period.ticket_name: period.price for period in parsed.ticket_sales}
    assert tier_prices["VIPチケット"] == 15000
    assert tier_prices["Tシャツ付きチケット"] == 6000
    assert tier_prices["無料チケット"] == 0
    assert "要予約" in (parsed.notes or "")
    assert "各+1D" in (parsed.notes or "")
    assert ticket_summary(CanonicalEvent.from_extracted(parsed)) == (
        "VIPチケット 15,000円 / Tシャツ付きチケット 6,000円 / 無料チケット 0円 / 8/20締切"
    )


def test_note_tweet_audit_neat_meets_no_longer_needs_review_when_complete(tmp_path, mock_posts_dir):
    state = SQLiteStateStore(tmp_path / "note-neat.sqlite")
    pipeline = SyncPipeline(
        fetcher=MockXClient(_note_tweet_audit_path(mock_posts_dir, tmp_path)),
        state=state,
        parser=PostParser(),
    )

    events, _ = pipeline.run_once(max_results=100)
    event = next(event for event in events if event.event_name == "Neat Meets vol.19")

    assert event.needs_review is False


def test_note_tweet_audit_meika_alias_posts_merge_into_one_event(tmp_path, mock_posts_dir):
    state = SQLiteStateStore(tmp_path / "note-meika.sqlite")
    pipeline = SyncPipeline(
        fetcher=MockXClient(_note_tweet_audit_path(mock_posts_dir, tmp_path)),
        state=state,
        parser=PostParser(),
    )

    events, result = pipeline.run_once(max_results=100)
    meika_events = [
        event
        for event in events
        if event.event_date == date(2026, 6, 8) and event.venue == "Veats Shibuya" and "明夏" in (event.event_name or "")
    ]

    assert result.non_event_skipped >= 2
    assert len(meika_events) == 1
    event = meika_events[0]
    assert event.event_name == "myojou oneman live 明夏"
    assert event.ticket_status == "sold_out"
    assert event.needs_review is False
    assert {"2063616270218707012", "2063849253471141988"}.issubset(
        set(event.source_post_ids)
    )
    assert "2063865003917410549" not in set(event.source_post_ids)
    assert len(event.all_source_urls) >= 2
    assert event.start_time == "19:00"
    assert any(other.event_name == "ラブコール vol.19" for other in events)
    assert any(other.event_name == "TOKYO GIRLS GIRLS" for other in events)
    assert all(other.event_name != "LIVE DIGEST" for other in events)


def test_backfill_lovecall_day_before_cleans_presenter_wrapped_title(mock_posts_dir):
    posts = _backfill_posts(mock_posts_dir)
    parsed = PostParser().parse_post(posts["2071189243687493679"])

    assert parsed is not None
    assert parsed.event_name == "ラブコール vol.19"
    assert parsed.event_date == date(2026, 6, 29)
    assert parsed.venue == "Spotify O-nest"


def test_backfill_tif_sale_warning_dates_do_not_become_event_dates(mock_posts_dir):
    posts = _backfill_posts(mock_posts_dir)
    parsed = PostParser().parse_post(posts["2066128909650002114"])

    assert parsed is not None
    assert parsed.event_name == "TOKYO IDOL FESTIVAL 2026"
    assert parsed.event_date == date(2026, 7, 31)
    assert parsed.event_dates == [date(2026, 7, 31), date(2026, 8, 1), date(2026, 8, 2)]
    assert date(2026, 6, 14) not in parsed.event_dates


def test_backfill_multi_event_post_keeps_title_from_first_live_block(mock_posts_dir):
    posts = _backfill_posts(mock_posts_dir)
    parsed = PostParser().parse_post(posts["2064611747852587108"])

    assert parsed is not None
    assert parsed.event_name == "アイドル甲子園 in KANDA SQUARE HALL\nsupported by My-th -DAY1"
    assert parsed.venue == "KANDA SQUARE HALL"
    assert parsed.ticket_url == "https://user.my-th.jp/tickets/event/aikou_0613"


def test_backfill_greeting_and_notice_only_posts_are_non_events(mock_posts_dir):
    posts = _backfill_posts(mock_posts_dir)
    parser = PostParser()

    for post_id in ("2070831050516025469", "2070148626668720156", "2050065563360063888"):
        classification = parser.classify_post(posts[post_id])
        assert classification.classification == PostClassification.NON_EVENT
        assert parser.parse_post(posts[post_id], classification=classification) is None


def test_note_tweet_audit_avilla_pipeline_keeps_review_false(tmp_path, mock_posts_dir):
    state = SQLiteStateStore(tmp_path / "note-avilla.sqlite")
    pipeline = SyncPipeline(
        fetcher=MockXClient(_note_tweet_audit_path(mock_posts_dir, tmp_path)),
        state=state,
        parser=PostParser(),
    )

    events, _ = pipeline.run_once(max_results=100)
    event = next(event for event in events if event.event_name == "A Villa idol festival HOKKAIDO 2026")

    assert event.needs_review is False
    assert event.general_ticket_price is None
    assert ticket_summary(event) == "VIPチケット 15,000円 / Tシャツ付きチケット 6,000円 / 無料チケット 0円 / 8/20締切"


def test_sold_out_event_does_not_report_missing_ticket_deadline_reason(tmp_path, mock_posts_dir):
    posts = _note_tweet_audit_posts(mock_posts_dir, tmp_path)
    parsed = PostParser().parse_post(posts["2063616270218707012"])

    assert parsed is not None
    assert parsed.ticket_status == "sold_out"
    reasons = needs_review_reasons(CanonicalEvent.from_extracted(parsed))
    assert "missing ticket deadline" not in reasons


def test_streaming_urls_are_not_ticket_urls():
    parsed = PostParser().parse_post(
        XPost(
            id="nico-url",
            created_at=datetime(2026, 6, 6, 11, 10, tzinfo=JST),
            text=(
                "【ライブ配信】\n"
                "6/29(月)「配信チェック」\n"
                "会場：Spotify O-nest\n"
                "開場19:20 / 開演19:40\n"
                "配信：https://t.co/nico"
            ),
            raw={
                "id": "nico-url",
                "text": "配信：https://t.co/nico",
                "entities": {
                    "urls": [
                        {
                            "url": "https://t.co/nico",
                            "expanded_url": "https://sp.ch.nicovideo.jp/tokyoidolchannel",
                            "display_url": "sp.ch.nicovideo.jp/tokyoidolchannel",
                        }
                    ]
                },
            },
        )
    )

    assert parsed is not None
    assert parsed.ticket_url is None


def test_photo_and_video_urls_are_not_ticket_urls():
    parser = PostParser()
    text = "6/29(月)「PHOTO URL LIVE」\n会場：Spotify O-nest\n開演19:40\nhttps://t.co/photo"

    assert (
        parser.extract_ticket_url(
            text,
            {
                "entities": {
                    "urls": [
                        {
                            "url": "https://t.co/photo",
                            "expanded_url": "https://x.com/info_myojou/status/1/photo/1",
                            "display_url": "pic.x.com/photo",
                            "media_key": "3_photo",
                        }
                    ]
                }
            },
        )
        is None
    )
    assert (
        parser.extract_ticket_url(
            text,
            {
                "entities": {
                    "urls": [
                        {
                            "url": "https://t.co/video",
                            "expanded_url": "https://x.com/info_myojou/status/1/video/1",
                            "display_url": "x.com/info_myojou/status/1/video/1",
                        }
                    ]
                }
            },
        )
        is None
    )


def _real_first_fetch_posts(mock_posts_dir: Path):
    client = MockXClient(mock_posts_dir / "real_samples" / "info_myojou_first_fetch.json")
    return {post.id: post for post in client.fetch_recent_posts(max_results=10)}


def _backfill_posts(mock_posts_dir: Path):
    client = MockXClient(mock_posts_dir / "real_samples" / "info_myojou_backfill_500.json")
    return {post.id: post for post in client.fetch_recent_posts(max_results=500)}


def _note_tweet_audit_posts(mock_posts_dir: Path, tmp_path: Path):
    client = MockXClient(_note_tweet_audit_path(mock_posts_dir, tmp_path))
    return {post.id: post for post in client.fetch_recent_posts(max_results=100)}


def _note_tweet_audit_path(mock_posts_dir: Path, tmp_path: Path) -> Path:
    path = mock_posts_dir / "real_samples" / "info_myojou_note_tweet_audit_20.json"
    if path.exists():
        return path
    fallback = tmp_path / "info_myojou_note_tweet_audit_20.json"
    fallback.write_text(json.dumps(_lovecall_note_tweet_fixture(), ensure_ascii=False), encoding="utf-8")
    return fallback


def _lovecall_note_tweet_fixture() -> dict:
    short_text = (
        "✮••┈┈┈┈┈┈┈••✮••┈┈┈┈┈┈┈••✮\n"
        "THE ENCORE presents\n"
        "「ラブコール vol.19」\n"
        "✮••┈┈┈┈┈┈┈••✮••┈┈┈┈┈┈┈••✮\n\n"
        "🎙19:40-20:05\n"
        "📸21:00-22:00\n\n"
        "⟣date：6/29（月）\n"
        "⟣place O-nest\n"
        "⟣open/start：19:20/19:40 https://t.co/ke1am7UQ2Q"
    )
    full_text = (
        "✮••┈┈┈┈┈┈┈••✮••┈┈┈┈┈┈┈••✮\n"
        "THE ENCORE presents\n"
        "「ラブコール vol.19」\n"
        "✮••┈┈┈┈┈┈┈••✮••┈┈┈┈┈┈┈••✮\n\n"
        "🎙19:40-20:05\n"
        "📸21:00-22:00\n\n"
        "⟣date：6/29（月）\n"
        "⟣place O-nest\n"
        "⟣open/start：19:20/19:40\n"
        "⟣price：前方¥3,000/一般¥1,000/当日各+¥500（各+1D）\n"
        "⟣入場特典：明星カード（サインありチェキ）\n\n"
        "【一般販売】\n"
        "6/7（日）21:00-6/28（日）23:59\n"
        "🔗 https://t.co/WCZ5iMP2uj\n\n"
        "#myojou"
    )
    tokyo_text = (
        "✮••┈┈┈┈┈••✮••┈┈┈┈┈••✮\n"
        "TOKYO GIRLS GIRLS\n"
        "✮••┈┈┈┈┈••✮••┈┈┈┈┈••✮\n\n"
        "🎙14:25-14:45\n"
        "📸14:55-16:05 E\n\n"
        "⟣date：6/16（火）\n"
        "⟣place : Zepp Shinjuku / KABUKICHO TOWER STAGE / WALLY\n"
        "⟣open/start：11:40/12:00\n"
        "⟣price：前方¥10,000/通常¥4,000円 当日+¥1,000（各＋1D）\n\n"
        "【先着販売】\n"
        "5/18(月) 20:00-\n"
        "🔗 https://t.co/G2JK1vvyyC\n\n"
        "#myojou"
    )
    souka_text = (
        "✮••┈┈┈••✮••┈┈┈••✮\n"
        "蒼夏序章\n"
        "✮••┈┈┈••✮••┈┈┈••✮\n\n"
        "⟣date：7/6（月）\n"
        "⟣place : 池袋西口公園野外劇場 グローバルリング シアター\n"
        "⟣open/start：TBA/TBA\n"
        "⟣price： 前方¥4,500/一般¥1,000 （各+1D）/後方観覧無料\n"
        "🔗 https://t.co/souka"
    )
    neat_text = (
        "✮••┈┈┈┈┈••✮••┈┈┈┈┈••✮\n"
        "なみだ色の消しごむ presents\n"
        "『Neat Meets vol.19』\n"
        "✮••┈┈┈┈┈••✮••┈┈┈┈┈••✮\n\n"
        "🎙19:30-19:55\n"
        "📸終演後物販\n\n"
        "⟣date：6/13（土）\n"
        "⟣place : 白金高輪SELENE b2\n"
        "⟣open/start：10:00/10:30\n"
        "⟣price：前方¥5,000/一般¥2,500（各+1D代）\n\n"
        "【一般販売期間】\n"
        "5/31（日）20:00-6/12（金）23:59\n"
        "🔗 https://t.co/neat"
    )
    soldout_text = (
        "✮••┈┈┈┈••✮••┈┈┈┈••✮\n"
        "SOLD OUT\n"
        "myojou oneman live\n"
        "明夏\n"
        "✮••┈┈┈┈••✮••┈┈┈┈••✮\n\n"
        "⟣date：2026/6/8(月)\n"
        "⟣place : Veats Shibuya\n"
        "⟣open/start：18:00/19:00\n"
        "⟣price：SOLD OUT"
    )
    live_digest_text = "✮••┈┈┈••✮\nLIVE DIGEST\nmyojou oneman live 明夏\n✮••┈┈┈••✮ https://t.co/digest"
    avilla_text = (
        "✮••┈┈┈┈┈┈┈••✮••┈┈┈┈┈┈┈••✮\n"
        "A Villa idol festival HOKKAIDO 2026\n"
        "✮••┈┈┈┈┈┈┈••✮••┈┈┈┈┈┈┈••✮\n\n"
        "⟣date：8/29（土）\n"
        "⟣place : 安平町ときわ公園\n"
        "⟣open/start：9:00/10:00（予定）\n"
        "⟣price：VIPチケット ¥15,000（VIPエリア&Tシャツ付き）/Tシャツ付きチケット ¥6,000/無料チケット¥0 ※要予約（各+1D）\n"
        "⟣入場特典 : 明星カード1枚(サインありチェキ)\n\n"
        "【販売期間】\n"
        "6/9（火）20:00-8/20（木）23:59\n"
        "ローチケ：https://t.co/avilla-l\n"
        "無料チケット※要予約：https://t.co/avilla-free\n\n"
        "#myojou"
    )
    return {
        "data": [
            {
                "id": "2063217018032328930",
                "text": short_text,
                "created_at": "2026-06-06T11:10:44+00:00",
                "url": "https://x.com/info_myojou/status/2063217018032328930",
                "entities": {
                    "urls": [
                        {
                            "url": "https://t.co/ke1am7UQ2Q",
                            "expanded_url": "https://x.com/info_myojou/status/2063217018032328930/photo/1",
                            "display_url": "pic.x.com/ke1am7UQ2Q",
                            "media_key": "3_2063217011564703744",
                        }
                    ]
                },
                "attachments": {"media_keys": ["3_2063217011564703744"]},
                "media": [{"media_key": "3_2063217011564703744", "type": "photo"}],
                "note_tweet": {
                    "text": full_text,
                    "entities": {
                        "urls": [
                            {
                                "url": "https://t.co/WCZ5iMP2uj",
                                "expanded_url": "https://t-dv.com/lc_vol19",
                                "display_url": "t-dv.com/lc_vol19",
                            }
                        ]
                    },
                },
            }
            ,
            {
                "id": "2064563144996045102",
                "text": tokyo_text,
                "created_at": "2026-06-10T04:19:46+00:00",
                "url": "https://x.com/info_myojou/status/2064563144996045102",
                "note_tweet": {
                    "text": tokyo_text,
                    "entities": {
                        "urls": [
                            {
                                "url": "https://t.co/G2JK1vvyyC",
                                "expanded_url": "https://ticketdive.com/event/tokyo-girls-girls",
                                "display_url": "ticketdive.com/event/tokyo…",
                            }
                        ]
                    },
                },
            },
            {
                "id": "2064003608367255700",
                "text": souka_text,
                "created_at": "2026-06-08T15:16:22+00:00",
                "url": "https://x.com/info_myojou/status/2064003608367255700",
                "entities": {
                    "urls": [
                        {
                            "url": "https://t.co/souka",
                            "expanded_url": "https://x.com/info_myojou/status/2064003608367255700/photo/1",
                            "display_url": "pic.x.com/souka",
                            "media_key": "3_souka",
                        }
                    ]
                },
            },
            {
                "id": "2063217194763452547",
                "text": neat_text,
                "created_at": "2026-06-06T11:11:26+00:00",
                "url": "https://x.com/info_myojou/status/2063217194763452547",
                "note_tweet": {
                    "text": neat_text,
                    "entities": {
                        "urls": [
                            {
                                "url": "https://t.co/neat",
                                "expanded_url": "https://t-dv.com/nm_vol19",
                                "display_url": "t-dv.com/nm_vol19",
                            }
                        ]
                    },
                },
            },
            {
                "id": "2063616270218707012",
                "text": soldout_text,
                "created_at": "2026-06-07T13:37:13+00:00",
                "url": "https://x.com/info_myojou/status/2063616270218707012",
            },
            {
                "id": "2063629163001774232",
                "text": live_digest_text,
                "created_at": "2026-06-07T14:28:27+00:00",
                "url": "https://x.com/info_myojou/status/2063629163001774232",
            },
            {
                "id": "2064004974288527729",
                "text": live_digest_text,
                "created_at": "2026-06-08T15:21:47+00:00",
                "url": "https://x.com/info_myojou/status/2064004974288527729",
            },
            {
                "id": "2064321642810294772",
                "text": avilla_text,
                "created_at": "2026-06-09T12:20:07+00:00",
                "url": "https://x.com/info_myojou/status/2064321642810294772",
                "note_tweet": {
                    "text": avilla_text,
                    "entities": {
                        "urls": [
                            {
                                "url": "https://t.co/avilla-l",
                                "expanded_url": "https://l-tike.com/avilla-idol-fes/",
                                "display_url": "l-tike.com/avilla-idol-fes",
                            },
                            {
                                "url": "https://t.co/avilla-free",
                                "expanded_url": "https://l-tike.com/avilla-idol-fes/free",
                                "display_url": "l-tike.com/avilla-idol-fes/free",
                            },
                        ]
                    },
                },
            },
        ]
    }


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


def test_real_archive_title_preserves_hajimemashite_vol4_subtitle():
    posts = {post.id: post for post in MockXClient("mock_posts/real_samples/info_myojou_backfill_500.json")._load_posts()}
    parsed = PostParser().parse_post(posts["2043265358182965514"])

    assert parsed is not None
    assert parsed.event_date == date(2026, 5, 10)
    assert parsed.event_name == 'はじめまして"myojou"です。Vol.4 - miu birthday SP -'


def test_real_archive_idol_infinite_premium_vol09_uses_live_date_not_sale_start():
    posts = {post.id: post for post in MockXClient("mock_posts/real_samples/info_myojou_backfill_500.json")._load_posts()}
    parsed = PostParser().parse_post(posts["2048016860084584595"])

    assert parsed is not None
    assert parsed.event_date == date(2026, 5, 11)
    assert parsed.event_name == "IDOL INFINITE PREMIUM vol.09"
    assert parsed.venue == "Spotify O-nest"


def test_real_archive_idol_infinity_premium_vol12_parses_as_public_live():
    posts = {post.id: post for post in MockXClient("mock_posts/real_samples/info_myojou_backfill_500.json")._load_posts()}
    parsed = PostParser().parse_post(posts["2067204104745869403"])

    assert parsed is not None
    assert parsed.event_date == date(2026, 6, 19)
    assert parsed.event_name == "IDOL ∞ INFINITY PREMIUM vol.12"
    assert parsed.venue == "Spotify O-nest"
    assert parsed.ticket_url == "https://ticketdive.com/event/idol_infinity_premium_vol12"


def test_real_archive_girls_girls_festival_title_not_vip_benefit_text():
    posts = {post.id: post for post in MockXClient("mock_posts/real_samples/info_myojou_backfill_500.json")._load_posts()}
    parsed = PostParser().parse_post(posts["2057721554885120196"])

    assert parsed is not None
    assert parsed.event_name == "GIRLS GIRLS FESTIVAL 2026"
    assert parsed.event_dates == [date(2026, 5, 23), date(2026, 5, 24)]


def test_real_archive_after_benefit_event_is_non_event():
    posts = {post.id: post for post in MockXClient("mock_posts/real_samples/info_myojou_backfill_500.json")._load_posts()}
    post = posts["2063644808548327828"]
    classification = PostParser().classify_post(post)

    assert classification.classification == PostClassification.NON_EVENT
    assert "benefit-only" in classification.reason
    assert PostParser().parse_post(post, classification=classification) is None


def test_real_archive_emergency_stream_rally_is_non_event_but_real_tif_live_remains_event():
    posts = {post.id: post for post in MockXClient("mock_posts/real_samples/info_myojou_backfill_500.json")._load_posts()}
    parser = PostParser()

    rally = parser.classify_post(posts["2056888480622624777"])
    live = parser.parse_post(posts["2057717199574532524"])

    assert rally.classification == PostClassification.NON_EVENT
    assert "streaming-only" in rally.reason
    assert live is not None
    assert live.event_name == "TIF2026メインステージ争奪LIVE 前哨戦"


def test_regular_geppou_with_pre_benefit_parses_as_public_live():
    post = XPost(
        id="2065388703644836098",
        created_at=datetime(2026, 6, 12, 12, 0, tzinfo=JST),
        raw={"url": "https://x.com/info_myojou/status/2065388703644836098"},
        text=(
            "✮••┈┈┈┈••✮••┈┈┈┈••✮\n"
            "         定期公演｢明星月報｣\n"
            "✮••┈┈┈┈••✮••┈┈┈┈••✮\n\n"
            "⟣date：7/8（水）\n"
            "⟣place : SHIBUYA RING\n"
            "⟣open/start：18:30/19:00\n"
            "⟣事前特典会：16:30-17:30\n"
            "⟣price：一般 ¥2,500（+1D）\n\n"
            "#myojou"
        ),
    )
    parser = PostParser()
    classification = parser.classify_post(post)
    parsed = parser.parse_post(post, classification=classification)

    assert classification.classification == PostClassification.EVENT
    assert parsed is not None
    assert parsed.event_name == "定期公演「明星月報」"
    assert parsed.event_date == date(2026, 7, 8)
    assert parsed.venue == "SHIBUYA RING"
    assert parsed.open_time == "18:30"
    assert parsed.start_time == "19:00"
    assert parsed.benefit_event_time == "16:30-17:30"
    assert parsed.general_ticket_price == 2500
    readiness = public_readiness(CanonicalEvent.from_extracted(parsed))
    assert readiness.public_ready is True
    assert not any("benefit-only" in reason for reason in readiness.reasons)


def test_regular_geppou_goods_only_post_is_non_event():
    post = XPost(
        id="geppou-goods-only",
        created_at=datetime(2026, 6, 12, 12, 0, tzinfo=JST),
        text="定期公演「明星月報」グッズ公開\nナンバーくじとグッズ販売のお知らせです。",
    )
    classification = PostParser().classify_post(post)

    assert classification.classification == PostClassification.NON_EVENT
