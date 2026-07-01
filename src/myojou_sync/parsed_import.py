from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .merger import EventMerger
from .models import CanonicalEvent, ExtractedEvent, PostClassification, SourceKind, XPost
from .normalization import normalize_event_name, normalize_url, normalize_venue
from .parser import PostParser
from .readiness import public_readiness
from .sample_capture import needs_review_reasons
from .sqlite_schema import initialize_sqlite_schema


@dataclass(frozen=True)
class ParsedEventImportResult:
    db_path: Path
    source_posts_read: int
    parsed_event_candidates: int
    events_inserted: int
    events_updated: int
    events_skipped: int
    event_sources_inserted: int
    event_sources_skipped: int


def import_parsed_events(db_path: str | Path, *, username: str = "info_myojou") -> ParsedEventImportResult:
    db = Path(db_path)
    initialize_sqlite_schema(db)
    parser = PostParser(username=username)
    merger = EventMerger()
    canonical_events: list[CanonicalEvent] = []
    extracted_by_post_id: dict[str, ExtractedEvent] = {}

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        source_rows = conn.execute(
            """
            SELECT *
            FROM source_posts
            WHERE platform = 'x'
            ORDER BY COALESCE(posted_at, fetched_at, created_at), source_post_id
            """
        ).fetchall()

        parsed_candidates = 0
        for row in source_rows:
            post = _xpost_from_source_row(row)
            classification = parser.classify_post(post)
            if classification.classification == PostClassification.NON_EVENT:
                continue
            extracted = parser.parse_post(post, classification=classification)
            if extracted is None:
                continue
            extracted_by_post_id[extracted.source_post_id] = extracted
            merger.merge_into_collection(extracted, canonical_events)
            parsed_candidates += 1

        event_counts = {"inserted": 0, "updated": 0, "skipped": 0}
        source_inserted = 0
        source_skipped = 0
        for event in canonical_events:
            for event_date in _event_dates_for_storage(event):
                event_record = _event_record(event, event_date=event_date)
                outcome = _upsert_event(conn, event_record)
                event_counts[outcome] += 1
                inserted_sources, skipped_sources = _insert_event_sources(
                    conn,
                    event_record["id"],
                    event,
                    extracted_by_post_id,
                )
                source_inserted += inserted_sources
                source_skipped += skipped_sources

    return ParsedEventImportResult(
        db_path=db,
        source_posts_read=len(source_rows),
        parsed_event_candidates=parsed_candidates,
        events_inserted=event_counts["inserted"],
        events_updated=event_counts["updated"],
        events_skipped=event_counts["skipped"],
        event_sources_inserted=source_inserted,
        event_sources_skipped=source_skipped,
    )


def _xpost_from_source_row(row: sqlite3.Row) -> XPost:
    raw = _json_load(row["raw_payload"]) if row["raw_payload"] else {}
    if isinstance(raw, dict):
        raw = {**raw}
    else:
        raw = {}
    raw.setdefault("url", f"https://x.com/info_myojou/status/{row['source_post_id']}")
    text = row["text"] or _raw_text(raw) or ""
    created_at = _parse_datetime(row["posted_at"]) or _parse_datetime(row["fetched_at"]) or datetime.now(timezone.utc)
    return XPost(
        id=row["source_post_id"],
        text=text,
        created_at=created_at,
        raw=raw,
        api_text=raw.get("api_text") if isinstance(raw.get("api_text"), str) else None,
        truncated_text=raw.get("truncated_text") if isinstance(raw.get("truncated_text"), str) else None,
        full_text_source=raw.get("full_text_source") if isinstance(raw.get("full_text_source"), str) else "text",
    )


