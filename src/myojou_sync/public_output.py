from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from .merger import select_relevant_ticket_period
from .models import CanonicalEvent
from .normalization import normalize_event_name, normalize_url, normalize_venue
from .readiness import public_readiness
from .sample_capture import needs_review_reasons


PUBLIC_COLUMNS = [
    "event_name",
    "event_date",
    "weekday",
    "venue",
    "live_summary",
    "ticket_summary",
    "application_summary",
    "ticket_sales_summary",
    "next_ticket_deadline_at",
    "next_ticket_sale_type",
    "open_time",
    "start_time",
    "myojou_performance_time",
    "benefit_event_time",
    "ticket_url",
    "general_ticket_price",
    "priority_ticket_name",
    "priority_ticket_price",
    "same_day_ticket_price",
    "ticket_application_start_at",
    "ticket_application_deadline_at",
    "lottery_result_at",
    "payment_deadline_at",
    "ticket_sale_type",
    "ticket_status",
    "notes",
    "source_summary",
    "primary_source_url",
    "latest_source_url",
    "all_source_urls",
    "last_source_posted_at",
    "last_source_kind",
    "last_updated_at",
    "needs_review",
    "manual_override",
]

PUBLIC_COLUMN_LABELS = {
    "event_name": "イベント名",
    "event_date": "日付",
    "weekday": "曜日",
    "venue": "会場",
    "live_summary": "ライブ情報",
    "ticket_summary": "チケット情報",
    "application_summary": "申込情報",
    "ticket_sales_summary": "販売期間一覧",
    "next_ticket_deadline_at": "次の申込締切",
    "next_ticket_sale_type": "次の販売方式",
    "open_time": "開場",
    "start_time": "開演",
    "myojou_performance_time": "出演時間",
    "benefit_event_time": "特典会",
    "ticket_url": "チケットURL",
    "general_ticket_price": "一般料金",
    "priority_ticket_name": "優先種別",
    "priority_ticket_price": "優先料金",
    "same_day_ticket_price": "当日料金",
    "ticket_application_start_at": "申込開始",
    "ticket_application_deadline_at": "申込締切",
    "lottery_result_at": "当落発表",
    "payment_deadline_at": "支払期限",
    "ticket_sale_type": "販売方式",
    "ticket_status": "販売状況",
    "notes": "備考",
    "source_summary": "告知ポスト",
    "primary_source_url": "初回告知URL",
    "latest_source_url": "最新告知URL",
    "all_source_urls": "関連告知URL",
    "last_source_posted_at": "最新告知日時",
    "last_source_kind": "最新告知種別",
    "last_updated_at": "最終更新",
    "needs_review": "要確認",
    "manual_override": "手動更新",
}

SHEET_HEADERS = list(PUBLIC_COLUMN_LABELS.values())

PREVIEW_TABLE_COLUMNS = [
    "日付",
    "曜日",
    "イベント名",
    "会場",
    "ライブ情報",
    "チケット情報",
    "申込情報",
    "チケットURL",
    "要確認",
]

MOBILE_PREVIEW_COLUMNS = PREVIEW_TABLE_COLUMNS

PUBLIC_WEB_FIELDS = [
    "public_event_id",
    "source_event_id",
    "event_date",
    "weekday",
    "event_name",
    "venue",
    "live_summary",
    "ticket_summary",
    "application_summary",
    "ticket_url",
    "ticket_status",
    "needs_review",
    "ticket_application_deadline_at",
    "payment_deadline_at",
    "ticket_sales",
    "next_ticket_deadline_at",
    "next_ticket_sale_type",
    "next_ticket_label",
    "public_ready",
    "public_not_ready_reasons",
    "review_reasons",
]

_WEEKDAYS = ("月", "火", "水", "木", "金", "土", "日")

_TICKET_STATUS_LABELS = {
    "on_sale": "販売中",
    "upcoming": "未販売",
    "sold_out": "完売",
    "same_day": "販売中",
    "same_day_available": "販売中",
    "ended": "販売終了",
    "unknown": "不明",
    "未確認": "不明",
    "不明": "不明",
    "販売前": "未販売",
    "未販売": "未販売",
    "販売中": "販売中",
    "完売": "完売",
    "売切": "完売",
    "終了": "販売終了",
    "販売終了": "販売終了",
    "当日券あり": "販売中",
}

