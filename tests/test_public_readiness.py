from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from myojou_sync.models import CanonicalEvent, XPost
from myojou_sync.parser import PostParser
from myojou_sync.pipeline import PipelineResult, build_quality_report
from myojou_sync.readiness import public_readiness


JST = timezone(timedelta(hours=9))


def _event(**kwargs) -> CanonicalEvent:
    defaults = {
        "event_date": date(2026, 6, 15),
        "event_name": "READY LIVE",
        "venue": "渋谷Milkyway",
        "start_time": "18:30",
        "source_post_id": "source-ready",
    }
    defaults.update(kwargs)
    return CanonicalEvent(**defaults)


def _not_ready_reason(event: CanonicalEvent) -> str:
    readiness = public_readiness(event)
    assert readiness.public_ready is False
    return " ".join(readiness.reasons)


def test_public_ready_false_for_radio_stream():
    assert "radio" in _not_ready_reason(_event(event_name="ラジオ配信"))


def test_public_ready_false_for_coming_soon_teaser():
    assert "teaser" in _not_ready_reason(_event(event_name="coming soon"))


def test_public_ready_false_for_campaign():
    assert "campaign" in _not_ready_reason(_event(event_name="ミョージョーサマーキャンペーン"))


def test_public_ready_false_for_online_signing_detail_content():
    reason = _not_ready_reason(_event(event_name="ニックネーム・サイン・日付・コメント"))

    assert "online signing" in reason


def test_public_ready_false_for_anti_complete_mv_like_post():
    assert "content/MV" in _not_ready_reason(_event(event_name="アンチコンプリート"))


def test_public_ready_false_for_program_content():
    assert "content program" in _not_ready_reason(_event(event_name="メインステージ争奪LIVE〜前哨戦〜直前SP!!春の学力テスト"))


def test_public_ready_false_for_profile_posts():
    assert "profile/member" in _not_ready_reason(_event(event_name="PROFILE 01"))
    assert "profile/member" in _not_ready_reason(_event(event_name="PROFILE 02 薄倉りな"))


def test_public_ready_false_for_member_profile_without_live_structure():
    reason = _not_ready_reason(
        CanonicalEvent(
            event_name="薄倉りな",
            source_text="薄倉りな\nプロフィール\n好きなもの：アイドル",
            source_post_id="member-profile",
        )
    )

    assert "profile/member" in reason


def test_public_ready_false_for_name_profile_with_date_but_no_live_structure():
    reason = _not_ready_reason(
        CanonicalEvent(
            event_date=date(2026, 2, 11),
            event_name="NAME┊︎ 真希しの",
            source_text="NAME┊︎ 真希しの\nBIRTHDAY┊︎2/11\nPROFILE 03",
            source_post_id="name-profile",
        )
    )

    assert "profile/member" in reason


def test_public_ready_false_for_blank_event_name():
    reason = _not_ready_reason(_event(event_name=""))

    assert "missing event_name" in reason


def test_public_ready_false_for_only_performance_time_without_context():
    reason = _not_ready_reason(
        CanonicalEvent(
            myojou_performance_time="19:00-19:20",
            source_post_id="perf-only",
        )
    )

    assert "only performance time" in reason
    assert "missing event_date" in reason
    assert "missing event_name" in reason


def test_public_ready_true_for_good_live_examples():
    good_events = [
        _event(
            event_name="ラブコール vol.19",
            event_date=date(2026, 6, 29),
            venue="Spotify O-nest",
            ticket_url="https://t-dv.com/lc_vol19",
            myojou_performance_time="19:40-20:05",
        ),
        _event(
            event_name="A Villa idol festival HOKKAIDO 2026",
            event_date=date(2026, 8, 29),
            venue="安平町ときわ公園",
            ticket_url="https://l-tike.com/avilla-idol-fes/",
        ),
        _event(event_name="SPARK 2026 渋谷納涼祭", venue="渋谷某所", ticket_url="https://ticketdive.com/event/spark"),
        _event(event_name="IDOL STORM", venue="Spotify O-WEST", ticket_url="https://tiget.net/events/123"),
        _event(event_name="HYPE IDOL! DX", venue="Zepp Shinjuku", start_time="12:00"),
        _event(event_name="MIX BOX vol.10", venue="渋谷DESEO", myojou_performance_time="19:10-19:35"),
    ]

    assert all(public_readiness(event).public_ready for event in good_events)


def test_clear_non_live_categories_classify_as_non_event():
    parser = PostParser()
    samples = [
        "本日21:00 ラジオ配信です",
        "ミョージョーサマーキャンペーン coming soon",
        "ニックネーム・サイン・日付・コメント 入り特典のお知らせ",
        "アンチコンプリート MV公開",
        "メインステージ争奪LIVE〜前哨戦〜直前SP!!春の学力テスト",
        "LIVE DIGEST 昨日の映像です",
        "御礼 本日はありがとうございました",
        "PROFILE 01\n薄倉りな\nメンバー紹介",
        "栗原ここね\nプロフィール",
        "NAME┊︎ 真希しの\nBIRTHDAY┊︎2/11\nPROFILE 03",
    ]

    for index, text in enumerate(samples):
        result = parser.classify_post(
            XPost(id=f"non-live-{index}", text=text, created_at=datetime(2026, 6, 10, 12, 0, tzinfo=JST))
        )
        assert result.classification == "non_event"


def test_member_name_in_real_live_post_is_not_blocked():
    parser = PostParser()
    result = parser.classify_post(
        XPost(
            id="live-with-member-name",
            text="6/29(月)『栗原ここね生誕ライブ』\n会場：Spotify O-nest\n開場19:00 / 開演19:30\nチケット：https://t-dv.com/birthday",
            created_at=datetime(2026, 6, 10, 12, 0, tzinfo=JST),
        )
    )

    assert result.classification == "event"


def test_quality_report_includes_public_ready_and_suspicious_examples():
    ready = _event(event_name="ラブコール vol.19", ticket_url="https://t-dv.com/lc_vol19")
    suspicious = _event(event_name="ラジオ配信", source_post_id="radio001")
    report = build_quality_report(
        [ready, suspicious],
        PipelineResult(fetched_posts=3, parsed_events=2, non_event_skipped=1),
    )

    assert report["public_ready_count"] == 1
    assert report["not_public_ready_count"] == 1
    assert report["suspicious_count"] == 1
    assert report["public_ready_quality"]["public_ready_events"] == 1
    assert report["suspicious_examples"][0]["event_name"] == "ラジオ配信"
    assert report["suspicious_examples"][0]["source_post_id"] == "radio001"
    assert "radio/non-live" in report["suspicious_examples"][0]["reasons"]
