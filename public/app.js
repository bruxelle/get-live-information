const state = {
  events: [],
  filter: "upcoming",
  sortMode: "event-date",
  viewMode: "cards",
  calendarStartMonth: "",
  calendarMonthCount: 3,
  calendarMode: "live",
  activeDetailTrigger: null,
};

const filterButtons = Array.from(document.querySelectorAll(".filter-button"));
const sortButtons = Array.from(document.querySelectorAll(".sort-button"));
const viewButtons = Array.from(document.querySelectorAll(".view-button"));
const calendarModeButtons = Array.from(document.querySelectorAll(".calendar-mode-button"));
const monthLoadButtons = Array.from(document.querySelectorAll("[data-month-load]"));
const eventList = document.querySelector("#eventList");
const emptyState = document.querySelector("#emptyState");
const eventCount = document.querySelector("#eventCount");
const calendarView = document.querySelector("#calendarView");
const calendarMonths = document.querySelector("#calendarMonths");
const deadlineAlertsList = document.querySelector("#deadlineAlertsList");
const deadlineAlertsEmpty = document.querySelector("#deadlineAlertsEmpty");
let detailSheetOverlay = null;
let detailSheetCloseButton = null;

init();

async function init() {
  filterButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.filter = button.dataset.filter;
      filterButtons.forEach((item) => item.classList.toggle("is-active", item === button));
      render();
    });
  });

  sortButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.sortMode = button.dataset.sort;
      sortButtons.forEach((item) => item.classList.toggle("is-active", item === button));
      render();
    });
  });

  viewButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.viewMode = button.dataset.view;
      viewButtons.forEach((item) => item.classList.toggle("is-active", item === button));
      render();
    });
  });

  calendarModeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.calendarMode = button.dataset.calendarMode;
      calendarModeButtons.forEach((item) => item.classList.toggle("is-active", item === button));
      render();
    });
  });

  monthLoadButtons.forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.monthLoad === "previous") {
        state.calendarStartMonth = MyojouCalendar.addMonths(state.calendarStartMonth, -1);
      }
      state.calendarMonthCount += 1;
      render();
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && detailSheetOverlay && !detailSheetOverlay.hidden) {
      closeDetailSheet();
    }
  });

  try {
    const response = await fetch("events.json", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`events.json ${response.status}`);
    }
    state.events = await response.json();
  } catch (error) {
    console.error(error);
    state.events = [];
  }

  const today = startOfToday();
  state.calendarStartMonth = MyojouCalendar.monthKey(today);
  render();
}

function render() {
  if (state.viewMode === "calendar") {
    renderCalendar();
    return;
  }
  renderCards();
}

function renderCards() {
  const events = filteredEvents(state.events);
  calendarView.hidden = true;
  eventList.hidden = false;
  eventList.replaceChildren(...groupedEvents(events));
  emptyState.textContent = "表示できる予定がありません。";
  emptyState.hidden = events.length !== 0;
  eventCount.textContent = `${events.length}件`;
}

function renderCalendar() {
  const todayKey = MyojouCalendar.dateKey(startOfToday());
  const months = MyojouCalendar.visibleMonthKeys(state.calendarStartMonth, state.calendarMonthCount);
  const monthSections = months.map((month) => calendarMonthSection(month, todayKey));
  const visibleEntryCount = monthSections.reduce((total, section) => total + section.entryCount, 0);

  eventList.hidden = true;
  emptyState.hidden = true;
  calendarView.hidden = false;
  eventCount.textContent = `${visibleEntryCount}件`;
  renderDeadlineAlerts(todayKey);
  calendarMonths.replaceChildren(...monthSections.map((section) => section.node));
}

function filteredEvents(events) {
  const today = startOfToday();
  const endOfWeek = addDays(today, 7);
  const endOfMonth = new Date(today.getFullYear(), today.getMonth() + 1, 1);

  return sortedEvents(events)
    .filter((event) => {
      const date = parseDate(event.event_date);
      if (state.filter === "missing-deadline") return hasMissingDeadline(event);
      if (!date || state.filter === "all") return true;
      if (state.filter === "upcoming") return date >= today;
      if (state.filter === "week") return date >= today && date < endOfWeek;
      if (state.filter === "month") return date >= today && date < endOfMonth;
      return true;
    });
}

