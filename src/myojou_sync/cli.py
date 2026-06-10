from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import Settings
from .env_validation import missing_for_target, validation_lines
from .parser import PostParser
from .pipeline import SyncPipeline, build_quality_report
from .public_output import events_to_json, events_to_table, events_to_web_rows, write_web_events_json
from .public_validation import compare_public_rows, read_public_rows, validate_public_rows
from .readiness import public_readiness
from .real_samples import evaluate_real_samples
from .sample_capture import write_x_samples
from .state import SQLiteStateStore
from .sync.notion import NotionEventSink, inspect_notion_schema
from .sync.sheets import GoogleSheetsEventSink
from .x_client import MockXClient, XApiClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync @info_myojou live schedule posts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_env = subparsers.add_parser("validate-env", help="Show which sync targets have required environment variables.")
    validate_env.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    inspect_notion = subparsers.add_parser("inspect-notion-schema", help="Read and print the configured Notion database schema.")
    inspect_notion.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    export_public = subparsers.add_parser("export-public", help="Export canonical events to a static public/events.json file.")
    export_public.add_argument("--db", help="SQLite state database path.")
    export_public.add_argument("--output", default="public/events.json", help="Output JSON path. Defaults to public/events.json.")
    export_public.add_argument(
        "--include-not-public-ready",
        action="store_true",
        help="Debug export: include suspicious/not-public-ready canonical events.",
    )
    export_public.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    validate_public = subparsers.add_parser("validate-public", help="Validate a static public events JSON file.")
    validate_public.add_argument("--input", default="public/events.json", help="Input JSON path. Defaults to public/events.json.")
    validate_public.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    refresh_public = subparsers.add_parser("refresh-public", help="Run incremental sync, validate, and optionally update public/events.json.")
    refresh_public.add_argument("--db", help="SQLite state database path.")
    refresh_public.add_argument("--output", default="public/events.json", help="Output JSON path. Defaults to public/events.json.")
    refresh_public.add_argument("--mock-posts", help="Explicit mock post file or directory for offline verification.")
    refresh_public.add_argument("--max-results", type=int, help="Maximum X posts to request. Defaults to X_MAX_RESULTS or 10.")
    refresh_public.add_argument("--allow-x-api", action="store_true", help="Permit real X API calls when NO_X_API=true.")
    refresh_mode = refresh_public.add_mutually_exclusive_group()
    refresh_mode.add_argument("--dry-run", action="store_true", help="Preview changes without writing public/events.json. This is the default.")
    refresh_mode.add_argument("--write", action="store_true", help="Write validated public/events.json.")
    refresh_public.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    inspect_state = subparsers.add_parser("inspect-state", help="Print local SQLite sync state.")
    inspect_state.add_argument("--db", help="SQLite state database path.")
    inspect_state.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    evaluate_samples = subparsers.add_parser("evaluate-real-samples", help="Evaluate manually collected real X post fixtures.")
    evaluate_samples.add_argument("--fixtures", default="mock_posts/real_samples", help="Fixture file or directory.")
    evaluate_samples.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    run = subparsers.add_parser("run", help="Fetch, parse, merge, and optionally sync events.")
    run.add_argument("--mock-posts", help="Path to a mock X JSON file or directory.")
    run.add_argument("--no-mock-posts", action="store_true", help="Ignore MYOJOU_MOCK_POSTS and use the real X client.")
    run.add_argument("--db", help="SQLite state database path.")
    run.add_argument("--max-results", type=int, help="Maximum X posts to request. Defaults to X_MAX_RESULTS or 10.")
    run.add_argument("--backfill", action="store_true", help="Fetch historical X posts with pagination.")
    run.add_argument("--max-posts", type=int, help="Maximum total posts to fetch during --backfill. Required with --backfill.")
    run.add_argument("--max-pages", type=int, default=5, help="Maximum API pages to fetch during --backfill. Defaults to 5.")
    run.add_argument("--page-size", type=int, default=10, help="Posts requested per page during --backfill. Defaults to 10.")
    dry_run = run.add_mutually_exclusive_group()
    dry_run.add_argument("--dry-run", action="store_true", dest="dry_run", help="Skip Notion and Google Sheets writes.")
    dry_run.add_argument("--no-dry-run", action="store_false", dest="dry_run", help="Allow requested external writes.")
    run.set_defaults(dry_run=None)
    run.add_argument("--allow-x-api", action="store_true", help="Permit real X API calls when NO_X_API=true.")
    run.add_argument(
        "--target",
        choices=["notion", "sheets", "both", "none"],
        help="External sync target. Defaults to both when writes are enabled.",
    )
    run.add_argument("--sync-notion", action="store_true", help="Sync to Notion when credentials are present.")
    run.add_argument("--sync-sheets", action="store_true", help="Sync to Google Sheets when credentials are present.")
    run.add_argument("--preview", choices=["none", "json", "table"], default="none", help="Print public canonical events before external sync.")
    run.add_argument("--save-x-samples", help="Save raw real X API posts and parser debug output to this JSON file.")
    run.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "validate-env":
        for line in validation_lines(settings):
            print(line)
        return 0

    if args.command == "inspect-notion-schema":
        if not settings.notion_token or not settings.notion_database_id:
            missing = []
            if not settings.notion_token:
                missing.append("NOTION_TOKEN")
            if not settings.notion_database_id:
                missing.append("NOTION_DATABASE_ID")
            print(f"Notion schema inspection requires: {', '.join(missing)}", file=sys.stderr)
            return 2
        print(inspect_notion_schema(settings.notion_token, settings.notion_database_id))
        return 0

    if args.command == "export-public":
        state = SQLiteStateStore(args.db or settings.state_db)
        events = state.load_events()
        if args.include_not_public_ready:
            export_events = events
            filtered_count = 0
        else:
            export_events = [event for event in events if public_readiness(event).public_ready]
            filtered_count = len(events) - len(export_events)
        output_path = write_web_events_json(export_events, args.output)
        occurrence_count = len(events_to_web_rows(export_events))
        if args.include_not_public_ready:
            print(
                f"Exported {occurrence_count} rows from {len(export_events)} events to {output_path} "
                "including not-public-ready records."
            )
        else:
            print(
                f"Exported {occurrence_count} public-ready rows from {len(export_events)} events "
                f"to {output_path}; filtered {filtered_count}."
        )
        return 0

    if args.command == "validate-public":
        rows, load_errors = read_public_rows(args.input)
        validation = validate_public_rows(rows)
        validation.errors[:0] = load_errors
        print(_format_public_validation_report(args.input, validation))
        return 0 if validation.ok else 1

    if args.command == "refresh-public":
        db_path = args.db or settings.state_db
        state = SQLiteStateStore(db_path)
        mock_posts = args.mock_posts
        max_results = args.max_results or (1000 if mock_posts else settings.max_results)
        if mock_posts:
            fetcher = MockXClient(mock_posts)
        else:
            if settings.no_x_api and not args.allow_x_api:
                print(
                    "X API is disabled. Use --mock-posts for offline refresh verification or set NO_X_API=false intentionally.",
                    file=sys.stderr,
                )
                return 2
            if not settings.x_bearer_token:
                print("X_BEARER_TOKEN is required unless --mock-posts is set.", file=sys.stderr)
                return 2
            fetcher = XApiClient(settings.x_bearer_token, username=settings.x_username, state=state)

        before_rows, before_load_errors = read_public_rows(args.output)
        pipeline = SyncPipeline(
            fetcher=fetcher,
            state=state,
            parser=PostParser(username=settings.x_username),
        )
        events, result = pipeline.run_once(max_results=max_results)
        export_events = [event for event in events if public_readiness(event).public_ready]
        after_rows = events_to_web_rows(export_events)
        validation = validate_public_rows(after_rows)
        diff = compare_public_rows(before_rows, after_rows)
        print(_format_refresh_public_summary(
            result,
            output_path=args.output,
            diff=diff,
            validation=validation,
            before_load_errors=before_load_errors,
            write=args.write,
        ))
        if validation.errors:
            print("public/events.json was not written because validation failed.", file=sys.stderr)
            return 1
        if args.write:
            _write_public_rows(args.output, after_rows)
            print(f"Wrote {len(after_rows)} public events to {Path(args.output)}.")
        else:
            print("Dry-run: public/events.json was not overwritten. Pass --write to update it.")
        return 0

    if args.command == "inspect-state":
        state = SQLiteStateStore(args.db or settings.state_db)
        print(_format_state_inspection(state, username=settings.x_username))
        return 0

    if args.command == "evaluate-real-samples":
        results = evaluate_real_samples(args.fixtures, parser=PostParser(username=settings.x_username))
        passed = sum(1 for result in results if result.passed)
        for result in results:
            status = "OK" if result.passed else "NG"
            print(
                f"{status} {result.sample_id}: classification {result.actual_classification}"
                f" (expected {result.expected_classification}), source_kind {result.actual_source_kind}"
                f" (expected {result.expected_source_kind}) - {result.reason}"
            )
        print(f"Evaluated {len(results)} samples: {passed} passed, {len(results) - passed} failed.")
        return 0 if passed == len(results) else 1

    if args.command == "run":
        if args.backfill and args.max_posts is None:
            print("--max-posts is required when --backfill is used.", file=sys.stderr)
            return 2
        if args.backfill and args.max_posts is not None and args.max_posts <= 0:
            print("--max-posts must be greater than 0.", file=sys.stderr)
            return 2
        if args.backfill and args.max_pages <= 0:
            print("--max-pages must be greater than 0.", file=sys.stderr)
            return 2
        if args.backfill and args.page_size <= 0:
            print("--page-size must be greater than 0.", file=sys.stderr)
            return 2
        db_path = args.db or settings.state_db
        dry_run = settings.dry_run if args.dry_run is None else args.dry_run
        target = _resolve_target(args.target, sync_notion=args.sync_notion, sync_sheets=args.sync_sheets)
        if args.backfill and not dry_run and target != "none":
            print(
                "WARNING: --backfill can process many historical posts. Prefer --target none --dry-run first; "
                "external writes are enabled for this run.",
                file=sys.stderr,
            )
        mock_posts = None if args.no_mock_posts else args.mock_posts or settings.mock_posts
        if args.max_results is not None:
            max_results = args.max_results
        elif mock_posts:
            max_results = 1000
        else:
            max_results = settings.max_results
        state = SQLiteStateStore(db_path)

        if mock_posts:
            fetcher = MockXClient(mock_posts)
        else:
            if settings.no_x_api and not args.allow_x_api:
                print("X API is disabled. Use mock_posts or set NO_X_API=false intentionally.", file=sys.stderr)
                return 2
            if not settings.x_bearer_token:
                print("X_BEARER_TOKEN is required unless --mock-posts or MYOJOU_MOCK_POSTS is set.", file=sys.stderr)
                return 2
            fetcher = XApiClient(settings.x_bearer_token, username=settings.x_username, state=state)

        pipeline = SyncPipeline(
            fetcher=fetcher,
            state=state,
            parser=PostParser(username=settings.x_username),
        )
        if args.backfill:
            events, result = pipeline.run_backfill(
                max_posts=args.max_posts,
                max_pages=args.max_pages,
                page_size=args.page_size,
            )
            quality_report = build_quality_report(events, result)
        else:
            events, result = pipeline.run_once(max_results=max_results)
            quality_report = None

        if args.save_x_samples:
            if mock_posts:
                logging.getLogger(__name__).info("--save-x-samples was provided with mock input; no real X sample file was written.")
            else:
                output_path = write_x_samples(
                    args.save_x_samples,
                    result.x_sample_records,
                    metadata={
                        "username": settings.x_username,
                        "max_results": max_results,
                        "max_posts": args.max_posts,
                        "max_pages": args.max_pages if args.backfill else None,
                        "page_size": args.page_size if args.backfill else None,
                        "posts_fetched": result.fetched_posts,
                        "estimated_x_post_reads": result.estimated_x_post_read_count,
                        "pages_fetched": result.pages_fetched,
                        "page_summaries": result.x_page_summaries,
                        "rate_limit_headers": result.x_rate_limit_headers or {},
                        "dry_run": dry_run,
                        "backfill": args.backfill,
                    },
                )
                print(f"Saved {len(result.x_sample_records)} X samples to {output_path}.")

        if args.preview == "json":
            print(events_to_json(events))
        elif args.preview == "table":
            print(events_to_table(events))

        if dry_run:
            logging.getLogger(__name__).info("DRY_RUN enabled; external Notion/Sheets writes are skipped.")
        elif target == "none":
            logging.getLogger(__name__).info("Sync target is none; external Notion/Sheets writes are skipped.")
        else:
            missing = missing_for_target(settings, target)
            if missing:
                print(f"{target} sync requested but missing: {', '.join(missing)}", file=sys.stderr)
                return 2
            if target in {"notion", "both"}:
                missing = missing_for_target(settings, "notion")
                if missing:
                    print(f"Notion sync requested but missing: {', '.join(missing)}", file=sys.stderr)
                    return 2
                notion = NotionEventSink(settings.notion_token, settings.notion_database_id)
                events = notion.sync_events(events)
                state.save_events(events)
            if target in {"sheets", "both"}:
                missing = missing_for_target(settings, "sheets")
                if missing:
                    print(f"Google Sheets sync requested but missing: {', '.join(missing)}", file=sys.stderr)
                    return 2
                sheets = GoogleSheetsEventSink(
                    settings.google_service_account_json,
                    settings.google_sheet_id,
                    settings.google_worksheet_name,
                )
                events = sheets.sync_events(events)
                state.save_events(events)

        print(
            "Fetched {fetched_posts}, parsed {parsed_events}, new_posts_processed {new_posts_processed}, "
            "created {created_events}, "
            "updated {updated_events}, skipped {skipped_posts}, already_processed {already_processed_skipped}, "
            "non_event_skipped {non_event_skipped}, "
            "estimated_x_post_reads {estimated_x_post_read_count}, canonical {canonical_events}.".format(**result.__dict__)
        )
        if quality_report:
            print(_format_quality_report(quality_report))
        else:
            print(_format_sync_quality(events, result))
        return 0

    return 1