_TICKET_SALE_TYPE_LABELS = {
    "first_come": "先着",
    "lottery": "抽選",
    "general": "一般",
    "same_day": "当日券",
    "free": "無料",
    "unknown": "不明",
    "先着": "先着",
    "先着順": "先着",
    "抽選": "抽選",
    "一般": "一般",
    "一般販売": "一般",
    "当日券": "当日券",
    "無料": "無料",
    "不明": "不明",
}


def weekday_label(event: CanonicalEvent) -> str:
    if not event.event_date:
        return ""
    return _WEEKDAYS[event.event_date.weekday()]


def ticket_status_label(status: str | None) -> str:
    if not status:
        return _TICKET_STATUS_LABELS["unknown"]
    return _TICKET_STATUS_LABELS.get(status, status)


def ticket_sale_type_label(sale_type: str | None) -> str:
    if not sale_type:
        return _TICKET_SALE_TYPE_LABELS["unknown"]
    return _TICKET_SALE_TYPE_LABELS.get(sale_type, sale_type)


def live_summary(event: CanonicalEvent) -> str:
    parts = []
    if event.start_time:
        parts.append(f"開演 {event.start_time}")
    if event.myojou_performance_time:
        parts.append(f"出演 {event.myojou_performance_time}")
    if event.benefit_event_time:
        parts.append(f"特典会 {event.benefit_event_time}")
    return " / ".join(parts)


def ticket_summary(event: CanonicalEvent) -> str:
    if event.ticket_sales:
        return _ticket_sales_summary_short(event)
    sale_type = ticket_sale_type_label(event.ticket_sale_type)
    status = ticket_status_label(event.ticket_status)
    parts = [] if sale_type == "不明" and status in {"完売", "販売終了"} else [sale_type]
    if event.general_ticket_price is not None:
        parts.append(f"一般 {_yen(event.general_ticket_price)}")
    if event.priority_ticket_price is not None:
        label = _compact_priority_label(event.priority_ticket_name)
        parts.append(f"{label} {_yen(event.priority_ticket_price)}")
    if event.same_day_ticket_price is not None:
        parts.append(f"当日 {_yen(event.same_day_ticket_price)}")
    parts.append(status)
    return " / ".join(parts)


def application_summary(event: CanonicalEvent) -> str:
    if event.ticket_sales:
        sales_summary = _ticket_sales_application_summary(event)
        if sales_summary:
            return sales_summary
    start = _compact_datetime(event.ticket_application_start_at)
    deadline = _compact_datetime(event.ticket_application_deadline_at)
    lottery = _compact_datetime(event.lottery_result_at)
    payment = _compact_datetime(event.payment_deadline_at)
    parts = []
    if start and deadline:
        parts.append(f"申込 {start}〜{deadline}")
    elif deadline:
        parts.append(f"申込締切 {deadline}")
    elif start:
        parts.append(f"申込開始 {start}")
    if lottery:
        parts.append(f"当落 {lottery}")
    if payment:
        parts.append(f"支払 {payment}")
    return " / ".join(parts) if parts else "未取得"


def ticket_sales_summary(event: CanonicalEvent) -> str:
    if not event.ticket_sales:
        return ""
    return "\n".join(_ticket_sale_line(period) for period in _unique_ticket_sales_for_display(event))


def next_ticket_period(event: CanonicalEvent):
    return select_relevant_ticket_period(event.ticket_sales) if event.ticket_sales else None


def next_ticket_label(event: CanonicalEvent) -> str:
    period = next_ticket_period(event)
    if not period:
        return ""
    sale_type = ticket_sale_type_label(period.sale_type)
    parts = [sale_type]
    if period.ticket_name:
        if period.ticket_name != sale_type:
            parts.append(period.ticket_name)
    elif period.ticket_tier and period.ticket_tier != "不明":
        if period.ticket_tier != sale_type:
            parts.append(period.ticket_tier)
    return " ".join(part for part in parts if part)


