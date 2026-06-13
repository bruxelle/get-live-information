from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from myojou_sync.cli import main
from myojou_sync.models import XPost
from myojou_sync.public_validation import PublicValidationResult
from myojou_sync.x_archive import update_x_archive
from myojou_sync.x_client import FetchMetadata


JST = timezone(timedelta(hours=9))


def test_x_archive_update_appends_deduplicates_preserves_note_tweet_and_strips_secrets(tmp_path):
    archive_path = tmp_path / "info_myojou_backfill_500.json"
    archive_path.write_text(
        json.dumps(
            {
                "captured_at": "2026-06-01T00:00:00+00:00",
                "source": "x_api",
                "metadata": {"username": "info_myojou", "bearer_token": "secret-token"},
                "data": [
                    {
                        "id": "100",
                        "text": "existing",
                        "created_at": "2026-06-01T00:00:00+09:00",
                        "note_tweet": {"text": "existing full text"},
                        "raw": {"id": "100", "authorization": "Bearer secret-token"},
                        "linked_event_id": "volatile_event_id",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    new_records = [
        {
            "id": "101",
            "text": "new",
            "created_at": "2026-06-02T00:00:00+09:00",
            "note_tweet": {
                "text": "new full text",
                "entities": {"urls": [{"url": "https://t.co/new", "expanded_url": "https://ticketdive.com/event/new"}]},
            },
            "raw": {
                "id": "101",
                "note_tweet": {"text": "new full text"},
                "media": [{"media_key": "3_101", "type": "photo", "alt_text": "告知画像"}],
                "secret": "do-not-write",
            },
        },
        {
            "id": "100",
            "text": "existing",
            "created_at": "2026-06-01T00:00:00+09:00",
            "note_tweet": {"text": "existing full text"},
            "raw": {"id": "100", "authorization": "Bearer secret-token"},
            "already_processed": True,
        },
    ]

    result = update_x_archive(archive_path, new_records, username="info_myojou")
    payload = json.loads(archive_path.read_text(encoding="utf-8"))
    content = archive_path.read_text(encoding="utf-8")

    assert result.wrote is True
    assert result.added == 1
    assert result.total_posts == 2
    assert result.latest_post_id == "101"
    assert payload["source"] == "x_api"
    assert payload["metadata"]["username"] == "info_myojou"
    assert payload["metadata"]["posts_fetched"] == 2
    assert payload["metadata"]["latest_post_id"] == "101"
    assert [item["id"] for item in payload["data"]] == ["101", "100"]
    assert payload["data"][0]["note_tweet"]["text"] == "new full text"
    assert payload["data"][0]["raw"]["media"][0]["alt_text"] == "告知画像"
    assert "secret-token" not in content
    assert "do-not-write" not in content
    assert "linked_event_id" not in content
    assert "already_processed" not in content


def test_x_archive_update_is_deterministic_when_records_do_not_change(tmp_path):
    archive_path = tmp_path / "archive.json"
    records = [
        {
            "id": "200",
            "text": "same",
            "created_at": "2026-06-02T00:00:00+09:00",
            "note_tweet": {"text": "same full text"},
            "raw": {"id": "200", "note_tweet": {"text": "same full text"}},
        }
    ]

    first = update_x_archive(archive_path, records, username="info_myojou")
    first_content = archive_path.read_text(encoding="utf-8")
    second = update_x_archive(archive_path, records, username="info_myojou")
    second_content = archive_path.read_text(encoding="utf-8")

    assert first.wrote is True
    assert second.wrote is False
    assert first_content == second_content


def test_x_archive_update_recovers_from_invalid_archive_json(tmp_path, caplog):
    archive_path = tmp_path / "archive.json"
    archive_path.write_text('{"data": [', encoding="utf-8")

    result = update_x_archive(
        archive_path,
        [
            {
                "id": "250",
                "text": "recovered",
                "created_at": "2026-06-03T00:00:00+09:00",
                "note_tweet": {"text": "recovered full text"},
                "raw": {"id": "250", "note_tweet": {"text": "recovered full text"}},
            }
        ],
        username="info_myojou",
    )
    payload = json.loads(archive_path.read_text(encoding="utf-8"))

    assert result.wrote is True
    assert result.added == 1
    assert result.total_posts == 1
    assert payload["data"][0]["id"] == "250"
    assert payload["metadata"]["latest_post_id"] == "250"
    assert "X archive JSON is unreadable" in caplog.text


def test_x_archive_latest_post_id_uses_created_at_for_non_numeric_ids(tmp_path):
    archive_path = tmp_path / "archive.json"
    records = [
        {
            "id": "sample-old",
            "text": "old",
            "created_at": "2026-06-01T00:00:00+09:00",
            "raw": {"id": "sample-old"},
        },
        {
            "id": "sample-new",
            "text": "new",
            "created_at": "2026-06-03T00:00:00+09:00",
            "raw": {"id": "sample-new"},
        },
    ]

    result = update_x_archive(archive_path, records, username="info_myojou")
    payload = json.loads(archive_path.read_text(encoding="utf-8"))

    assert result.latest_post_id == "sample-new"
    assert payload["metadata"]["latest_post_id"] == "sample-new"
    assert [record["id"] for record in payload["data"]] == ["sample-new", "sample-old"]


def test_refresh_public_write_updates_x_archive_with_fake_x_posts(tmp_path, monkeypatch, capsys):
    class FakeIncrementalXClient:
        def __init__(self, bearer_token, username, state):
            assert bearer_token == "super-secret-token"
            self.last_fetch_metadata = FetchMetadata()

        def fetch_recent_posts(self, *, since_id=None, max_results=10):
            self.last_fetch_metadata = FetchMetadata(posts_fetched=1, estimated_post_read_count=1)
            return [
                XPost(
                    id="300",
                    created_at=datetime(2026, 6, 13, 9, 0, tzinfo=JST),
                    text=(
                        "6/20(土)『ARCHIVE REFRESH LIVE』\n"
                        "会場：渋谷Milkyway\n"
                        "OPEN 18:00 / START 18:30\n"
                        "チケット：https://ticketdive.com/event/archive-refresh"
                    ),
                    raw={
                        "id": "300",
                        "text": (
                            "6/20(土)『ARCHIVE REFRESH LIVE』\n"
                            "会場：渋谷Milkyway\n"
                            "OPEN 18:00 / START 18:30\n"
                            "チケット：https://ticketdive.com/event/archive-refresh"
                        ),
                        "note_tweet": {"text": "ARCHIVE REFRESH LIVE full text"},
                        "entities": {"urls": []},
                        "media": [{"media_key": "3_300", "type": "photo", "alt_text": "ライブ告知"}],
                        "authorization": "Bearer super-secret-token",
                    },
                )
            ]

        def fetch_historical_posts(self, **kwargs):
            raise AssertionError("refresh-public should not use backfill")

    def fail(*args, **kwargs):
        raise AssertionError("refresh-public must not construct external write adapters")

    output_path = tmp_path / "public" / "events.json"
    archive_path = tmp_path / "mock_posts" / "real_samples" / "info_myojou_backfill_500.json"
    output_path.parent.mkdir()
    output_path.write_text("[]\n", encoding="utf-8")
    archive_path.parent.mkdir(parents=True)
    archive_path.write_text('{"source":"x_api","metadata":{},"data":[]}\n', encoding="utf-8")
    monkeypatch.setenv("NO_X_API", "false")
    monkeypatch.setenv("X_BEARER_TOKEN", "super-secret-token")
    monkeypatch.setattr("myojou_sync.cli.XApiClient", FakeIncrementalXClient)
    monkeypatch.setattr("myojou_sync.cli.NotionEventSink", fail)
    monkeypatch.setattr("myojou_sync.cli.GoogleSheetsEventSink", fail)

    result = main(
        [
            "refresh-public",
            "--db",
            str(tmp_path / "state.sqlite"),
            "--output",
            str(output_path),
            "--write",
            "--x-archive",
            str(archive_path),
            "--update-archive",
        ]
    )
    output = capsys.readouterr().out
    public_rows = json.loads(output_path.read_text(encoding="utf-8"))
    archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
    archive_content = archive_path.read_text(encoding="utf-8")

    assert result == 0
    assert "Wrote 1 public events" in output
    assert "X archive update:" in output
    assert "added: 1" in output
    assert public_rows[0]["event_name"] == "ARCHIVE REFRESH LIVE"
    assert archive_payload["metadata"]["latest_post_id"] == "300"
    assert archive_payload["data"][0]["note_tweet"]["text"] == "ARCHIVE REFRESH LIVE full text"
    assert archive_payload["data"][0]["media"][0]["alt_text"] == "ライブ告知"
    assert "super-secret-token" not in archive_content


def test_refresh_public_update_archive_requires_x_archive(tmp_path, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise AssertionError("refresh-public should fail before constructing an X client")

    monkeypatch.setenv("NO_X_API", "false")
    monkeypatch.setenv("X_BEARER_TOKEN", "token")
    monkeypatch.setattr("myojou_sync.cli.XApiClient", fail)

    result = main(
        [
            "refresh-public",
            "--db",
            str(tmp_path / "state.sqlite"),
            "--output",
            str(tmp_path / "events.json"),
            "--write",
            "--update-archive",
        ]
    )
    error = capsys.readouterr().err

    assert result == 2
    assert "--x-archive is required when --update-archive is used." in error


def test_refresh_public_dry_run_does_not_modify_x_archive(tmp_path, capsys):
    mock_path = tmp_path / "mock.json"
    archive_path = tmp_path / "archive.json"
    output_path = tmp_path / "events.json"
    mock_path.write_text(
        json.dumps(
            [
                {
                    "id": "400",
                    "created_at": "2026-06-13T09:00:00+09:00",
                    "text": (
                        "6/21(日)『ARCHIVE DRY RUN LIVE』\n"
                        "会場：渋谷Milkyway\n"
                        "OPEN 18:00 / START 18:30\n"
                        "チケット：https://ticketdive.com/event/archive-dry-run"
                    ),
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    archive_text = json.dumps(
        {
            "captured_at": "2026-06-01T00:00:00+00:00",
            "source": "x_api",
            "metadata": {"username": "info_myojou", "latest_post_id": "399"},
            "data": [{"id": "399", "text": "old", "created_at": "2026-06-01T00:00:00+09:00"}],
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    archive_path.write_text(archive_text, encoding="utf-8")
    output_path.write_text("[]\n", encoding="utf-8")

    result = main(
        [
            "refresh-public",
            "--mock-posts",
            str(mock_path),
            "--db",
            str(tmp_path / "state.sqlite"),
            "--output",
            str(output_path),
            "--dry-run",
            "--x-archive",
            str(archive_path),
            "--update-archive",
        ]
    )
    output = capsys.readouterr().out

    assert result == 0
    assert archive_path.read_text(encoding="utf-8") == archive_text
    assert output_path.read_text(encoding="utf-8") == "[]\n"
    assert "Dry-run: X archive was not updated." in output


def test_refresh_public_validation_failure_does_not_modify_output_or_archive(tmp_path, monkeypatch, capsys):
    mock_path = tmp_path / "mock.json"
    archive_path = tmp_path / "archive.json"
    output_path = tmp_path / "events.json"
    mock_path.write_text(
        json.dumps(
            [
                {
                    "id": "500",
                    "created_at": "2026-06-13T09:00:00+09:00",
                    "text": (
                        "6/22(月)『ARCHIVE VALIDATION LIVE』\n"
                        "会場：渋谷Milkyway\n"
                        "OPEN 18:00 / START 18:30\n"
                        "チケット：https://ticketdive.com/event/archive-validation"
                    ),
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    archive_text = '{"source":"x_api","metadata":{},"data":[]}\n'
    output_text = "[]\n"
    archive_path.write_text(archive_text, encoding="utf-8")
    output_path.write_text(output_text, encoding="utf-8")

    def fail_validation(rows):
        return PublicValidationResult(event_count=len(rows), errors=["forced validation error"])

    monkeypatch.setattr("myojou_sync.cli.validate_public_rows", fail_validation)

    result = main(
        [
            "refresh-public",
            "--mock-posts",
            str(mock_path),
            "--db",
            str(tmp_path / "state.sqlite"),
            "--output",
            str(output_path),
            "--write",
            "--x-archive",
            str(archive_path),
            "--update-archive",
        ]
    )
    captured = capsys.readouterr()

    assert result == 1
    assert "validation_error: forced validation error" in captured.out
    assert "public/events.json was not written because validation failed." in captured.err
    assert archive_path.read_text(encoding="utf-8") == archive_text
    assert output_path.read_text(encoding="utf-8") == output_text