def _resolve_target(target: str | None, *, sync_notion: bool, sync_sheets: bool) -> str:
    if target:
        return target
    if sync_notion and sync_sheets:
        return "both"
    if sync_notion:
        return "notion"
    if sync_sheets:
        return "sheets"
    return "both"


def _format_quality_report(report: dict) -> str:
    canonical_events = report["canonical_events"]

    def ratio(key: str) -> str:
        return f"{report[key]}/{canonical_events}"

    def public_ready_ratio(key: str) -> str:
        ready = report.get("public_ready_quality", {})
        ready_count = ready.get("public_ready_events", 0)
        return f"{ready.get(key, 0)}/{ready_count}"

    lines = [
        "Backfill quality:",
        f"posts_fetched: {report['posts_fetched']}",
        f"posts_parsed: {report['posts_parsed']}",
        f"non_event_skipped: {report['non_event_skipped']}",
        f"canonical_events: {canonical_events}",
        f"public_ready: {ratio('public_ready_count')}",
        f"not_public_ready: {ratio('not_public_ready_count')}",
        f"ticket_url: {ratio('events_with_ticket_url')}",
        f"application_deadline: {ratio('events_with_application_deadline')}",
        f"sale_period: {ratio('events_with_sale_period')}",
        f"price: {ratio('events_with_price')}",
        f"venue: {ratio('events_with_venue')}",
        f"performance_time: {ratio('events_with_performance_time')}",
        f"benefit_time: {ratio('events_with_benefit_time')}",
        f"needs_review: {ratio('needs_review_count')}",
        f"suspicious_count: {report['suspicious_count']}",
    ]
    suspicious = report.get("suspicious_examples") or []
    if suspicious:
        lines.append("suspicious_examples:")
        for item in suspicious[:10]:
            label = item.get("event_name") or "missing event_name"
            date = item.get("event_date") or "no date"
            source = item.get("source_post_id") or "unknown source"
            reasons = ", ".join(item.get("reasons") or [])
            lines.append(f"- {date} {label}: {reasons} source_post_id={source}")
    ready_quality = report.get("public_ready_quality") or {}
    if ready_quality:
        lines.extend(
            [
                "Backfill public-ready quality:",
                f"public_ready_events: {ready_quality.get('public_ready_events', 0)}",
                f"ticket_url: {public_ready_ratio('events_with_ticket_url')}",
                f"application_deadline: {public_ready_ratio('events_with_application_deadline')}",
                f"sale_period: {public_ready_ratio('events_with_sale_period')}",
                f"price: {public_ready_ratio('events_with_price')}",
                f"venue: {public_ready_ratio('events_with_venue')}",
                f"performance_time: {public_ready_ratio('events_with_performance_time')}",
                f"benefit_time: {public_ready_ratio('events_with_benefit_time')}",
                f"needs_review: {public_ready_ratio('needs_review_count')}",
            ]
        )
    missing = report.get("top_missing_fields") or []
    if missing:
        lines.append(
            "top_missing_fields: "
            + ", ".join(f"{item['field']}={item['missing']}" for item in missing[:5])
        )
    else:
        lines.append("top_missing_fields: none")
    return "\n".join(lines)


