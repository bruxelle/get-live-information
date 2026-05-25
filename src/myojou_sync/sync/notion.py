from __future__ import annotations

from typing import Any

from myojou_sync.models import CanonicalEvent
from myojou_sync.public_output import event_to_public_dict


class NotionEventSink:
    def __init__(self, token: str | None, database_id: str | None) -> None:
        missing = []
        if not token:
            missing.append("NOTION_TOKEN")
        if not database_id:
            missing.append("NOTION_DATABASE_ID")
        if missing:
            raise ValueError(f"Notion sync is not configured; missing: {', '.join(missing)}")
        try:
            from notion_client import Client
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install notion-client to sync Notion.") from exc
        self.client = Client(auth=token)
        self.database_id = database_id

    def sync_events(self, events: list[CanonicalEvent]) -> list[CanonicalEvent]:
        return [self.sync_event(event) for event in events]

    def sync_event(self, event: CanonicalEvent) -> CanonicalEvent:
        page_id = event.notion_page_id or self.find_page_id(event.event_id)
        properties = _event_to_notion_properties(event)
        if page_id:
            existing = self.client.pages.retrieve(page_id=page_id)
            if _notion_checkbox(existing, "manual_override"):
                event.manual_override = True
                properties = _event_to_notion_properties(event, omit_protected=True)
            self.client.pages.update(page_id=page_id, properties=properties)
            event.notion_page_id = page_id
            return event

        response = self.client.pages.create(
            parent={"database_id": self.database_id},
            properties=properties,
        )
        event.notion_page_id = response["id"]
        return event

    def find_page_id(self, event_id: str) -> str | None:
        response = self.client.databases.query(
            database_id=self.database_id,
            filter={"property": "event_id", "rich_text": {"equals": event_id}},
            page_size=1,
        )
        results = response.get("results", [])
        return results[0]["id"] if results else None


def _event_to_notion_properties(event: CanonicalEvent, *, omit_protected: bool = False) -> dict[str, Any]:
    public = event_to_public_dict(event)
    data: dict[str, Any] = {
        "event_id": _rich_text(event.event_id),
        "weekday": _rich_text(public["weekday"]),
        "ticket_status": _select(event.ticket_status),
        "notes": _rich_text(event.notes),
        "source_summary": _rich_text(event.source_summary),
        "primary_source_url": _url(event.primary_source_url),
        "latest_source_url": _url(event.latest_source_url),
        "all_source_urls": _rich_text(public["all_source_urls"]),
        "last_updated_at": _date(event.updated_at.isoformat()),
        "needs_review": {"checkbox": event.needs_review},
        "manual_override": {"checkbox": event.manual_override},
        "last_source_posted_at": _date(event.last_source_posted_at.isoformat() if event.last_source_posted_at else None),
        "last_source_kind": _select(str(event.last_source_kind) if event.last_source_kind else None),
    }

    protected = {
        "event_date": _date(event.event_date.isoformat() if event.event_date else None),
        "event_name": _title(event.event_name or "Untitled live"),
        "venue": _rich_text(event.venue),
        "open_time": _rich_text(event.open_time),
        "start_time": _rich_text(event.start_time),
        "myojou_performance_time": _rich_text(event.myojou_performance_time),
        "benefit_event_time": _rich_text(event.benefit_event_time),
        "ticket_url": _url(event.ticket_url),
        "general_ticket_price": _number(event.general_ticket_price),
        "priority_ticket_name": _rich_text(event.priority_ticket_name),
        "priority_ticket_price": _number(event.priority_ticket_price),
        "same_day_ticket_price": _number(event.same_day_ticket_price),
    }

    if not omit_protected:
        data.update(protected)
    return data


def _notion_checkbox(page: dict[str, Any], property_name: str) -> bool:
    prop = page.get("properties", {}).get(property_name, {})
    return bool(prop.get("checkbox"))


def _title(value: str) -> dict[str, Any]:
    return {"title": [{"text": {"content": value[:2000]}}]}


def _rich_text(value: str | None) -> dict[str, Any]:
    return {"rich_text": [{"text": {"content": value[:2000]}}] if value else []}


def _url(value: str | None) -> dict[str, Any]:
    return {"url": value}


def _number(value: int | float | None) -> dict[str, Any]:
    return {"number": value}


def _date(value: str | None) -> dict[str, Any]:
    return {"date": {"start": value} if value else None}


def _select(value: str | None) -> dict[str, Any]:
    return {"select": {"name": value} if value else None}
