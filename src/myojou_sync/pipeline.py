from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .merger import EventMerger
from .models import CanonicalEvent, PostClassification
from .parser import PostParser
from .readiness import public_readiness
from .sample_capture import needs_review_reasons, sample_record_for_post
from .state import SQLiteStateStore
from .x_client import PostFetcher


logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    fetched_posts: int = 0
    parsed_events: int = 0
    created_events: int = 0
    updated_events: int = 0
    skipped_posts: int = 0
    already_processed_skipped: int = 0
    non_event_skipped: int = 0
    new_posts_processed: int = 0
    canonical_events: int = 0
    estimated_x_post_read_count: int = 0
    x_rate_limit_headers: dict[str, str] | None = None
    x_sample_records: list[dict[str, Any]] = field(default_factory=list)
    pages_fetched: int = 0
    x_page_summaries: list[dict[str, Any]] = field(default_factory=list)


class SyncPipeline:
    def __init__(
        self,
        *,
        fetcher: PostFetcher,
        state: SQLiteStateStore,
        parser: PostParser | None = None,
        merger: EventMerger | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.state = state
        self.parser = parser or PostParser()
        self.merger = merger or EventMerger()

    def run_once(self, *, max_results: int = 10) -> tuple[list[CanonicalEvent], PipelineResult]:
        result = PipelineResult()
        since_id = self.state.get_last_seen_post_id()
        posts = self.fetcher.fetch_recent_posts(since_id=since_id, max_results=max_results)
        self._copy_fetch_metadata(result, posts)

        events = self.state.load_events()
        processed_ids = self.state.processed_post_ids()

        self._process_posts(posts, events, processed_ids, result, advance_last_seen=True)
        result.canonical_events = len(events)
        logger.info(
            "Sync run: posts_fetched=%s new_posts_processed=%s already_processed_skipped=%s "
            "non_event_skipped=%s estimated_x_post_reads=%s rate_limit=%s",
            result.fetched_posts,
            result.new_posts_processed,
            result.already_processed_skipped,
            result.non_event_skipped,
            result.estimated_x_post_read_count,
            result.x_rate_limit_headers or {},
        )
        return events, result

    def run_backfill(
        self,
        *,
        max_posts: int,
        max_pages: int = 5,
        page_size: int = 10,
    ) -> tuple[list[CanonicalEvent], PipelineResult]:
        fetch_historical = getattr(self.fetcher, "fetch_historical_posts", None)
        if fetch_historical is None:
            raise TypeError("Configured fetcher does not support historical backfill.")
        result = PipelineResult()
        posts = fetch_historical(max_posts=max_posts, max_pages=max_pages, page_size=page_size)
        self._copy_fetch_metadata(result, posts)

        events = self.state.load_events()
        processed_ids = self.state.processed_post_ids()
        self._process_posts(posts, events, processed_ids, result, advance_last_seen=False)
        result.canonical_events = len(events)
        logger.info(
            "Backfill run: posts_fetched=%s pages_fetched=%s new_posts_processed=%s "
            "already_processed_skipped=%s non_event_skipped=%s estimated_x_post_reads=%s rate_limit=%s",
            result.fetched_posts,
            result.pages_fetched,
            result.new_posts_processed,
            result.already_processed_skipped,
            result.non_event_skipped,
            result.estimated_x_post_read_count,
            result.x_rate_limit_headers or {},
        )
        return events, result

    def _copy_fetch_metadata(self, result: PipelineResult, posts: list[Any]) -> None:
        result.fetched_posts = len(posts)
        metadata = getattr(self.fetcher, "last_fetch_metadata", None)
        if metadata:
            result.estimated_x_post_read_count = metadata.estimated_post_read_count
            result.x_rate_limit_headers = metadata.rate_limit_headers
            result.pages_fetched = getattr(metadata, "pages_fetched", 0)
            result.x_page_summaries = list(getattr(metadata, "page_summaries", []) or [])

    def _process_posts(
        self,
        posts,
        events: list[CanonicalEvent],
        processed_ids: set[str],
        result: PipelineResult,
        *,
        advance_last_seen: bool,
    ) -> None:
        for post in sorted(posts, key=lambda item: item.created_at):
            source_url = self.parser.source_url_for_post(post)
            if post.id in processed_ids:
                result.skipped_posts += 1
                result.already_processed_skipped += 1
                result.x_sample_records.append(
                    sample_record_for_post(post, source_url=source_url, already_processed=True)
                )
                continue

            classification = self.parser.classify_post(post)
            if classification.classification == PostClassification.NON_EVENT:
                result.skipped_posts += 1
                result.non_event_skipped += 1
                self.state.save_classified_source_post(
                    post,
                    classification,
                    source_url=source_url,
                )
                result.x_sample_records.append(
                    sample_record_for_post(post, source_url=source_url, classification=classification)
                )
                if advance_last_seen:
                    self._advance_last_seen(post.id)
                continue

            extracted = self.parser.parse_post(post, classification=classification)
            if extracted is None:
                result.skipped_posts += 1
                result.non_event_skipped += 1
                self.state.save_classified_source_post(
                    post,
                    classification,
                    source_url=source_url,
                )
                result.x_sample_records.append(
                    sample_record_for_post(post, source_url=source_url, classification=classification)
                )
                if advance_last_seen:
                    self._advance_last_seen(post.id)
                continue

            event, created, merge_confidence = self.merger.merge_into_collection(extracted, events)
            self.state.save_source_post(extracted, linked_event_id=event.event_id)
            self.state.save_event(event)
            result.x_sample_records.append(
                sample_record_for_post(
                    post,
                    source_url=source_url,
                    classification=classification,
                    extracted=extracted,
                    event=event,
                    merge_confidence=merge_confidence,
                )
            )
            if event.needs_review:
                logger.warning(
                    "needs_review event_id=%s event_name=%r reasons=%s",
                    event.event_id,
                    event.event_name or "",
                    needs_review_reasons(event, merge_confidence=merge_confidence),
                )
            result.parsed_events += 1
            result.new_posts_processed += 1
            if created:
                result.created_events += 1
            else:
                result.updated_events += 1
            if advance_last_seen:
                self._advance_last_seen(post.id)

    def _advance_last_seen(self, post_id: str) -> None:
        current = self.state.get_last_seen_post_id()
        if current is None:
            self.state.set_last_seen_post_id(post_id)
            return
        if current.isdigit() and post_id.isdigit():
            if int(post_id) > int(current):
                self.state.set_last_seen_post_id(post_id)
        elif post_id > current:
            self.state.set_last_seen_post_id(post_id)


def build_quality_report(events: list[CanonicalEvent], result: PipelineResult) -> dict[str, Any]:
    canonical_events = len(events)
    missing_counts = {
        "ticket_url": 0,
        "application_deadline": 0,
        "sale_period": 0,
        "price": 0,
        "venue": 0,
        "performance_time": 0,
        "benefit_time": 0,
    }
    counts = {
        "events_with_ticket_url": 0,
        "events_with_application_deadline": 0,
        "events_with_sale_period": 0,
        "events_with_price": 0,
        "events_with_venue": 0,
        "events_with_performance_time": 0,
        "events_with_benefit_time": 0,
        "needs_review_count": 0,
        "public_ready_count": 0,
        "not_public_ready_count": 0,
        "suspicious_count": 0,
    }
    suspicious_examples: list[dict[str, Any]] = []
    public_ready_events: list[CanonicalEvent] = []
    for event in events:
        field_checks = {
            "ticket_url": bool(event.ticket_url),
            "application_deadline": _has_application_deadline(event),
            "sale_period": _has_sale_period(event),
            "price": _has_price(event),
            "venue": bool(event.venue),
            "performance_time": bool(event.myojou_performance_time),
            "benefit_time": bool(event.benefit_event_time),
        }
        for field_name, present in field_checks.items():
            if present:
                counts[f"events_with_{field_name}"] += 1
            else:
                missing_counts[field_name] += 1
        if event.needs_review:
            counts["needs_review_count"] += 1
        readiness = public_readiness(event)
        if readiness.public_ready:
            counts["public_ready_count"] += 1
            public_ready_events.append(event)
        else:
            counts["not_public_ready_count"] += 1
            counts["suspicious_count"] += 1
            if len(suspicious_examples) < 10:
                suspicious_examples.append(
                    {
                        "event_date": event.event_date.isoformat() if event.event_date else "",
                        "event_name": event.event_name or "",
                        "venue": event.venue or "",
                        "source_post_id": event.source_post_id or "",
                        "reasons": readiness.reasons,
                    }
                )

    return {
        "posts_fetched": result.fetched_posts,
        "posts_parsed": result.parsed_events,
        "non_event_skipped": result.non_event_skipped,
        "canonical_events": canonical_events,
        **counts,
        "public_ready_quality": _quality_counts(public_ready_events),
        "suspicious_examples": suspicious_examples,
        "top_missing_fields": [
            {"field": field_name, "missing": missing}
            for field_name, missing in sorted(missing_counts.items(), key=lambda item: (-item[1], item[0]))
            if missing > 0
        ],
    }


def _quality_counts(events: list[CanonicalEvent]) -> dict[str, int]:
    counts = {
        "public_ready_events": len(events),
        "events_with_ticket_url": 0,
        "events_with_application_deadline": 0,
        "events_with_sale_period": 0,
        "events_with_price": 0,
        "events_with_venue": 0,
        "events_with_performance_time": 0,
        "events_with_benefit_time": 0,
        "needs_review_count": 0,
    }
    for event in events:
        if event.ticket_url:
            counts["events_with_ticket_url"] += 1
        if _has_application_deadline(event):
            counts["events_with_application_deadline"] += 1
        if _has_sale_period(event):
            counts["events_with_sale_period"] += 1
        if _has_price(event):
            counts["events_with_price"] += 1
        if event.venue:
            counts["events_with_venue"] += 1
        if event.myojou_performance_time:
            counts["events_with_performance_time"] += 1
        if event.benefit_event_time:
            counts["events_with_benefit_time"] += 1
        if event.needs_review:
            counts["needs_review_count"] += 1
    return counts


def _has_application_deadline(event: CanonicalEvent) -> bool:
    return bool(event.ticket_application_deadline_at or any(period.deadline_at for period in event.ticket_sales))


def _has_sale_period(event: CanonicalEvent) -> bool:
    return any(period.start_at or period.deadline_at for period in event.ticket_sales)


def _has_price(event: CanonicalEvent) -> bool:
    return bool(
        event.general_ticket_price is not None
        or event.priority_ticket_price is not None
        or event.same_day_ticket_price is not None
        or any(period.price is not None for period in event.ticket_sales)
    )
