from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from .models import CanonicalEvent, EventFields, ExtractedEvent, SourceKind, source_summary_line, utc_now
from .normalization import normalize_event_name, normalize_url, normalize_venue


MANUAL_PROTECTED_FIELDS = {
    "event_date",
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
}

STRONG_MATCH_THRESHOLD = 0.72
WEAK_MATCH_THRESHOLD = 0.45


@dataclass(frozen=True)
class MatchResult:
    event: CanonicalEvent | None
    confidence: float
    reason: str


class EventMerger:
    def find_match(self, extracted: ExtractedEvent, events: list[CanonicalEvent]) -> MatchResult:
        best_event: CanonicalEvent | None = None
        best_score = 0.0
        best_reasons: list[str] = []
        for event in events:
            score, reasons = self.match_score(extracted, event)
            if score > best_score:
                best_score = score
                best_event = event
                best_reasons = reasons
        return MatchResult(best_event, round(best_score, 2), ", ".join(best_reasons))

    def merge_into_collection(
        self,
        extracted: ExtractedEvent,
        events: list[CanonicalEvent],
    ) -> tuple[CanonicalEvent, bool, float]:
        match = self.find_match(extracted, events)
        if match.event is None or match.confidence < WEAK_MATCH_THRESHOLD:
            event = CanonicalEvent.from_extracted(
                extracted,
                needs_review=extracted.extraction_confidence < 0.65 or (match.event is not None and match.confidence > 0),
            )
            events.append(event)
            return event, True, match.confidence

        cautious = match.confidence < STRONG_MATCH_THRESHOLD
        self.apply_update(match.event, extracted, cautious=cautious)
        if cautious:
            match.event.needs_review = True
        return match.event, False, match.confidence

    def match_score(self, extracted: ExtractedEvent, event: CanonicalEvent) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []

        if extracted.source_post_id in event.source_post_ids:
            return 1.0, ["same source post"]

        same_ticket_url = False
        both_have_different_ticket_urls = False
        if extracted.ticket_url and event.ticket_url:
            same_ticket_url = normalize_url(extracted.ticket_url) == normalize_url(event.ticket_url)
            if same_ticket_url:
                score += 0.45
                reasons.append("same ticket_url")
            else:
                both_have_different_ticket_urls = True

        if extracted.event_date and event.event_date:
            if extracted.event_date == event.event_date:
                score += 0.3
                reasons.append("same event_date")
            else:
                score -= 0.35
                reasons.append("different event_date")

        name_similarity = _similarity(normalize_event_name(extracted.event_name), normalize_event_name(event.event_name))
        if extracted.event_name and event.event_name and both_have_different_ticket_urls and name_similarity < 0.92:
            return 0.0, ["different ticket_url and event_name"]
        if extracted.event_name and event.event_name and name_similarity < 0.45 and not same_ticket_url:
            return 0.0, ["clearly different event_name"]
        if name_similarity >= 0.92:
            score += 0.35
            reasons.append("same event_name")
        elif name_similarity >= 0.72:
            score += 0.2
            reasons.append("similar event_name")
        elif extracted.event_name and event.event_name:
            score -= 0.1

        venue_similarity = _similarity(normalize_venue(extracted.venue), normalize_venue(event.venue))
        if venue_similarity >= 0.92:
            score += 0.25
            reasons.append("same venue")
        elif venue_similarity >= 0.72:
            score += 0.12
            reasons.append("similar venue")
        elif extracted.venue and event.venue:
            score -= 0.08

        if extracted.source_kind in {
            SourceKind.TIMETABLE_UPDATE,
            SourceKind.DAY_BEFORE_REMINDER,
            SourceKind.SAME_DAY_REMINDER,
            SourceKind.TICKET_UPDATE,
            SourceKind.SOLD_OUT,
            SourceKind.CORRECTION,
        }:
            if extracted.event_date and event.event_date and extracted.event_date == event.event_date:
                score += 0.15
                reasons.append("update/reminder for same date")
            if extracted.ticket_url and event.ticket_url and normalize_url(extracted.ticket_url) == normalize_url(event.ticket_url):
                score += 0.05
                reasons.append("update shares ticket_url")

        return max(0.0, min(score, 1.0)), reasons

    def apply_update(self, event: CanonicalEvent, extracted: ExtractedEvent, *, cautious: bool = False) -> None:
        for field_name in EventFields.model_fields:
            new_value = getattr(extracted, field_name)
            if new_value is None:
                continue
            old_value = getattr(event, field_name)
            if event.manual_override and field_name in MANUAL_PROTECTED_FIELDS:
                continue
            if self._is_reminder_source(extracted) and old_value is not None and field_name in MANUAL_PROTECTED_FIELDS:
                continue
            if cautious and old_value is not None and field_name in MANUAL_PROTECTED_FIELDS:
                continue
            setattr(event, field_name, new_value)

        self.update_source_tracking(event, extracted)

        if extracted.extraction_confidence < 0.6:
            event.needs_review = True
        event.updated_at = utc_now()

    def update_source_tracking(self, event: CanonicalEvent, extracted: ExtractedEvent) -> None:
        if extracted.source_url not in event.all_source_urls:
            event.all_source_urls.append(extracted.source_url)
        if extracted.source_post_id not in event.source_post_ids:
            event.source_post_ids.append(extracted.source_post_id)
            line = source_summary_line(extracted)
            event.source_summary = f"{event.source_summary}\n{line}" if event.source_summary else line

        if event.primary_source_url is None:
            event.primary_source_url = extracted.source_url
        if event.source_url is None:
            event.source_url = extracted.source_url

        if event.last_source_posted_at is None or extracted.source_posted_at >= event.last_source_posted_at:
            event.latest_source_url = extracted.source_url
            event.last_source_posted_at = extracted.source_posted_at
            event.last_source_kind = extracted.source_kind

        if event.source_posted_at is None or extracted.source_posted_at >= event.source_posted_at:
            event.source_type = extracted.source_type
            event.source_url = extracted.source_url
            event.source_post_id = extracted.source_post_id
            event.source_posted_at = extracted.source_posted_at
            event.source_text = extracted.source_text
            event.source_kind = extracted.source_kind
            event.extraction_confidence = extracted.extraction_confidence

    def _is_reminder_source(self, extracted: ExtractedEvent) -> bool:
        return extracted.source_kind in {SourceKind.DAY_BEFORE_REMINDER, SourceKind.SAME_DAY_REMINDER}


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()