def event_to_public_values(event: CanonicalEvent) -> dict[str, Any]:
    selected_period = next_ticket_period(event)
    return {
        "event_name": event.event_name or "",
        "event_date": event.event_date.isoformat() if event.event_date else "",
        "weekday": weekday_label(event),
        "venue": event.venue or "",
        "live_summary": live_summary(event),
        "ticket_summary": ticket_summary(event),
        "application_summary": application_summary(event),
        "ticket_sales_summary": ticket_sales_summary(event),
        "next_ticket_deadline_at": _datetime_value(selected_period.deadline_at if selected_period else None),
        "next_ticket_sale_type": ticket_sale_type_label(selected_period.sale_type if selected_period else event.ticket_sale_type),
        "open_time": event.open_time or "",
        "start_time": event.start_time or "",
        "myojou_performance_time": event.myojou_performance_time or "",
        "benefit_event_time": event.benefit_event_time or "",
        "ticket_url": event.ticket_url or "",
        "general_ticket_price": event.general_ticket_price,
        "priority_ticket_name": event.priority_ticket_name or "",
        "priority_ticket_price": event.priority_ticket_price,
        "same_day_ticket_price": event.same_day_ticket_price,
        "ticket_application_start_at": _datetime_value(event.ticket_application_start_at),
        "ticket_application_deadline_at": _datetime_value(event.ticket_application_deadline_at),
        "lottery_result_at": _datetime_value(event.lottery_result_at),
        "payment_deadline_at": _datetime_value(event.payment_deadline_at),
        "ticket_sale_type": ticket_sale_type_label(event.ticket_sale_type),
        "ticket_status": ticket_status_label(event.ticket_status),
        "notes": event.notes or "",
        "source_summary": event.source_summary or "",
        "primary_source_url": event.primary_source_url or "",
        "latest_source_url": event.latest_source_url or "",
        "all_source_urls": "\n".join(event.all_source_urls),
        "last_source_posted_at": _datetime_value(event.last_source_posted_at),
        "last_source_kind": str(event.last_source_kind or ""),
        "last_updated_at": event.updated_at.isoformat(),
        "needs_review": event.needs_review,
        "manual_override": event.manual_override,
    }


def event_to_public_dict(event: CanonicalEvent) -> dict[str, Any]:
    values = event_to_public_values(event)
    return {
        PUBLIC_COLUMN_LABELS[column]: values[column]
        for column in PUBLIC_COLUMNS
    }


def events_to_public_rows(events: list[CanonicalEvent]) -> list[dict[str, Any]]:
    return [event_to_public_dict(event) for event in sorted(events, key=_sort_key)]


def events_to_json(events: list[CanonicalEvent]) -> str:
    return json.dumps(events_to_public_rows(events), ensure_ascii=False, indent=2)


def event_to_web_dict(event: CanonicalEvent, occurrence_date: date | None = None) -> dict[str, Any]:
    occurrence = event.model_copy(update={"event_date": occurrence_date}) if occurrence_date else event
    values = event_to_public_values(occurrence)
    readiness = public_readiness(occurrence)
    date_key = values["event_date"] or "no-date"
    return {
        "public_event_id": f"{event.event_id}:{date_key}",
        "source_event_id": event.event_id,
        "event_date": values["event_date"],
        "weekday": values["weekday"],
        "event_name": values["event_name"],
        "venue": values["venue"],
        "live_summary": values["live_summary"],
        "ticket_summary": values["ticket_summary"],
        "application_summary": values["application_summary"],
        "ticket_url": values["ticket_url"],
        "ticket_status": values["ticket_status"],
        "needs_review": values["needs_review"],
        "ticket_application_deadline_at": values["ticket_application_deadline_at"],
        "payment_deadline_at": values["payment_deadline_at"],
        "ticket_sales": _ticket_sales_to_web(occurrence),
        "next_ticket_deadline_at": values["next_ticket_deadline_at"],
        "next_ticket_sale_type": values["next_ticket_sale_type"],
        "next_ticket_label": next_ticket_label(occurrence),
        "public_ready": readiness.public_ready,
        "public_not_ready_reasons": readiness.reasons,
        "review_reasons": needs_review_reasons(occurrence),
    }


