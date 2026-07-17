#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from myojou_sync.public_id_reconciliation import (  # noqa: E402
    PublicIdReconciliationError,
    reconcile_public_files,
    report_to_csv,
    report_to_markdown,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit canonical public event ID reconciliation.")
    parser.add_argument("--before", required=True, help="Earlier public events JSON file.")
    parser.add_argument("--after", required=True, help="Later public events JSON file.")
    parser.add_argument("--json-output", help="Optional JSON report path.")
    parser.add_argument("--csv-output", help="Optional CSV report path.")
    parser.add_argument("--markdown-output", help="Optional Markdown summary path.")
    parser.add_argument("--fail-on-ambiguous", action="store_true", help="Exit nonzero for ambiguous, split, or merge candidates.")
    parser.add_argument("--max-id-only-churn", type=int, help="Exit nonzero when ID-only churn exceeds this count.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_id_only_churn is not None and args.max_id_only_churn < 0:
        print("--max-id-only-churn must be zero or greater.", file=sys.stderr)
        return 2
    try:
        report = reconcile_public_files(args.before, args.after)
    except PublicIdReconciliationError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    _write_optional(args.json_output, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _write_optional(args.csv_output, report_to_csv(report))
    _write_optional(args.markdown_output, report_to_markdown(report))
    metrics = report["metrics"]
    print(
        "Public ID reconciliation audit:\n"
        f"parents: {metrics['old_parent_count']} -> {metrics['new_parent_count']}\n"
        f"matched: {metrics['matched_parent_count']}\n"
        f"same_id: {metrics['same_id_count']}\n"
        f"id_only_changed: {metrics['id_only_changed_count']}\n"
        f"content_and_id_changed: {metrics['content_and_id_changed_count']}\n"
        f"content_changed_same_id: {metrics['content_changed_same_id_count']}\n"
        f"matched_occurrences: {metrics['same_occurrence_id_count'] + metrics['changed_occurrence_id_count']}\n"
        f"id_only_changed_occurrences: {metrics['id_only_changed_occurrence_count']}\n"
        f"content_and_id_changed_occurrences: {metrics['content_and_id_changed_occurrence_count']}\n"
        f"added: {metrics['added_parent_count']}\n"
        f"removed: {metrics['removed_parent_count']}\n"
        f"ambiguous: {metrics['ambiguous_match_count']}\n"
        f"split_candidates: {metrics['split_candidate_count']}\n"
        f"merge_candidates: {metrics['merge_candidate_count']}"
    )
    if args.fail_on_ambiguous and any(
        metrics[key]
        for key in ("ambiguous_match_count", "split_candidate_count", "merge_candidate_count")
    ):
        return 1
    if args.max_id_only_churn is not None and metrics["id_only_changed_count"] > args.max_id_only_churn:
        return 1
    return 0


def _write_optional(path_value: str | None, content: str) -> None:
    if not path_value:
        return
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
