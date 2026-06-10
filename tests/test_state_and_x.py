from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from myojou_sync.parser import PostParser
from myojou_sync.pipeline import SyncPipeline
from myojou_sync.state import SQLiteStateStore
from myojou_sync.x_client import MockXClient, XApiClient


class FakeResponse:
    def __init__(self, payload, headers=None):
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self):
        self.urls: list[str] = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        if "/users/by/username/" in url:
            return FakeResponse({"data": {"id": "12345"}})
        return FakeResponse(
            {
                "data": [
                    {
                        "id": "200001",
                        "created_at": "2026-05-20T00:00:00Z",
                        "text": "6/15(月)『STARLIGHT LIVE vol.7』\n会場：渋谷Milkyway\nOPEN 18:00 / START 18:30",
                    }
                ]
            },
            headers={
                "x-rate-limit-limit": "15",
                "x-rate-limit-remaining": "14",
                "x-rate-limit-reset": "1770000000",
            },
        )


class FakeEntitySession:
    def __init__(self):
        self.params = []

    def get(self, url, **kwargs):
        self.params.append(kwargs.get("params", {}))
        if "/users/by/username/" in url:
            return FakeResponse({"data": {"id": "12345"}})
        return FakeResponse(
            {
                "data": [
                    {
                        "id": "200002",
                        "created_at": "2026-05-20T00:00:00Z",
                        "text": (
                            "6/15(月)『REAL ENTITY LIVE』\n"
                            "会場：渋谷Milkyway\n"
                            "OPEN 18:00 / START 18:30\n"
                            "チケット：https://t.co/abc123"
                        ),
                        "entities": {
                            "urls": [
                                {
                                    "url": "https://t.co/abc123",
                                    "expanded_url": "https://t.livepocket.jp/e/real-entity-live",
                                }
                            ]
                        },
                        "attachments": {"media_keys": ["3_200002"]},
                    }
                ],
                "includes": {
                    "media": [
                        {
                            "media_key": "3_200002",
                            "type": "photo",
                            "url": "https://pbs.twimg.com/media/example.jpg",
                            "preview_image_url": "https://pbs.twimg.com/media/example-preview.jpg",
                            "width": 1200,
                            "height": 800,
                            "alt_text": "告知画像",
                        }
                    ]
                },
            },
            headers={"x-rate-limit-remaining": "13"},
        )


class FakeNoteTweetSession:
    def __init__(self):
        self.params = []

    def get(self, url, **kwargs):
        self.params.append(kwargs.get("params", {}))
        if "/users/by/username/" in url:
            return FakeResponse({"data": {"id": "12345"}})
        truncated_text = (
            "✮••┈┈┈┈┈┈┈••✮••┈┈┈┈┈┈┈••✮\n"
            "THE ENCORE presents\n"
            "「ラブコール vol.19」\n"
            "✮••┈┈┈┈┈┈┈••✮••┈┈┈┈┈┈┈••✮\n\n"
            "🎙19:40-20:05\n"
            "📸21:00-22:00\n\n"
            "⟣date：6/29（月）\n"
            "⟣place :Spotify O-nest\n"
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
            "⟣place :Spotify O-nest\n"
            "⟣open/start：19:20/19:40\n"
            "⟣price：前方¥3,000/一般¥1,000/当日各+¥500（各+1D）\n"
            "入場特典：明星カード（サインありチェキ）\n"
            "【一般販売】\n"
            "6/7（日）21:00-6/28（日）23:59\n"
            "https://t.co/fullnote"
        )
        return FakeResponse(
            {
                "data": [
                    {
                        "id": "2063217018032328930",
                        "created_at": "2026-06-06T11:10:44Z",
                        "text": truncated_text,
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
                        "note_tweet": {
                            "text": full_text,
                            "entities": {
                                "urls": [
                                    {
                                        "url": "https://t.co/fullnote",
                                        "expanded_url": "https://t-dv.com/lc_vol19",
                                        "display_url": "t-dv.com/lc_vol19",
                                    }
                                ]
                            },
                        },
                    }
                ],
                "includes": {
                    "media": [
                        {
                            "media_key": "3_2063217011564703744",
                            "type": "photo",
                            "url": "https://pbs.twimg.com/media/HKIE8MzbcAA_STm.jpg",
                            "width": 2481,
                            "height": 2888,
                        }
                    ]
                },
            }
        )


