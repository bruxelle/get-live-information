from __future__ import annotations

import json
import sqlite3

from myojou_sync.cli import main
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


def _row(db_path, post_id: str):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            """
            SELECT *
            FROM source_posts
            WHERE platform = 'x' AND source_post_id = ?
            """,
            (post_id,),
        ).fetchone()


def test_import_source_posts_initializes_schema_and_stores_key_fields(tmp_path):
    db_path = tmp_path / "myojou.sqlite"
    archive_path = tmp_path / "archive.json"
    _write_archive(
        archive_path,
        [
            {
                "id": "100001",
                "text": "短縮本文 https://t.co/live",
                "created_at": "2026-06-29T14:23:45+00:00",
                "url": "https://x.com/info_myojou/status/100001",
                "entities": {
                    "urls": [
                        {
                            "url": "https://t.co/photo",
                            "expanded_url": "https://x.com/info_myojou/status/100001/photo/1",
                            "display_url": "pic.x.com/photo",
                            "media_key": "3_100001",
                        }
                    ]
                },
                "note_tweet": {
                    "text": "全文 https://t.co/live",
                    "entities": {
                        "urls": [
                            {
                                "url": "https://t.co/live",
                                "expanded_url": "https://t-dv.com/example",
                                "display_url": "t-dv.com/example",
                            }
                        ]
                    },
                },
                "media": [
                    {
                        "media_key": "3_100001",
                        "type": "photo",
                        "url": "https://pbs.twimg.com/media/example.jpg",
                        "width": 1200,
                        "height": 800,
                    }
                ],
                "raw": {"id": "100001", "extra": "preserved"},
            }
        ],
    )

    result = import_source_posts(db_path, archive_path)
    row = _row(db_path, "100001")

    assert result.read_count == 1
    assert result.inserted_count == 1
    assert result.updated_count == 0
    assert result.skipped_count == 0
    assert row is not None
    assert row["id"] == "x:100001"
    assert row["platform"] == "x"
    assert row["source_post_id"] == "100001"
    assert row["author_handle"] == "info_myojou"
    assert row["text"] == "短縮本文 https://t.co/live"
    assert row["posted_at"] == "2026-06-29T14:23:45+00:00"
    assert row["fetched_at"] == "2026-06-30T12:00:00+00:00"
    assert row["content_hash"]
    urls = json.loads(row["urls"])
    media_urls = json.loads(row["media_urls"])
    raw_payload = json.loads(row["raw_payload"])
    assert {"expanded_url": "https://t-dv.com/example", "display_url": "t-dv.com/example", "url": "https://t.co/live"} in urls
    assert media_urls == [
        {
            "height": 800,
            "media_key": "3_100001",
            "type": "photo",
            "url": "https://pbs.twimg.com/media/example.jpg",
            "width": 1200,
        }
    ]
    assert raw_payload["raw"]["extra"] == "preserved"


def test_import_source_posts_is_idempotent_and_updates_changed_content(tmp_path):
    db_path = tmp_path / "myojou.sqlite"
    archive_path = tmp_path / "archive.json"
    post = {
        "id": "100002",
        "text": "初回本文",
        "created_at": "2026-06-29T14:23:45+00:00",
        "entities": {"urls": []},
    }
    _write_archive(archive_path, [post])

    first = import_source_posts(db_path, archive_path)
    second = import_source_posts(db_path, archive_path)
    first_hash = _row(db_path, "100002")["content_hash"]

    changed = {**post, "text": "更新本文"}
    _write_archive(archive_path, [changed])
    third = import_source_posts(db_path, archive_path)
    row = _row(db_path, "100002")

    assert (first.inserted_count, first.updated_count, first.skipped_count) == (1, 0, 0)
    assert (second.inserted_count, second.updated_count, second.skipped_count) == (0, 0, 1)
    assert (third.inserted_count, third.updated_count, third.skipped_count) == (0, 1, 0)
    assert row["text"] == "更新本文"
    assert row["content_hash"] != first_hash
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM source_posts").fetchone()[0]
    assert count == 1


def test_import_source_posts_cli_prints_summary(tmp_path, capsys):
    db_path = tmp_path / "myojou.sqlite"
    archive_path = tmp_path / "archive.json"
    _write_archive(
        archive_path,
        [{"id": "100003", "text": "CLI import", "created_at": "2026-06-29T14:23:45+00:00"}],
    )

    result = main(["import-source-posts", "--db", str(db_path), "--archive", str(archive_path)])
    output = capsys.readouterr().out

    assert result == 0
    assert "Imported source posts:" in output
    assert "read: 1" in output
    assert "inserted: 1" in output
    assert "updated: 0" in output
    assert "skipped: 0" in output
    assert _row(db_path, "100003") is not None


def test_import_source_posts_skips_posts_without_ids(tmp_path):
    db_path = tmp_path / "myojou.sqlite"
    archive_path = tmp_path / "archive.json"
    _write_archive(archive_path, [{"text": "idなし"}])

    result = import_source_posts(db_path, archive_path)

    assert result.read_count == 1
    assert result.inserted_count == 0
    assert result.updated_count == 0
    assert result.skipped_count == 1
