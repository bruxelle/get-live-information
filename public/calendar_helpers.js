(function (root) {
  const CALENDAR_MODES = new Set(["live", "application", "payment", "all"]);

  function isValidEventDate(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const date = parseDateKey(value);
    return Boolean(date) && dateKey(date) === value;
  }

  function parseDateKey(value) {
    if (typeof value !== "string") return null;
    const parts = value.split("-").map(Number);
    if (parts.length !== 3 || parts.some(Number.isNaN)) return null;
    const date = new Date(parts[0], parts[1] - 1, parts[2]);
    if (date.getFullYear() !== parts[0] || date.getMonth() !== parts[1] - 1 || date.getDate() !== parts[2]) {
      return null;
    }
    return date;
  }

  function dateKey(date) {
    return [
      date.getFullYear(),
      String(date.getMonth() + 1).padStart(2, "0"),
      String(date.getDate()).padStart(2, "0"),
    ].join("-");
  }

  function monthKey(date) {
    return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0")].join("-");
  }

  function monthLabel(month) {
    const date = monthDate(month);
    return `${date.getFullYear()}年${date.getMonth() + 1}月`;
  }

  function monthDate(month) {
    if (month instanceof Date) {
      return new Date(month.getFullYear(), month.getMonth(), 1);
    }
    if (typeof month === "string" && /^\d{4}-\d{2}$/.test(month)) {
      const [year, monthNumber] = month.split("-").map(Number);
      return new Date(year, monthNumber - 1, 1);
    }
    return new Date();
  }

  function addMonths(month, delta) {
    const date = monthDate(month);
    return monthKey(new Date(date.getFullYear(), date.getMonth() + delta, 1));
  }

  function visibleMonthKeys(startMonth, count) {
    const length = Math.max(1, Number(count) || 1);
    return Array.from({ length }, (_, index) => addMonths(startMonth, index));
  }

  function isoDatePart(value) {
    if (!value || typeof value !== "string") return "";
    const match = value.match(/^\d{4}-\d{2}-\d{2}/);
    return match && isValidEventDate(match[0]) ? match[0] : "";
  }

  function applicationDeadlineKey(event) {
    return isoDatePart(event.next_ticket_deadline_at) || isoDatePart(event.ticket_application_deadline_at);
  }

  function paymentDeadlineKey(event) {
    return isoDatePart(event.payment_deadline_at);
  }

  function groupEventsByDate(events) {
    const groups = {};
    for (const event of events || []) {
      if (!isValidEventDate(event.event_date)) continue;
      if (!groups[event.event_date]) groups[event.event_date] = [];
      groups[event.event_date].push(event);
    }
    for (const key of Object.keys(groups)) {
      groups[key].sort(eventSort);
    }
    return groups;
  }

  function eventsForDate(events, key) {
    return groupEventsByDate(events)[key] || [];
  }

  function groupCalendarEntries(events, mode) {
    const activeMode = CALENDAR_MODES.has(mode) ? mode : "live";
    const groups = {};
    for (const event of events || []) {
      for (const entry of calendarEntriesForEvent(event, activeMode)) {
        if (!groups[entry.date]) groups[entry.date] = [];
        groups[entry.date].push(entry);
      }
    }
    for (const key of Object.keys(groups)) {
      groups[key].sort((left, right) => eventSort(left.event, right.event) || kindSort(left.kind, right.kind));
    }
    return groups;
  }

  function calendarEntriesForEvent(event, mode) {
    const entries = [];
    const includeLive = mode === "live" || mode === "all";
    const includeApplication = mode === "application" || mode === "all";
    const includePayment = mode === "payment" || mode === "all";

    if (includeLive && isValidEventDate(event.event_date)) {
      entries.push({ kind: "live", label: "ライブ", date: event.event_date, event });
    }
    if (includeApplication) {
      const deadline = applicationDeadlineKey(event);
      if (deadline) entries.push({ kind: "application", label: "申込", date: deadline, event });
    }
    if (includePayment) {
      const payment = paymentDeadlineKey(event);
      if (payment) entries.push({ kind: "payment", label: "支払", date: payment, event });
    }
    return entries;
  }

  function buildMonthCalendar(month, events, todayKey, mode = "live") {
    const start = monthDate(month);
    const calendarStart = new Date(start);
    calendarStart.setDate(start.getDate() - start.getDay());
    const groups = groupCalendarEntries(events, mode);
    const cells = [];
    const tomorrowKey = addDaysKey(todayKey, 1);

    for (let index = 0; index < 42; index += 1) {
      const date = new Date(calendarStart);
      date.setDate(calendarStart.getDate() + index);
      const key = dateKey(date);
      const entries = groups[key] || [];
      const counts = countEntries(entries);
      cells.push({
        key,
        day: date.getDate(),
        month: monthKey(date),
        is_current_month: date.getMonth() === start.getMonth(),
        is_today: key === todayKey,
        is_tomorrow: key === tomorrowKey,
        event_count: entries.length,
        live_count: counts.live,
        application_count: counts.application,
        payment_count: counts.payment,
        sold_out_count: counts.sold_out,
        ended_count: counts.ended,
        events: entries.map((entry) => entry.event),
        entries,
      });
    }

    return cells;
  }

  function buildDeadlineAlerts(events, todayKey) {
    const tomorrowKey = addDaysKey(todayKey, 1);
    const alerts = {
      today: [],
      tomorrow: [],
      missing: [],
    };

    for (const event of events || []) {
      const deadline = applicationDeadlineKey(event);
      if (deadline === todayKey) alerts.today.push(event);
      if (deadline === tomorrowKey) alerts.tomorrow.push(event);
      if (isMissingDeadline(event)) alerts.missing.push(event);
    }

    alerts.today.sort(eventSort);
    alerts.tomorrow.sort(eventSort);
    alerts.missing.sort(eventSort);
    return alerts;
  }

  function isMissingDeadline(event) {
    return (
      !applicationDeadlineKey(event) ||
      event.application_summary === "未取得" ||
      event.needs_review === true
    );
  }

  function addDaysKey(key, days) {
    const date = parseDateKey(key);
    if (!date) return "";
    date.setDate(date.getDate() + days);
    return dateKey(date);
  }

  function countEntries(entries) {
    const counts = { live: 0, application: 0, payment: 0, sold_out: 0, ended: 0 };
    const statusEvents = new Set();
    for (const entry of entries) {
      counts[entry.kind] += 1;
      if (statusEvents.has(entry.event)) continue;
      statusEvents.add(entry.event);
      if (entry.event.ticket_status === "完売") counts.sold_out += 1;
      if (entry.event.ticket_status === "販売終了" || entry.event.ticket_status === "終了") counts.ended += 1;
    }
    return counts;
  }

  function eventSort(left, right) {
    return [
      left.event_date || "",
      left.event_name || "",
      left.venue || "",
    ].join("\u0000").localeCompare([
      right.event_date || "",
      right.event_name || "",
      right.venue || "",
    ].join("\u0000"));
  }

  function kindSort(left, right) {
    const order = { application: 0, payment: 1, live: 2 };
    return (order[left] ?? 9) - (order[right] ?? 9);
  }

  const api = {
    addDaysKey,
    addMonths,
    applicationDeadlineKey,
    buildDeadlineAlerts,
    buildMonthCalendar,
    calendarEntriesForEvent,
    dateKey,
    eventsForDate,
    groupCalendarEntries,
    groupEventsByDate,
    isMissingDeadline,
    isValidEventDate,
    monthKey,
    monthLabel,
    parseDateKey,
    paymentDeadlineKey,
    visibleMonthKeys,
  };

  root.MyojouCalendar = api;

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
