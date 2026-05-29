from __future__ import annotations

import logging
from typing import Any

from myojou_sync.models import CanonicalEvent
from myojou_sync.public_output import PUBLIC_COLUMN_LABELS, event_to_public_dict


logger = logging.getLogger(__name__)


class NotionEventSink:
    def __init__(self, token: str | None, database_id: str | None, *, client: Any | None = None) -> None:
        missing = []
        if not token:
            missing.append("NOTION_TOKEN")
        if not database_id:
            missing.append("NOTION_DATABASE_ID")
        if missing:
            raise ValueError(f"Notion sync is not configured; missing: {', '.join(missing)}")
        if client is None:
            try:
                from notion_client import Client
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("Install notion-client to sync Notion.") from exc
            client = Client(auth=token)
        self.client = client
        self.database_id = database_id
        self._data_source_id: str | None = None
        self._property_types: dict[str, str] | None = None
        self._select_options: dict[str, tuple[str, ...]] | None = None
        self._schema_object: dict[str, Any] | None = None

    def sync_events(self, events: list[CanonicalEvent]) -> list[CanonicalEvent]:
        return [self.sync_event(event) for event in events]

    def sync_event(self, event: CanonicalEvent) -> CanonicalEvent:
        page_id = event.notion_page_id or self.find_page_id(event)
        properties = self.event_to_notion_properties(event)
        if page_id:
            existing = self.client.pages.retrieve(page_id=page_id)
            if _notion_checkbox(existing, "手動更新"):
                event.manual_override = True
                properties = self.event_to_notion_properties(event, omit_protected=True)
            try:
                self.client.pages.update(page_id=page_id, properties=properties)
            except Exception as exc:
                _log_notion_payload_error(event, properties, exc)
                raise
            event.notion_page_id = page_id
            return event

        try:
            response = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
            )
        except Exception as exc:
            _log_notion_payload_error(event, properties, exc)
            raise
        event.notion_page_id = response["id"]
        return event

    def event_to_notion_properties(self, event: CanonicalEvent, *, omit_protected: bool = False) -> dict[str, Any]:
        return _event_to_notion_properties(
            event,
            omit_protected=omit_protected,
            property_types=self.property_types(),
            select_options=self.select_options(),
        )

    def find_page_id(self, event: CanonicalEvent) -> str | None:
        if not event.event_name:
            return None
        query_filter: dict[str, Any]
        if event.event_date:
            query_filter = {
                "and": [
                    {"property": "イベント名", "title": {"equals": event.event_name}},
                    {"property": "日付", "date": {"equals": event.event_date.isoformat()}},
                ]
            }
        else:
            query_filter = {"property": "イベント名", "title": {"equals": event.event_name}}
        response = self.client.data_sources.query(
            data_source_id=self.resolve_data_source_id(),
            filter=query_filter,
            page_size=1,
        )
        results = response.get("results", [])
        return results[0]["id"] if results else None

    def resolve_data_source_id(self) -> str:
        if self._data_source_id:
            return self._data_source_id

        database = self.client.databases.retrieve(database_id=self.database_id)
        data_sources = database.get("data_sources") or []
        if not data_sources or not data_sources[0].get("id"):
            raise RuntimeError(
                "Could not resolve a Notion data source ID from NOTION_DATABASE_ID. "
                "Expected databases.retrieve(...) to return data_sources with at least one id."
            )

        self._data_source_id = data_sources[0]["id"]
        return self._data_source_id

    def property_types(self) -> dict[str, str]:
        if self._property_types is None:
            self._property_types = extract_property_types(self.retrieve_schema_object())
        return self._property_types

    def select_options(self) -> dict[str, tuple[str, ...]]:
        if self._select_options is None:
            self._select_options = extract_select_options(self.retrieve_schema_object())
        return self._select_options

    def inspect_schema(self) -> str:
        return format_database_schema(self.retrieve_schema_object())

    def retrieve_schema_object(self) -> dict[str, Any]:
        if self._schema_object is not None:
            return self._schema_object

        database = self.client.databases.retrieve(database_id=self.database_id)
        if database.get("properties"):
            self._schema_object = database
            return self._schema_object

        data_sources = database.get("data_sources") or []
        if data_sources and data_sources[0].get("id") and hasattr(self.client, "data_sources"):
            data_source_id = data_sources[0]["id"]
            self._data_source_id = data_source_id
            self._schema_object = self.client.data_sources.retrieve(data_source_id=data_source_id)
            return self._schema_object

        self._schema_object = database
        return self._schema_object


