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


def test_info_myojou_first_fetch_parses_english_style_free_event_labels(mock_posts_dir):
    posts = _real_first_fetch_posts(mock_posts_dir)
    parsed = PostParser().parse_post(posts["2064018631219183632"])

    assert parsed is not None
    assert parsed.event_date == date(2026, 6, 9)
    assert parsed.event_name == 'myojou oneman live "明夏"アフター特典会'
    assert parsed.venue == "ふれあい貸し会議室 渋谷No.77"
    assert parsed.start_time == "18:30"
    assert parsed.general_ticket_price == 0
    assert parsed.ticket_sale_type == "無料"
    assert parsed.ticket_url is None
    assert parsed.source_raw["media"][0]["url"].startswith("https://pbs.twimg.com/media/")


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


def test_info_myojou_first_fetch_pipeline_reduces_false_needs_review(tmp_path, mock_posts_dir):
    state = SQLiteStateStore(tmp_path / "state.sqlite")
    pipeline = SyncPipeline(
        fetcher=MockXClient(mock_posts_dir / "real_samples" / "info_myojou_first_fetch.json"),
        state=state,
        parser=PostParser(),
    )

    events, result = pipeline.run_once(max_results=10)

    assert result.fetched_posts == 4
    assert result.parsed_events == 3
    assert result.non_event_skipped == 1
    assert result.created_events == 2
    assert result.updated_events == 1
    assert result.canonical_events == 2
    afterparty = next(event for event in events if event.event_name == 'myojou oneman live "明夏"アフター特典会')
    assert afterparty.venue == "ふれあい貸し会議室 渋谷No.77"
    assert afterparty.general_ticket_price == 0
    assert afterparty.ticket_sale_type == "無料"
    assert afterparty.ticket_url is None
    assert afterparty.needs_review is False
    assert len(afterparty.all_source_urls) == 2
    assert all(
        "missing ticket deadline" not in record["needs_review_reasons"]
        for record in result.x_sample_records
        if record["id"] in {"2064018631219183632", "2064266242069004344"}
    )


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
    assert ticket_summary(CanonicalEvent.from_extracted(parsed)) == "一般 1,000円 / 前方 4,500円 / 後方観覧 無料"


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
        "VIPチケット 15,000円 / Tシャツ付きチケット 6,000円 / 無料チケット 0円"
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
    assert {"2063616270218707012", "2063849253471141988", "2063865003917410549"}.issubset(
        set(event.source_post_ids)
    )
    assert len(event.all_source_urls) >= 3
    assert event.myojou_performance_time == "19:00"
    assert any(other.event_name == "ラブコール vol.19" for other in events)
    assert any(other.event_name == "TOKYO GIRLS GIRLS" for other in events)
    assert all(other.event_name != "LIVE DIGEST" for other in events)


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
    assert ticket_summary(event) == "VIPチケット 15,000円 / Tシャツ付きチケット 6,000円 / 無料チケット 0円"


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