def events_to_web_rows(events: list[CanonicalEvent]) -> list[dict[str, Any]]:
    rows_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for event in sorted(events, key=_sort_key):
        for occurrence_date in _occurrence_dates(event):
            row = event_to_web_dict(event, occurrence_date=occurrence_date)
            key = _occurrence_dedupe_key(event, occurrence_date)
            existing = rows_by_key.get(key)
            if existing is None or _web_row_score(row) > _web_row_score(existing):
                rows_by_key[key] = row
    return sorted(rows_by_key.values(), key=lambda row: (row.get("event_date") or "9999-99-99", row.get("event_name") or ""))


def events_to_web_json(events: list[CanonicalEvent]) -> str:
    return json.dumps(events_to_web_rows(events), ensure_ascii=False, indent=2)


def write_web_events_json(events: list[CanonicalEvent], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(events_to_web_json(events) + "\n", encoding="utf-8")
    return path


def events_to_table(events: list[CanonicalEvent]) -> str:
    rows = events_to_public_rows(events)
    columns = PREVIEW_TABLE_COLUMNS
    table_rows = [[_preview_cell(column, row.get(column)) for column in columns] for row in rows]
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


def _occurrence_dates(event: CanonicalEvent) -> list[date | None]:
    dates: list[date | None] = []
    if event.event_date:
        dates.append(event.event_date)
    dates.extend(event.event_dates or [])
    unique: list[date | None] = []
    seen: set[date | None] = set()
    for item in dates:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique or [None]


def _occurrence_dedupe_key(event: CanonicalEvent, occurrence_date: date | None) -> tuple[str, str, str]:
    date_key = occurrence_date.isoformat() if occurrence_date else ""
    name_key = normalize_event_name(event.event_name)
    location_or_ticket_key = normalize_venue(event.venue) or normalize_url(event.ticket_url) or event.event_id
    return date_key, name_key, location_or_ticket_key


def _web_row_score(row: dict[str, Any]) -> int:
    score = 0
    for value in row.values():
        if value not in (None, "", [], False):
            score += 1
    return score


def _cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\n", " / ")


_PREVIEW_DATE_COLUMNS = {"日付"}
_PREVIEW_DATETIME_COLUMNS = {"申込開始", "申込締切", "当落発表", "支払期限"}
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<hour>\d{2}):(?P<minute>\d{2})(?::\d{2})?")


def _preview_cell(column: str, value: Any) -> str:
    text = _cell(value)
    if not text:
        return ""
    if column in _PREVIEW_DATE_COLUMNS:
        return _format_preview_date(text)
    if column in _PREVIEW_DATETIME_COLUMNS:
        return _format_preview_datetime(text)
    return text


def _format_preview_date(value: str) -> str:
    if not _ISO_DATE_RE.match(value):
        return value
    return value.replace("-", "/")


def _format_preview_datetime(value: str) -> str:
    match = _ISO_DATETIME_RE.match(value)
    if not match:
        return value
    return f"{match.group('date').replace('-', '/')} {match.group('hour')}:{match.group('minute')}"


def _compact_datetime(value: Any) -> str:
    if not value:
        return ""
    if hasattr(value, "month") and hasattr(value, "day") and hasattr(value, "hour") and hasattr(value, "minute"):
        return f"{value.month}/{value.day} {value.hour:02d}:{value.minute:02d}"
    match = _ISO_DATETIME_RE.match(str(value))
    if not match:
        return ""
    month = int(match.group("date")[5:7])
    day = int(match.group("date")[8:10])
    return f"{month}/{day} {match.group('hour')}:{match.group('minute')}"


def _compact_deadline(value: Any) -> str:
    compact = _compact_datetime(value)
    if not compact:
        return ""
    return compact.split(" ", 1)[0] + "締切"


