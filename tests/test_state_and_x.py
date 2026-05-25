from __future__ import annotations

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
