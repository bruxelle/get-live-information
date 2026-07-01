from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .public_validation import compare_public_rows, read_public_rows, validate_public_rows


@dataclass(frozen=True)
class SQLitePreviewExportResult:
    db_path: Path
    output_path: Path
    rows: list[dict[str, Any]]
    validation_errors: list[str]
    validation_warnings: list[str]


_PUBLIC_SCHEMA_KEYS = frozenset({
    "public_event_id", "source_event_id", "event_date", "weekday", "event_name",
    "venue", "live_summary", "ticket_summary", "application_summary", "ticket_url",
    "ticket_status", "needs_review", "ticket_application_deadline_at",
    "payment_deadline_at", "ticket_sales", "next_ticket_deadline_at",
    "next_ticket_sale_type", "next_ticket_label", "public_ready",
    "public_not_ready_reasons", "review_reasons",
})


def sqlite_public_preview_rows(db_path: str | Path) -> list[dict[str, Any]]:
    db = Path(db_path)
    if not db.exists():
<<<<<<< HEAD
        raise FileNotFoundError(f"SQLite database not found: {db}")
=======
        raise FileNotFoundError(f"SQLite database does not exist: {db}")
    initialize_sqlite_schema(db)
>>>>>>> 549d0f8 (address sqlite public export review comments)
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                event.id,
                event.display_title,
                event.event_date,
                event.open_time,
                event.start_time,
                event.status,
                event.public_ready,
                event.needs_review,
                event.review_reasons,
                venue.name AS venue_name,
                MIN(source.source_url) AS source_url,
                GROUP_CONCAT(source.source_url, '\n') AS all_source_urls
            FROM events AS event
            LEFT JOIN venues AS venue ON venue.id = event.venue_id
            LEFT JOIN event_sources AS source ON source.event_id = event.id
            WHERE event.public_ready = 1
              AND event.needs_review = 0
            GROUP BY event.id
            ORDER BY event.event_date, event.display_title, event.id
            """
        ).fetchall()
    return [_preview_row_from_sqlite(row) for row in rows]


def write_sqlite_public_preview(db_path: str | Path, output_path: str | Path) -> SQLitePreviewExportResult:
    rows = sqlite_public_preview_rows(db_path)
    validation = validate_public_rows(rows)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return SQLitePreviewExportResult(
        db_path=Path(db_path),
        output_path=path,
        rows=rows,
        validation_errors=validation.errors,
        validation_warnings=validation.warnings,
    )


def sqlite_public_diff(db_path: str | Path, current_path: str | Path) -> dict[str, Any]:
    preview_rows = sqlite_public_preview_rows(db_path)
    current_rows, current_load_errors = read_public_rows(current_path)
    preview_validation = validate_public_rows(preview_rows)
    current_validation = validate_public_rows(current_rows)
    current_validation.errors[:0] = current_load_errors
<<<<<<< HEAD
    diff_counts = compare_public_rows(current_rows, [_to_public_schema_row(r) for r in preview_rows])
=======
    diff_counts = compare_public_rows(current_rows, _strip_preview_debug_keys(preview_rows))
>>>>>>> 549d0f8 (address sqlite public export review comments)
    current_keys = {_row_key(row): row for row in current_rows}
    preview_keys = {_row_key(row): row for row in preview_rows}
    current_titles = {_title_key(row) for row in current_rows if _title_key(row)}
    preview_titles = {_title_key(row) for row in preview_rows if _title_key(row)}
    return {
        **diff_counts,
        "current_validation_errors": len(current_validation.errors),
        "sqlite_validation_errors": len(preview_validation.errors),
        "current_validation_warnings": len(current_validation.warnings),
        "sqlite_validation_warnings": len(preview_validation.warnings),
        "titles_only_in_current": sorted(current_titles - preview_titles)[:20],
        "titles_only_in_sqlite": sorted(preview_titles - current_titles)[:20],
        "keys_only_in_current": sorted(set(current_keys) - set(preview_keys))[:20],
        "keys_only_in_sqlite": sorted(set(preview_keys) - set(current_keys))[:20],
        "sqlite_missing_fields": _missing_field_counts(preview_rows),
    }


def _to_public_schema_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k in _PUBLIC_SCHEMA_KEYS}


def _preview_row_from_sqlite(row: sqlite3.Row) -> dict[str, Any]:
    review_reasons = _json_list(row["review_reasons"])
    source_urls = _source_urls(row["all_source_urls"])
    event_name = row["display_title"] or ""
    event_date = row["event_date"] or ""
    return {
        "public_event_id": f"{row['id']}:{event_date or 'no-date'}",
        "source_event_id": row["id"],
        "event_date": event_date,
        "weekday": _weekday_label(event_date),
        "event_name": event_name,
        "venue": row["venue_name"] or "",
        "live_summary": _live_summary(row["start_time"], row["open_time"]),
        "ticket_summary": "",
        "application_summary": "",
        "ticket_url": "",
        "ticket_status": row["status"] or "unknown",
        "needs_review": bool(row["needs_review"]),
        "ticket_application_deadline_at": "",
        "payment_deadline_at": "",
        "ticket_sales": [],
        "next_ticket_deadline_at": "",
        "next_ticket_sale_type": "",
        "next_ticket_label": "",
        "public_ready": bool(row["public_ready"]),
        "public_not_ready_reasons": [],
        "review_reasons": review_reasons,
        "source_url": row["source_url"] or "",
        "all_source_urls": source_urls,
    }


def _weekday_label(value: str) -> str:
    from datetime import date

    if not value:
        return ""
    try:
        weekdays = ("月", "火", "水", "木", "金", "土", "日")
        return weekdays[date.fromisoformat(value).weekday()]
    except ValueError:
        return ""


def _live_summary(start_time: str | None, open_time: str | None) -> str:
    parts = []
    if open_time:
        parts.append(f"開場 {open_time}")
    if start_time:
        parts.append(f"開演 {start_time}")
    return " / ".join(parts)


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return [value]
    return [str(item) for item in payload] if isinstance(payload, list) else []


def _source_urls(value: str | None) -> list[str]:
    if not value:
        return []
    return [item for item in value.splitlines() if item]


def _row_key(row: dict[str, Any]) -> str:
    public_id = str(row.get("public_event_id") or "").strip()
    if public_id:
        return f"id:{public_id}"
    return "|".join(
        [
            str(row.get("event_date") or ""),
            str(row.get("event_name") or row.get("title") or "").casefold(),
            str(row.get("venue") or "").casefold(),
        ]
    )


def _title_key(row: dict[str, Any]) -> str:
    return str(row.get("event_name") or row.get("title") or "").strip().casefold()


def _missing_field_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    important_fields = ("event_date", "event_name", "venue", "ticket_url", "live_summary")
    return {
        field: sum(1 for row in rows if not row.get(field))
        for field in important_fields
    }


def _strip_preview_debug_keys(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    debug_keys = {"source_url", "all_source_urls"}
    return [
        {key: value for key, value in row.items() if key not in debug_keys}
        for row in rows
    ]
