from __future__ import annotations

import argparse
import logging
import sys

from .config import Settings
from .env_validation import missing_for_target, validation_lines
from .parser import PostParser
from .pipeline import SyncPipeline
from .public_output import events_to_json, events_to_table
from .state import SQLiteStateStore
from .sync.notion import NotionEventSink
from .sync.sheets import GoogleSheetsEventSink
from .x_client import MockXClient, XApiClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync @info_myojou live schedule posts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_env = subparsers.add_parser("validate-env", help="Show which sync targets have required environment variables.")
    validate_env.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

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
    run.add_argument("--sync-notion", action="store_true", help="Sync to Notion when credentials are present.")
    run.add_argument("--sync-sheets", action="store_true", help="Sync to Google Sheets when credentials are present.")
    run.add_argument("--preview", choices=["none", "json", "table"], default="none", help="Print public canonical events before external sync.")
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

    if args.command == "run":
        db_path = args.db or settings.state_db
        max_results = args.max_results if args.max_results is not None else settings.max_results
        dry_run = settings.dry_run if args.dry_run is None else args.dry_run
        mock_posts = None if args.no_mock_posts else args.mock_posts or settings.mock_posts
        state = SQLiteStateStore(db_path)

        if mock_posts:
            fetcher = MockXClient(mock_posts)
        else:
            if settings.no_x_api and not args.allow_x_api:
                print("NO_X_API is enabled. Use --mock-posts for local runs or --allow-x-api for a real X fetch.", file=sys.stderr)
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

        if args.preview == "json":
            print(events_to_json(events))
        elif args.preview == "table":
            print(events_to_table(events))

        if dry_run:
            logging.getLogger(__name__).info("DRY_RUN enabled; external Notion/Sheets writes are skipped.")
        else:
            if args.sync_notion:
                missing = missing_for_target(settings, "notion")
                if missing:
                    print(f"Notion sync requested but missing: {', '.join(missing)}", file=sys.stderr)
                    return 2
                notion = NotionEventSink(settings.notion_token, settings.notion_database_id)
                events = notion.sync_events(events)
                state.save_events(events)
            if args.sync_sheets:
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
