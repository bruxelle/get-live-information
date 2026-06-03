from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from .models import CanonicalEvent, EventFields, ExtractedEvent, PostClassification, SourceKind, TicketSalePeriod, source_summary_line, utc_now
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
    "ticket_application_start_at",
    "ticket_application_deadline_at",
    "lottery_result_at",
    "payment_deadline_at",
    "ticket_sale_type",
    "ticket_sales",
}

_STATUS_ONLY_PROTECTED_FIELDS = {
    "general_ticket_price",
    "priority_ticket_name",
    "priority_ticket_price",
    "same_day_ticket_price",
    "ticket_application_start_at",
    "ticket_application_deadline_at",
    "lottery_result_at",
    "payment_deadline_at",
    "ticket_sale_type",
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
                needs_review=extracted.classification == PostClassification.NEEDS_REVIEW
                or extracted.extraction_confidence < 0.65
                or (match.event is not None and match.confidence > 0),
            )
            derive_compatible_ticket_fields(event)
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
        targeted_ticket_status = self._is_targeted_ticket_status_update(extracted)
        for field_name in EventFields.model_fields:
            if field_name == "ticket_sales":
                continue
            if field_name == "ticket_status" and targeted_ticket_status:
                continue
            if extracted.ticket_status in {"sold_out", "ended"} and field_name in _STATUS_ONLY_PROTECTED_FIELDS:
                continue
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

        self.merge_ticket_sales(event, extracted)
        derive_compatible_ticket_fields(event)
        self.update_source_tracking(event, extracted)

        if extracted.classification == PostClassification.NEEDS_REVIEW or extracted.extraction_confidence < 0.6:
            event.needs_review = True
        if extracted.ticket_status in {"sold_out", "ended"} and not targeted_ticket_status:
            event.needs_review = True
        event.updated_at = utc_now()

    def merge_ticket_sales(self, event: CanonicalEvent, extracted: ExtractedEvent) -> None:
        if event.manual_override and "ticket_sales" in MANUAL_PROTECTED_FIELDS:
            return
        for period in extracted.ticket_sales:
            existing = self._find_existing_period(event.ticket_sales, period)
            if existing is None:
                event.ticket_sales.append(period)
            else:
                _update_period(existing, period)

    def _find_existing_period(
        self,
        existing_periods: list[TicketSalePeriod],
        new_period: TicketSalePeriod,
    ) -> TicketSalePeriod | None:
        new_key = _period_identity(new_period)
        for existing in existing_periods:
            if _period_identity(existing) == new_key:
                return existing
        if new_period.status in {"完売", "販売終了"}:
            for existing in existing_periods:
                if _same_ticket_target(existing, new_period):
                    return existing
        return None

    def _is_targeted_ticket_status_update(self, extracted: ExtractedEvent) -> bool:
        if extracted.ticket_status not in {"sold_out", "ended"}:
            return False
        return any(period.status in {"完売", "販売終了"} and period.ticket_tier != "不明" for period in extracted.ticket_sales)

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


_JST = timezone(timedelta(hours=9))


def derive_compatible_ticket_fields(event: CanonicalEvent, *, now: datetime | None = None) -> None:
    _derive_compatible_price_fields(event)
    if not event.ticket_sales:
        return
    selected = select_relevant_ticket_period(event.ticket_sales, now=now)
    if selected is None or not any((selected.start_at, selected.deadline_at, selected.result_at, selected.payment_deadline_at)):
        _set_derived_field(event, "ticket_application_start_at", None)
        _set_derived_field(event, "ticket_application_deadline_at", None)
        _set_derived_field(event, "lottery_result_at", None)
        _set_derived_field(event, "payment_deadline_at", None)
        _set_derived_field(event, "ticket_sale_type", None)
        return
    _set_derived_field(event, "ticket_application_start_at", selected.start_at)
    _set_derived_field(event, "ticket_application_deadline_at", selected.deadline_at)
    _set_derived_field(event, "lottery_result_at", selected.result_at)
    _set_derived_field(event, "payment_deadline_at", selected.payment_deadline_at)
    _set_derived_field(event, "ticket_sale_type", selected.sale_type)


