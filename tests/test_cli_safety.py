from __future__ import annotations

from pathlib import Path

from myojou_sync.cli import main
from myojou_sync.public_output import PUBLIC_COLUMNS, event_to_public_dict
from myojou_sync.sync.notion import NotionEventSink
from myojou_sync.sync.sheets import GoogleSheetsEventSink


def test_dry_run_mock_sync_skips_external_writes(tmp_path, mock_posts_dir: Path, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("NO_X_API", "true")
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.delenv("NOTION_DATABASE_ID", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)

    result = main(
        [
            "run",
            "--mock-posts",
            str(mock_posts_dir),
            "--db",
            str(tmp_path / "state.sqlite"),
            "--dry-run",
            "--sync-notion",
            "--sync-sheets",
        ]
    )

    assert result == 0


def test_dry_run_does_not_call_external_write_adapters(tmp_path, mock_posts_dir: Path, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("external adapter should not be constructed during dry-run")

    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("NO_X_API", "true")
    monkeypatch.setattr("myojou_sync.cli.NotionEventSink", fail)
    monkeypatch.setattr("myojou_sync.cli.GoogleSheetsEventSink", fail)

    result = main(
        [
            "run",
            "--mock-posts",
            str(mock_posts_dir),
            "--db",
            str(tmp_path / "state.sqlite"),
            "--dry-run",
            "--sync-notion",
            "--sync-sheets",
        ]
    )

    assert result == 0


def test_no_x_api_blocks_real_fetch_without_mock(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_X_API", "true")
    monkeypatch.delenv("MYOJOU_MOCK_POSTS", raising=False)
    monkeypatch.setenv("X_BEARER_TOKEN", "would-not-be-used")

    result = main(["run", "--db", str(tmp_path / "state.sqlite")])

    assert result == 2


def test_no_mock_posts_ignores_mock_env_and_keeps_no_x_api_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_X_API", "true")
    monkeypatch.setenv("MYOJOU_MOCK_POSTS", "mock_posts")
    monkeypatch.setenv("X_BEARER_TOKEN", "would-not-be-used")

    result = main(["run", "--db", str(tmp_path / "state.sqlite"), "--no-mock-posts"])

    assert result == 2


def test_public_columns_match_required_public_output():
    assert PUBLIC_COLUMNS == [
        "event_date",
        "weekday",
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
        "ticket_status",
        "notes",
        "source_summary",
        "primary_source_url",
        "latest_source_url",
        "all_source_urls",
        "last_updated_at",
        "needs_review",
        "manual_override",
    ]


def test_public_output_contains_all_required_fields(mock_posts):
    from myojou_sync.models import CanonicalEvent
    from myojou_sync.parser import PostParser

    parsed = PostParser().parse_post(mock_posts["180001"])
    assert parsed is not None
    public = event_to_public_dict(CanonicalEvent.from_extracted(parsed))

    for column in PUBLIC_COLUMNS:
        assert column in public


def test_notion_adapter_rejects_missing_credentials():
    try:
        NotionEventSink(None, "db")
    except ValueError as exc:
        assert "NOTION_TOKEN" in str(exc)
    else:
        raise AssertionError("missing NOTION_TOKEN should fail before constructing Notion client")

    try:
        NotionEventSink("token", None)
    except ValueError as exc:
        assert "NOTION_DATABASE_ID" in str(exc)
    else:
        raise AssertionError("missing NOTION_DATABASE_ID should fail before constructing Notion client")


def test_sheets_adapter_rejects_missing_credentials():
    try:
        GoogleSheetsEventSink(None, "sheet")
    except ValueError as exc:
        assert "GOOGLE_SERVICE_ACCOUNT_JSON" in str(exc)
    else:
        raise AssertionError("missing GOOGLE_SERVICE_ACCOUNT_JSON should fail before constructing Sheets client")

    try:
        GoogleSheetsEventSink("{}", None)
    except ValueError as exc:
        assert "GOOGLE_SHEET_ID" in str(exc)
    else:
        raise AssertionError("missing GOOGLE_SHEET_ID should fail before constructing Sheets client")


def test_preview_json_works_with_mock_data(tmp_path, mock_posts_dir: Path, capsys):
    result = main(
        [
            "run",
            "--mock-posts",
            str(mock_posts_dir),
            "--db",
            str(tmp_path / "preview.sqlite"),
            "--dry-run",
            "--preview",
            "json",
        ]
    )

    output = capsys.readouterr().out

    assert result == 0
    assert '"event_date"' in output
    assert '"event_name"' in output
    assert "STARLIGHT LIVE vol.7" in output


def test_validate_env_reports_missing_and_available(monkeypatch, capsys):
    monkeypatch.setenv("NOTION_TOKEN", "token")
    monkeypatch.setenv("NOTION_DATABASE_ID", "db")
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)

    result = main(["validate-env"])
    output = capsys.readouterr().out

    assert result == 0
    assert "notion: available" in output
    assert "sheets: unavailable; missing GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SHEET_ID" in output
    assert "x: unavailable; missing X_BEARER_TOKEN" in output
