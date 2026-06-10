from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .merger import EventMerger
from .models import CanonicalEvent, PostClassification
from .parser import PostParser
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
        result.fetched_posts = len(posts)
        metadata = getattr(self.fetcher, "last_fetch_metadata", None)
        if metadata:
            result.estimated_x_post_read_count = metadata.estimated_post_read_count
            result.x_rate_limit_headers = metadata.rate_limit_headers

        events = self.state.load_events()
        processed_ids = self.state.processed_post_ids()

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
            self._advance_last_seen(post.id)

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
