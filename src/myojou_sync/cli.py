from __future__ import annotations

import argparse
import logging
import sys

from .config import Settings
from .env_validation import missing_for_target, validation_lines
from .parser import PostParser
from .pipeline import SyncPipeline
from .public_output import events_to_json, events_to_table, write_web_events_json
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
    export_public.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    evaluate_samples = subparsers.add_parser("evaluate-real-samples", help="Evaluate manually collected real X post fixtures.")
    evaluate_samples.add_argument("--fixtures", default="mock_posts/real_samples", help="Fixture file or directory.")
    evaluate_samples.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    run = subparsers.add_parser("run", help="Fetch, parse, merge, and optionally sync events.")
    run.add_argument("--mock-posts", help="Path to a mock X JSON file or directory.")
    run.add_argument("--no-mock-posts", action="store_true", help="Ignore MYOJOU_MOCK_POSTS and use the real X client.")
    run.add_argument("--db", help="SQLite state database path.")
    run.add_argument("--max-results", type=int, help="Maximum X posts to request. Defaults to X_MAX_RESULTS or 10.")
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
        output_path = write_web_events_json(events, args.output)
        print(f"Exported {len(events)} events to {output_path}.")
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
        db_path = args.db or settings.state_db
        dry_run = settings.dry_run if args.dry_run is None else args.dry_run
        target = _resolve_target(args.target, sync_notion=args.sync_notion, sync_sheets=args.sync_sheets)
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
        events, result = pipeline.run_once(max_results=max_results)

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
                        "posts_fetched": result.fetched_posts,
                        "estimated_x_post_reads": result.estimated_x_post_read_count,
                        "rate_limit_headers": result.x_rate_limit_headers or {},
                        "dry_run": dry_run,
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
            "Fetched {fetched_posts}, parsed {parsed_events}, created {created_events}, "
            "updated {updated_events}, skipped {skipped_posts}, already_processed {already_processed_skipped}, "
            "estimated_x_post_reads {estimated_x_post_read_count}, canonical {canonical_events}.".format(**result.__dict__)
        )
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