function sortedEvents(events) {
  return [...events].sort((left, right) => {
    if (state.sortMode === "deadline") {
      return (
        deadlineSortKey(left).localeCompare(deadlineSortKey(right)) ||
        eventSortKey(left).localeCompare(eventSortKey(right))
      );
    }
    return eventSortKey(left).localeCompare(eventSortKey(right));
  });
}

function groupedEvents(events) {
  const groups = new Map();
  for (const event of events) {
    const key = groupKey(event);
    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key).push(event);
  }

  return Array.from(groups, ([date, items]) => {
    const section = el("section", { className: "date-group" }, [
      el("h2", { className: "date-heading" }, groupHeading(date, items[0])),
      el("div", { className: "date-events" }, items.map(eventCard)),
    ]);
    return section;
  });
}

function eventCard(event) {
  const card = document.createElement("article");
  card.className = "event-card";

  card.append(
    el("div", { className: "card-head" }, [
      el("p", { className: "event-date" }, formatDate(event.event_date, event.weekday)),
      el("div", { className: "card-badges" }, [
        deadlineBadge(event),
        el("span", { className: `status ${statusClass(event.ticket_status)}` }, event.ticket_status || "不明"),
      ]),
    ]),
    el("h2", { className: "event-title" }, event.event_name || "未定"),
    el("p", { className: "venue" }, event.venue || "会場未定"),
    summaryList(event),
    ticketSalesList(event),
    actionRow(event),
  );

  return card;
}

function calendarMonthSection(month, todayKey) {
  const cells = MyojouCalendar.buildMonthCalendar(month, state.events, todayKey, state.calendarMode);
  const entryCount = cells
    .filter((cell) => cell.month === month)
    .reduce((total, cell) => total + cell.event_count, 0);
  const node = el("section", { className: "calendar-month" }, [
    el("h2", { className: "calendar-month-label" }, [
      MyojouCalendar.monthLabel(month),
      el("span", { className: "calendar-month-count" }, `${entryCount}件`),
    ]),
    el("div", { className: "calendar-weekdays", ariaHidden: "true" }, [
      "日", "月", "火", "水", "木", "金", "土",
    ].map((weekday) => el("span", {}, weekday))),
    el("div", { className: "calendar-grid" }, cells.map(calendarCell)),
  ]);
  return { node, entryCount };
}

function calendarCell(cell) {
  const classes = [
    "calendar-day",
    cell.is_current_month ? "" : "is-outside-month",
    cell.is_today ? "is-today" : "",
    cell.event_count ? "has-events" : "",
  ].filter(Boolean).join(" ");
  const chips = calendarCellChips(cell);
  const labels = calendarCellLabels(cell);
  const isActionable = cell.event_count > 0;
  const cellNode = el("button", {
    className: classes,
    type: "button",
    disabled: !isActionable,
    ariaLabel: isActionable ? `${formatDate(cell.key, weekdayForDate(cell.key))}の詳細を開く` : `${cell.day}日`,
  }, [
    el("span", { className: "calendar-day-number" }, cell.day),
    chips.length ? el("span", { className: "calendar-chips" }, chips) : null,
    labels.length ? el("span", { className: "calendar-event-labels" }, labels) : null,
  ]);
  if (isActionable) {
    cellNode.addEventListener("click", () => openCalendarDetail(cell, cellNode));
  }
  return cellNode;
}

function calendarCellChips(cell) {
  const chips = [];
  if (cell.live_count) chips.push(calendarChip("ライブ", cell.live_count, "calendar-chip-live"));
  if (cell.application_count) {
    const urgencyClass = cell.is_today ? "calendar-chip-today" : cell.is_tomorrow ? "calendar-chip-tomorrow" : "";
    chips.push(calendarChip("申込", cell.application_count, ["calendar-chip-application", urgencyClass].filter(Boolean).join(" ")));
  }
  if (cell.payment_count) chips.push(calendarChip("支払", cell.payment_count, "calendar-chip-payment"));
  if (cell.sold_out_count) chips.push(calendarChip("完売", cell.sold_out_count, "calendar-chip-sold-out"));
  if (cell.ended_count) chips.push(calendarChip("販売終了", cell.ended_count, "calendar-chip-ended"));
  return chips;
}