def _tweet_payload(post_id: int) -> dict:
    return {
        "id": str(post_id),
        "created_at": "2026-05-20T00:00:00Z",
        "text": f"6/15(月)『BACKFILL LIVE {post_id}』\n会場：渋谷Milkyway\nOPEN 18:00 / START 18:30",
    }


class FakePaginatedSession:
    def __init__(self, pages):
        self.pages = pages
        self.params = []

    def get(self, url, **kwargs):
        if "/users/by/username/" in url:
            return FakeResponse({"data": {"id": "12345"}})
        params = kwargs.get("params", {})
        self.params.append(params)
        page_index = len(self.params) - 1
        return FakeResponse(
            self.pages[page_index],
            headers={
                "x-rate-limit-limit": "15",
                "x-rate-limit-remaining": str(14 - page_index),
                "x-rate-limit-reset": "1770000000",
            },
        )


def test_x_user_id_lookup_is_cached_in_sqlite(tmp_path):
    state = SQLiteStateStore(tmp_path / "state.sqlite")
    session = FakeSession()
    client = XApiClient("token", state=state, session=session)

    client.fetch_recent_posts(max_results=10)
    client.fetch_recent_posts(max_results=10)

    lookup_calls = [url for url in session.urls if "/users/by/username/" in url]
    timeline_calls = [url for url in session.urls if url.endswith("/tweets")]

    assert lookup_calls == ["https://api.x.com/2/users/by/username/info_myojou"]
    assert len(timeline_calls) == 2
    assert state.get_cached_x_user_id("info_myojou") == "12345"
    assert client.last_fetch_metadata.estimated_post_read_count == 1
    assert client.last_fetch_metadata.rate_limit_headers["x-rate-limit-remaining"] == "14"


def test_x_client_preserves_expanded_urls_and_media_metadata(tmp_path):
    state = SQLiteStateStore(tmp_path / "state.sqlite")
    session = FakeEntitySession()
    client = XApiClient("token", state=state, session=session)

    posts = client.fetch_recent_posts(max_results=10)

    assert session.params[-1]["tweet.fields"] == "id,text,created_at,entities,attachments,referenced_tweets,note_tweet"
    assert session.params[-1]["expansions"] == "attachments.media_keys"
    assert "alt_text" in session.params[-1]["media.fields"]
    assert posts[0].raw["entities"]["urls"][0]["expanded_url"] == "https://t.livepocket.jp/e/real-entity-live"
    assert posts[0].raw["media"] == [
        {
            "media_key": "3_200002",
            "type": "photo",
            "url": "https://pbs.twimg.com/media/example.jpg",
            "preview_image_url": "https://pbs.twimg.com/media/example-preview.jpg",
            "width": 1200,
            "height": 800,
            "alt_text": "告知画像",
        }
    ]

    parsed = PostParser().parse_post(posts[0])
    assert parsed is not None
    assert parsed.ticket_url == "https://t.livepocket.jp/e/real-entity-live"
    assert parsed.source_raw["media"][0]["alt_text"] == "告知画像"


def test_x_client_and_parser_use_note_tweet_full_text(tmp_path):
    state = SQLiteStateStore(tmp_path / "state.sqlite")
    session = FakeNoteTweetSession()
    client = XApiClient("token", state=state, session=session)

    posts = client.fetch_recent_posts(max_results=5)
    post = posts[0]
    parsed = PostParser().parse_post(post)

    assert "note_tweet" in session.params[-1]["tweet.fields"]
    assert post.full_text_source == "note_tweet"
    assert post.api_text is not None
    assert post.truncated_text == post.api_text
    assert len(post.text) > len(post.api_text)
    assert post.raw["note_tweet"]["entities"]["urls"][0]["expanded_url"] == "https://t-dv.com/lc_vol19"
    assert parsed is not None
    assert parsed.source_text == post.text
    assert parsed.source_raw["api_text"] == post.api_text
    assert parsed.source_raw["full_text_source"] == "note_tweet"
    assert parsed.event_name == "ラブコール vol.19"
    assert parsed.venue == "Spotify O-nest"
    assert parsed.open_time == "19:20"
    assert parsed.start_time == "19:40"
    assert parsed.myojou_performance_time == "19:40-20:05"
    assert parsed.benefit_event_time == "21:00-22:00"
    assert parsed.ticket_url == "https://t-dv.com/lc_vol19"
    assert parsed.general_ticket_price == 1000
    assert parsed.priority_ticket_name == "前方"
    assert parsed.priority_ticket_price == 3000
    assert parsed.same_day_ticket_price == 500
    assert parsed.ticket_application_start_at == datetime(2026, 6, 7, 21, 0, tzinfo=timezone(timedelta(hours=9)))
    assert parsed.ticket_application_deadline_at == datetime(2026, 6, 28, 23, 59, tzinfo=timezone(timedelta(hours=9)))
    assert parsed.ticket_sale_type == "一般"
    assert parsed.notes and "明星カード" in parsed.notes
    assert parsed.ticket_sales


