from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import CanonicalEvent, ExtractedEvent, PostClassificationResult, SourceKind, XPost


class SQLiteStateStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_posts (
                    post_id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL DEFAULT 'x',
                    source_post_id TEXT,
                    source_url TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    posted_at TEXT NOT NULL,
                    source_posted_at TEXT,
                    source_text TEXT,
                    linked_event_id TEXT,
                    extraction_confidence REAL,
                    classification TEXT,
                    classification_confidence TEXT,
                    classification_reason TEXT,
                    payload_json TEXT NOT NULL,
                    processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS canonical_events (
                    event_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        self._ensure_source_post_columns()

    def get_state(self, key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_state (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_last_seen_post_id(self) -> str | None:
        return self.get_state("last_seen_post_id")

    def set_last_seen_post_id(self, post_id: str) -> None:
        self.set_state("last_seen_post_id", post_id)

    def get_cached_x_user_id(self, username: str) -> str | None:
        return self.get_state(f"x_user_id:{username.casefold()}")

    def set_cached_x_user_id(self, username: str, user_id: str) -> None:
        self.set_state(f"x_user_id:{username.casefold()}", user_id)

    def processed_post_ids(self) -> set[str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT post_id FROM source_posts").fetchall()
        return {row["post_id"] for row in rows}

    def has_processed_post(self, post_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM source_posts WHERE post_id = ?", (post_id,)).fetchone()
        return row is not None

    def save_source_post(self, extracted: ExtractedEvent, *, linked_event_id: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO source_posts (
                    post_id,
                    source_type,
                    source_post_id,
                    source_url,
                    source_kind,
                    posted_at,
                    source_posted_at,
                    source_text,
                    linked_event_id,
                    extraction_confidence,
                    classification,
                    classification_confidence,
                    classification_reason,
                    payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(post_id) DO UPDATE SET
                    source_type = excluded.source_type,
                    source_post_id = excluded.source_post_id,
                    source_url = excluded.source_url,
                    source_kind = excluded.source_kind,
                    posted_at = excluded.posted_at,
                    source_posted_at = excluded.source_posted_at,
                    source_text = excluded.source_text,
                    linked_event_id = excluded.linked_event_id,
                    extraction_confidence = excluded.extraction_confidence,
                    classification = excluded.classification,
                    classification_confidence = excluded.classification_confidence,
                    classification_reason = excluded.classification_reason,
                    payload_json = excluded.payload_json
                """,
                (
                    extracted.source_post_id,
                    extracted.source_type,
                    extracted.source_post_id,
                    extracted.source_url,
                    str(extracted.source_kind),
                    extracted.source_posted_at.isoformat(),
                    extracted.source_posted_at.isoformat(),
                    extracted.source_text,
                    linked_event_id,
                    extracted.extraction_confidence,
                    str(extracted.classification),
                    str(extracted.classification_confidence),
                    extracted.classification_reason,
                    _dump_model(extracted),
                ),
            )

    def save_classified_source_post(
        self,
        post: XPost,
        classification: PostClassificationResult,
        *,
        source_url: str,
        linked_event_id: str | None = None,
    ) -> None:
        payload = {
            "id": post.id,
            "text": post.text,
            "created_at": post.created_at.isoformat(),
            "raw": post.raw,
            "classification": classification.model_dump(mode="json"),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO source_posts (
                    post_id,
                    source_type,
                    source_post_id,
                    source_url,
                    source_kind,
                    posted_at,
                    source_posted_at,
                    source_text,
                    linked_event_id,
                    extraction_confidence,
                    classification,
                    classification_confidence,
                    classification_reason,
                    payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(post_id) DO UPDATE SET
                    source_type = excluded.source_type,
                    source_post_id = excluded.source_post_id,
                    source_url = excluded.source_url,
                    source_kind = excluded.source_kind,
                    posted_at = excluded.posted_at,
                    source_posted_at = excluded.source_posted_at,
                    source_text = excluded.source_text,
                    linked_event_id = excluded.linked_event_id,
                    extraction_confidence = excluded.extraction_confidence,
                    classification = excluded.classification,
                    classification_confidence = excluded.classification_confidence,
                    classification_reason = excluded.classification_reason,
                    payload_json = excluded.payload_json
                """,
                (
                    post.id,
                    "x",
                    post.id,
                    source_url,
                    str(classification.source_kind or SourceKind.OTHER),
                    post.created_at.isoformat(),
                    post.created_at.isoformat(),
                    post.text,
                    linked_event_id,
                    0.0,
                    str(classification.classification),
                    str(classification.confidence),
                    classification.reason,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                ),
            )

    def source_post_records(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    source_type,
                    COALESCE(source_post_id, post_id) AS source_post_id,
                    source_url,
                    COALESCE(source_posted_at, posted_at) AS source_posted_at,
                    source_text,
                    source_kind,
                    linked_event_id,
                    extraction_confidence,
                    classification,
                    classification_confidence,
                    classification_reason
                FROM source_posts
                ORDER BY posted_at, post_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def load_events(self) -> list[CanonicalEvent]:
        with self.connect() as conn:
            rows = conn.execute("SELECT payload_json FROM canonical_events ORDER BY updated_at, event_id").fetchall()
        return [CanonicalEvent.model_validate_json(row["payload_json"]) for row in rows]

    def save_event(self, event: CanonicalEvent) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO canonical_events (event_id, payload_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (event.event_id, _dump_model(event), event.updated_at.isoformat()),
            )

    def save_events(self, events: list[CanonicalEvent]) -> None:
        for event in events:
            self.save_event(event)

    def _ensure_source_post_columns(self) -> None:
        required_columns = {
            "source_type": "TEXT NOT NULL DEFAULT 'x'",
            "source_post_id": "TEXT",
            "source_posted_at": "TEXT",
            "source_text": "TEXT",
            "linked_event_id": "TEXT",
            "extraction_confidence": "REAL",
            "classification": "TEXT",
            "classification_confidence": "TEXT",
            "classification_reason": "TEXT",
        }
        with self.connect() as conn:
            existing = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(source_posts)").fetchall()
            }
            for column, column_type in required_columns.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE source_posts ADD COLUMN {column} {column_type}")
            conn.execute(
                """
                UPDATE source_posts
                SET
                    source_type = COALESCE(source_type, 'x'),
                    source_post_id = COALESCE(source_post_id, post_id),
                    source_posted_at = COALESCE(source_posted_at, posted_at)
                """
            )


def _dump_model(model: Any) -> str:
    return json.dumps(model.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