function calendarChip(label, count, className) {
  return el("span", { className: `calendar-chip ${className}` }, `${label}${count > 1 ? count : ""}`);
}

function calendarCellLabels(cell) {
  const labels = [];
  const seen = new Set();
  for (const entry of cell.entries) {
    const label = shortEventLabel(entry.event.event_name || "ライブ");
    if (seen.has(label)) continue;
    seen.add(label);
    labels.push(el("span", { className: `calendar-event-label calendar-event-${entry.kind}` }, label));
    if (labels.length === 2) break;
  }
  if (seen.size < cell.entries.length) {
    labels.push(el("span", { className: "calendar-event-more" }, `+${cell.entries.length - seen.size}`));
  }
  return labels;
}

function openCalendarDetail(cell, trigger) {
  const entries = relevantCalendarEntries(cell);
  const events = dedupeEvents(entries.map((entry) => entry.event));
  if (!events.length) return;
  openDetailSheet({
    title: `${formatDate(cell.key, weekdayForDate(cell.key))}の予定`,
    subtitle: detailModeLabel(),
    events,
    trigger,
  });
}

function relevantCalendarEntries(cell) {
  const entries = Array.isArray(cell.entries) ? cell.entries : [];
  if (state.calendarMode === "application") {
    return entries.filter((entry) => entry.kind === "application");
  }
  if (state.calendarMode === "payment") {
    return entries.filter((entry) => entry.kind === "payment");
  }
  if (state.calendarMode === "all") {
    const liveEntries = entries.filter((entry) => entry.kind === "live");
    return liveEntries.length ? liveEntries : entries;
  }
  return entries.filter((entry) => entry.kind === "live");
}

function detailModeLabel() {
  if (state.calendarMode === "application") return "申込締切";
  if (state.calendarMode === "payment") return "支払期限";
  if (state.calendarMode === "all") return "ライブ・締切";
  return "ライブ日";
}

function dedupeEvents(events) {
  const seen = new Set();
  const deduped = [];
  for (const event of events) {
    const key = event.public_event_id || [event.event_date, event.event_name, event.venue, event.ticket_url].join("\u0000");
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(event);
  }
  return deduped;
}

function ensureDetailSheet() {
  if (detailSheetOverlay) return detailSheetOverlay;
  detailSheetCloseButton = el("button", {
    className: "detail-sheet-close",
    type: "button",
    ariaLabel: "詳細を閉じる",
  }, "閉じる");
  detailSheetCloseButton.addEventListener("click", closeDetailSheet);

  detailSheetOverlay = el("div", {
    className: "detail-sheet-overlay",
    hidden: true,
  }, [
    el("section", {
      className: "detail-sheet",
      role: "dialog",
      ariaModal: "true",
      ariaLabelledby: "detailSheetTitle",
      tabIndex: -1,
    }, [
      el("header", { className: "detail-sheet-header" }, [
        el("div", {}, [
          el("p", { id: "detailSheetMode", className: "detail-sheet-subtitle" }, ""),
          el("h2", { id: "detailSheetTitle", className: "detail-sheet-title" }, ""),
        ]),
        detailSheetCloseButton,
      ]),
      el("div", { id: "detailSheetBody", className: "detail-sheet-body" }),
    ]),
  ]);
  detailSheetOverlay.addEventListener("click", (event) => {
    if (event.target === detailSheetOverlay) {
      closeDetailSheet();
    }
  });
  document.body.append(detailSheetOverlay);
  return detailSheetOverlay;
}

function openDetailSheet({ title, subtitle, events, trigger }) {
  const overlay = ensureDetailSheet();
  state.activeDetailTrigger = trigger || document.activeElement;
  overlay.querySelector("#detailSheetTitle").textContent = title;
  overlay.querySelector("#detailSheetMode").textContent = subtitle || "";
  overlay.querySelector("#detailSheetBody").replaceChildren(...events.map(detailEventCard));
  overlay.hidden = false;
  document.body.classList.add("detail-sheet-open");
  detailSheetCloseButton?.focus();
}