def test_x_backfill_pagination_stops_at_max_posts(tmp_path):
    state = SQLiteStateStore(tmp_path / "state.sqlite")
    session = FakePaginatedSession(
        [
            {
                "data": [_tweet_payload(index) for index in range(300001, 300006)],
                "meta": {"next_token": "next-page"},
            }
        ]
    )
    client = XApiClient("token", state=state, session=session)

    posts = client.fetch_historical_posts(max_posts=3, max_pages=5, page_size=5)

    assert [post.id for post in posts] == ["300001", "300002", "300003"]
    assert len(session.params) == 1
    assert client.last_fetch_metadata.posts_fetched == 3
    assert client.last_fetch_metadata.estimated_post_read_count == 5
    assert client.last_fetch_metadata.pages_fetched == 1
    assert client.last_fetch_metadata.page_summaries[0]["has_next_token"] is True


def test_x_backfill_final_page_requests_only_remaining_posts(tmp_path):
    state = SQLiteStateStore(tmp_path / "state.sqlite")
    session = FakePaginatedSession(
        [
            {
                "data": [_tweet_payload(index) for index in range(301000, 301096)],
                "meta": {"next_token": "page-2"},
            },
            {
                "data": [_tweet_payload(index) for index in range(301100, 301105)],
                "meta": {"next_token": "page-3"},
            },
        ]
    )
    client = XApiClient("token", state=state, session=session)

    posts = client.fetch_historical_posts(max_posts=100, max_pages=10, page_size=100)

    assert len(posts) == 100
    assert len(session.params) == 2
    assert session.params[0]["max_results"] == 100
    assert session.params[1]["max_results"] == 5
    assert client.last_fetch_metadata.estimated_post_read_count == 101
    assert client.last_fetch_metadata.page_summaries[1]["posts_fetched"] == 5
    assert client.last_fetch_metadata.page_summaries[1]["posts_accepted"] == 4


def test_x_backfill_pagination_stops_at_max_pages(tmp_path):
    state = SQLiteStateStore(tmp_path / "state.sqlite")
    session = FakePaginatedSession(
        [
            {"data": [_tweet_payload(index) for index in range(300010, 300015)], "meta": {"next_token": "page-2"}},
            {"data": [_tweet_payload(index) for index in range(300020, 300025)], "meta": {"next_token": "page-3"}},
            {"data": [_tweet_payload(index) for index in range(300030, 300035)], "meta": {"next_token": "page-4"}},
        ]
    )
    client = XApiClient("token", state=state, session=session)

    posts = client.fetch_historical_posts(max_posts=20, max_pages=2, page_size=5)

    assert len(posts) == 10
    assert len(session.params) == 2
    assert "pagination_token" not in session.params[0]
    assert session.params[1]["pagination_token"] == "page-2"
    assert client.last_fetch_metadata.pages_fetched == 2
    assert client.last_fetch_metadata.estimated_post_read_count == 10


def test_x_backfill_pagination_stops_when_next_token_absent(tmp_path):
    state = SQLiteStateStore(tmp_path / "state.sqlite")
    session = FakePaginatedSession(
        [
            {"data": [_tweet_payload(index) for index in range(300100, 300103)], "meta": {}},
            {"data": [_tweet_payload(300999)], "meta": {}},
        ]
    )
    client = XApiClient("token", state=state, session=session)

    posts = client.fetch_historical_posts(max_posts=20, max_pages=5, page_size=5)

    assert len(posts) == 3
    assert len(session.params) == 1
    assert client.last_fetch_metadata.pages_fetched == 1
    assert client.last_fetch_metadata.page_summaries[0]["has_next_token"] is False


