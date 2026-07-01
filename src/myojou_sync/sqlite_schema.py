from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


SCHEMA_TABLES = (
    "source_posts",
    "venues",
    "events",
    "ticket_sales",
    "deadlines",
    "event_sources",
    "classification_reviews",
    "public_exports",
)

SCHEMA_INDEXES = (
    "ux_source_posts_platform_source_post_id",
    "idx_events_canonical_title_event_date",
    "idx_events_venue_id",
    "idx_ticket_sales_event_id",
    "idx_deadlines_event_id",
    "idx_deadlines_ticket_sale_id",
    "ux_event_sources_event_source",
    "idx_event_sources_source_post_id",
    "idx_classification_reviews_source_post_id",
    "idx_classification_reviews_event_id",
)

REQUIRED_COLUMNS = {
    "source_posts": {
        "id",
        "platform",
        "source_post_id",
        "author_handle",
        "text",
        "posted_at",
        "urls",
        "media_urls",
        "raw_payload",
        "fetched_at",
        "content_hash",
        "created_at",
        "updated_at",
    },
    "venues": {"id", "name", "normalized_name", "address", "area", "map_url", "created_at", "updated_at"},
    "events": {
        "id",
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
        "created_at",
        "updated_at",
    },
    "ticket_sales": {
        "id",
        "event_id",
        "label",
        "sale_type",
        "tier",
        "price",
        "url",
        "starts_at",
        "ends_at",
        "payment_deadline_at",
        "status",
        "created_at",
        "updated_at",
    },
    "deadlines": {
        "id",
        "event_id",
        "ticket_sale_id",
        "deadline_type",
        "deadline_at",
        "label",
        "created_at",
        "updated_at",
    },
    "event_sources": {
        "id",
        "event_id",
        "source_post_id",
        "source_url",
        "relation_type",
        "confidence",
        "created_at",
        "updated_at",
    },
    "classification_reviews": {
        "id",
        "source_post_id",
        "event_id",
        "rule_classification",
        "ai_classification",
        "final_classification",
        "confidence",
        "reasons",
        "risk_flags",
        "reviewed_by",
        "reviewed_at",
        "notes",
        "created_at",
        "updated_at",
    },
    "public_exports": {
        "id",
        "export_type",
        "output_path",
        "generated_at",
        "event_count",
        "content_hash",
        "notes",
    },
}


@dataclass(frozen=True)
class SQLiteSchemaInitResult:
    db_path: Path
    tables: tuple[str, ...]
    indexes: tuple[str, ...]


class SQLiteSchemaCompatibilityError(RuntimeError):
    pass


def initialize_sqlite_schema(db_path: str | Path) -> SQLiteSchemaInitResult:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        _ensure_compatible_existing_tables(conn)
        conn.executescript(_SCHEMA_SQL)
    return SQLiteSchemaInitResult(db_path=path, tables=SCHEMA_TABLES, indexes=SCHEMA_INDEXES)


