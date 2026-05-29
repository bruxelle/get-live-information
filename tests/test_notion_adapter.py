from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from myojou_sync.models import CanonicalEvent
from myojou_sync.sync.notion import NotionEventSink, _event_to_notion_properties, inspect_notion_schema


JST = timezone(timedelta(hours=9))


class FakeDatabasesEndpoint:
    def __init__(self, payload):
        self.payload = payload
        self.retrieve_calls: list[dict] = []

    def retrieve(self, **kwargs):
        self.retrieve_calls.append(kwargs)
        return self.payload


class FakeDataSourcesEndpoint:
    def __init__(self, retrieve_payload=None, query_results=None):
        self.query_calls: list[dict] = []
        self.retrieve_calls: list[dict] = []
        self.retrieve_payload = retrieve_payload or {}
        self.query_results = query_results

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        if callable(self.query_results):
            return self.query_results(kwargs)
        if self.query_results is not None:
            return {"results": self.query_results}
        return {"results": [{"id": "page_xxx"}]}

    def retrieve(self, **kwargs):
        self.retrieve_calls.append(kwargs)
        return self.retrieve_payload


class FakePagesEndpoint:
    def __init__(self, retrieve_payload=None, create_response=None):
        self.retrieve_payload = retrieve_payload or {"properties": {}}
        self.create_response = create_response or {"id": "page_new"}
        self.retrieve_calls: list[dict] = []
        self.update_calls: list[dict] = []
        self.create_calls: list[dict] = []

    def retrieve(self, **kwargs):
        self.retrieve_calls.append(kwargs)
        return self.retrieve_payload

    def update(self, **kwargs):
        self.update_calls.append(kwargs)
        return {}

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return self.create_response


class FakeNotionClient:
    def __init__(self, database_payload, data_source_payload=None, query_results=None, pages=None):
        self.databases = FakeDatabasesEndpoint(database_payload)
        self.data_sources = FakeDataSourcesEndpoint(data_source_payload, query_results=query_results)
        self.pages = pages or FakePagesEndpoint()


def test_find_page_id_uses_current_data_source_query_api():
    client = FakeNotionClient({"data_sources": [{"id": "ds_xxx"}]})
    sink = NotionEventSink("token", "db_xxx", client=client)
    event = CanonicalEvent(event_name="STARLIGHT LIVE vol.7", event_date=date(2026, 6, 15))

    first_page_id = sink.find_page_id(event)
    second_page_id = sink.find_page_id(event)

    assert first_page_id == "page_xxx"
    assert second_page_id == "page_xxx"
    assert client.databases.retrieve_calls == [{"database_id": "db_xxx"}]
    assert client.data_sources.query_calls == [
        {
            "data_source_id": "ds_xxx",
            "filter": {
                "and": [
                    {"property": "イベント名", "title": {"equals": "STARLIGHT LIVE vol.7"}},
                    {"property": "日付", "date": {"equals": "2026-06-15"}},
                ]
            },
            "page_size": 1,
        },
        {
            "data_source_id": "ds_xxx",
            "filter": {
                "and": [
                    {"property": "イベント名", "title": {"equals": "STARLIGHT LIVE vol.7"}},
                    {"property": "日付", "date": {"equals": "2026-06-15"}},
                ]
            },
            "page_size": 1,
        },
    ]


def test_find_page_id_uses_title_only_for_undated_events():
    client = FakeNotionClient({"data_sources": [{"id": "ds_xxx"}]})
    sink = NotionEventSink("token", "db_xxx", client=client)

    assert sink.find_page_id(CanonicalEvent(event_name="DATE TBD LIVE")) == "page_xxx"
    assert client.data_sources.query_calls == [
        {
            "data_source_id": "ds_xxx",
            "filter": {"property": "イベント名", "title": {"equals": "DATE TBD LIVE"}},
            "page_size": 1,
        }
    ]


def test_duplicate_notion_sync_updates_existing_page_instead_of_creating():
    client = FakeNotionClient({"data_sources": [{"id": "ds_xxx"}]}, query_results=[{"id": "page_existing"}])
    sink = NotionEventSink("token", "db_xxx", client=client)

    synced = sink.sync_event(CanonicalEvent(event_name="STARLIGHT LIVE vol.7", event_date=date(2026, 6, 15)))

    assert synced.notion_page_id == "page_existing"
    assert client.pages.create_calls == []
    assert len(client.pages.update_calls) == 1


