from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import CanonicalEvent, ExtractedEvent, PostClassificationResult, XPost


def sample_record_for_post(
    post: XPost,
    *,
    source_url: str | None = None,
    classification: PostClassificationResult | None = None,
    extracted: ExtractedEvent | None = None,
    event: CanonicalEvent | None = None,
    already_processed: bool = False,
    merge_confidence: float | None = None,
) -> dict[str, Any]:
    raw = post.raw or {}
    parsed_subject = event or extracted
    reasons = needs_review_reasons(parsed_subject, merge_confidence=merge_confidence) if parsed_subject else []
    if classification and _looks_image_dependent(classification.reason):
        reasons = _append_unique(reasons, "likely image-dependent")

    record: dict[str, Any] = {
        "id": post.id,
        "text": post.text,
        "created_at": post.created_at.isoformat(),
        "url": source_url or raw.get("url"),
        "entities": raw.get("entities", {}),
        "attachments": raw.get("attachments", {}),
        "referenced_tweets": raw.get("referenced_tweets", []),
        "media": raw.get("media", []),
        "classification": classification.model_dump(mode="json") if classification else None,
        "parsed_fields": extracted.model_dump(mode="json") if extracted else None,
        "linked_event_id": event.event_id if event else None,
        "needs_review": bool(getattr(parsed_subject, "needs_review", False)) if parsed_subject else False,
        "needs_review_reasons": reasons,
        "already_processed": already_processed,
        "raw": raw,
    }
    return record


def needs_review_reasons(
    record: CanonicalEvent | ExtractedEvent | None,
    *,
    merge_confidence: float | None = None,
) -> list[str]:
    if record is None:
        return []

    reasons: list[str] = []
    if not getattr(record, "event_name", None):
        reasons.append("missing event_name")
    if not getattr(record, "venue", None):
        reasons.append("missing venue")
    if not _has_ticket_deadline(record):
        reasons.append("missing ticket deadline")

    classification_reason = getattr(record, "classification_reason", None)
    if _looks_image_dependent(classification_reason or "") or _looks_image_dependent(getattr(record, "source_text", "") or ""):
        reasons = _append_unique(reasons, "likely image-dependent")
    if merge_confidence is not None and 0 < merge_confidence < 0.72:
        reasons = _append_unique(reasons, "ambiguous event match")
    if classification_reason:
        reasons = _append_unique(reasons, f"classification: {classification_reason}")

    return reasons


def write_x_samples(
    path: str | Path,
    records: list[dict[str, Any]],
    *,
    metadata: dict[str, Any] | None = None,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": "x_api",
        "metadata": metadata or {},
        "data": records,
    }
    output_path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path


def _has_ticket_deadline(record: CanonicalEvent | ExtractedEvent) -> bool:
    if _is_free_event(record):
        return True
    if getattr(record, "ticket_application_deadline_at", None):
        return True
    for period in getattr(record, "ticket_sales", []) or []:
        if getattr(period, "deadline_at", None):
            return True
    return False


def _is_free_event(record: CanonicalEvent | ExtractedEvent) -> bool:
    if getattr(record, "ticket_sale_type", None) == "無料":
        return True
    if getattr(record, "general_ticket_price", None) == 0:
        return True
    for period in getattr(record, "ticket_sales", []) or []:
        if getattr(period, "sale_type", None) == "無料" or getattr(period, "price", None) == 0:
            return True
    return False


def _looks_image_dependent(value: str) -> bool:
    normalized = value.casefold()
    return any(token in normalized for token in ("image", "画像", "本日はこちら", "明日はこちら"))


def _append_unique(values: list[str], value: str) -> list[str]:
    if value not in values:
        values.append(value)
    return values


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value
