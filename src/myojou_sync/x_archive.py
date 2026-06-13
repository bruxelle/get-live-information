from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class XArchiveUpdateResult:
    path: Path
    added: int = 0
    updated: int = 0
    total_posts: int = 0
    latest_post_id: str = ""
    wrote: bool = False


def update_x_archive(path: str | Path, records: list[dict[str, Any]], *, username: str) -> XArchiveUpdateResult:
    archive_path = Path(path)
    existing_payload = _read_archive(archive_path)
    existing_records = _records_from_payload(existing_payload)
    records_by_id: dict[str, dict[str, Any]] = {}

    for record in existing_records:
        record_id = _record_id(record)
        if record_id:
            records_by_id[record_id] = _sanitize_public_archive_record(record)

    added = 0
    updated = 0
    for record in records:
        record_id = _record_id(record)
        if not record_id:
            continue
        clean_record = _sanitize_public_archive_record(record)
        previous = records_by_id.get(record_id)
        if previous is None:
            added += 1
            records_by_id[record_id] = clean_record
        elif _stable_json(previous) != _stable_json(clean_record):
            updated += 1
            records_by_id[record_id] = clean_record

    merged_records = sorted(records_by_id.values(), key=_record_sort_key)
    latest_post_id = _latest_post_id(merged_records)
    if not added and not updated:
        return XArchiveUpdateResult(
            path=archive_path,
            total_posts=len(merged_records),
            latest_post_id=latest_post_id,
            wrote=False,
        )

    now = datetime.now(timezone.utc).isoformat()
    existing_metadata = existing_payload.get("metadata") if isinstance(existing_payload.get("metadata"), dict) else {}
    metadata = _sanitize_public_archive_record(existing_metadata)
    metadata.update(
        {
            "username": username,
            "posts_fetched": len(merged_records),
            "total_posts": len(merged_records),
            "latest_post_id": latest_post_id,
            "updated_at": now,
        }
    )
    payload = {
        "captured_at": existing_payload.get("captured_at") or now,
        "updated_at": now,
        "source": "x_api",
        "metadata": metadata,
        "data": merged_records,
    }
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(_stable_json(payload) + "\n", encoding="utf-8")
    return XArchiveUpdateResult(
        path=archive_path,
        added=added,
        updated=updated,
        total_posts=len(merged_records),
        latest_post_id=latest_post_id,
        wrote=True,
    )


def _read_archive(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"source": "x_api", "metadata": {}, "data": []}
    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        logger.warning("X archive JSON is unreadable; starting with an empty archive. path=%s error=%s", path, exc)
        return {"source": "x_api", "metadata": {}, "data": []}
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        return {"source": "x_api", "metadata": {}, "data": payload}
    return {"source": "x_api", "metadata": {}, "data": []}


def _records_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = payload.get("data", [])
    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def _record_id(record: dict[str, Any]) -> str:
    value = record.get("id") or record.get("source_post_id") or record.get("post_id")
    return str(value) if value not in (None, "") else ""


def _sanitize_public_archive_record(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_secret_like_key(key_text) or key_text in {"already_processed", "linked_event_id"}:
                continue
            clean[key_text] = _sanitize_public_archive_record(item)
        return clean
    if isinstance(value, list):
        return [_sanitize_public_archive_record(item) for item in value]
    return value


def _is_secret_like_key(key: str) -> bool:
    key_text = key.casefold()
    return any(part in key_text for part in ("token", "secret", "authorization", "bearer"))


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _record_sort_key(record: dict[str, Any]) -> tuple[int, float, str, str]:
    record_id = _record_id(record)
    if record_id.isdigit():
        return (0, -float(record_id), "", record_id)
    return (1, -_created_at_timestamp(record), str(record.get("created_at") or ""), record_id)


def _latest_post_id(records: list[dict[str, Any]]) -> str:
    numeric_ids = [int(_record_id(record)) for record in records if _record_id(record).isdigit()]
    if numeric_ids:
        return str(max(numeric_ids))
    if not records:
        return ""
    latest = max(records, key=lambda record: (_created_at_timestamp(record), str(record.get("created_at") or ""), _record_id(record)))
    return _record_id(latest)


def _created_at_timestamp(record: dict[str, Any]) -> float:
    value = str(record.get("created_at") or "")
    if not value:
        return float("-inf")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return float("-inf")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()