def _ticket_sales_summary_short(event: CanonicalEvent) -> str:
    if _has_same_day_surcharge(event):
        parts = []
        if event.priority_ticket_price is not None:
            parts.append(f"{_compact_priority_label(event.priority_ticket_name)} {_yen(event.priority_ticket_price)}")
        if event.general_ticket_price is not None:
            parts.append(f"一般 {_yen(event.general_ticket_price)}")
        if event.same_day_ticket_price is not None:
            parts.append(f"当日各+{_yen(event.same_day_ticket_price)}")
        return " / ".join(parts)

    unique_types = _unique_sale_types(event)
    parts: list[str] = []
    if len(unique_types) >= 2 and {"抽選", "一般"}.issubset(set(unique_types)):
        parts.append("抽選あり・一般販売あり")
    elif unique_types and not (unique_types == ["不明"] and _has_ticket_price_details(event)):
        sale_type = unique_types[0]
        has_clear_status_only = sale_type == "不明" and _has_terminal_ticket_status(event)
        has_redundant_general_price = sale_type == "一般" and event.general_ticket_price is not None
        if not has_clear_status_only and not has_redundant_general_price:
            parts.append("当日券あり" if sale_type == "当日券" else sale_type)
    if event.general_ticket_price is not None:
        parts.append(f"一般 {_yen(event.general_ticket_price)}")
    if event.priority_ticket_price is not None:
        parts.append(f"{_compact_priority_label(event.priority_ticket_name)} {_yen(event.priority_ticket_price)}")
    elif event.general_ticket_price is None:
        first_price = next((period for period in event.ticket_sales if period.price is not None), None)
        if first_price:
            label = first_price.ticket_name or first_price.ticket_tier
            parts.append(f"{label} {_yen(first_price.price)}" if label and label != "不明" else _yen(first_price.price))
    parts.extend(_additional_named_price_parts(event))
    parts.extend(_free_tier_summary_parts(event))
    selected = next_ticket_period(event)
    if selected and selected.deadline_at and len(unique_types) <= 1:
        parts.append(_compact_deadline(selected.deadline_at))
    if event.same_day_ticket_price is not None:
        parts.append(f"当日 {_yen(event.same_day_ticket_price)}")
    if not any(part in {"完売", "販売終了", "販売中", "未販売", "不明"} for part in parts):
        status = ticket_status_label(event.ticket_status)
        if status != "不明" or not parts:
            parts.append(status)
    return " / ".join(part for part in parts if part)


def _ticket_sales_application_summary(event: CanonicalEvent) -> str:
    parts: list[str] = []
    for period in _unique_ticket_sales_for_display(event):
        start = _compact_datetime(period.start_at)
        deadline = _compact_datetime(period.deadline_at)
        if start and deadline:
            label = "一般販売" if period.sale_type == "一般" else period.sale_type
            parts.append(f"{label} {start}〜{deadline}")
        elif deadline:
            parts.append(f"{period.sale_type}締切 {deadline}")
        elif start:
            label = "一般販売" if period.sale_type == "一般" else period.sale_type
            parts.append(f"{label} {start}〜")
        if period.result_at:
            parts.append(f"当落 {_compact_datetime(period.result_at)}")
        if period.payment_deadline_at:
            parts.append(f"支払 {_compact_datetime(period.payment_deadline_at)}")
    return " / ".join(parts) if parts else ""


def _unique_sale_types(event: CanonicalEvent) -> list[str]:
    types: list[str] = []
    for period in event.ticket_sales:
        sale_type = ticket_sale_type_label(period.sale_type)
        if sale_type and sale_type not in types:
            types.append(sale_type)
    return types


def _has_ticket_price_details(event: CanonicalEvent) -> bool:
    return bool(
        event.general_ticket_price is not None
        or event.priority_ticket_price is not None
        or event.same_day_ticket_price is not None
        or any(period.price is not None for period in event.ticket_sales)
    )


def _has_terminal_ticket_status(event: CanonicalEvent) -> bool:
    return ticket_status_label(event.ticket_status) in {"完売", "販売終了"} or any(
        period.status in {"完売", "販売終了"} for period in event.ticket_sales
    )


def _free_tier_summary_parts(event: CanonicalEvent) -> list[str]:
    parts: list[str] = []
    seen: set[str] = set()
    for period in event.ticket_sales:
        if period.price != 0 or period.sale_type == "無料":
            continue
        label = period.ticket_name or period.ticket_tier
        if not label or label in {"一般", "優先", "VIP", "SS", "前方", "カメラ", "不明"}:
            continue
        part = f"{label} {_yen(0)}" if "無料チケット" in label else f"{label} 無料"
        if part not in seen:
            seen.add(part)
            parts.append(part)
    return parts