def _ensure_compatible_existing_tables(conn: sqlite3.Connection) -> None:
    for table_name, required_columns in REQUIRED_COLUMNS.items():
        if not _table_exists(conn, table_name):
            continue
        existing_columns = _table_columns(conn, table_name)
        missing = sorted(required_columns - existing_columns)
        if missing:
            raise SQLiteSchemaCompatibilityError(
                f"Existing table {table_name!r} is not compatible with the future normalized schema; "
                f"missing columns: {', '.join(missing)}. Use a fresh DB path for init-db."
            )


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")}


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS source_posts (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL DEFAULT 'x',
    source_post_id TEXT NOT NULL,
    author_handle TEXT,
    text TEXT,
    posted_at TEXT,
    urls TEXT,
    media_urls TEXT,
    raw_payload TEXT,
    fetched_at TEXT,
    content_hash TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS venues (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    address TEXT,
    area TEXT,
    map_url TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    canonical_title TEXT NOT NULL,
    display_title TEXT NOT NULL,
    event_date TEXT,
    venue_id TEXT,
    open_time TEXT,
    start_time TEXT,
    end_time TEXT,
    status TEXT NOT NULL DEFAULT 'unknown',
    public_ready INTEGER NOT NULL DEFAULT 0,
    needs_review INTEGER NOT NULL DEFAULT 0,
    review_reasons TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (venue_id) REFERENCES venues(id) ON UPDATE CASCADE ON DELETE SET NULL,
    CHECK (public_ready IN (0, 1)),
    CHECK (needs_review IN (0, 1))
);

CREATE TABLE IF NOT EXISTS ticket_sales (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    label TEXT,
    sale_type TEXT NOT NULL DEFAULT 'unknown',
    tier TEXT NOT NULL DEFAULT 'unknown',
    price INTEGER,
    url TEXT,
    starts_at TEXT,
    ends_at TEXT,
    payment_deadline_at TEXT,
    status TEXT NOT NULL DEFAULT 'unknown',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (event_id) REFERENCES events(id) ON UPDATE CASCADE ON DELETE CASCADE,
    CHECK (sale_type IN ('lottery', 'first_come', 'general', 'unknown')),
    CHECK (tier IN ('VIP', 'priority', 'general', 'same_day', 'unknown')),
    CHECK (price IS NULL OR price >= 0)
);

CREATE TABLE IF NOT EXISTS deadlines (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    ticket_sale_id TEXT,
    deadline_type TEXT NOT NULL DEFAULT 'unknown',
    deadline_at TEXT,
    label TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (event_id) REFERENCES events(id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (ticket_sale_id) REFERENCES ticket_sales(id) ON UPDATE CASCADE ON DELETE SET NULL,
    CHECK (deadline_type IN ('lottery_application', 'first_come_application', 'payment', 'unknown'))
);

CREATE TABLE IF NOT EXISTS event_sources (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    source_post_id TEXT NOT NULL,
    source_url TEXT,
    relation_type TEXT,
    confidence REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (event_id) REFERENCES events(id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (source_post_id) REFERENCES source_posts(id) ON UPDATE CASCADE ON DELETE CASCADE,
    CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
);

CREATE TABLE IF NOT EXISTS classification_reviews (
    id TEXT PRIMARY KEY,
    source_post_id TEXT NOT NULL,
    event_id TEXT,
    rule_classification TEXT,
    ai_classification TEXT,
    final_classification TEXT,
    confidence REAL,
    reasons TEXT,
    risk_flags TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_post_id) REFERENCES source_posts(id) ON UPDATE CASCADE ON DELETE CASCADE,
    FOREIGN KEY (event_id) REFERENCES events(id) ON UPDATE CASCADE ON DELETE SET NULL,
    CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
);

CREATE TABLE IF NOT EXISTS public_exports (
    id TEXT PRIMARY KEY,
    export_type TEXT NOT NULL,
    output_path TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    event_count INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT,
    notes TEXT,
    CHECK (event_count >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_source_posts_platform_source_post_id
    ON source_posts(platform, source_post_id);
CREATE INDEX IF NOT EXISTS idx_events_canonical_title_event_date
    ON events(canonical_title, event_date);
CREATE INDEX IF NOT EXISTS idx_events_venue_id
    ON events(venue_id);
CREATE INDEX IF NOT EXISTS idx_ticket_sales_event_id
    ON ticket_sales(event_id);
CREATE INDEX IF NOT EXISTS idx_deadlines_event_id
    ON deadlines(event_id);
CREATE INDEX IF NOT EXISTS idx_deadlines_ticket_sale_id
    ON deadlines(ticket_sale_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_event_sources_event_source
    ON event_sources(event_id, source_post_id);
CREATE INDEX IF NOT EXISTS idx_event_sources_source_post_id
    ON event_sources(source_post_id);
CREATE INDEX IF NOT EXISTS idx_classification_reviews_source_post_id
    ON classification_reviews(source_post_id);
CREATE INDEX IF NOT EXISTS idx_classification_reviews_event_id
    ON classification_reviews(event_id);
"""
