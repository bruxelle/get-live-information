from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from myojou_sync.public_id_reconciliation import (
    PublicIdReconciliationError,
    group_public_rows,
    normalize_identity_text,
    normalize_ticket_url,
    reconcile_public_rows,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_public_id_reconciliation.py"


def _row(
    parent_id: str,
    event_date: str = "2026-07-20",
    *,
    title: str = "IDOL STORM",
    venue: str = "Spotify O-WEST",
    ticket_url: str = "https://ticket.example/events/idol-storm?utm_source=x&slot=1",
    ticket_summary: str = "一般 3,000円",
    source_post_id: str = "post-1",
) -> dict:
    return {
        "public_event_id": f"{parent_id}:{event_date}",
        "source_event_id": parent_id,
        "event_date": event_date,
        "weekday": "月",
        "event_name": title,
        "venue": venue,
        "live_summary": "開演 18:00",
        "ticket_summary": ticket_summary,
        "application_summary": "一般販売 7/1 20:00〜7/19 23:59",
        "ticket_url": ticket_url,
        "ticket_status": "販売中",
        "needs_review": False,
        "ticket_application_deadline_at": "2026-07-19T23:59:00+09:00",
        "payment_deadline_at": "",
        "ticket_sales": [
            {
                "sale_type": "一般",
                "ticket_name": "一般",
                "ticket_tier": "一般",
                "price": 3000,
                "start_at": "2026-07-01T20:00:00+09:00",
                "deadline_at": "2026-07-19T23:59:00+09:00",
                "result_at": "",
                "payment_deadline_at": "",
                "status": "販売中",
                "source_url": f"https://x.com/info_myojou/status/{source_post_id}",
                "source_post_id": source_post_id,
                "notes": "",
                "is_next_deadline": True,
            }
        ],
        "next_ticket_deadline_at": "2026-07-19T23:59:00+09:00",
        "next_ticket_sale_type": "一般",
        "next_ticket_label": "一般",
        "public_ready": True,
        "public_not_ready_reasons": [],
        "review_reasons": [],
    }


def _multi(parent_id: str, dates: list[str], **kwargs) -> list[dict]:
    return [_row(parent_id, event_date, **kwargs) for event_date in dates]


def test_identical_parent_with_identical_id_is_same_id():
    rows = [_row("evt_same")]

    report = reconcile_public_rows(rows, list(reversed(rows)))

    assert report["metrics"]["matched_parent_count"] == 1
    assert report["metrics"]["same_id_count"] == 1
    assert report["metrics"]["id_only_changed_count"] == 0
    assert report["matches"][0]["rule"] == "single_occurrence_title_venue"


def test_identical_content_with_different_ids_is_id_only_churn():
    before = [_row("evt_old")]
    after = [_row("evt_new")]

    report = reconcile_public_rows(before, after)

    assert report["metrics"]["id_only_changed_count"] == 1
    assert report["metrics"]["id_only_changed_occurrence_count"] == 1
    assert report["matches"][0]["content_changed"] is False
    assert report["matches"][0]["changed_occurrence_id_count"] == 1


def test_changed_content_and_changed_id_is_separate_from_id_only_churn():
    before = [_row("evt_old")]
    after = [_row("evt_new", ticket_summary="一般 3,500円")]

    report = reconcile_public_rows(before, after)

    assert report["metrics"]["content_and_id_changed_count"] == 1
    assert report["metrics"]["id_only_changed_count"] == 0


def test_nested_ticket_sale_source_content_is_not_excluded_from_fingerprint():
    before = [_row("evt_old", source_post_id="source-old")]
    after = [_row("evt_new", source_post_id="source-new")]

    report = reconcile_public_rows(before, after)

    assert report["metrics"]["content_and_id_changed_count"] == 1


def test_content_changed_with_same_id_is_classified_separately():
    before = [_row("evt_same")]
    after = [_row("evt_same", ticket_summary="一般 3,500円")]

    report = reconcile_public_rows(before, after)

    assert report["metrics"]["content_changed_same_id_count"] == 1


def test_exact_occurrence_set_title_and_venue_matches():
    dates = ["2026-09-21", "2026-09-22", "2026-09-23"]

    report = reconcile_public_rows(_multi("old", dates), _multi("new", list(reversed(dates))))

    assert report["matches"][0]["rule"] == "exact_occurrence_set_title_venue"


def test_ticket_url_with_matching_title_corroborates_changed_venue():
    before = [_row("old", venue="会場未定")]
    after = [_row("new", venue="Spotify O-WEST")]

    report = reconcile_public_rows(before, after)

    assert report["metrics"]["matched_parent_count"] == 1
    assert report["matches"][0]["rule"] == "exact_occurrence_set_ticket_url_corroborated"
    assert report["matches"][0]["evidence"]["title_equal"] is True


def test_title_only_match_is_rejected():
    before = [_row("old", venue="Venue A", ticket_url="https://ticket.example/a")]
    after = [_row("new", venue="Venue B", ticket_url="https://ticket.example/b")]

    report = reconcile_public_rows(before, after)

    assert report["metrics"]["matched_parent_count"] == 0
    assert report["ambiguous"][0]["reason"] == "conflicting_identity_evidence"


def test_ticket_url_only_match_is_rejected():
    before = [_row("old", title="Live A", venue="Venue A")]
    after = [_row("new", title="Live B", venue="Venue B")]

    report = reconcile_public_rows(before, after)

    assert report["metrics"]["matched_parent_count"] == 0
    assert report["ambiguous"][0]["shared_ticket_urls"]


def test_date_only_match_is_rejected_as_added_and_removed():
    before = [_row("old", title="Live A", venue="Venue A", ticket_url="https://ticket.example/a")]
    after = [_row("new", title="Live B", venue="Venue B", ticket_url="https://ticket.example/b")]

    report = reconcile_public_rows(before, after)

    assert report["metrics"]["matched_parent_count"] == 0
    assert report["metrics"]["added_parent_count"] == 1
    assert report["metrics"]["removed_parent_count"] == 1


def test_venue_only_match_is_rejected_as_added_and_removed():
    before = [_row("old", title="Live A", ticket_url="https://ticket.example/a")]
    after = [_row("new", title="Live B", ticket_url="https://ticket.example/b")]

    report = reconcile_public_rows(before, after)

    assert report["metrics"]["ambiguous_match_count"] == 0
    assert report["metrics"]["added_parent_count"] == 1
    assert report["metrics"]["removed_parent_count"] == 1


def test_one_old_parent_with_two_new_candidates_is_split_and_ambiguous():
    before = [_row("old")]
    after = [_row("new-a"), _row("new-b")]

    report = reconcile_public_rows(before, after)

    assert report["metrics"]["matched_parent_count"] == 0
    assert report["metrics"]["split_candidate_count"] == 1
    assert report["split_candidates"][0]["new_parent_ids"] == ["new-a", "new-b"]
    assert report["metrics"]["ambiguous_match_count"] == 2


def test_two_old_parents_with_one_new_candidate_is_merge_and_ambiguous():
    before = [_row("old-a"), _row("old-b")]
    after = [_row("new")]

    report = reconcile_public_rows(before, after)

    assert report["metrics"]["matched_parent_count"] == 0
    assert report["metrics"]["merge_candidate_count"] == 1
    assert report["merge_candidates"][0]["old_parent_ids"] == ["old-a", "old-b"]


def test_multi_day_parents_require_the_complete_occurrence_set():
    before = _multi("old", ["2026-09-21", "2026-09-22", "2026-09-23"])
    complete = _multi("new", ["2026-09-21", "2026-09-22", "2026-09-23"])
    partial = _multi("new", ["2026-09-21", "2026-09-22"])

    complete_report = reconcile_public_rows(before, complete)
    partial_report = reconcile_public_rows(before, partial)

    assert complete_report["metrics"]["matched_parent_count"] == 1
    assert partial_report["metrics"]["matched_parent_count"] == 0
    assert partial_report["ambiguous"][0]["reason"] == "partial_multi_day_overlap"
    assert partial_report["metrics"]["split_candidate_count"] == 1
    assert partial_report["metrics"]["merge_candidate_count"] == 0


def test_different_input_row_order_produces_identical_report():
    before = [_row("old-a"), _row("old-b", "2026-07-21", title="Live B", venue="Venue B")]
    after = [_row("new-a"), _row("new-b", "2026-07-21", title="Live B", venue="Venue B")]

    forward = reconcile_public_rows(before, after)
    reversed_report = reconcile_public_rows(list(reversed(before)), list(reversed(after)))

    assert forward == reversed_report


def test_unicode_punctuation_and_url_tracking_normalization_is_conservative():
    assert normalize_identity_text(" ＩＤＯＬ「ＳＴＯＲＭ」 ") == normalize_identity_text("idol storm")
    assert normalize_identity_text("Ｓｐｏｔｉｆｙ　Ｏ－ＷＥＳＴ", venue=True) == normalize_identity_text(
        "spotify o-west", venue=True
    )
    assert normalize_ticket_url("http://Ticket.Example/event/A?slot=1&utm_source=x#top") == (
        "https://ticket.example/event/A?slot=1"
    )
    assert normalize_ticket_url("https://ticket.example/event/A?slot=2") != normalize_ticket_url(
        "https://ticket.example/event/A?slot=1"
    )


def test_grouping_prefers_source_event_id_and_collects_nested_source_post_ids():
    row = _row("dedicated-parent", source_post_id="source-123")
    row["public_event_id"] = "unrelated-format"

    parent = group_public_rows([row])[0]

    assert parent.parent_id == "dedicated-parent"
    assert parent.source_post_ids == ("source-123",)


def test_duplicate_public_rows_are_rejected_explicitly():
    row = _row("duplicate")

    with pytest.raises(PublicIdReconciliationError, match="Duplicate public_event_id"):
        group_public_rows([row, row])


def test_unsupported_public_schema_fails_clearly():
    with pytest.raises(PublicIdReconciliationError, match="Unsupported public JSON schema"):
        group_public_rows([{"public_event_id": "event:2026-07-20"}])


def test_cli_output_and_reports_are_deterministic(tmp_path):
    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    before_path.write_text(json.dumps([_row("old")], ensure_ascii=False), encoding="utf-8")
    after_path.write_text(json.dumps([_row("new")], ensure_ascii=False), encoding="utf-8")

    outputs = []
    for suffix in ("a", "b"):
        json_path = tmp_path / f"audit-{suffix}.json"
        csv_path = tmp_path / f"audit-{suffix}.csv"
        markdown_path = tmp_path / f"audit-{suffix}.md"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--before",
                str(before_path),
                "--after",
                str(after_path),
                "--json-output",
                str(json_path),
                "--csv-output",
                str(csv_path),
                "--markdown-output",
                str(markdown_path),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "id_only_changed: 1" in result.stdout
        outputs.append((json_path.read_bytes(), csv_path.read_bytes(), markdown_path.read_bytes()))

    assert outputs[0] == outputs[1]


def test_cli_strict_options_are_opt_in(tmp_path):
    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    before_path.write_text(json.dumps([_row("old")]), encoding="utf-8")
    after_path.write_text(json.dumps([_row("new")]), encoding="utf-8")

    default = subprocess.run(
        [sys.executable, str(SCRIPT), "--before", str(before_path), "--after", str(after_path)],
        cwd=ROOT,
        check=False,
    )
    strict = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--before",
            str(before_path),
            "--after",
            str(after_path),
            "--max-id-only-churn",
            "0",
        ],
        cwd=ROOT,
        check=False,
    )

    assert default.returncode == 0
    assert strict.returncode == 1
