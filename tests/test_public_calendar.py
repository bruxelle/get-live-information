from __future__ import annotations

import subprocess
import textwrap


def test_calendar_helpers_group_modes_alerts_month_range_and_invalid_dates():
    script = textwrap.dedent(
        """
        const assert = require("assert");
        const helpers = require("./public/calendar_helpers.js");
        const events = [
          {
            event_date: "2026-06-15",
            event_name: "A LIVE",
            venue: "渋谷",
            next_ticket_deadline_at: "2026-06-04T23:59:00+09:00",
            payment_deadline_at: "2026-06-06T23:59:00+09:00",
            application_summary: "申込 6/1 20:00〜6/4 23:59",
            ticket_status: "販売中",
          },
          {
            event_date: "2026-06-15",
            event_name: "B LIVE",
            venue: "新宿",
            ticket_application_deadline_at: "2026-06-05T23:59:00+09:00",
            payment_deadline_at: "",
            application_summary: "申込締切 6/5 23:59",
            ticket_status: "完売",
          },
          {
            event_date: "2026-06-20",
            event_name: "C LIVE",
            venue: "横浜",
            payment_deadline_at: "2026-06-07T12:00:00+09:00",
            application_summary: "未取得",
            ticket_status: "販売終了",
          },
          { event_date: "", event_name: "NO DATE", application_summary: "未取得" },
          { event_date: "2026-02-31", event_name: "BAD DATE", next_ticket_deadline_at: "bad" },
          { event_date: "not-a-date", event_name: "TEXT DATE" },
        ];

        const liveGroups = helpers.groupCalendarEntries(events, "live");
        assert.deepStrictEqual(Object.keys(liveGroups).sort(), ["2026-06-15", "2026-06-20"]);
        assert.strictEqual(liveGroups["2026-06-15"].length, 2);

        const applicationGroups = helpers.groupCalendarEntries(events, "application");
        assert.deepStrictEqual(Object.keys(applicationGroups).sort(), ["2026-06-04", "2026-06-05"]);
        assert.strictEqual(applicationGroups["2026-06-04"][0].kind, "application");

        const paymentGroups = helpers.groupCalendarEntries(events, "payment");
        assert.deepStrictEqual(Object.keys(paymentGroups).sort(), ["2026-06-06", "2026-06-07"]);
        assert.strictEqual(paymentGroups["2026-06-07"][0].kind, "payment");

        const allGroups = helpers.groupCalendarEntries(events, "all");
        assert.deepStrictEqual(Object.keys(allGroups).sort(), [
          "2026-06-04",
          "2026-06-05",
          "2026-06-06",
          "2026-06-07",
          "2026-06-15",
          "2026-06-20",
        ]);

        const cells = helpers.buildMonthCalendar("2026-06", events, "2026-06-04", "all");
        assert.strictEqual(cells.length, 42);
        assert.strictEqual(cells.find((cell) => cell.key === "2026-06-04").application_count, 1);
        assert.strictEqual(cells.find((cell) => cell.key === "2026-06-04").is_today, true);
        assert.strictEqual(cells.find((cell) => cell.key === "2026-06-05").is_tomorrow, true);
        assert.strictEqual(cells.find((cell) => cell.key === "2026-06-15").live_count, 2);
        assert.strictEqual(cells.find((cell) => cell.key === "2026-06-15").sold_out_count, 1);
        assert.strictEqual(cells.find((cell) => cell.key === "2026-06-20").ended_count, 1);
        assert.strictEqual(cells.find((cell) => cell.key === "2026-05-31").is_current_month, false);

        const alerts = helpers.buildDeadlineAlerts(events, "2026-06-04");
        assert.strictEqual(alerts.today.length, 1);
        assert.strictEqual(alerts.tomorrow.length, 1);
        assert.strictEqual(alerts.missing.length, 4);

        assert.deepStrictEqual(helpers.visibleMonthKeys("2026-06", 3), ["2026-06", "2026-07", "2026-08"]);
        assert.strictEqual(helpers.addMonths("2026-06", -1), "2026-05");
        assert.strictEqual(helpers.addMonths("2026-12", 1), "2027-01");
        assert.strictEqual(helpers.monthLabel("2026-06"), "2026年6月");
        assert.strictEqual(helpers.isValidEventDate("2026-06-15"), true);
        assert.strictEqual(helpers.isValidEventDate("2026-02-31"), false);
        assert.strictEqual(helpers.isValidEventDate(""), false);
        """
    )

    subprocess.run(["node", "-e", script], check=True, cwd=".")


