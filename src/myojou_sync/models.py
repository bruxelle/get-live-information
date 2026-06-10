from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SourceKind(StrEnum):
    INITIAL_ANNOUNCEMENT = "initial_announcement"
    TIMETABLE_UPDATE = "timetable_update"
    DAY_BEFORE_REMINDER = "day_before_reminder"
    SAME_DAY_REMINDER = "same_day_reminder"
    TICKET_UPDATE = "ticket_update"
    CORRECTION = "correction"
    SOLD_OUT = "sold_out"
    OTHER = "other"


class PostClassification(StrEnum):
    EVENT = "event"
    NON_EVENT = "non_event"
    NEEDS_REVIEW = "needs_review"


class ClassificationConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TicketSalePeriod(BaseModel):
    sale_type: str = "不明"
    ticket_name: str | None = None
    ticket_tier: str = "不明"
    price: int | None = None
    start_at: datetime | None = None
    deadline_at: datetime | None = None
    result_at: datetime | None = None
    payment_deadline_at: datetime | None = None
    status: str = "不明"
    source_url: str | None = None
    source_post_id: str | None = None
    notes: str | None = None


class PostClassificationResult(BaseModel):
    classification: PostClassification = PostClassification.NON_EVENT
    confidence: ClassificationConfidence = ClassificationConfidence.LOW
    reason: str = ""
    source_kind: SourceKind = SourceKind.OTHER


class XPost(BaseModel):
    id: str
    text: str
    created_at: datetime
    raw: dict[str, Any] = Field(default_factory=dict)
    api_text: str | None = None
    truncated_text: str | None = None
    full_text_source: str = "text"


class EventFields(BaseModel):
    event_date: date | None = None
    event_dates: list[date] = Field(default_factory=list)
    event_name: str | None = None
    venue: str | None = None
    open_time: str | None = None
    start_time: str | None = None
    myojou_performance_time: str | None = None
    benefit_event_time: str | None = None
    ticket_url: str | None = None
    general_ticket_price: int | None = None
    priority_ticket_name: str | None = None
    priority_ticket_price: int | None = None
    same_day_ticket_price: int | None = None
    ticket_application_start_at: datetime | None = None
    ticket_application_deadline_at: datetime | None = None
    lottery_result_at: datetime | None = None
    payment_deadline_at: datetime | None = None
    ticket_sale_type: str | None = None
    ticket_sales: list[TicketSalePeriod] = Field(default_factory=list)
    ticket_status: str | None = None
    notes: str | None = None


class SourceMetadata(BaseModel):
    source_type: str = "x"
    source_url: str
    source_post_id: str
    source_posted_at: datetime
    source_text: str
    source_raw: dict[str, Any] = Field(default_factory=dict)
    source_kind: SourceKind = SourceKind.OTHER
    extraction_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    classification: PostClassification | str = PostClassification.EVENT
    classification_confidence: ClassificationConfidence | str = ClassificationConfidence.MEDIUM
    classification_reason: str | None = None


class ExtractedEvent(EventFields, SourceMetadata):
    model_config = ConfigDict(use_enum_values=True)


class CanonicalEvent(EventFields):
    model_config = ConfigDict(use_enum_values=True)

    event_id: str = Field(default_factory=lambda: f"evt_{uuid4().hex}")
    needs_review: bool = False
    manual_override: bool = False

    primary_source_url: str | None = None
    latest_source_url: str | None = None
    all_source_urls: list[str] = Field(default_factory=list)
    source_summary: str | None = None
    last_source_posted_at: datetime | None = None
    last_source_kind: SourceKind | str | None = None
    source_post_ids: list[str] = Field(default_factory=list)

    source_type: str | None = None
    source_url: str | None = None
    source_post_id: str | None = None
    source_posted_at: datetime | None = None
    source_text: str | None = None
    source_kind: SourceKind | str | None = None
    extraction_confidence: float | None = None
    classification: PostClassification | str | None = None
    classification_confidence: ClassificationConfidence | str | None = None
    classification_reason: str | None = None

    notion_page_id: str | None = None
    google_row_number: int | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @classmethod
    def from_extracted(cls, extracted: ExtractedEvent, *, needs_review: bool = False) -> "CanonicalEvent":
        values = extracted.model_dump()
        return cls(
            **{key: values.get(key) for key in EventFields.model_fields},
            needs_review=needs_review,
            primary_source_url=extracted.source_url,
            latest_source_url=extracted.source_url,
            all_source_urls=[extracted.source_url],
            source_summary=source_summary_line(extracted),
            last_source_posted_at=extracted.source_posted_at,
            last_source_kind=extracted.source_kind,
            source_post_ids=[extracted.source_post_id],
            source_type=extracted.source_type,
            source_url=extracted.source_url,
            source_post_id=extracted.source_post_id,
            source_posted_at=extracted.source_posted_at,
            source_text=extracted.source_text,
            source_kind=extracted.source_kind,
            extraction_confidence=extracted.extraction_confidence,
            classification=extracted.classification,
            classification_confidence=extracted.classification_confidence,
            classification_reason=extracted.classification_reason,
        )


def source_summary_line(source: SourceMetadata) -> str:
    posted_at = source.source_posted_at.isoformat()
    return f"{posted_at} {source.source_kind}: {source.source_url}"