def _additional_named_price_parts(event: CanonicalEvent) -> list[str]:
    represented_labels = {"一般"}
    if event.priority_ticket_name:
        represented_labels.add(_compact_priority_label(event.priority_ticket_name))
        represented_labels.add(event.priority_ticket_name)
    represented_tiers = {"一般"}
    if event.priority_ticket_price is not None:
        represented_tiers.update({"優先", "VIP", "SS", "前方", "カメラ"})

    parts: list[str] = []
    seen: set[str] = set()
    for period in event.ticket_sales:
        if period.price is None or period.price == 0:
            continue
        label = period.ticket_name or period.ticket_tier
        if not label or label == "不明":
            continue
        if label in represented_labels or period.ticket_tier in represented_tiers:
            continue
        part = f"{label} {_yen(period.price)}"
        if part not in seen:
            seen.add(part)
            parts.append(part)
    return parts


def _unique_ticket_sales_for_display(event: CanonicalEvent):
    unique = []
    seen: set[tuple[str, str, str]] = set()
    for period in sorted(event.ticket_sales, key=lambda item: (
        item.deadline_at.isoformat() if item.deadline_at else "9999-99-99",
        item.start_at.isoformat() if item.start_at else "9999-99-99",
        item.sale_type,
        item.ticket_tier,
    )):
        key = (
            period.sale_type,
            period.start_at.isoformat() if period.start_at else "",
            period.deadline_at.isoformat() if period.deadline_at else "",
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(period)
    return unique


def _ticket_sale_line(period) -> str:
    parts = [ticket_sale_type_label(period.sale_type)]
    if period.ticket_name:
        parts.append(period.ticket_name)
    elif period.ticket_tier and period.ticket_tier != "不明":
        parts.append(period.ticket_tier)
    if period.price is not None:
        parts.append(_yen(period.price))
    start = _compact_datetime(period.start_at)
    deadline = _compact_datetime(period.deadline_at)
    if start and deadline:
        parts.append(f"{start}〜{deadline}")
    elif deadline:
        parts.append(f"締切 {deadline}")
    elif start:
        parts.append(f"{start}〜")
    if period.status and period.status != "不明":
        parts.append(period.status)
    return " / ".join(part for part in parts if part)


def _has_same_day_surcharge(event: CanonicalEvent) -> bool:
    if event.same_day_ticket_price is None:
        return False
    source_text = (event.source_text or "").replace(" ", "")
    notes = (event.notes or "").replace(" ", "")
    return "当日各+" in source_text or "当日各+" in notes or "各+1D" in source_text or "各+1D" in notes


def _ticket_sales_to_web(event: CanonicalEvent) -> list[dict[str, Any]]:
    selected = next_ticket_period(event)
    selected_key = _ticket_period_key(selected) if selected else None
    rows = []
    for period in event.ticket_sales:
        key = _ticket_period_key(period)
        rows.append(
            {
                "sale_type": ticket_sale_type_label(period.sale_type),
                "ticket_name": period.ticket_name or "",
                "ticket_tier": period.ticket_tier or "不明",
                "price": period.price,
                "start_at": _datetime_value(period.start_at),
                "deadline_at": _datetime_value(period.deadline_at),
                "result_at": _datetime_value(period.result_at),
                "payment_deadline_at": _datetime_value(period.payment_deadline_at),
                "status": period.status or "不明",
                "source_url": period.source_url or "",
                "source_post_id": period.source_post_id or "",
                "notes": period.notes or "",
                "is_next_deadline": bool(selected_key and key == selected_key),
            }
        )
    return rows


def _ticket_period_key(period: Any) -> tuple[str, str, str, str] | None:
    if not period:
        return None
    return (
        period.sale_type,
        period.ticket_name or period.ticket_tier or "",
        _datetime_value(period.start_at),
        _datetime_value(period.deadline_at),
    )


def _yen(value: int | float) -> str:
    return f"{int(value):,}円"


def _compact_priority_label(value: str | None) -> str:
    if not value:
        return "優先"
    for label in ("優先", "前方", "Sチケット", "優先エリア"):
        if label in value:
            return "優先" if label == "優先エリア" else label
    return value[:16]


def _datetime_value(value: Any) -> str:
    return value.isoformat() if value else ""
