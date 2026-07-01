from __future__ import annotations

import json
import sqlite3

from myojou_sync.cli import main
from myojou_sync.parsed_import import import_parsed_events
from myojou_sync.source_import import import_source_posts


def _write_archive(path, posts):
    path.write_text(
        json.dumps(
            {
                "source": "x_api",
                "captured_at": "2026-06-30T12:00:00+00:00",
                "metadata": {"username": "info_myojou"},
                "data": posts,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _live_post(post_id="200001", title="SQLITE IMPORT LIVE"):
    return {
        "id": post_id,
        "text": (
            f"✮ Next Live\n"
            f"『{title}』\n"
            "⟣date：6/29（月）\n"
            "⟣place：Spotify O-nest\n"
            "⟣open/start：19:20/19:40\n"
            "チケット：https://ticketdive.com/event/sqlite-import-live"
        ),
        "created_at": "2026-06-01T12:00:00+09:00",
        "url": f"https://x.com/info_myojou/status/{post_id}",
        "entities": {
            "urls": [
                {
                    "url": "https://t.co/ticket",
                    "expanded_url": "https://ticketdive.com/event/sqlite-import-live",
                    "display_url": "ticketdive.com/event/sqlite-import-live",
                }
            ]
        },
    }


def _rows(db_path, table_name):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(f"SELECT * FROM {table_name} ORDER BY id").fetchall()


def test_import_parsed_events_creates_events_and_event_sources(tmp_path):
    db_path = tmp_path / "myojou.sqlite"
    archive_path = tmp_path / "archive.json"
    _write_archive(archive_path, [_live_post()])
    import_source_posts(db_path, archive_path)

    result = import_parsed_events(db_path)
    events = _rows(db_path, "events")
    event_sources = _rows(db_path, "event_sources")

    assert result.source_posts_read == 1
    assert result.parsed_event_candidates == 1
    assert result.events_inserted == 1
    assert result.events_updated == 0
    assert result.events_skipped == 0
    assert result.event_sources_inserted == 1
    assert result.event_sources_skipped == 0
    assert len(events) == 1
    assert events[0]["display_title"] == "SQLITE IMPORT LIVE"
    assert events[0]["event_date"] == "2026-06-29"
    assert events[0]["open_time"] == "19:20"
    assert events[0]["start_time"] == "19:40"
    assert events[0]["public_ready"] == 1
    assert event_sources[0]["event_id"] == events[0]["id"]
    assert event_sources[0]["source_post_id"] == "x:200001"
    assert event_sources[0]["source_url"] == "https://x.com/info_myojou/status/200001"
    assert event_sources[0]["relation_type"] == "initial_announcement"


def test_import_parsed_events_is_idempotent(tmp_path):
    db_path = tmp_path / "myojou.sqlite"
    archive_path = tmp_path / "archive.json"
    _write_archive(archive_path, [_live_post()])
    import_source_posts(db_path, archive_path)

    first = import_parsed_events(db_path)
    second = import_parsed_events(db_path)

    assert first.events_inserted == 1
    assert first.event_sources_inserted == 1
    assert second.events_inserted == 0
    assert second.events_updated == 0
    assert second.events_skipped == 1
    assert second.event_sources_inserted == 0
    assert second.event_sources_skipped == 1
    assert len(_rows(db_path, "events")) == 1
    assert len(_rows(db_path, "event_sources")) == 1


def test_import_parsed_events_expands_multiday_events_to_one_row_per_date(tmp_path):
    db_path = tmp_path / "myojou.sqlite"
    archive_path = tmp_path / "archive.json"
    _write_archive(
        archive_path,
        [
            {
                "id": "200002",
                "text": (
                    "Next Live\n"
                    "『MULTIDAY FESTIVAL』\n"
                    "日付：5/2, 5/3\n"
                    "会場：渋谷Milkyway\n"
                    "OPEN 10:00 / START 10:30\n"
                    "チケット：https://ticketdive.com/event/multiday"
                ),
                "created_at": "2026-04-01T12:00:00+09:00",
                "url": "https://x.com/info_myojou/status/200002",
            }
        ],
    )
    import_source_posts(db_path, archive_path)

    result = import_parsed_events(db_path)
    events = _rows(db_path, "events")

    assert result.parsed_event_candidates == 1
    assert result.events_inserted == 2
    assert [row["event_date"] for row in events] == ["2026-05-02", "2026-05-03"]
    assert {row["display_title"] for row in events} == {"MULTIDAY FESTIVAL"}


def test_import_parsed_events_skips_non_event_source_posts(tmp_path):
    db_path = tmp_path / "myojou.sqlite"
    archive_path = tmp_path / "archive.json"
    _write_archive(
        archive_path,
        [
            _live_post(post_id="200003", title="VALID LIVE"),
            {
                "id": "200004",
                "text": "グッズ&ナンバーくじ公開\n通販のお知らせです",
                "created_at": "2026-06-01T12:00:00+09:00",
                "url": "https://x.com/info_myojou/status/200004",
            },
        ],
    )
    import_source_posts(db_path, archive_path)

    result = import_parsed_events(db_path)

    assert result.source_posts_read == 2
    assert result.parsed_event_candidates == 1
    assert len(_rows(db_path, "events")) == 1
    assert len(_rows(db_path, "event_sources")) == 1


def test_import_parsed_events_cli_prints_summary(tmp_path, capsys):
    db_path = tmp_path / "myojou.sqlite"
    archive_path = tmp_path / "archive.json"
    _write_archive(archive_path, [_live_post(post_id="200005", title="CLI PARSED LIVE")])
    import_source_posts(db_path, archive_path)

    result = main(["import-parsed-events", "--db", str(db_path)])
    output = capsys.readouterr().out

    assert result == 0
    assert "Imported parsed events:" in output
    assert "source_posts_read: 1" in output
    assert "parsed_event_candidates: 1" in output
    assert "events_inserted: 1" in output
    assert "event_sources_inserted: 1" in output
