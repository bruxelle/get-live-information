from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from myojou_sync.cli import main
from myojou_sync.models import CanonicalEvent
from myojou_sync.public_output import (
    PREVIEW_TABLE_COLUMNS,
    PUBLIC_COLUMNS,
    SHEET_HEADERS,
    application_summary,
    event_to_public_dict,
    events_to_web_json,
    events_to_json,
    events_to_table,
    live_summary,
    ticket_summary,
    ticket_status_label,
)
from myojou_sync.state import SQLiteStateStore
from myojou_sync.sync.notion import _event_to_notion_properties
from myojou_sync.sync.notion import NotionEventSink
from myojou_sync.sync.sheets import GoogleSheetsEventSink


class FakeNotionSink:
    calls: list[str] = []

    def __init__(self, token, database_id):
        self.calls.append("init")

    def sync_events(self, events):
        self.calls.append("sync")
        return events


class FakeSheetsSink:
    calls: list[str] = []

    def __init__(self, service_account_json, sheet_id, worksheet_name="Live Schedule"):
        self.calls.append("init")

    def sync_events(self, events):
        self.calls.append("sync")
        return events


def _reset_fake_sinks():
    FakeNotionSink.calls.clear()
    FakeSheetsSink.calls.clear()


JST = timezone(timedelta(hours=9))


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
            "--target",
            "both",
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
            "--target",
            "both",
        ]
    )

    assert result == 0


