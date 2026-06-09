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