def test_calendar_application_entries_are_grouped_by_sale_period_deadline_and_kind():
    script = textwrap.dedent(
        """
        const assert = require("assert");
        const helpers = require("./public/calendar_helpers.js");
        const events = [
          {
            public_event_id: "one-only:2026-07-20",
            event_date: "2026-07-20",
            event_name: "ONE AND ONLY",
            venue: "Zepp Shinjuku",
            ticket_sales: [
              { sale_type: "抽選", ticket_name: "前方", deadline_at: "2026-06-29T23:59:00+09:00" },
              { sale_type: "抽選", ticket_name: "一般", deadline_at: "2026-06-29T23:59:00+09:00" },
              { sale_type: "一般", ticket_name: "前方", deadline_at: "2026-07-15T23:59:00+09:00" },
              { sale_type: "一般", ticket_name: "一般", deadline_at: "2026-07-15T23:59:00+09:00" },
              { sale_type: "当日券", ticket_name: "当日券" },
            ],
          },
        ];

        const applicationGroups = helpers.groupCalendarEntries(events, "application");
        assert.deepStrictEqual(Object.keys(applicationGroups).sort(), ["2026-06-29", "2026-07-15"]);

        assert.strictEqual(applicationGroups["2026-06-29"].length, 1);
        assert.strictEqual(applicationGroups["2026-06-29"][0].application_kind, "lottery");
        assert.strictEqual(applicationGroups["2026-06-29"][0].deadline_kind, "lotteryDeadline");
        assert.strictEqual(applicationGroups["2026-06-29"][0].label, "抽選申込締切");
        assert.strictEqual(applicationGroups["2026-06-29"][0].ticket_sales.length, 2);
        assert.deepStrictEqual(
          applicationGroups["2026-06-29"][0].ticket_sales.map((sale) => sale.ticket_name).sort(),
          ["一般", "前方"],
        );

        assert.strictEqual(applicationGroups["2026-07-15"].length, 1);
        assert.strictEqual(applicationGroups["2026-07-15"][0].application_kind, "first");
        assert.strictEqual(applicationGroups["2026-07-15"][0].deadline_kind, "firstComeDeadline");
        assert.strictEqual(applicationGroups["2026-07-15"][0].label, "先着申込締切");
        assert.strictEqual(applicationGroups["2026-07-15"][0].ticket_sales.length, 2);

        const liveGroups = helpers.groupCalendarEntries(events, "live");
        assert.strictEqual(liveGroups["2026-07-20"].length, 1);
        assert.strictEqual(liveGroups["2026-07-20"][0].application_kind, undefined);

        const allGroups = helpers.groupCalendarEntries(events, "all");
        assert.strictEqual(allGroups["2026-06-29"][0].application_kind, "lottery");
        assert.strictEqual(allGroups["2026-06-29"][0].deadline_kind, "lotteryDeadline");
        assert.strictEqual(allGroups["2026-07-15"][0].application_kind, "first");
        assert.strictEqual(allGroups["2026-07-15"][0].deadline_kind, "firstComeDeadline");
        assert.strictEqual(allGroups["2026-07-20"][0].kind, "live");
        """
    )

    subprocess.run(["node", "-e", script], check=True, cwd=".")


def test_calendar_deadline_kind_uses_sale_period_text_not_whole_event_text():
    script = textwrap.dedent(
        """
        const assert = require("assert");
        const helpers = require("./public/calendar_helpers.js");
        const events = [
          {
            public_event_id: "one-only:2026-07-16",
            event_date: "2026-07-16",
            event_name: "ONE AND ONLY",
            venue: "Spotify O-EAST",
            ticket_summary: "抽選あり・一般販売あり / 優先 11,000円 / 一般 4,500円",
            application_summary: "抽選 6/15 20:30〜6/29 23:59 / 一般販売 7/4 20:00〜7/15 23:59",
            ticket_sales: [
              { sale_type: "抽選", ticket_name: "前方", deadline_at: "2026-06-29T23:59:00+09:00" },
              { sale_type: "抽選", ticket_name: "一般", deadline_at: "2026-06-29T23:59:00+09:00" },
              { sale_type: "一般", ticket_name: "前方", deadline_at: "2026-07-15T23:59:00+09:00" },
              { sale_type: "一般", ticket_name: "一般", deadline_at: "2026-07-15T23:59:00+09:00" },
            ],
          },
        ];

        const applicationGroups = helpers.groupCalendarEntries(events, "application");
        assert.deepStrictEqual(
          applicationGroups["2026-06-29"].map((entry) => entry.deadline_kind),
          ["lotteryDeadline"],
        );
        assert.deepStrictEqual(
          applicationGroups["2026-06-29"].map((entry) => entry.label),
          ["抽選申込締切"],
        );
        assert.deepStrictEqual(
          applicationGroups["2026-07-15"].map((entry) => entry.deadline_kind),
          ["firstComeDeadline"],
        );
        assert.deepStrictEqual(
          applicationGroups["2026-07-15"].map((entry) => entry.label),
          ["先着申込締切"],
        );

        const noSaleRows = [
          {
            event_date: "2026-07-16",
            event_name: "NO ROWS",
            ticket_application_deadline_at: "2026-06-29T23:59:00+09:00",
            ticket_summary: "抽選あり・一般販売あり",
            application_summary: "抽選 6/29締切 / 一般販売 7/15締切",
          },
        ];
        const fallbackGroups = helpers.groupCalendarEntries(noSaleRows, "application");
        assert.strictEqual(fallbackGroups["2026-06-29"].length, 1);
        assert.strictEqual(fallbackGroups["2026-06-29"][0].deadline_kind, "");
        assert.strictEqual(fallbackGroups["2026-06-29"][0].label, "");
        """
    )

    subprocess.run(["node", "-e", script], check=True, cwd=".")