def test_no_x_api_blocks_real_fetch_without_mock(tmp_path, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise AssertionError("XApiClient should not be constructed when NO_X_API=true")

    monkeypatch.setenv("NO_X_API", "true")
    monkeypatch.delenv("MYOJOU_MOCK_POSTS", raising=False)
    monkeypatch.setenv("X_BEARER_TOKEN", "would-not-be-used")
    monkeypatch.setattr("myojou_sync.cli.XApiClient", fail)

    result = main(["run", "--db", str(tmp_path / "state.sqlite"), "--no-mock-posts"])
    error = capsys.readouterr().err

    assert result == 2
    assert "X API is disabled. Use mock_posts or set NO_X_API=false intentionally." in error


def test_no_mock_posts_ignores_mock_env_and_keeps_no_x_api_guard(tmp_path, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise AssertionError("XApiClient should not be constructed when NO_X_API=true")

    monkeypatch.setenv("NO_X_API", "true")
    monkeypatch.setenv("MYOJOU_MOCK_POSTS", "mock_posts")
    monkeypatch.setenv("X_BEARER_TOKEN", "would-not-be-used")
    monkeypatch.setattr("myojou_sync.cli.XApiClient", fail)

    result = main(["run", "--db", str(tmp_path / "state.sqlite"), "--no-mock-posts"])
    error = capsys.readouterr().err

    assert result == 2
    assert "X API is disabled. Use mock_posts or set NO_X_API=false intentionally." in error


def test_public_columns_match_required_public_output():
    assert PUBLIC_COLUMNS == [
        "event_name",
        "event_date",
        "weekday",
        "venue",
        "live_summary",
        "ticket_summary",
        "application_summary",
        "ticket_sales_summary",
        "next_ticket_deadline_at",
        "next_ticket_sale_type",
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
        "ticket_status",
        "notes",
        "source_summary",
        "primary_source_url",
        "latest_source_url",
        "all_source_urls",
        "last_source_posted_at",
        "last_source_kind",
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

    assert set(public) == set(SHEET_HEADERS)


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
    assert '"日付"' in output
    assert '"イベント名"' in output
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
    assert "both: unavailable; missing GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SHEET_ID" in output
    assert "x: unavailable; missing X_BEARER_TOKEN" in output


def test_inspect_notion_schema_command_prints_schema(monkeypatch, capsys):
    monkeypatch.setenv("NOTION_TOKEN", "token")
    monkeypatch.setenv("NOTION_DATABASE_ID", "db")
    monkeypatch.setattr(
        "myojou_sync.cli.inspect_notion_schema",
        lambda token, database_id: "data_source_id: ds_xxx\n- 曜日: (select) supported",
    )

    result = main(["inspect-notion-schema"])
    output = capsys.readouterr().out

    assert result == 0
    assert "data_source_id: ds_xxx" in output
    assert "- 曜日: (select) supported" in output


def test_japanese_weekday_and_ticket_status_output(mock_posts):
    from myojou_sync.models import CanonicalEvent
    from myojou_sync.parser import PostParser

    parsed = PostParser().parse_post(mock_posts["180004"])
    assert parsed is not None
    public = event_to_public_dict(CanonicalEvent.from_extracted(parsed))

    assert public["曜日"] == "月"
    assert public["販売状況"] == "販売中"


def test_public_ticket_status_labels_are_mobile_friendly():
    assert ticket_status_label("sold_out") == "完売"
    assert ticket_status_label("売切") == "完売"
    assert ticket_status_label("ended") == "販売終了"
    assert ticket_status_label("終了") == "販売終了"
    assert ticket_status_label("unknown") == "不明"
    assert ticket_status_label("未確認") == "不明"
    assert ticket_status_label("upcoming") == "未販売"
    assert ticket_status_label("same_day") == "販売中"


def test_compact_summary_generation():
    event = CanonicalEvent(
        start_time="18:45",
        myojou_performance_time="19:10-19:35",
        benefit_event_time="20:00-21:00",
        general_ticket_price=2500,
        priority_ticket_price=4000,
        ticket_sale_type="抽選",
        ticket_status="sold_out",
        ticket_application_start_at=datetime(2026, 5, 25, 20, 0, tzinfo=JST),
        ticket_application_deadline_at=datetime(2026, 6, 1, 23, 59, tzinfo=JST),
        payment_deadline_at=datetime(2026, 6, 5, 23, 59, tzinfo=JST),
    )

    assert live_summary(event) == "開演 18:45 / 出演 19:10-19:35 / 特典会 20:00-21:00"
    assert ticket_summary(event) == "抽選 / 一般 2,500円 / 優先 4,000円 / 完売"
    assert application_summary(event) == "申込 5/25 20:00〜6/1 23:59 / 支払 6/5 23:59"


def test_compact_summary_omits_missing_parts_and_marks_missing_deadline():
    event = CanonicalEvent(
        start_time="18:45",
        general_ticket_price=2800,
        ticket_sale_type="先着",
        ticket_status="on_sale",
    )

    assert live_summary(event) == "開演 18:45"
    assert ticket_summary(event) == "先着 / 一般 2,800円 / 販売中"
    assert application_summary(event) == "未取得"


def test_compact_application_summary_single_deadline_and_lottery():
    event = CanonicalEvent(
        ticket_application_deadline_at=datetime(2026, 6, 1, 23, 59, tzinfo=JST),
        lottery_result_at=datetime(2026, 6, 3, 18, 0, tzinfo=JST),
    )

    assert application_summary(event) == "申込締切 6/1 23:59 / 当落 6/3 18:00"


def test_application_summary_includes_lottery_and_general_sales():
    from myojou_sync.models import TicketSalePeriod

    event = CanonicalEvent(
        event_name="SALES TEST LIVE",
        general_ticket_price=2500,
        priority_ticket_price=4000,
        ticket_sales=[
            TicketSalePeriod(
                sale_type="抽選",
                ticket_name="優先",
                ticket_tier="優先",
                price=4000,
                start_at=datetime(2026, 5, 1, 20, 0, tzinfo=JST),
                deadline_at=datetime(2026, 5, 10, 23, 59, tzinfo=JST),
            ),
            TicketSalePeriod(
                sale_type="一般",
                ticket_name="一般",
                ticket_tier="一般",
                price=2500,
                start_at=datetime(2026, 5, 11, 20, 0, tzinfo=JST),
                deadline_at=datetime(2026, 5, 30, 23, 59, tzinfo=JST),
            ),
        ],
    )

    assert ticket_summary(event) == "抽選あり・一般販売あり / 一般 2,500円 / 優先 4,000円"
    assert application_summary(event) == "抽選 5/1 20:00〜5/10 23:59 / 一般販売 5/11 20:00〜5/30 23:59"
    payload = json.loads(events_to_web_json([event]))[0]
    assert len(payload["ticket_sales"]) == 2
    assert payload["next_ticket_deadline_at"]


def test_preview_table_uses_compact_mobile_columns():
    table = events_to_table(
        [
            CanonicalEvent(
                event_name="STARLIGHT LIVE vol.7",
                event_date=date(2026, 6, 15),
                venue="渋谷Milkyway",
                start_time="18:45",
                myojou_performance_time="19:20-19:40",
                benefit_event_time="20:10-21:00",
                ticket_url="https://example.com/ticket",
                general_ticket_price=2500,
                priority_ticket_price=4000,
                ticket_sale_type="抽選",
                ticket_status="sold_out",
                ticket_application_start_at=datetime(2026, 5, 25, 20, 0, tzinfo=JST),
                ticket_application_deadline_at=datetime(2026, 6, 1, 23, 59, tzinfo=JST),
                payment_deadline_at=datetime(2026, 6, 5, 23, 59, tzinfo=JST),
                notes="管理用メモ",
                needs_review=True,
            )
        ]
    )
    header = [column.strip() for column in table.splitlines()[0].split("|")]

    assert header == PREVIEW_TABLE_COLUMNS
    assert header == ["日付", "曜日", "イベント名", "会場", "ライブ情報", "チケット情報", "申込情報", "チケットURL", "要確認"]
    assert "一般料金" not in header
    assert "優先料金" not in header
    assert "申込締切" not in header
    assert "支払期限" not in header
    assert "要確認" in header
    assert "備考" not in header


def test_preview_table_formats_dates_for_japanese_readers():
    table = events_to_table(
        [
            CanonicalEvent(
                event_name="STARLIGHT LIVE vol.7",
                event_date=date(2026, 6, 15),
                ticket_application_start_at=datetime(2026, 5, 25, 20, 0, 30, tzinfo=JST),
                ticket_application_deadline_at=datetime(2026, 6, 1, 23, 59, 45, tzinfo=JST),
                payment_deadline_at=datetime(2026, 6, 5, 23, 59, 15, tzinfo=JST),
            )
        ]
    )

    assert "2026/06/15" in table
    assert "5/25 20:00" in table
    assert "6/1 23:59" in table
    assert "6/5 23:59" in table
    assert "20:00:30" not in table
    assert "23:59:45" not in table
    assert "2026-05-25T20:00:30+09:00" not in table
    assert "2026-06-01T23:59:45+09:00" not in table


def test_preview_table_keeps_empty_deadline_fields_empty():
    table = events_to_table([CanonicalEvent(event_name="No Deadline", event_date=date(2026, 6, 15))])
    row = [cell.strip() for cell in table.splitlines()[2].split("|")]
    header = [cell.strip() for cell in table.splitlines()[0].split("|")]

    assert row[header.index("申込情報")] == "未取得"


def test_public_json_still_contains_full_detail_fields():
    payload = json.loads(
        events_to_json(
            [
                CanonicalEvent(
                    event_name="STARLIGHT LIVE vol.7",
                    event_date=date(2026, 6, 15),
                    open_time="18:00",
                    myojou_performance_time="19:20-19:40",
                    benefit_event_time="20:10-21:00",
                    same_day_ticket_price=3000,
                    ticket_application_start_at=datetime(2026, 5, 25, 20, 0, tzinfo=JST),
                    ticket_application_deadline_at=datetime(2026, 6, 1, 23, 59, tzinfo=JST),
                    lottery_result_at=datetime(2026, 6, 3, 18, 0, tzinfo=JST),
                    payment_deadline_at=datetime(2026, 6, 5, 23, 59, tzinfo=JST),
                    ticket_sale_type="抽選",
                    general_ticket_price=2500,
                    notes="詳細メモ",
                    source_summary="source",
                    primary_source_url="https://x.com/info_myojou/status/1",
                    latest_source_url="https://x.com/info_myojou/status/2",
                    all_source_urls=["https://x.com/info_myojou/status/1", "https://x.com/info_myojou/status/2"],
                    manual_override=True,
                )
            ]
        )
    )

    row = payload[0]
    assert "開場" in row
    assert "出演時間" in row
    assert "特典会" in row
    assert "一般料金" in row
    assert "当日料金" in row
    assert "申込開始" in row
    assert "申込締切" in row
    assert "当落発表" in row
    assert "支払期限" in row
    assert "販売方式" in row
    assert "ライブ情報" in row
    assert "チケット情報" in row
    assert "申込情報" in row
    assert "備考" in row
    assert "告知ポスト" in row
    assert "初回告知URL" in row
    assert "最新告知URL" in row
    assert "関連告知URL" in row
    assert "手動更新" in row
    assert row["販売状況"] == "不明"
    assert row["日付"] == "2026-06-15"
    assert row["申込開始"] == "2026-05-25T20:00:00+09:00"
    assert row["申込締切"] == "2026-06-01T23:59:00+09:00"


def test_web_events_json_export_shape():
    payload = json.loads(
        events_to_web_json(
            [
                CanonicalEvent(
                    event_name="STARLIGHT LIVE vol.7",
                    event_date=date(2026, 6, 15),
                    venue="渋谷Milkyway",
                    start_time="18:45",
                    myojou_performance_time="19:10-19:35",
                    benefit_event_time="20:00-21:00",
                    ticket_url="https://example.com/ticket",
                    general_ticket_price=2500,
                    priority_ticket_price=4000,
                    ticket_sale_type="抽選",
                    ticket_status="sold_out",
                    ticket_application_start_at=datetime(2026, 5, 25, 20, 0, tzinfo=JST),
                    ticket_application_deadline_at=datetime(2026, 6, 1, 23, 59, tzinfo=JST),
                    payment_deadline_at=datetime(2026, 6, 5, 23, 59, tzinfo=JST),
                    needs_review=True,
                )
            ]
        )
    )

    assert payload == [
        {
            "event_date": "2026-06-15",
            "weekday": "月",
            "event_name": "STARLIGHT LIVE vol.7",
            "venue": "渋谷Milkyway",
            "live_summary": "開演 18:45 / 出演 19:10-19:35 / 特典会 20:00-21:00",
            "ticket_summary": "抽選 / 一般 2,500円 / 優先 4,000円 / 完売",
            "application_summary": "申込 5/25 20:00〜6/1 23:59 / 支払 6/5 23:59",
            "ticket_url": "https://example.com/ticket",
            "ticket_status": "完売",
            "needs_review": True,
            "ticket_application_deadline_at": "2026-06-01T23:59:00+09:00",
            "payment_deadline_at": "2026-06-05T23:59:00+09:00",
            "ticket_sales": [],
            "next_ticket_deadline_at": "",
            "next_ticket_sale_type": "抽選",
            "next_ticket_label": "",
        }
    ]


def test_web_events_json_keeps_events_without_deadline_for_missing_filter():
    payload = json.loads(
        events_to_web_json(
            [
                CanonicalEvent(
                    event_name="締切未取得ライブ",
                    event_date=date(2026, 6, 20),
                    venue="渋谷近未来会館",
                    ticket_status="unknown",
                )
            ]
        )
    )

    assert payload == [
        {
            "event_date": "2026-06-20",
            "weekday": "土",
            "event_name": "締切未取得ライブ",
            "venue": "渋谷近未来会館",
            "live_summary": "",
            "ticket_summary": "不明 / 不明",
            "application_summary": "未取得",
            "ticket_url": "",
            "ticket_status": "不明",
            "needs_review": False,
            "ticket_application_deadline_at": "",
            "payment_deadline_at": "",
            "ticket_sales": [],
            "next_ticket_deadline_at": "",
            "next_ticket_sale_type": "不明",
            "next_ticket_label": "",
        }
    ]


def test_export_public_command_writes_events_json(tmp_path, capsys):
    db_path = tmp_path / "state.sqlite"
    output_path = tmp_path / "public" / "events.json"
    state = SQLiteStateStore(db_path)
    state.save_event(
        CanonicalEvent(
            event_name="STARLIGHT LIVE vol.7",
            event_date=date(2026, 6, 15),
            venue="渋谷Milkyway",
            start_time="18:45",
            ticket_url="https://example.com/ticket",
            general_ticket_price=2500,
            ticket_status="sold_out",
        )
    )

    result = main(["export-public", "--db", str(db_path), "--output", str(output_path)])
    output = capsys.readouterr().out
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert result == 0
    assert "Exported 1 events" in output
    assert output_path.exists()
    assert payload[0]["event_name"] == "STARLIGHT LIVE vol.7"
    assert payload[0]["ticket_status"] == "完売"
    assert "ticket_application_deadline_at" in payload[0]
    assert "payment_deadline_at" in payload[0]


def test_large_mock_dataset_exports_many_events_and_skips_non_events(tmp_path, mock_posts_dir: Path, capsys):
    db_path = tmp_path / "large.sqlite"
    output_path = tmp_path / "events.json"

    run_result = main(
        [
            "run",
            "--mock-posts",
            str(mock_posts_dir),
            "--db",
            str(db_path),
            "--target",
            "none",
            "--dry-run",
        ]
    )
    run_output = capsys.readouterr().out
    export_result = main(["export-public", "--db", str(db_path), "--output", str(output_path)])
    export_output = capsys.readouterr().out
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert run_result == 0
    assert export_result == 0
    assert "Fetched 42" in run_output
    assert "skipped 5" in run_output
    assert "canonical 22" in run_output
    assert "Exported 22 events" in export_output
    assert len(payload) == 22
    multi_tier = next(row for row in payload if row["event_name"] == "MULTI TIER NIGHT")
    assert len(multi_tier["ticket_sales"]) == 5
    assert {sale["ticket_tier"] for sale in multi_tier["ticket_sales"]} == {"一般", "VIP", "SS", "前方", "カメラ"}
    assert any(sale["ticket_tier"] == "VIP" and sale["status"] == "完売" for sale in multi_tier["ticket_sales"])
    basic = next(row for row in payload if row["event_name"] == "BASIC INFO ONLY")
    assert basic["ticket_sales"] == []
    assert basic["application_summary"] == "未取得"
    source_records = SQLiteStateStore(db_path).source_post_records()
    assert sum(1 for record in source_records if record["classification"] == "non_event") == 5
    assert {row["event_name"] for row in payload}.isdisjoint(
        {
            "新アクリルキーホルダー",
            "光の方へ",
            "本日のライブありがとうございました",
        }
    )


def test_public_web_json_has_required_keys_for_large_sample(tmp_path, mock_posts_dir: Path, capsys):
    db_path = tmp_path / "large.sqlite"
    output_path = tmp_path / "events.json"
    required_keys = {
        "event_date",
        "weekday",
        "event_name",
        "venue",
        "live_summary",
        "ticket_summary",
        "application_summary",
        "ticket_url",
        "ticket_status",
        "needs_review",
        "ticket_application_deadline_at",
        "payment_deadline_at",
        "ticket_sales",
        "next_ticket_deadline_at",
        "next_ticket_sale_type",
        "next_ticket_label",
    }

    assert main(["run", "--mock-posts", str(mock_posts_dir), "--db", str(db_path), "--target", "none", "--dry-run"]) == 0
    capsys.readouterr()
    assert main(["export-public", "--db", str(db_path), "--output", str(output_path)]) == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload
    assert all(set(row) == required_keys for row in payload)
    assert any(row["event_date"] == "2026-05-28" for row in payload)
    assert any(row["event_date"].startswith("2026-06") for row in payload)
    assert any(row["event_date"].startswith("2026-07") for row in payload)
    assert any(row["ticket_application_deadline_at"] for row in payload)
    assert any(row["ticket_sales"] for row in payload)
    assert any("next_ticket_deadline_at" in row for row in payload)
    assert any(
        row["application_summary"] == "未取得" and row["ticket_application_deadline_at"] == ""
        for row in payload
    )


def test_static_public_ui_has_filters_date_groups_and_status_badges():
    app_js = Path("public/app.js").read_text(encoding="utf-8")
    html = Path("public/index.html").read_text(encoding="utf-8")
    css = Path("public/styles.css").read_text(encoding="utf-8")

    for filter_name in ("upcoming", "week", "month", "missing-deadline", "all"):
        assert f'data-filter="{filter_name}"' in html
    for sort_name in ("event-date", "deadline"):
        assert f'data-sort="{sort_name}"' in html
    for view_name in ("cards", "calendar"):
        assert f'data-view="{view_name}"' in html
    for calendar_mode in ("live", "application", "payment", "all"):
        assert f'data-calendar-mode="{calendar_mode}"' in html
    for month_load in ("previous", "next"):
        assert f'data-month-load="{month_load}"' in html
    assert "前の月を表示" in html
    assert "次の月を表示" in html
    assert "calendar_helpers.js" in html
    assert "groupedEvents" in app_js
    assert "renderCalendar" in app_js
    assert "calendarCell" in app_js
    assert "renderDeadlineAlerts" in app_js
    assert "deadlineAlertItem" in app_js
    assert "selectedDate" not in app_js
    assert "selected-date" not in html
    assert "この日のライブ予定はありません" not in html
    assert "statusClass" in app_js
    assert "deadlineUrgency" in app_js
    assert "deadlineSortKey" in app_js
    assert "next_ticket_deadline_at" in app_js
    assert "ticketSalesList" in app_js
    assert "ticket-sale-chip" in css
    assert "view-switcher" in css
    assert "calendar-mode-controls" in css
    assert "deadline-alerts" in css
    assert "calendar-grid" in css
    assert "calendar-day" in css
    assert "has-events" in css
    assert "is-today" in css
    assert "calendar-chip-live" in css
    assert "calendar-chip-application" in css
    assert "calendar-chip-payment" in css
    assert "calendar-chip-sold-out" in css
    assert "calendar-chip-ended" in css
    assert "overflow-x: hidden" in css
    assert "is-selected" not in css
    assert "selected-date-events" not in css
    assert "締切未取得" in app_js
    assert "今日締切" in app_js
    assert "明日締切" in app_js
    assert "あと${diff}日" in app_js
    assert "status-sold-out" in css
    assert "status-ended" in css
    assert "deadline-badge" in css
    assert "deadline-today" in css
    assert "summary-missing" in app_js
    assert "summary-missing" in css
    assert "application-row" in css
    assert "ticket-button" in css


def test_readme_documents_empty_deadlines_stay_visible():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "申込締切が空欄のライブも申込・締切ビューに表示する" in readme
    assert "前の月を表示" in readme
    assert "次の月を表示" in readme
    assert "ライブ日" in readme
    assert "申込締切" in readme
    assert "支払期限" in readme
    assert "締切アラート" in readme
    assert "Tapping a date does not open a separate selected-date list" in readme


def test_japanese_sheets_headers():
    assert SHEET_HEADERS == [
        "イベント名",
        "日付",
        "曜日",
        "会場",
        "ライブ情報",
            "チケット情報",
            "申込情報",
            "販売期間一覧",
            "次の申込締切",
            "次の販売方式",
            "開場",
        "開演",
        "出演時間",
        "特典会",
        "チケットURL",
        "一般料金",
        "優先種別",
        "優先料金",
        "当日料金",
        "申込開始",
        "申込締切",
        "当落発表",
        "支払期限",
        "販売方式",
        "販売状況",
        "備考",
        "告知ポスト",
        "初回告知URL",
        "最新告知URL",
        "関連告知URL",
        "最新告知日時",
        "最新告知種別",
        "最終更新",
        "要確認",
        "手動更新",
    ]


def test_japanese_notion_property_mapping(mock_posts):
    from myojou_sync.models import CanonicalEvent
    from myojou_sync.parser import PostParser

    parsed = PostParser().parse_post(mock_posts["180005"])
    assert parsed is not None
    properties = _event_to_notion_properties(CanonicalEvent.from_extracted(parsed))

    assert "イベント名" in properties
    assert "日付" in properties
    assert "曜日" in properties
    assert "販売状況" in properties
    assert "要確認" in properties
    assert "manual_override" not in properties
    assert properties["販売状況"]["select"]["name"] == "完売"


def test_target_notion_does_not_require_sheets_env(tmp_path, mock_posts_dir: Path, monkeypatch):
    _reset_fake_sinks()
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("NO_X_API", "true")
    monkeypatch.setenv("NOTION_TOKEN", "token")
    monkeypatch.setenv("NOTION_DATABASE_ID", "db")
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.setattr("myojou_sync.cli.NotionEventSink", FakeNotionSink)
    monkeypatch.setattr("myojou_sync.cli.GoogleSheetsEventSink", FakeSheetsSink)

    result = main(
        [
            "run",
            "--mock-posts",
            str(mock_posts_dir),
            "--db",
            str(tmp_path / "notion.sqlite"),
            "--no-dry-run",
            "--target",
            "notion",
        ]
    )

    assert result == 0
    assert FakeNotionSink.calls == ["init", "sync"]
    assert FakeSheetsSink.calls == []


def test_target_sheets_does_not_require_notion_env(tmp_path, mock_posts_dir: Path, monkeypatch):
    _reset_fake_sinks()
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("NO_X_API", "true")
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.delenv("NOTION_DATABASE_ID", raising=False)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "{}")
    monkeypatch.setenv("GOOGLE_SHEET_ID", "sheet")
    monkeypatch.setattr("myojou_sync.cli.NotionEventSink", FakeNotionSink)
    monkeypatch.setattr("myojou_sync.cli.GoogleSheetsEventSink", FakeSheetsSink)

    result = main(
        [
            "run",
            "--mock-posts",
            str(mock_posts_dir),
            "--db",
            str(tmp_path / "sheets.sqlite"),
            "--no-dry-run",
            "--target",
            "sheets",
        ]
    )

    assert result == 0
    assert FakeNotionSink.calls == []
    assert FakeSheetsSink.calls == ["init", "sync"]


def test_target_both_requires_both_env_sets(tmp_path, mock_posts_dir: Path, monkeypatch):
    _reset_fake_sinks()
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("NO_X_API", "true")
    monkeypatch.setenv("NOTION_TOKEN", "token")
    monkeypatch.setenv("NOTION_DATABASE_ID", "db")
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.setattr("myojou_sync.cli.NotionEventSink", FakeNotionSink)
    monkeypatch.setattr("myojou_sync.cli.GoogleSheetsEventSink", FakeSheetsSink)

    result = main(
        [
            "run",
            "--mock-posts",
            str(mock_posts_dir),
            "--db",
            str(tmp_path / "both-missing.sqlite"),
            "--no-dry-run",
            "--target",
            "both",
        ]
    )

    assert result == 2
    assert FakeNotionSink.calls == []
    assert FakeSheetsSink.calls == []


def test_target_both_runs_both_when_env_is_available(tmp_path, mock_posts_dir: Path, monkeypatch):
    _reset_fake_sinks()
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("NO_X_API", "true")
    monkeypatch.setenv("NOTION_TOKEN", "token")
    monkeypatch.setenv("NOTION_DATABASE_ID", "db")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "{}")
    monkeypatch.setenv("GOOGLE_SHEET_ID", "sheet")
    monkeypatch.setattr("myojou_sync.cli.NotionEventSink", FakeNotionSink)
    monkeypatch.setattr("myojou_sync.cli.GoogleSheetsEventSink", FakeSheetsSink)

    result = main(
        [
            "run",
            "--mock-posts",
            str(mock_posts_dir),
            "--db",
            str(tmp_path / "both.sqlite"),
            "--no-dry-run",
            "--target",
            "both",
        ]
    )

    assert result == 0
    assert FakeNotionSink.calls == ["init", "sync"]
    assert FakeSheetsSink.calls == ["init", "sync"]


def test_target_none_does_not_call_external_adapters(tmp_path, mock_posts_dir: Path, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("external adapter should not be constructed for --target none")

    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("NO_X_API", "true")
    monkeypatch.setattr("myojou_sync.cli.NotionEventSink", fail)
    monkeypatch.setattr("myojou_sync.cli.GoogleSheetsEventSink", fail)

    result = main(
        [
            "run",
            "--mock-posts",
            str(mock_posts_dir),
            "--db",
            str(tmp_path / "none.sqlite"),
            "--no-dry-run",
            "--target",
            "none",
        ]
    )

    assert result == 0


def test_dry_run_skips_external_adapters_regardless_of_target(tmp_path, mock_posts_dir: Path, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("external adapter should not be constructed during dry-run")

    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("NO_X_API", "true")
    monkeypatch.setattr("myojou_sync.cli.NotionEventSink", fail)
    monkeypatch.setattr("myojou_sync.cli.GoogleSheetsEventSink", fail)

    for target in ("notion", "sheets", "both", "none"):
        result = main(
            [
                "run",
                "--mock-posts",
                str(mock_posts_dir),
                "--db",
                str(tmp_path / f"{target}.sqlite"),
                "--dry-run",
                "--target",
                target,
            ]
        )

        assert result == 0
