from __future__ import annotations

import json
from typing import Any

from myojou_sync.merger import MANUAL_PROTECTED_FIELDS
from myojou_sync.models import CanonicalEvent
from myojou_sync.public_output import PUBLIC_COLUMN_LABELS, SHEET_HEADERS, event_to_public_dict


class GoogleSheetsEventSink:
    def __init__(self, service_account_json: str | None, sheet_id: str | None, worksheet_name: str = "Live Schedule") -> None:
        missing = []
        if not service_account_json:
            missing.append("GOOGLE_SERVICE_ACCOUNT_JSON")
        if not sheet_id:
            missing.append("GOOGLE_SHEET_ID")
        if missing:
            raise ValueError(f"Google Sheets sync is not configured; missing: {', '.join(missing)}")
        try:
            import gspread
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install gspread to sync Google Sheets.") from exc

        credentials = json.loads(service_account_json)
        client = gspread.service_account_from_dict(credentials)
        spreadsheet = client.open_by_key(sheet_id)
        try:
            self.worksheet = spreadsheet.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            self.worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=len(SHEET_HEADERS))
        self.ensure_headers()

    def ensure_headers(self) -> None:
        existing = self.worksheet.row_values(1)
        if existing != SHEET_HEADERS:
            self.worksheet.update([SHEET_HEADERS], "A1")

    def sync_events(self, events: list[CanonicalEvent]) -> list[CanonicalEvent]:
        rows = self.worksheet.get_all_records()
        event_key_to_row = {
            _sheet_key(row): index + 2
            for index, row in enumerate(rows)
            if _sheet_key(row)
        }

        for event in events:
            values = _event_to_sheet_row(event)
            public = event_to_public_dict(event)
            row_number = event_key_to_row.get(_sheet_key(public))
            if row_number:
                existing = rows[row_number - 2]
                if _truthy(existing.get("手動更新")):
                    event.manual_override = True
                    values = _merge_with_manual_override(existing, values)
                self.worksheet.update([values], f"A{row_number}")
                event.google_row_number = row_number
            else:
                self.worksheet.append_row(values, value_input_option="USER_ENTERED")
                event.google_row_number = len(rows) + 2
                rows.append(dict(zip(SHEET_HEADERS, values, strict=False)))
        return events


def _event_to_sheet_row(event: CanonicalEvent) -> list[Any]:
    values = event_to_public_dict(event)
    return [values[header] if values[header] is not None else "" for header in SHEET_HEADERS]


def _merge_with_manual_override(existing: dict[str, Any], values: list[Any]) -> list[Any]:
    merged = dict(zip(SHEET_HEADERS, values, strict=False))
    for field_name in MANUAL_PROTECTED_FIELDS:
        label = PUBLIC_COLUMN_LABELS.get(field_name)
        if label and label in existing:
            merged[label] = existing[label]
    merged["手動更新"] = True
    return [merged[header] for header in SHEET_HEADERS]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"true", "yes", "1", "y"}


def _sheet_key(row: dict[str, Any]) -> tuple[str, str, str] | None:
    event_name = str(row.get("イベント名") or "").strip()
    event_date = str(row.get("日付") or "").strip()
    venue = str(row.get("会場") or "").strip()
    if not event_name and not event_date and not venue:
        return None
    return event_date, event_name, venue