def _format_sync_quality(events: list, result: PipelineResult) -> str:
    canonical_events = len(events)
    public_ready_count = sum(1 for event in events if public_readiness(event).public_ready)
    not_public_ready_count = canonical_events - public_ready_count
    lines = [
        "Sync quality:",
        f"public_ready: {public_ready_count}/{canonical_events}",
        f"not_public_ready: {not_public_ready_count}/{canonical_events}",
    ]
    if result.x_rate_limit_headers:
        lines.append("x_rate_limit: " + json.dumps(result.x_rate_limit_headers, ensure_ascii=False, sort_keys=True))
    else:
        lines.append("x_rate_limit: none")
    return "\n".join(lines)


def _format_state_inspection(state: SQLiteStateStore, *, username: str) -> str:
    latest = state.latest_processed_source_post()
    lines = [
        f"db_path: {state.db_path}",
        f"cached_user_id: {state.get_cached_x_user_id(username) or ''}",
        f"last_seen_post_id: {state.get_last_seen_post_id() or ''}",
        f"latest_processed_post_id: {(latest or {}).get('source_post_id', '')}",
        f"latest_processed_post_created_at: {(latest or {}).get('source_posted_at', '')}",
        f"processed_posts: {state.processed_post_count()}",
        f"canonical_events: {state.canonical_event_count()}",
    ]
    return "\n".join(lines)