def test_calendar_display_mode_filter_keeps_live_and_deadline_modes_exclusive():
    script = textwrap.dedent(
        """
        const assert = require("assert");
        const helpers = require("./public/calendar_helpers.js");
        const events = [
          {
            public_event_id: "one-only:2026-07-16",
            event_date: "2026-07-16",
            event_name: "ONE AND ONLY",
            venue: "Spotify O-EAST",
            ticket_sales: [
              { sale_type: "抽選", ticket_name: "前方", deadline_at: "2026-06-29T23:59:00+09:00" },
              { sale_type: "抽選", ticket_name: "一般", deadline_at: "2026-06-29T23:59:00+09:00" },
              { sale_type: "一般", ticket_name: "前方", deadline_at: "2026-07-15T23:59:00+09:00" },
              { sale_type: "一般", ticket_name: "一般", deadline_at: "2026-07-15T23:59:00+09:00" },
            ],
          },
        ];

        const allGroups = helpers.groupCalendarEntries(events, "all");
        assert.deepStrictEqual(
          helpers.filterCalendarEntriesForDisplay(allGroups["2026-06-29"], "live"),
          [],
        );
        assert.deepStrictEqual(
          helpers.filterCalendarEntriesForDisplay(allGroups["2026-07-15"], "live"),
          [],
        );
        assert.deepStrictEqual(
          helpers.filterCalendarEntriesForDisplay(allGroups["2026-07-16"], "live")
            .map((entry) => entry.kind),
          ["live"],
        );
        assert.deepStrictEqual(
          helpers.filterCalendarEntriesForDisplay(allGroups["2026-06-29"], "lotteryDeadline")
            .map((entry) => entry.deadline_kind),
          ["lotteryDeadline"],
        );
        assert.deepStrictEqual(
          helpers.filterCalendarEntriesForDisplay(allGroups["2026-07-15"], "lotteryDeadline"),
          [],
        );
        assert.deepStrictEqual(
          helpers.filterCalendarEntriesForDisplay(allGroups["2026-07-16"], "lotteryDeadline"),
          [],
        );
        assert.deepStrictEqual(
          helpers.filterCalendarEntriesForDisplay(allGroups["2026-06-29"], "firstComeDeadline"),
          [],
        );
        assert.deepStrictEqual(
          helpers.filterCalendarEntriesForDisplay(allGroups["2026-07-15"], "firstComeDeadline")
            .map((entry) => entry.deadline_kind),
          ["firstComeDeadline"],
        );
        assert.deepStrictEqual(
          helpers.filterCalendarEntriesForDisplay(allGroups["2026-07-16"], "firstComeDeadline"),
          [],
        );
        """
    )

    subprocess.run(["node", "-e", script], check=True, cwd=".")


def test_public_ui_spec_calendar_mode_filter_semantics_are_exclusive():
    script = textwrap.dedent(
        """
        const assert = require("assert");
        const helpers = require("./public/calendar_helpers.js");
        const event = { event_name: "ONE AND ONLY", event_date: "2026-07-16" };
        const entries = [
          { kind: "live", event },
          { kind: "application", deadline_kind: "lotteryDeadline", label: "抽選申込締切", event },
          { kind: "application", deadline_kind: "firstComeDeadline", label: "先着申込締切", event },
          { kind: "payment", event },
        ];

        assert.deepStrictEqual(
          helpers.filterCalendarEntriesForDisplay(entries, "live").map((entry) => entry.kind),
          ["live"],
        );
        assert.deepStrictEqual(
          helpers.filterCalendarEntriesForDisplay(entries, "lotteryDeadline").map((entry) => entry.label),
          ["抽選申込締切"],
        );
        assert.deepStrictEqual(
          helpers.filterCalendarEntriesForDisplay(entries, "firstComeDeadline").map((entry) => entry.label),
          ["先着申込締切"],
        );
        assert.deepStrictEqual(
          helpers.filterCalendarEntriesForDisplay(entries, "application"),
          [],
        );
        assert.deepStrictEqual(
          helpers.filterCalendarEntriesForDisplay(entries, "payment"),
          [],
        );
        assert.deepStrictEqual(
          helpers.filterCalendarEntriesForDisplay(entries, "all"),
          [],
        );
      """
    )

    subprocess.run(["node", "-e", script], check=True, cwd=".")
