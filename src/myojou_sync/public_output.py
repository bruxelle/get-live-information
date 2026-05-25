from __future__ import annotations

import json
from typing import Any

from .models import CanonicalEvent


PUBLIC_COLUMNS = [
    "event_date",
    "weekday",
    "event_name",
    "venue",
    "open_time",
    "start_time",
    "myojou_performance_time",
    "benefit_event_time",
    "ticket_url",
    "general_ticket_price",
    "priority_ticket_name",
    "priority_ticket_price",
    "same_day_ticket_price",
    "ticket_status",
    "notes",
    "source_summary",
    "primary_source_url",
    "latest_source_url",
    "all_source_urls",
    "last_updated_at",
    "needs_review",
    "manual_override",
]

INTERNAL_COLUMNS = ["event_id"]
SHEET_HEADERS = INTERNAL_COLUMNS + PUBLIC_COLUMNS

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def weekday_label(event: CanonicalEvent) -> str:
    if not event.event_date:
        return ""
    return _WEEKDAYS[event.event_date.weekday()]


def event_to_public_dict(event: CanonicalEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "event_date": event.event_date.isoformat() if event.event_date else "",
        "weekday": weekday_label(event),
        "event_name": event.event_name or "",
        "venue": event.venue or "",
        "open_time": event.open_time or "",
        "start_time": event.start_time or "",
        "myojou_performance_time": event.myojou_performance_time or "",
        "benefit_event_time": event.benefit_event_time or "",
        "ticket_url": event.ticket_url or "",
        "general_ticket_price": event.general_ticket_price,
        "priority_ticket_name": event.priority_ticket_name or "",
        "priority_ticket_price": event.priority_ticket_price,
        "same_day_ticket_price": event.same_day_ticket_price,
        "ticket_status": event.ticket_status or "",
        "notes": event.notes or "",
        "source_summary": event.source_summary or "",
        "primary_source_url": event.primary_source_url or "",
        "latest_source_url": event.latest_source_url or "",
        "all_source_urls": "\n".join(event.all_source_urls),
        "last_updated_at": event.updated_at.isoformat(),
        "needs_review": event.needs_review,
        "manual_override": event.manual_override,
    }


def events_to_public_rows(events: list[CanonicalEvent]) -> list[dict[str, Any]]:
    return [event_to_public_dict(event) for event in sorted(events, key=_sort_key)]


def events_to_json(events: list[CanonicalEvent]) -> str:
    return json.dumps(events_to_public_rows(events), ensure_ascii=False, indent=2)


def events_to_table(events: list[CanonicalEvent]) -> str:
    rows = events_to_public_rows(events)
    columns = ["event_date", "weekday", "event_name", "venue", "start_time", "ticket_status", "needs_review"]
    table_rows = [[_cell(row.get(column)) for column in columns] for row in rows]
    widths = [
        max(len(column), *(len(row[index]) for row in table_rows)) if table_rows else len(column)
        for index, column in enumerate(columns)
    ]
    header = " | ".join(column.ljust(widths[index]) for index, column in enumerate(columns))
    divider = "-+-".join("-" * width for width in widths)
    body = [" | ".join(row[index].ljust(widths[index]) for index in range(len(columns))) for row in table_rows]
    return "\n".join([header, divider, *body])


def _sort_key(event: CanonicalEvent) -> tuple[str, str, str]:
    return (
        event.event_date.isoformat() if event.event_date else "9999-99-99",
        event.start_time or "",
        event.event_name or "",
    )


def _cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\n", " / ")