def _event_to_notion_properties(
    event: CanonicalEvent,
    *,
    omit_protected: bool = False,
    property_types: dict[str, str] | None = None,
    select_options: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    public = event_to_public_dict(event)
    property_types = property_types or DEFAULT_NOTION_PROPERTY_TYPES
    select_options = select_options or {}
    data: dict[str, Any] = {}
    _add_prop(data, property_types, "曜日", public["曜日"], select_options)
    _add_prop(data, property_types, "ライブ情報", public["ライブ情報"], select_options)
    _add_prop(data, property_types, "チケット情報", public["チケット情報"], select_options)
    _add_prop(data, property_types, "申込情報", public["申込情報"], select_options)
    _add_prop(data, property_types, "販売期間一覧", public.get("販売期間一覧"), select_options)
    _add_prop(data, property_types, "次の申込締切", public.get("次の申込締切"), select_options)
    _add_prop(data, property_types, "次の販売方式", public.get("次の販売方式"), select_options)
    _add_prop(data, property_types, "販売状況", public["販売状況"] or "未確認", select_options)
    _add_prop(data, property_types, "備考", public["備考"], select_options)
    _add_prop(data, property_types, "告知ポスト", _source_url_for_event(event), select_options)
    _add_prop(data, property_types, "最終更新", public["最終更新"], select_options)
    _add_prop(data, property_types, "要確認", event.needs_review, select_options)
    _add_prop(data, property_types, "手動更新", event.manual_override, select_options)

    protected: dict[str, Any] = {}
    _add_prop(protected, property_types, "日付", public["日付"], select_options)
    _add_prop(protected, property_types, "イベント名", public["イベント名"] or "未設定", select_options)
    _add_prop(protected, property_types, "会場", public["会場"], select_options)
    _add_prop(protected, property_types, "開場", public["開場"], select_options)
    _add_prop(protected, property_types, "開演", public["開演"], select_options)
    _add_prop(protected, property_types, "出演時間", public["出演時間"], select_options)
    _add_prop(protected, property_types, "特典会", public["特典会"], select_options)
    _add_prop(protected, property_types, "チケットURL", public["チケットURL"], select_options)
    _add_prop(protected, property_types, "一般料金", event.general_ticket_price, select_options)
    _add_prop(protected, property_types, "優先種別", public["優先種別"], select_options)
    _add_prop(protected, property_types, "優先料金", event.priority_ticket_price, select_options)
    _add_prop(protected, property_types, "当日料金", event.same_day_ticket_price, select_options)
    _add_prop(protected, property_types, "申込開始", public["申込開始"], select_options)
    _add_prop(protected, property_types, "申込締切", public["申込締切"], select_options)
    _add_prop(protected, property_types, "当落発表", public["当落発表"], select_options)
    _add_prop(protected, property_types, "支払期限", public["支払期限"], select_options)
    _add_prop(protected, property_types, "販売方式", public["販売方式"], select_options)

    if not omit_protected:
        data.update(protected)
    return data


NOTION_PUBLIC_PROPERTY_NAMES = list(PUBLIC_COLUMN_LABELS.values())

SUPPORTED_NOTION_PROPERTY_TYPES = {"title", "date", "rich_text", "url", "number", "select", "checkbox"}

DEFAULT_NOTION_PROPERTY_TYPES = {
    "イベント名": "title",
    "日付": "date",
    "曜日": "select",
    "ライブ情報": "rich_text",
    "チケット情報": "rich_text",
    "申込情報": "rich_text",
    "販売期間一覧": "rich_text",
    "次の申込締切": "date",
    "次の販売方式": "select",
    "会場": "rich_text",
    "開場": "rich_text",
    "開演": "rich_text",
    "出演時間": "rich_text",
    "特典会": "rich_text",
    "チケットURL": "url",
    "一般料金": "number",
    "優先種別": "rich_text",
    "優先料金": "number",
    "当日料金": "number",
    "申込開始": "date",
    "申込締切": "date",
    "当落発表": "date",
    "支払期限": "date",
    "販売方式": "select",
    "販売状況": "select",
    "備考": "rich_text",
    "告知ポスト": "url",
    "最終更新": "date",
    "要確認": "checkbox",
    "手動更新": "checkbox",
}

OPTIONAL_NOTION_PROPERTY_NAMES = {"販売期間一覧", "次の申込締切", "次の販売方式"}


def inspect_notion_schema(token: str | None, database_id: str | None, *, client: Any | None = None) -> str:
    sink = NotionEventSink(token, database_id, client=client)
    return sink.inspect_schema()


def extract_property_types(database: dict[str, Any]) -> dict[str, str]:
    return {
        name: definition.get("type", "unknown")
        for name, definition in database.get("properties", {}).items()
    }


def extract_select_options(database: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    options: dict[str, tuple[str, ...]] = {}
    for name, definition in database.get("properties", {}).items():
        if definition.get("type") != "select":
            continue
        raw_options = definition.get("select", {}).get("options", [])
        options[name] = tuple(option["name"] for option in raw_options if option.get("name"))
    return options


def format_database_schema(database: dict[str, Any]) -> str:
    lines: list[str] = []
    data_sources = database.get("data_sources") or []
    if database.get("object") == "data_source" and database.get("id"):
        lines.append(f"data_source_id: {database['id']}")
    elif data_sources and data_sources[0].get("id"):
        lines.append(f"data_source_id: {data_sources[0]['id']}")
    else:
        lines.append("data_source_id: unresolved")
    lines.append("properties:")
    for name, definition in sorted(database.get("properties", {}).items()):
        prop_type = definition.get("type", "unknown")
        supported = prop_type in SUPPORTED_NOTION_PROPERTY_TYPES
        lines.append(f"- {name}: ({prop_type}) {'supported' if supported else 'unsupported'}")
        if prop_type == "select":
            options = definition.get("select", {}).get("options", [])
            option_names = [option.get("name", "") for option in options if option.get("name")]
            lines.append(f"  options: {', '.join(option_names) if option_names else '(none)'}")
    return "\n".join(lines)


def title_prop(value: str | None) -> dict[str, Any]:
    text = (value or "")[:2000]
    return {"title": [{"text": {"content": text}}] if text else []}


def rich_text_prop(value: str | None) -> dict[str, Any]:
    text = (value or "")[:2000]
    return {"rich_text": [{"text": {"content": text}}] if text else []}


def select_prop(value: str | None) -> dict[str, Any]:
    return {"select": {"name": value or "未確認"}}


def url_prop(value: str | None) -> dict[str, Any]:
    return {"url": value or None}


def number_prop(value: int | float | None) -> dict[str, Any]:
    return {"number": value}


def date_prop(value: str | None) -> dict[str, Any]:
    return {"date": {"start": value} if value else None}


def checkbox_prop(value: bool | None) -> dict[str, Any]:
    return {"checkbox": bool(value)}


def _add_prop(
    properties: dict[str, Any],
    property_types: dict[str, str],
    name: str,
    value: Any,
    select_options: dict[str, tuple[str, ...]] | None = None,
) -> None:
    if (
        name in OPTIONAL_NOTION_PROPERTY_NAMES
        and property_types is not DEFAULT_NOTION_PROPERTY_TYPES
        and name not in property_types
    ):
        return
    prop_type = property_types.get(name, DEFAULT_NOTION_PROPERTY_TYPES.get(name))
    if prop_type == "title":
        properties[name] = title_prop(str(value) if value is not None else None)
    elif prop_type == "rich_text":
        properties[name] = rich_text_prop(str(value) if value is not None else None)
    elif prop_type == "select":
        properties[name] = select_prop(_select_value_for_property(name, str(value) if value else None, select_options or {}))
    elif prop_type == "url":
        properties[name] = url_prop(str(value) if value else None)
    elif prop_type == "number":
        properties[name] = number_prop(value if isinstance(value, (int, float)) else None)
    elif prop_type == "date":
        properties[name] = date_prop(str(value) if value else None)
    elif prop_type == "checkbox":
        properties[name] = checkbox_prop(bool(value))
    elif prop_type is None:
        return
    else:
        properties[name] = rich_text_prop(str(value) if value is not None else None)


def _source_url_for_event(event: CanonicalEvent) -> str | None:
    return event.latest_source_url or event.primary_source_url or (event.all_source_urls[0] if event.all_source_urls else None)


def _select_value_for_property(
    property_name: str,
    value: str | None,
    select_options: dict[str, tuple[str, ...]],
) -> str:
    requested = _notion_select_requested_value(property_name, value)
    if property_name == "販売状況":
        return requested

    available = select_options.get(property_name, ())
    if not available or requested in available:
        return requested

    if "不明" in available:
        return "不明"
    return available[0]


NOTION_TICKET_STATUS_LABELS = {
    "unknown": "不明",
    "未確認": "不明",
    "不明": "不明",
    "upcoming": "未販売",
    "販売前": "未販売",
    "未販売": "未販売",
    "on_sale": "販売中",
    "販売中": "販売中",
    "same_day": "販売中",
    "当日券あり": "販売中",
    "sold_out": "完売",
    "完売": "完売",
    "売切": "完売",
    "ended": "販売終了",
    "終了": "販売終了",
    "販売終了": "販売終了",
}


def _notion_select_requested_value(property_name: str, value: str | None) -> str:
    requested = value or "未確認"
    if property_name == "販売状況":
        return NOTION_TICKET_STATUS_LABELS.get(requested, requested)
    return requested


def _log_notion_payload_error(event: CanonicalEvent, properties: dict[str, Any], exc: Exception) -> None:
    logger.error(
        "Notion API error while syncing event_name=%r property_names=%s payload_keys=%s error=%s",
        event.event_name,
        sorted(properties),
        {name: sorted(payload.keys()) for name, payload in properties.items() if isinstance(payload, dict)},
        exc,
    )


def _notion_checkbox(page: dict[str, Any], property_name: str) -> bool:
    prop = page.get("properties", {}).get(property_name, {})
    return bool(prop.get("checkbox"))


def _title(value: str) -> dict[str, Any]:
    return title_prop(value)


def _rich_text(value: str | None) -> dict[str, Any]:
    return rich_text_prop(value)


def _url(value: str | None) -> dict[str, Any]:
    return url_prop(value)


def _number(value: int | float | None) -> dict[str, Any]:
    return number_prop(value)


def _date(value: str | None) -> dict[str, Any]:
    return date_prop(value)


def _select(value: str | None) -> dict[str, Any]:
    return select_prop(value)
