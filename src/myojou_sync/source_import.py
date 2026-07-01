from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .sqlite_schema import initialize_sqlite_schema


@dataclass(frozen=True)
class SourcePostImportResult:
    db_path: Path
    archive_path: Path
    read_count: int
    inserted_count: int
    updated_count: int
    skipped_count: int


def import_source_posts(db_path: str | Path, archive_path: str | Path) -> SourcePostImportResult:
    db = Path(db_path)
    archive = Path(archive_path)
    initialize_sqlite_schema(db)
    payload = _load_archive(archive)
    posts = _archive_posts(payload)
    fetched_at = _archive_fetched_at(payload)
    author_handle = _archive_author_handle(payload)

    inserted = 0
    updated = 0
    skipped = 0
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        for post in posts:
            record = _source_post_record(post, fetched_at=fetched_at, author_handle=author_handle)
            if not record:
                skipped += 1
                continue
            existing = conn.execute(
                """
                SELECT id, content_hash
                FROM source_posts
                WHERE platform = ? AND source_post_id = ?
                """,
                (record["platform"], record["source_post_id"]),
            ).fetchone()
            if existing is None:
                conn.execute(_INSERT_SQL, record)
                inserted += 1
            elif existing["content_hash"] != record["content_hash"]:
                record["id"] = existing["id"]
                conn.execute(_UPDATE_SQL, record)
                updated += 1
            else:
                skipped += 1

    return SourcePostImportResult(
        db_path=db,
        archive_path=archive,
        read_count=len(posts),
        inserted_count=inserted,
        updated_count=updated,
        skipped_count=skipped,
    )


def _load_archive(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _archive_posts(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "posts"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    raise ValueError("Archive JSON must be a list of posts or an object with a data/posts list.")


def _archive_fetched_at(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("captured_at", "updated_at"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            value = metadata.get("captured_at") or metadata.get("updated_at")
            if isinstance(value, str) and value:
                return value
    return datetime.now(timezone.utc).isoformat()


def _archive_author_handle(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    metadata = payload.get("metadata")
    candidates = [
        payload.get("username"),
        payload.get("author_handle"),
        metadata.get("username") if isinstance(metadata, dict) else None,
        metadata.get("author_handle") if isinstance(metadata, dict) else None,
    ]
    for value in candidates:
        if isinstance(value, str) and value:
            return value.lstrip("@")
    return None


def _source_post_record(
    post: dict[str, Any],
    *,
    fetched_at: str,
    author_handle: str | None,
) -> dict[str, Any] | None:
    post_id = _string_value(post.get("id") or post.get("source_post_id") or post.get("post_id"))
    if not post_id:
        return None
    text = _string_value(post.get("text")) or _string_value(post.get("full_text")) or _note_text(post)
    created_at = _string_value(post.get("created_at") or post.get("posted_at"))
    raw_payload = _json_dump(post)
    content_hash = _content_hash(
        {
            "id": post_id,
            "text": text,
            "created_at": created_at,
            "entities": post.get("entities"),
            "note_tweet": post.get("note_tweet"),
            "attachments": post.get("attachments"),
            "media": post.get("media"),
            "raw": post.get("raw"),
        }
    )
    return {
        "id": f"x:{post_id}",
        "platform": "x",
        "source_post_id": post_id,
        "author_handle": _post_author_handle(post) or author_handle,
        "text": text,
        "posted_at": created_at,
        "urls": _json_dump(_post_urls(post)),
        "media_urls": _json_dump(_post_media_urls(post)),
        "raw_payload": raw_payload,
        "fetched_at": fetched_at,
        "content_hash": content_hash,
    }


def _string_value(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _note_text(post: dict[str, Any]) -> str | None:
    note_tweet = post.get("note_tweet")
    if isinstance(note_tweet, dict):
        return _string_value(note_tweet.get("text"))
    return None


def _post_author_handle(post: dict[str, Any]) -> str | None:
    for key in ("author_handle", "username"):
        value = post.get(key)
        if isinstance(value, str) and value:
            return value.lstrip("@")
    raw = post.get("raw")
    if isinstance(raw, dict):
        for key in ("author_handle", "username"):
            value = raw.get(key)
            if isinstance(value, str) and value:
                return value.lstrip("@")
    return None


def _post_urls(post: dict[str, Any]) -> list[dict[str, Any]]:
    urls: list[dict[str, Any]] = []
    _extend_urls(urls, post.get("entities"))
    note_tweet = post.get("note_tweet")
    if isinstance(note_tweet, dict):
        _extend_urls(urls, note_tweet.get("entities"))
    raw = post.get("raw")
    if isinstance(raw, dict):
        _extend_urls(urls, raw.get("entities"))
        raw_note = raw.get("note_tweet")
        if isinstance(raw_note, dict):
            _extend_urls(urls, raw_note.get("entities"))
    seen = set()
    deduped = []
    for item in urls:
        key = item.get("expanded_url") or item.get("url") or json.dumps(item, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _extend_urls(target: list[dict[str, Any]], entities: Any) -> None:
    if not isinstance(entities, dict):
        return
    for item in entities.get("urls") or []:
        if isinstance(item, dict):
            target.append({
                key: item[key]
                for key in ("url", "expanded_url", "display_url", "media_key")
                if key in item
            })


def _post_media_urls(post: dict[str, Any]) -> list[dict[str, Any]]:
    media_items = post.get("media")
    if not isinstance(media_items, list):
        media_items = []
    output = []
    for item in media_items:
        if not isinstance(item, dict):
            continue
        output.append({
            key: item[key]
            for key in ("media_key", "type", "url", "preview_image_url", "width", "height", "alt_text")
            if key in item
        })
    return output


def _content_hash(value: dict[str, Any]) -> str:
    data = _json_dump(value).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


_INSERT_SQL = """
INSERT INTO source_posts (
    id,
    platform,
    source_post_id,
    author_handle,
    text,
    posted_at,
    urls,
    media_urls,
    raw_payload,
    fetched_at,
    content_hash
) VALUES (
    :id,
    :platform,
    :source_post_id,
    :author_handle,
    :text,
    :posted_at,
    :urls,
    :media_urls,
    :raw_payload,
    :fetched_at,
    :content_hash
)
"""


_UPDATE_SQL = """
UPDATE source_posts
SET
    author_handle = :author_handle,
    text = :text,
    posted_at = :posted_at,
    urls = :urls,
    media_urls = :media_urls,
    raw_payload = :raw_payload,
    fetched_at = :fetched_at,
    content_hash = :content_hash,
    updated_at = CURRENT_TIMESTAMP
WHERE id = :id
"""