function closeDetailSheet() {
  if (!detailSheetOverlay || detailSheetOverlay.hidden) return;
  detailSheetOverlay.hidden = true;
  document.body.classList.remove("detail-sheet-open");
  const trigger = state.activeDetailTrigger;
  state.activeDetailTrigger = null;
  if (trigger && typeof trigger.focus === "function" && document.contains(trigger)) {
    trigger.focus();
  }
}

function detailEventCard(event) {
  const card = el("article", { className: "detail-event-card" }, [
    el("div", { className: "detail-event-head" }, [
      el("p", { className: "event-date" }, formatDate(event.event_date || event.date, event.weekday)),
      el("span", { className: `status ${statusClass(event.ticket_status)}` }, event.ticket_status || "不明"),
    ]),
    el("h3", { className: "detail-event-title" }, event.event_name || event.title || "未定"),
    detailText("会場", event.venue),
    detailScheduleList(event),
    detailSummaryList(event),
    ticketSalesList(event),
    detailReviewNotice(event),
    detailActions(event),
  ]);
  return card;
}

function detailScheduleList(event) {
  const rows = [
    ["開場", event.open_time],
    ["開演", event.start_time],
    ["出演", event.performance_time || event.myojou_performance_time],
    ["特典会", event.benefit_time || event.tokutenkai_time || event.benefit_event_time],
  ].filter(([, value]) => value);
  if (!rows.length) return null;
  return el("dl", { className: "detail-schedule-list" }, rows.map(([label, value]) => detailRow(label, value)));
}

function detailSummaryList(event) {
  return el("dl", { className: "summary-list detail-summary-list" }, [
    detailRow("チケット", event.ticket_summary || event.ticket_info),
    summaryRow("申込", event.application_summary || event.application_info || "未取得", "application-row"),
    detailRow("次の締切", compactDateTime(event.next_ticket_deadline_at) || event.next_ticket_deadline_at),
    detailRow("支払期限", compactDateTime(event.payment_deadline_at) || event.payment_deadline_at),
  ].filter(Boolean));
}

function detailText(label, value) {
  if (!value) return null;
  return el("p", { className: "detail-text-row" }, [
    el("span", { className: "detail-text-label" }, label),
    el("span", { className: "detail-text-value" }, value),
  ]);
}

function detailRow(label, value) {
  if (!value) return null;
  return el("div", { className: "summary-row" }, [
    el("dt", { className: "summary-label" }, label),
    el("dd", { className: "summary-value" }, value),
  ]);
}

function detailReviewNotice(event) {
  if (!event.needs_review) return null;
  const reasons = Array.isArray(event.review_reasons) && event.review_reasons.length
    ? ` ${event.review_reasons.slice(0, 2).join(" / ")}`
    : "";
  return el("p", { className: "detail-review-notice" }, `要確認${reasons}`);
}

function detailActions(event) {
  const actions = [];
  const ticketUrl = event.ticket_url;
  if (ticketUrl) {
    actions.push(detailActionLink(ticketUrl, "チケットを開く", "detail-action-primary"));
  }
  const sourceUrl = sourceUrlForEvent(event);
  if (sourceUrl) {
    actions.push(detailActionLink(sourceUrl, "告知ポスト", ""));
  }
  return actions.length ? el("div", { className: "detail-actions" }, actions) : null;
}