def test_persisted_page_id_is_used_without_querying_or_creating():
    client = FakeNotionClient({"data_sources": [{"id": "ds_xxx"}]}, query_results=[])
    sink = NotionEventSink("token", "db_xxx", client=client)
    event = CanonicalEvent(
        event_name="STARLIGHT LIVE vol.7",
        event_date=date(2026, 6, 15),
        notion_page_id="page_existing",
    )

    synced = sink.sync_event(event)

    assert synced.notion_page_id == "page_existing"
    assert client.data_sources.query_calls == []
    assert client.pages.create_calls == []
    assert client.pages.update_calls[0]["page_id"] == "page_existing"


def test_resolve_data_source_id_fails_clearly_when_database_has_no_data_sources():
    client = FakeNotionClient({"data_sources": []})
    sink = NotionEventSink("token", "db_xxx", client=client)

    with pytest.raises(RuntimeError, match="Could not resolve a Notion data source ID"):
        sink.resolve_data_source_id()


def test_inspect_notion_schema_prints_property_names_types_and_select_options():
    client = FakeNotionClient(
        {
            "data_sources": [{"id": "ds_xxx"}],
            "properties": {
                "イベント名": {"type": "title", "title": {}},
                "曜日": {
                    "type": "select",
                    "select": {"options": [{"name": "月"}, {"name": "火"}]},
                },
                "告知ポスト": {"type": "url", "url": {}},
            },
        }
    )

    output = inspect_notion_schema("token", "db_xxx", client=client)

    assert "data_source_id: ds_xxx" in output
    assert "- イベント名: (title) supported" in output
    assert "- 曜日: (select) supported" in output
    assert "options: 月, 火" in output
    assert "- 告知ポスト: (url) supported" in output


def test_inspect_notion_schema_reads_properties_from_data_source_when_database_is_empty():
    client = FakeNotionClient(
        {"data_sources": [{"id": "ds_xxx"}]},
        {
            "object": "data_source",
            "id": "ds_xxx",
            "properties": {"曜日": {"type": "select", "select": {"options": [{"name": "月"}]}}},
        },
    )

    output = inspect_notion_schema("token", "db_xxx", client=client)

    assert client.databases.retrieve_calls == [{"database_id": "db_xxx"}]
    assert client.data_sources.retrieve_calls == [{"data_source_id": "ds_xxx"}]
    assert "data_source_id: ds_xxx" in output
    assert "- 曜日: (select) supported" in output


def test_notion_payload_uses_actual_schema_property_types():
    event = CanonicalEvent(
        event_name="STARLIGHT LIVE vol.7",
        event_date=date(2026, 6, 15),
        start_time="18:45",
        myojou_performance_time="19:10-19:35",
        benefit_event_time="20:00-21:00",
        ticket_status="sold_out",
        ticket_url="https://example.com/ticket",
        general_ticket_price=2500,
        priority_ticket_price=4000,
        same_day_ticket_price=3000,
        ticket_application_start_at=datetime(2026, 5, 25, 20, 0, tzinfo=JST),
        ticket_application_deadline_at=datetime(2026, 6, 1, 23, 59, tzinfo=JST),
        lottery_result_at=datetime(2026, 6, 3, 18, 0, tzinfo=JST),
        payment_deadline_at=datetime(2026, 6, 5, 23, 59, tzinfo=JST),
        ticket_sale_type="抽選",
        latest_source_url="https://x.com/info_myojou/status/180001",
        needs_review=True,
        manual_override=False,
        updated_at=datetime(2026, 5, 26, 17, 30, tzinfo=JST),
    )
    properties = _event_to_notion_properties(
        event,
        property_types={
            "イベント名": "title",
            "日付": "date",
            "曜日": "select",
            "ライブ情報": "rich_text",
            "チケット情報": "rich_text",
            "申込情報": "rich_text",
            "販売状況": "select",
            "告知ポスト": "url",
            "チケットURL": "url",
            "一般料金": "number",
            "優先料金": "number",
            "当日料金": "number",
            "申込開始": "date",
            "申込締切": "date",
            "当落発表": "date",
            "支払期限": "date",
            "販売方式": "select",
            "最終更新": "date",
            "要確認": "checkbox",
            "手動更新": "checkbox",
        },
    )

    assert properties["曜日"] == {"select": {"name": "月"}}
    assert properties["ライブ情報"] == {"rich_text": [{"text": {"content": "開演 18:45 / 出演 19:10-19:35 / 特典会 20:00-21:00"}}]}
    assert properties["チケット情報"] == {"rich_text": [{"text": {"content": "抽選 / 一般 2,500円 / 優先 4,000円 / 当日 3,000円 / 完売"}}]}
    assert properties["申込情報"] == {
        "rich_text": [{"text": {"content": "申込 5/25 20:00〜6/1 23:59 / 当落 6/3 18:00 / 支払 6/5 23:59"}}]
    }
    assert properties["日付"] == {"date": {"start": "2026-06-15"}}
    assert properties["販売状況"] == {"select": {"name": "完売"}}
    assert properties["告知ポスト"] == {"url": "https://x.com/info_myojou/status/180001"}
    assert properties["チケットURL"] == {"url": "https://example.com/ticket"}
    assert properties["一般料金"] == {"number": 2500}
    assert properties["優先料金"] == {"number": 4000}
    assert properties["当日料金"] == {"number": 3000}
    assert properties["申込開始"] == {"date": {"start": "2026-05-25T20:00:00+09:00"}}
    assert properties["申込締切"] == {"date": {"start": "2026-06-01T23:59:00+09:00"}}
    assert properties["当落発表"] == {"date": {"start": "2026-06-03T18:00:00+09:00"}}
    assert properties["支払期限"] == {"date": {"start": "2026-06-05T23:59:00+09:00"}}
    assert properties["販売方式"] == {"select": {"name": "抽選"}}
    assert properties["最終更新"] == {"date": {"start": "2026-05-26T17:30:00+09:00"}}
    assert properties["要確認"] == {"checkbox": True}
    assert properties["手動更新"] == {"checkbox": False}