def _raw_text(raw: dict[str, Any]) -> str | None:
    if isinstance(raw.get("text"), str):
        return raw["text"]
    note_tweet = raw.get("note_tweet")
    if isinstance(note_tweet, dict) and isinstance(note_tweet.get("text"), str):
        return note_tweet["text"]
    return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _json_load(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def _event_dates_for_storage(event: CanonicalEvent) -> list[Any]:
    dates = []
    if event.event_date:
        dates.append(event.event_date)
    dates.extend(event.event_dates or [])
    unique = []
    seen = set()
    for value in dates:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique or [None]


def _event_record(event: CanonicalEvent, *, event_date) -> dict[str, Any]:
    readiness = public_readiness(event)
    review_reasons = list(dict.fromkeys([*readiness.reasons, *needs_review_reasons(event)]))
    canonical_title = normalize_event_name(event.event_name) or "unknown"
    display_title = event.event_name or "未取得"
    venue_key = normalize_venue(event.venue)
    ticket_url_key = normalize_url(event.ticket_url)
    event_date_text = event_date.isoformat() if event_date else None
    identity_parts = [canonical_title, event_date_text or "", venue_key, ticket_url_key]
    if _is_weak_event_identity(event, event_date_text=event_date_text, venue_key=venue_key, ticket_url_key=ticket_url_key):
        identity_parts.append(",".join(sorted(event.source_post_ids)))
    event_id = _stable_id("evt_sqlite", *identity_parts)
    return {
        "id": event_id,
        "canonical_title": canonical_title,
        "display_title": display_title,
        "event_date": event_date_text,
        "venue_id": None,
        "open_time": event.open_time,
        "start_time": event.start_time,
        "end_time": None,
        "status": event.ticket_status or "unknown",
        "public_ready": 1 if readiness.public_ready else 0,
        "needs_review": 1 if event.needs_review else 0,
        "review_reasons": json.dumps(review_reasons, ensure_ascii=False, sort_keys=True),
    }


def _upsert_event(conn: sqlite3.Connection, record: dict[str, Any]) -> str:
    existing = conn.execute("SELECT * FROM events WHERE id = ?", (record["id"],)).fetchone()
    if existing is None:
        conn.execute(_INSERT_EVENT_SQL, record)
        return "inserted"
    comparable_fields = [
        "canonical_title",
        "display_title",
        "event_date",
        "venue_id",
        "open_time",
        "start_time",
        "end_time",
        "status",
        "public_ready",
        "needs_review",
        "review_reasons",
    ]
    if all(existing[field] == record[field] for field in comparable_fields):
        return "skipped"
    conn.execute(_UPDATE_EVENT_SQL, record)
    return "updated"


def _is_weak_event_identity(
    event: CanonicalEvent,
    *,
    event_date_text: str | None,
    venue_key: str,
    ticket_url_key: str,
) -> bool:
    return not event.event_name or not event_date_text or not (venue_key or ticket_url_key)


def _insert_event_sources(
    conn: sqlite3.Connection,
    event_id: str,
    event: CanonicalEvent,
    extracted_by_post_id: dict[str, ExtractedEvent],
) -> tuple[int, int]:
    inserted = 0
    skipped = 0
    for post_id in event.source_post_ids:
        extracted = extracted_by_post_id.get(post_id)
        source_row_id = f"x:{post_id}"
        source_url = extracted.source_url if extracted else f"https://x.com/info_myojou/status/{post_id}"
        relation_type = _relation_type(extracted.source_kind if extracted else None)
        confidence = extracted.extraction_confidence if extracted else None
        result = conn.execute(
            _INSERT_EVENT_SOURCE_SQL,
            {
                "id": _stable_id("evsrc_sqlite", event_id, source_row_id),
                "event_id": event_id,
                "source_post_id": source_row_id,
                "source_url": source_url,
                "relation_type": relation_type,
                "confidence": confidence,
            },
        )
        if result.rowcount:
            inserted += 1
        else:
            skipped += 1
    return inserted, skipped


def _relation_type(source_kind: SourceKind | str | None) -> str:
    value = str(source_kind or "")
    if value == SourceKind.INITIAL_ANNOUNCEMENT:
        return "initial_announcement"
    if value == SourceKind.TICKET_UPDATE:
        return "ticket_announcement"
    if value == SourceKind.TIMETABLE_UPDATE:
        return "timetable_update"
    if value in {SourceKind.DAY_BEFORE_REMINDER, SourceKind.SAME_DAY_REMINDER}:
        return "reminder"
    if value == SourceKind.CORRECTION:
        return "correction"
    return value or "unknown"


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\u0000".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


_INSERT_EVENT_SQL = """
INSERT INTO events (
    id,
    canonical_title,
    display_title,
    event_date,
    venue_id,
    open_time,
    start_time,
    end_time,
    status,
    public_ready,
    needs_review,
    review_reasons
) VALUES (
    :id,
    :canonical_title,
    :display_title,
    :event_date,
    :venue_id,
    :open_time,
    :start_time,
    :end_time,
    :status,
    :public_ready,
    :needs_review,
    :review_reasons
)
"""


_UPDATE_EVENT_SQL = """
UPDATE events
SET
    canonical_title = :canonical_title,
    display_title = :display_title,
    event_date = :event_date,
    venue_id = :venue_id,
    open_time = :open_time,
    start_time = :start_time,
    end_time = :end_time,
    status = :status,
    public_ready = :public_ready,
    needs_review = :needs_review,
    review_reasons = :review_reasons,
    updated_at = CURRENT_TIMESTAMP
WHERE id = :id
"""


_INSERT_EVENT_SOURCE_SQL = """
INSERT OR IGNORE INTO event_sources (
    id,
    event_id,
    source_post_id,
    source_url,
    relation_type,
    confidence
) VALUES (
    :id,
    :event_id,
    :source_post_id,
    :source_url,
    :relation_type,
    :confidence
)
"""