def test_pipeline_source_posts_store_linked_event_metadata(tmp_path, mock_posts_dir: Path):
    state = SQLiteStateStore(tmp_path / "state.sqlite")
    pipeline = SyncPipeline(
        fetcher=MockXClient(mock_posts_dir),
        state=state,
        parser=PostParser(),
    )

    events, result = pipeline.run_once(max_results=10)
    records = state.source_post_records()

    assert result.estimated_x_post_read_count == 0
    assert len(records) == result.parsed_events
    assert all(record["source_type"] == "x" for record in records)
    assert all(record["source_post_id"] for record in records)
    assert all(record["source_url"].startswith("https://x.com/info_myojou/status/") for record in records)
    assert all(record["source_posted_at"] for record in records)
    assert all(record["source_text"] for record in records)
    assert all(record["source_kind"] for record in records)
    assert all(record["linked_event_id"] for record in records)
    assert all(record["extraction_confidence"] is not None for record in records)
    assert {record["linked_event_id"] for record in records}.issubset({event.event_id for event in events})


def test_source_post_payload_preserves_raw_media_metadata(tmp_path):
    fixture_path = tmp_path / "real_samples"
    fixture_path.mkdir()
    (fixture_path / "first_live_fetch.json").write_text(
        json.dumps(
            {
                "captured_at": "2026-06-10T00:00:00+00:00",
                "source": "x_api",
                "data": [
                    {
                        "id": "real_media_001",
                        "created_at": "2026-05-20T00:00:00+09:00",
                        "url": "https://x.com/info_myojou/status/real_media_001",
                        "text": (
                            "6/15(月)『RAW MEDIA LIVE』\n"
                            "会場：渋谷Milkyway\n"
                            "OPEN 18:00 / START 18:30\n"
                            "チケット：https://t.co/rawmedia"
                        ),
                        "entities": {
                            "urls": [
                                {
                                    "url": "https://t.co/rawmedia",
                                    "expanded_url": "https://t.livepocket.jp/e/raw-media-live",
                                }
                            ]
                        },
                        "media": [
                            {
                                "media_key": "3_raw_media",
                                "type": "photo",
                                "url": "https://pbs.twimg.com/media/raw.jpg",
                                "width": 1000,
                                "height": 1000,
                                "alt_text": "ライブ告知",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "state.sqlite"
    state = SQLiteStateStore(db_path)
    pipeline = SyncPipeline(fetcher=MockXClient(fixture_path), state=state, parser=PostParser())

    events, result = pipeline.run_once(max_results=10)

    assert result.parsed_events == 1
    assert events[0].ticket_url == "https://t.livepocket.jp/e/raw-media-live"
    with sqlite3.connect(db_path) as conn:
        payload_json = conn.execute("SELECT payload_json FROM source_posts WHERE post_id = ?", ("real_media_001",)).fetchone()[0]
    payload = json.loads(payload_json)
    assert payload["source_raw"]["media"][0]["alt_text"] == "ライブ告知"
    assert payload["source_raw"]["entities"]["urls"][0]["expanded_url"] == "https://t.livepocket.jp/e/raw-media-live"


def test_saved_real_sample_json_can_be_loaded_as_mock_input(tmp_path):
    fixture_path = tmp_path / "real_samples"
    fixture_path.mkdir()
    (fixture_path / "saved_sample.json").write_text(
        json.dumps(
            {
                "captured_at": "2026-06-10T00:00:00+00:00",
                "source": "x_api",
                "data": [
                    {
                        "id": "saved_real_001",
                        "created_at": "2026-05-20T00:00:00+09:00",
                        "url": "https://x.com/info_myojou/status/saved_real_001",
                        "text": "6/15(月)『SAVED SAMPLE LIVE』\n会場：渋谷Milkyway\nチケット：https://t.co/saved",
                        "entities": {
                            "urls": [
                                {
                                    "url": "https://t.co/saved",
                                    "expanded_url": "https://ticketdive.com/event/saved-sample-live",
                                }
                            ]
                        },
                        "media": [{"media_key": "3_saved", "type": "photo", "alt_text": "保存サンプル"}],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    posts = MockXClient(fixture_path).fetch_recent_posts(max_results=10)
    parsed = PostParser().parse_post(posts[0])

    assert posts[0].raw["media"][0]["alt_text"] == "保存サンプル"
    assert parsed is not None
    assert parsed.ticket_url == "https://ticketdive.com/event/saved-sample-live"
