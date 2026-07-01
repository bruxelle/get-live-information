from __future__ import annotations

import json
from pathlib import Path

from myojou_sync.cli import main
from myojou_sync.parsed_import import import_parsed_events
from myojou_sync.source_import import import_source_posts
from myojou_sync.sqlite_public_export import sqlite_public_diff, sqlite_public_preview_rows


def _write_archive(path: Path):
    path.write_text(
        json.dumps(
            {
                "source": "x_api",
                "captured_at": "2026-06-30T12:00:00+00:00",
                "metadata": {"username": "info_myojou"},
                "data": [
                    {
                        "id": "300001",
                        "text": (
                            "Next Live\n"
                            "『SQLITE PREVIEW LIVE』\n"
                            "⟣date：6/29（月）\n"
                            "⟣place：Spotify O-nest\n"
                            "⟣open/start：19:20/19:40\n"
                            "チケット：https://ticketdive.com/event/sqlite-preview-live"
                        ),
                        "created_at": "2026-06-01T12:00:00+09:00",
                        "url": "https://x.com/info_myojou/status/300001",
                        "entities": {
                            "urls": [
                                {
                                    "url": "https://t.co/ticket",
                                    "expanded_url": "https://ticketdive.com/event/sqlite-preview-live",
                                    "display_url": "ticketdive.com/event/sqlite-preview-live",
                                }
                            ]
                        },
                    },
                    {
                        "id": "300002",
                        "text": "グッズ&ナンバーくじ公開\n通販のお知らせです",
                        "created_at": "2026-06-01T12:00:00+09:00",
                        "url": "https://x.com/info_myojou/status/300002",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _prepare_db(tmp_path):
    db_path = tmp_path / "myojou.sqlite"
    archive_path = tmp_path / "archive.json"
    _write_archive(archive_path)
    import_source_posts(db_path, archive_path)
    import_parsed_events(db_path)
    return db_path


def test_sqlite_public_preview_rows_contains_public_like_fields(tmp_path):
    db_path = _prepare_db(tmp_path)

    rows = sqlite_public_preview_rows(db_path)

    assert len(rows) == 1
    row = rows[0]
    assert row["event_name"] == "SQLITE PREVIEW LIVE"
    assert row["event_date"] == "2026-06-29"
    assert row["weekday"] == "月"
    assert row["public_ready"] is True
    assert row["needs_review"] is False
    assert row["source_url"] == "https://x.com/info_myojou/status/300001"
    assert "public_event_id" in row
    assert "ticket_sales" in row
    assert "review_reasons" in row


def test_sqlite_public_preview_rows_missing_db_fails_without_creating_file(tmp_path):
    db_path = tmp_path / "missing.sqlite"

    try:
        sqlite_public_preview_rows(db_path)
    except FileNotFoundError as exc:
        assert "SQLite database does not exist" in str(exc)
    else:
        raise AssertionError("missing database should fail fast")

    assert not db_path.exists()


def test_preview_sqlite_public_export_command_writes_separate_file(tmp_path, capsys):
    db_path = _prepare_db(tmp_path)
    output_path = tmp_path / "reports" / "sqlite-public-preview.json"
    public_path = tmp_path / "public" / "events.json"
    public_path.parent.mkdir()
    public_path.write_text("[]\n", encoding="utf-8")

    result = main(["preview-sqlite-public-export", "--db", str(db_path), "--output", str(output_path)])
    output = capsys.readouterr().out

    assert result == 0
    assert output_path.exists()
    assert public_path.read_text(encoding="utf-8") == "[]\n"
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload[0]["event_name"] == "SQLITE PREVIEW LIVE"
    assert "SQLite public export preview:" in output
    assert "events: 1" in output
    assert "validation_errors: 0" in output


def test_sqlite_public_diff_reports_counts_and_title_differences(tmp_path):
    db_path = _prepare_db(tmp_path)
    current_path = tmp_path / "events.json"
    current_path.write_text(
        json.dumps(
            [
                {
                    "public_event_id": "current:1",
                    "event_date": "2026-06-29",
                    "event_name": "CURRENT ONLY LIVE",
                    "venue": "Spotify O-nest",
                    "ticket_url": "https://ticketdive.com/event/current",
                    "public_ready": True,
                    "needs_review": False,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    diff = sqlite_public_diff(db_path, current_path)

    assert diff["events_before"] == 1
    assert diff["events_after"] == 1
    assert diff["added"] == 1
    assert diff["removed"] == 1
    assert diff["titles_only_in_current"] == ["current only live"]
    assert diff["titles_only_in_sqlite"] == ["sqlite preview live"]
    assert diff["sqlite_missing_fields"]["ticket_url"] == 1


def test_sqlite_public_diff_ignores_preview_debug_only_source_fields(tmp_path):
    db_path = _prepare_db(tmp_path)
    current_path = tmp_path / "events.json"
    current_rows = []
    for row in sqlite_public_preview_rows(db_path):
        public_row = dict(row)
        public_row.pop("source_url")
        public_row.pop("all_source_urls")
        current_rows.append(public_row)
    current_path.write_text(json.dumps(current_rows, ensure_ascii=False), encoding="utf-8")

    diff = sqlite_public_diff(db_path, current_path)

    assert diff["events_before"] == 1
    assert diff["events_after"] == 1
    assert diff["added"] == 0
    assert diff["removed"] == 0
    assert diff["possibly_changed"] == 0
    assert sqlite_public_preview_rows(db_path)[0]["source_url"]
    assert sqlite_public_preview_rows(db_path)[0]["all_source_urls"]


def test_diff_sqlite_public_export_command_prints_summary(tmp_path, capsys):
    db_path = _prepare_db(tmp_path)
    current_path = tmp_path / "events.json"
    current_path.write_text("[]\n", encoding="utf-8")

    result = main(["diff-sqlite-public-export", "--db", str(db_path), "--current", str(current_path)])
    output = capsys.readouterr().out

    assert result == 0
    assert "SQLite public export diff:" in output
    assert "events_before: 0" in output
    assert "events_after: 1" in output
    assert "title_only_in_sqlite: sqlite preview live" in output