function detailActionLink(url, label, extraClass) {
  const link = el("a", { className: ["detail-action-button", extraClass].filter(Boolean).join(" ") }, label);
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function sourceUrlForEvent(event) {
  if (event.source_url) return event.source_url;
  if (event.source_post_url) return event.source_post_url;
  if (event.announcement_url) return event.announcement_url;
  if (event.primary_source_url) return event.primary_source_url;
  if (event.latest_source_url) return event.latest_source_url;
  if (Array.isArray(event.ticket_sales)) {
    const saleWithSource = event.ticket_sales.find((sale) => sale.source_url);
    if (saleWithSource) return saleWithSource.source_url;
  }
  return "";
}

function renderDeadlineAlerts(todayKey) {
  const alerts = MyojouCalendar.buildDeadlineAlerts(state.events, todayKey);
  const items = [
    deadlineAlertItem("今日締切", alerts.today, "deadline-alert-today"),
    deadlineAlertItem("明日締切", alerts.tomorrow, "deadline-alert-tomorrow"),
    deadlineAlertItem("締切未取得", alerts.missing, "deadline-alert-missing"),
  ].filter(Boolean);

  deadlineAlertsList.replaceChildren(...items);
  deadlineAlertsEmpty.hidden = items.length !== 0;
}

function deadlineAlertItem(label, events, className) {
  if (!events.length) return null;
  const names = events.slice(0, 2).map((event) => event.event_name || "ライブ");
  const extra = events.length > names.length ? ` +${events.length - names.length}` : "";
  return el("article", { className: `deadline-alert-item ${className}` }, [
    el("strong", {}, `${label} ${events.length}件`),
    el("span", {}, `${names.join(" / ")}${extra}`),
  ]);
}

function shortEventLabel(value) {
  return value.length > 12 ? `${value.slice(0, 11)}…` : value;
}

function summaryList(event) {
  return el("dl", { className: "summary-list" }, [
    summaryRow("ライブ", event.live_summary),
    summaryRow("チケット", event.ticket_summary),
    summaryRow("申込", event.application_summary, "application-row"),
  ]);
}

function summaryRow(label, value, extraClass = "") {
  const missing = label === "申込" && (!value || value === "未取得");
  const rowClass = ["summary-row", extraClass].filter(Boolean).join(" ");
  return el("div", { className: rowClass }, [
    el("dt", { className: "summary-label" }, label),
    el("dd", { className: `summary-value${missing ? " summary-missing" : ""}` }, value || "未取得"),
  ]);
}

function ticketSalesList(event) {
  const sales = Array.isArray(event.ticket_sales) ? event.ticket_sales : [];
  if (!sales.length) return null;
  return el("div", { className: "ticket-sales", ariaLabel: "販売期間" }, [
    el("p", { className: "ticket-sales-title" }, "販売期間"),
    el("div", { className: "ticket-sales-list" }, sales.map((sale) => ticketSaleChip(sale))),
  ]);
}

function ticketSaleChip(sale) {
  const saleType = sale.sale_type || "不明";
  const ticketLabel = sale.ticket_name || (sale.ticket_tier && sale.ticket_tier !== "不明" ? sale.ticket_tier : "");
  const labelParts = [saleType];
  if (ticketLabel && ticketLabel !== saleType) {
    labelParts.push(ticketLabel);
  }
  const price = sale.price === 0 || sale.price ? `${Number(sale.price).toLocaleString("ja-JP")}円` : "";
  const deadline = compactDateTime(sale.deadline_at);
  const period = sale.start_at && sale.deadline_at
    ? `${compactDateTime(sale.start_at)}〜${deadline}`
    : deadline
      ? `締切 ${deadline}`
      : compactDateTime(sale.start_at);
  const status = sale.status && sale.status !== "不明" ? sale.status : "";
  return el("div", { className: `ticket-sale-chip${sale.is_next_deadline ? " is-next" : ""}` }, [
    el("strong", {}, labelParts.join(" / ") || "販売情報"),
    el("span", {}, [price, period, status].filter(Boolean).join(" / ") || "詳細未取得"),
  ]);
}

function actionRow(event) {
  const link = el("a", { className: "ticket-button" }, event.ticket_url ? "チケットURL" : "URL未取得");
  if (event.ticket_url) {
    link.href = event.ticket_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  } else {
    link.setAttribute("aria-disabled", "true");
  }
  return el("div", { className: "card-actions" }, link);
}

function el(tagName, props = {}, children = []) {
  const node = document.createElement(tagName);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined) continue;
    if (key === "className") {
      node.className = value;
    } else if (key === "htmlFor") {
      node.setAttribute("for", value);
    } else if (key.startsWith("aria") && key !== "ariaHidden") {
      node.setAttribute(ariaAttributeName(key), String(value));
    } else {
      node[key] = value;
    }
  }
  const list = Array.isArray(children) ? children : [children];
  for (const child of list) {
    if (child === null || child === undefined) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function ariaAttributeName(key) {
  return `aria-${key.slice(4).replace(/[A-Z]/g, (match) => `-${match.toLowerCase()}`).replace(/^-/, "")}`;
}

function formatDate(value, weekday) {
  if (!value) return "日付未定";
  const parts = value.split("-");
  if (parts.length !== 3) return value;
  const formatted = `${parts[0]}/${parts[1]}/${parts[2]}`;
  return weekday ? `${formatted}（${weekday}）` : formatted;
}

function statusClass(status) {
  const normalized = status || "不明";
  if (normalized === "販売中") return "status-on-sale";
  if (normalized === "完売") return "status-sold-out";
  if (normalized === "販売終了") return "status-ended";
  if (normalized === "未販売") return "status-upcoming";
  return "status-unknown";
}

function deadlineBadge(event) {
  const urgency = deadlineUrgency(event);
  return el("span", { className: `deadline-badge ${urgency.className}` }, urgency.label);
}

function deadlineUrgency(event) {
  const key = deadlineDateKey(event);
  if (!key) {
    return { label: "締切未取得", className: "deadline-missing" };
  }
  const deadline = parseDate(key);
  if (!deadline) {
    return { label: "締切未取得", className: "deadline-missing" };
  }
  const diff = daysBetween(startOfToday(), deadline);
  if (diff < 0) return { label: "締切済", className: "deadline-past" };
  if (diff === 0) return { label: "今日締切", className: "deadline-today" };
  if (diff === 1) return { label: "明日締切", className: "deadline-tomorrow" };
  if (diff <= 3) return { label: `あと${diff}日`, className: "deadline-soon" };
  return { label: `${compactMonthDay(key)}締切`, className: "deadline-normal" };
}

function groupKey(event) {
  if (state.sortMode === "deadline") {
    return deadlineDateKey(event) || "__missing_deadline__";
  }
  return event.event_date || "";
}

function groupHeading(key, event) {
  if (state.sortMode === "deadline") {
    if (key === "__missing_deadline__") return "締切未取得";
    return `申込締切 ${formatDate(key, weekdayForDate(key))}`;
  }
  return formatDate(key, event?.weekday);
}

function hasMissingDeadline(event) {
  return !deadlineDateKey(event) || event.application_summary === "未取得";
}

function deadlineDateKey(event) {
  const value = event.next_ticket_deadline_at || event.ticket_application_deadline_at || "";
  return isoDatePart(value);
}

function deadlineSortKey(event) {
  return deadlineDateKey(event) || "9999-99-99";
}

function eventSortKey(event) {
  return [event.event_date || "9999-99-99", event.event_name || "", event.venue || ""].join("\u0000");
}

function isoDatePart(value) {
  if (!value || typeof value !== "string") return "";
  const match = value.match(/^\d{4}-\d{2}-\d{2}/);
  return match ? match[0] : "";
}

function parseDate(value) {
  if (!value) return null;
  const parts = value.split("-").map(Number);
  if (parts.length !== 3 || parts.some(Number.isNaN)) return null;
  return new Date(parts[0], parts[1] - 1, parts[2]);
}

function startOfToday() {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

function addDays(date, days) {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function daysBetween(start, end) {
  const millis = startOfDay(end).getTime() - startOfDay(start).getTime();
  return Math.round(millis / 86400000);
}

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function compactMonthDay(value) {
  const parts = value.split("-").map(Number);
  if (parts.length !== 3 || parts.some(Number.isNaN)) return value;
  return `${parts[1]}/${parts[2]}`;
}

function weekdayForDate(value) {
  const date = parseDate(value);
  if (!date) return "";
  return ["日", "月", "火", "水", "木", "金", "土"][date.getDay()];
}

function compactDateTime(value) {
  if (!value || typeof value !== "string") return "";
  const match = value.match(/^\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!match) return "";
  return `${Number(match[1])}/${Number(match[2])} ${match[3]}:${match[4]}`;
}