def _format_public_validation_report(input_path: str, validation) -> str:
    lines = [
        "Public JSON validation:",
        f"input: {input_path}",
        f"events: {validation.event_count}",
        f"earliest_date: {validation.earliest_date}",
        f"latest_date: {validation.latest_date}",
        f"needs_review: {validation.needs_review_count}",
        f"not_public_ready: {validation.not_public_ready_count}",
        f"errors: {len(validation.errors)}",
        f"warnings: {len(validation.warnings)}",
    ]
    lines.extend(f"error: {error}" for error in validation.errors)
    lines.extend(f"warning: {warning}" for warning in validation.warnings)
    return "\n".join(lines)


def _format_refresh_public_summary(
    result: PipelineResult,
    *,
    output_path: str,
    diff: dict[str, int],
    validation,
    before_load_errors: list[str],
    write: bool,
) -> str:
    lines = [
        "Refresh public summary:",
        f"mode: {'write' if write else 'dry-run'}",
        f"output: {output_path}",
        f"posts_fetched: {result.fetched_posts}",
        f"new_posts_processed: {result.new_posts_processed}",
        f"already_processed_skipped: {result.already_processed_skipped}",
        f"non_event_skipped: {result.non_event_skipped}",
        f"estimated_x_post_reads: {result.estimated_x_post_read_count}",
        f"events_before: {diff['events_before']}",
        f"events_after: {diff['events_after']}",
        f"added: {diff['added']}",
        f"removed: {diff['removed']}",
        f"possibly_changed: {diff['possibly_changed']}",
        f"not_public_ready: {validation.not_public_ready_count}",
        f"needs_review: {validation.needs_review_count}",
        f"earliest_date: {validation.earliest_date}",
        f"latest_date: {validation.latest_date}",
        f"validation_errors: {len(validation.errors)}",
        f"validation_warnings: {len(validation.warnings)}",
    ]
    if result.x_rate_limit_headers:
        lines.append("x_rate_limit: " + json.dumps(result.x_rate_limit_headers, ensure_ascii=False, sort_keys=True))
    else:
        lines.append("x_rate_limit: none")
    lines.extend(f"existing_output_warning: {error}" for error in before_load_errors)
    lines.extend(f"validation_error: {error}" for error in validation.errors)
    lines.extend(f"validation_warning: {warning}" for warning in validation.warnings)
    return "\n".join(lines)


def _write_public_rows(output_path: str, rows: list[dict]) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