def test_notion_payload_uses_canonical_status_even_when_old_options_are_present():
    event = CanonicalEvent(event_name="STARLIGHT LIVE vol.7", ticket_status="sold_out")

    properties = _event_to_notion_properties(
        event,
        property_types={"販売状況": "select"},
        select_options={"販売状況": ("未販売", "販売中", "売切", "終了", "不明")},
    )

    assert properties["販売状況"] == {"select": {"name": "完売"}}


def test_notion_payload_includes_optional_ticket_sales_properties_when_schema_has_them():
    from myojou_sync.models import TicketSalePeriod

    event = CanonicalEvent(
        event_name="SALES TEST LIVE",
        ticket_sales=[
            TicketSalePeriod(
                sale_type="抽選",
                ticket_name="優先",
                ticket_tier="優先",
                price=4000,
                start_at=datetime(2026, 5, 1, 20, 0, tzinfo=JST),
                deadline_at=datetime(2026, 5, 10, 23, 59, tzinfo=JST),
            )
        ],
    )

    properties = _event_to_notion_properties(
        event,
        property_types={
            "イベント名": "title",
            "販売期間一覧": "rich_text",
            "次の申込締切": "date",
            "次の販売方式": "select",
        },
    )

    assert properties["販売期間一覧"]["rich_text"]
    assert properties["次の申込締切"] == {"date": {"start": "2026-05-10T23:59:00+09:00"}}
    assert properties["次の販売方式"] == {"select": {"name": "抽選"}}


@pytest.mark.parametrize(
    ("public_label", "notion_label"),
    [
        ("未確認", "不明"),
        ("unknown", "不明"),
        ("完売", "完売"),
        ("売切", "完売"),
        ("sold_out", "完売"),
        ("販売前", "未販売"),
        ("upcoming", "未販売"),
        ("販売中", "販売中"),
        ("on_sale", "販売中"),
        ("当日券あり", "販売中"),
        ("same_day", "販売中"),
        ("終了", "販売終了"),
        ("販売終了", "販売終了"),
        ("ended", "販売終了"),
    ],
)
def test_notion_ticket_status_mapping_matches_actual_select_options(public_label, notion_label):
    properties = _event_to_notion_properties(
        CanonicalEvent(event_name="Status Test", ticket_status=public_label),
        property_types={"販売状況": "select"},
        select_options={"販売状況": ("未販売", "販売中", "売切", "終了", "不明")},
    )

    assert properties["販売状況"] == {"select": {"name": notion_label}}


def test_notion_payload_empty_urls_and_none_numbers_are_safe():
    properties = _event_to_notion_properties(
        CanonicalEvent(event_name="No Ticket Yet"),
        property_types={
            "イベント名": "title",
            "告知ポスト": "url",
            "チケットURL": "url",
            "一般料金": "number",
            "優先料金": "number",
            "当日料金": "number",
        },
    )

    assert properties["告知ポスト"] == {"url": None}
    assert properties["チケットURL"] == {"url": None}
    assert properties["一般料金"] == {"number": None}
    assert properties["優先料金"] == {"number": None}
    assert properties["当日料金"] == {"number": None}
    assert properties["一般料金"]["number"] != ""
