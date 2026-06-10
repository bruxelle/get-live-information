from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


@dataclass
class PublicValidationResult:
    event_count: int = 0
    earliest_date: str = ""
    latest_date: str = ""
    needs_review_count: int = 0
    not_public_ready_count: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def read_public_rows(path: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        with Path(path).open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return [], []
    except json.JSONDecodeError as exc:
        return [], [f"invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}"]

    if not isinstance(payload, list):
        return [], ["public JSON must be a list of event objects"]
    if not all(isinstance(item, dict) for item in payload):
        return [], ["public JSON list must contain only event objects"]
    return payload, []


def validate_public_rows(rows: list[dict[str, Any]]) -> PublicValidationResult:
    result = PublicValidationResult(event_count=len(rows))
    dates: list[str] = []
    public_ids: set[str] = set()
    duplicate_public_ids: set[str] = set()
    composite_keys: set[tuple[str, str, str]] = set()
    duplicate_composites: set[tuple[str, str, str]] = set()

    for index, row in enumerate(rows, start=1):
        public_id = str(row.get("public_event_id") or "")
        if public_id:
            if public_id in public_ids:
                duplicate_public_ids.add(public_id)
            public_ids.add(public_id)

        if row.get("public_ready") is False:
            result.not_public_ready_count += 1
            result.errors.append(f"row {index}: public_ready=false")

        if row.get("needs_review"):
            result.needs_review_count += 1

        event_name = str(row.get("event_name") or row.get("title") or "").strip()
        if not event_name:
            result.errors.append(f"row {index}: event_name/title is required")

        event_date = str(row.get("event_date") or row.get("date") or "").strip()
        if not event_date:
            result.errors.append(f"row {index}: event_date is required")
        else:
            try:
                date.fromisoformat(event_date)
                dates.append(event_date)
            except ValueError:
                result.errors.append(f"row {index}: event_date is not parseable: {event_date}")

        ticket_url = str(row.get("ticket_url") or "").strip()
        if ticket_url and not _looks_like_url(ticket_url):
            result.errors.append(f"row {index}: ticket_url does not look like a URL: {ticket_url}")

        _check_secret_like_keys(row, result, prefix=f"row {index}")

        composite = (
            event_date,
            event_name.casefold(),
            str(row.get("venue") or "").strip().casefold(),
        )
        if all(composite):
            if composite in composite_keys:
                duplicate_composites.add(composite)
            composite_keys.add(composite)

    for public_id in sorted(duplicate_public_ids):
        result.errors.append(f"duplicate public_event_id: {public_id}")

    for event_date, event_name, venue in sorted(duplicate_composites):
        result.warnings.append(f"duplicate same date/title/venue: {event_date} {event_name} {venue}")

    if dates:
        result.earliest_date = min(dates)
        result.latest_date = max(dates)
    return result


def compare_public_rows(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, int]:
    before_by_key = {_public_row_key(row): row for row in before}
    after_by_key = {_public_row_key(row): row for row in after}
    before_keys = set(before_by_key)
    after_keys = set(after_by_key)
    shared_keys = before_keys & after_keys
    return {
        "events_before": len(before),
        "events_after": len(after),
        "added": len(after_keys - before_keys),
        "removed": len(before_keys - after_keys),
        "possibly_changed": sum(1 for key in shared_keys if before_by_key[key] != after_by_key[key]),
    }


def public_rows_summary(rows: list[dict[str, Any]]) -> dict[str, int | str]:
    validation = validate_public_rows(rows)
    return {
        "event_count": validation.event_count,
        "not_public_ready": validation.not_public_ready_count,
        "needs_review": validation.needs_review_count,
        "earliest_date": validation.earliest_date,
        "latest_date": validation.latest_date,
    }


def _public_row_key(row: dict[str, Any]) -> str:
    public_id = str(row.get("public_event_id") or "").strip()
    if public_id:
        return f"id:{public_id}"
    event_date = str(row.get("event_date") or row.get("date") or "").strip()
    event_name = str(row.get("event_name") or row.get("title") or "").strip()
    venue = str(row.get("venue") or "").strip()
    return f"composite:{event_date}|{event_name.casefold()}|{venue.casefold()}"


def _looks_like_url(value: str) -> bool:
    return value.startswith(("https://", "http://"))


def _check_secret_like_keys(row: dict[str, Any], result: PublicValidationResult, *, prefix: str) -> None:
    for key, value in row.items():
        key_text = str(key).casefold()
        if any(secret_word in key_text for secret_word in ("token", "secret", "authorization", "bearer")):
            result.errors.append(f"{prefix}: secret-like key must not be public: {key}")
        if isinstance(value, dict):
            _check_secret_like_keys(value, result, prefix=prefix)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _check_secret_like_keys(item, result, prefix=prefix)