def select_relevant_ticket_period(periods: list[TicketSalePeriod], *, now: datetime | None = None) -> TicketSalePeriod | None:
    dated = [period for period in periods if period.start_at or period.deadline_at]
    if not dated:
        return None
    now = now or datetime.now(_JST)
    active_or_upcoming = [period for period in dated if _period_phase(period, now) in {"active", "upcoming"}]
    if active_or_upcoming:
        lottery = [period for period in active_or_upcoming if period.sale_type == "抽選"]
        if lottery:
            return sorted(lottery, key=_period_deadline_sort_key)[0]
        general = [period for period in active_or_upcoming if period.sale_type in {"一般", "先着"}]
        if general:
            return sorted(general, key=_period_deadline_sort_key)[0]
        return sorted(active_or_upcoming, key=_period_deadline_sort_key)[0]
    return sorted(dated, key=_period_deadline_sort_key)[0]


def _period_phase(period: TicketSalePeriod, now: datetime) -> str:
    if period.status in {"完売", "販売終了"}:
        return "ended"
    start = _as_jst(period.start_at)
    deadline = _as_jst(period.deadline_at)
    if deadline and deadline < now:
        return "ended"
    if start and start > now:
        return "upcoming"
    if deadline and deadline >= now:
        return "active"
    return "unknown"


def _as_jst(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=_JST)
    return value.astimezone(_JST)


def _period_deadline_sort_key(period: TicketSalePeriod) -> tuple[str, str, str]:
    return (
        period.deadline_at.isoformat() if period.deadline_at else "9999-99-99T99:99:99",
        period.start_at.isoformat() if period.start_at else "9999-99-99T99:99:99",
        period.sale_type,
    )


def _period_identity(period: TicketSalePeriod) -> tuple[str, str, str, str]:
    return (
        period.sale_type,
        period.ticket_name or period.ticket_tier or "",
        period.start_at.isoformat() if period.start_at else "",
        period.deadline_at.isoformat() if period.deadline_at else "",
    )


def _same_ticket_target(left: TicketSalePeriod, right: TicketSalePeriod) -> bool:
    if right.ticket_tier != "不明" and left.ticket_tier == right.ticket_tier:
        return True
    if right.ticket_name and left.ticket_name and right.ticket_name in left.ticket_name:
        return True
    return False


def _derive_compatible_price_fields(event: CanonicalEvent) -> None:
    if not event.ticket_sales:
        return
    general = _best_price_period(event.ticket_sales, {"一般"}, sale_types={"一般", "先着", "抽選", "不明"})
    priority = _best_price_period(event.ticket_sales, {"優先", "VIP", "SS", "前方", "カメラ"})
    same_day = _best_price_period(event.ticket_sales, {"一般", "不明"}, sale_types={"当日券"})

    if general and general.price is not None:
        _set_derived_field(event, "general_ticket_price", general.price, only_if_empty=True)
    if priority and priority.price is not None:
        _set_derived_field(event, "priority_ticket_price", priority.price, only_if_empty=True)
        _set_derived_field(event, "priority_ticket_name", priority.ticket_name or priority.ticket_tier, only_if_empty=True)
    if same_day and same_day.price is not None:
        _set_derived_field(event, "same_day_ticket_price", same_day.price, only_if_empty=True)


def _best_price_period(
    periods: list[TicketSalePeriod],
    tiers: set[str],
    *,
    sale_types: set[str] | None = None,
) -> TicketSalePeriod | None:
    candidates = [
        period
        for period in periods
        if period.price is not None
        and period.ticket_tier in tiers
        and (sale_types is None or period.sale_type in sale_types)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=_period_deadline_sort_key)[0]


def _set_derived_field(event: CanonicalEvent, field_name: str, value: object, *, only_if_empty: bool = False) -> None:
    current = getattr(event, field_name)
    if event.manual_override and current is not None:
        return
    if only_if_empty and current is not None:
        return
    setattr(event, field_name, value)


def _update_period(existing: TicketSalePeriod, new: TicketSalePeriod) -> None:
    for field_name in TicketSalePeriod.model_fields:
        value = getattr(new, field_name)
        if value in (None, "", "不明"):
            continue
        if field_name == "sale_type" and existing.sale_type != "不明" and not (new.start_at or new.deadline_at):
            continue
        setattr(existing, field_name, value)
