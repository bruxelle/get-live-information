const state = {
  events: [],
  filter: "upcoming",
  sortMode: "event-date",
  viewMode: "calendar",
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
const calendarView = document.querySelector("#calendarView");
const calendarMonths = document.querySelector("#calendarMonths");
const deadlineStatusList = document.querySelector("#deadlineStatusList");
const deadlineStatusEmpty = document.querySelector("#deadlineStatusEmpty");
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
      updateViewButtons();
      render();
    });
  });
  updateViewButtons();
  syncViewState();

  calendarModeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.calendarMode = button.dataset.calendarMode;
      updateCalendarModeButtons();
      render();
    });
  });
  updateCalendarModeButtons();

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
  syncViewState();
  if (state.viewMode === "calendar") {
    renderCalendar();
    return;
  }
  renderCards();
}

function renderCards() {
  const events = filteredEvents(state.events);
  renderDeadlineAlerts(MyojouCalendar.dateKey(startOfToday()));
  calendarView.hidden = true;
  eventList.hidden = false;
  eventList.removeAttribute("hidden");
  eventList.replaceChildren(...groupedEvents(events));
  emptyState.textContent = "表示できる予定がありません。";
  emptyState.hidden = events.length !== 0;
}

function renderCalendar() {
  const todayKey = MyojouCalendar.dateKey(startOfToday());
  const months = MyojouCalendar.visibleMonthKeys(state.calendarStartMonth, state.calendarMonthCount);
  const monthSections = months.map((month) => calendarMonthSection(month, todayKey));

  eventList.hidden = true;
  eventList.setAttribute("hidden", "");
  emptyState.hidden = true;
  calendarView.hidden = false;
  calendarView.removeAttribute("hidden");
  renderDeadlineAlerts(todayKey);
  calendarMonths.replaceChildren(...monthSections.map((section) => section.node));
}

function updateViewButtons() {
  viewButtons.forEach((button) => {
    const isActive = button.dataset.view === state.viewMode;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
  });
}

function syncViewState() {
  updateViewButtons();
  document.body.classList.toggle("is-calendar-view", state.viewMode === "calendar");
  document.body.classList.toggle("is-cards-view", state.viewMode === "cards");
  if (state.viewMode === "calendar") {
    calendarView.hidden = false;
    calendarView.removeAttribute("hidden");
    eventList.hidden = true;
    eventList.setAttribute("hidden", "");
    return;
  }
  calendarView.hidden = true;
  calendarView.setAttribute("hidden", "");
  eventList.hidden = false;
  eventList.removeAttribute("hidden");
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
    el("div", { className: "card-main" }, [
      el("div", { className: "card-head" }, [
        el("p", { className: "event-date" }, formatDate(event.event_date, event.weekday)),
        el("div", { className: "card-badges" }, [
          deadlineBadge(event),
          el("span", { className: `status ${statusClass(event.ticket_status)}` }, event.ticket_status || "不明"),
        ]),
      ]),
      el("div", { className: "card-title-block" }, [
        el("h2", { className: "event-title" }, event.event_name || "未定"),
        el("p", { className: "venue" }, `会場 ${event.venue || "未定"}`),
      ]),
      summaryList(event),
    ]),
    ticketSalesList(event),
    actionRow(event),
  );

  return card;
}

function calendarMonthSection(month, todayKey) {
  const cells = applyCalendarEntryVisibility(
    MyojouCalendar.buildMonthCalendar(month, state.events, todayKey, calendarSourceMode()),
  );
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
  const entryGroups = groupedCalendarLabelEntries(cell.entries);
  for (const group of entryGroups) {
    labels.push(el("span", { className: `calendar-event-label calendar-event-${group.primaryKind}` }, [
      group.contextLabel ? el("span", { className: "calendar-entry-context" }, group.contextLabel) : null,
      el("span", { className: "calendar-event-title-text" }, shortEventLabel(group.event.event_name || "ライブ")),
      applicationBadgeListForEntries(group.entries, "calendar-application-badges"),
    ]));
    if (labels.length === 2) break;
  }
  if (entryGroups.length > labels.length) {
    labels.push(el("span", { className: "calendar-event-more" }, `+${entryGroups.length - labels.length}`));
  }
  return labels;
}

function groupedCalendarLabelEntries(entries) {
  const groups = new Map();
  for (const entry of entries || []) {
    const event = entry.event || {};
    const appKind = shouldShowApplicationKindOnCalendar(entry) ? (entry.application_kind || "") : "";
    const key = [
      event.public_event_id || event.source_event_id || event.event_name || "",
      entry.kind,
      entry.deadline_kind || appKind,
      entry.date || "",
    ].join("\u0000");
    if (!groups.has(key)) {
      groups.set(key, {
        event,
        primaryKind: entry.kind,
        contextLabel: calendarContextLabel(entry),
        entries: [],
      });
    }
    groups.get(key).entries.push(entry);
  }
  return Array.from(groups.values());
}

function calendarContextLabel(entry) {
  if (!entry) return "";
  if (entry.kind === "application") return "";
  if (entry.kind === "payment") return "支払期限";
  return "";
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
  if (state.calendarMode === "lotteryDeadline" || state.calendarMode === "firstComeDeadline") {
    return entries.filter((entry) => entry.kind === "application");
  }
  return entries.filter((entry) => entry.kind === "live");
}

function detailModeLabel() {
  if (state.calendarMode === "lotteryDeadline") return "抽選申込締切";
  if (state.calendarMode === "firstComeDeadline") return "先着申込締切";
  return "ライブ日";
}

function shouldShowApplicationKindOnCalendar(entry) {
  return entry && entry.kind === "application";
}

function applyCalendarEntryVisibility(cells) {
  return cells.map((cell) => {
    const entries = Array.isArray(cell.entries) ? cell.entries : [];
    const visibleEntries = entries.filter(shouldKeepCalendarEntry);
    if (visibleEntries.length === entries.length) return cell;
    const counts = countCalendarEntries(visibleEntries);
    return {
      ...cell,
      event_count: visibleEntries.length,
      live_count: counts.live,
      application_count: counts.application,
      payment_count: counts.payment,
      sold_out_count: counts.sold_out,
      ended_count: counts.ended,
      events: visibleEntries.map((entry) => entry.event),
      entries: visibleEntries,
    };
  });
}

function shouldKeepCalendarEntry(entry) {
  return visibleCalendarEntries(
    [entry],
    state.calendarMode,
  ).length > 0;
}

function visibleCalendarEntries(entries, mode = "live") {
  if (
    typeof MyojouCalendar !== "undefined" &&
    MyojouCalendar &&
    typeof MyojouCalendar.filterCalendarEntriesForDisplay === "function"
  ) {
    return MyojouCalendar.filterCalendarEntriesForDisplay(entries, mode);
  }
  return (entries || []).filter((entry) => {
    if (!entry) return false;
    if (mode === "live") return entry.kind === "live" || entry.entryType === "live";
    const deadlineKind = entry.deadline_kind || entry.deadlineKind || "";
    if (mode === "lotteryDeadline" || mode === "firstComeDeadline") {
      return (entry.kind === "application" || entry.entryType === "deadline") && deadlineKind === mode;
    }
    return false;
  });
}

function countCalendarEntries(entries) {
  const counts = {
    live: 0,
    application: 0,
    payment: 0,
    sold_out: 0,
    ended: 0,
  };
  for (const entry of entries || []) {
    if (entry.kind === "live") counts.live += 1;
    if (entry.kind === "application") counts.application += 1;
    if (entry.kind === "payment") counts.payment += 1;
    const status = entry.event && entry.event.ticket_status;
    if (status === "完売") counts.sold_out += 1;
    if (status === "販売終了") counts.ended += 1;
  }
  return counts;
}

function updateCalendarModeButtons() {
  calendarModeButtons.forEach((button) => {
    const isActive = button.dataset.calendarMode === state.calendarMode;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
  });
}

function calendarSourceMode() {
  if (state.calendarMode === "live") return "live";
  return "application";
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
      el("span", { className: "detail-sheet-grip", ariaHidden: "true" }, ""),
      el("header", { className: "detail-sheet-header" }, [
        el("div", { className: "detail-sheet-heading" }, [
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
  overlay.querySelector("#detailSheetBody").replaceChildren(...events.map((event) => detailEventCard(event, subtitle)));
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

function detailEventCard(event, contextLabel = "") {
  const card = el("article", { className: "detail-event-card" }, [
    el("div", { className: "detail-event-hero" }, [
      el("div", { className: "detail-event-head" }, [
        el("p", { className: "event-date" }, formatDate(event.event_date || event.date, event.weekday)),
        el("span", { className: `status ${statusClass(event.ticket_status)}` }, event.ticket_status || "不明"),
      ]),
      el("h3", { className: "detail-event-title" }, event.event_name || event.title || "未定"),
      detailContextBadge(contextLabel),
    ]),
    detailSection("ライブ情報", [
      detailLiveInfoList(event),
      detailScheduleList(event),
    ]),
    detailSection("チケット情報", [
      detailTicketSummaryList(event),
      ticketSalesList(event),
    ]),
    detailSection("申込情報", [
      detailApplicationList(event),
    ]),
    detailReviewNotice(event),
    detailSection("リンク", [
      detailActions(event),
    ]),
  ]);
  return card;
}

function detailContextBadge(label) {
  if (!label) return null;
  return el("p", { className: "detail-context-badge" }, label);
}

function detailSection(title, children) {
  const visibleChildren = children.filter(Boolean);
  if (!visibleChildren.length) return null;
  return el("section", { className: `detail-section ${detailSectionClass(title)}` }, [
    el("h4", { className: "detail-section-title" }, title),
    ...visibleChildren,
  ]);
}

function detailSectionClass(title) {
  if (title === "ライブ情報") return "detail-section-live";
  if (title === "チケット情報") return "detail-section-ticket";
  if (title === "申込情報") return "detail-section-application";
  if (title === "リンク") return "detail-section-links";
  return "";
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

function detailLiveInfoList(event) {
  return el("dl", { className: "detail-key-info" }, [
    detailRow("日付", formatDate(event.event_date || event.date, event.weekday)),
    detailRow("会場", event.venue),
  ].filter(Boolean));
}

function detailTicketSummaryList(event) {
  return el("dl", { className: "summary-list detail-summary-list" }, [
    detailRow("チケット", event.ticket_summary || event.ticket_info),
  ].filter(Boolean));
}

function detailApplicationList(event) {
  return el("div", { className: "detail-application-list" }, [
    applicationBadgeList(event, "detail-application-badges"),
    el("dl", { className: "summary-list detail-summary-list" }, [
      summaryRow("申込", event.application_summary || event.application_info || "未取得", "application-row"),
      detailRow("次の締切", compactDateTime(event.next_ticket_deadline_at) || event.next_ticket_deadline_at),
      detailRow("支払期限", compactDateTime(event.payment_deadline_at) || event.payment_deadline_at),
    ].filter(Boolean)),
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
    deadlineAlertItem("今日締切", alerts.today, "deadline-status-today"),
    deadlineAlertItem("明日締切", alerts.tomorrow, "deadline-status-tomorrow"),
    missingDeadlineNotice(alerts.missing),
  ].filter(Boolean);

  deadlineStatusList.replaceChildren(...items);
  deadlineStatusEmpty.hidden = items.length !== 0;
}

function deadlineAlertItem(label, events, className) {
  if (!events.length) return null;
  return el("span", { className: `deadline-status-item ${className}` }, `${label}: ${events.length}件`);
}

function missingDeadlineNotice(events) {
  if (!events.length) return null;
  return el("span", { className: "deadline-status-item missing-deadline-notice" }, `締切未取得: ${events.length}件`);
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

function applicationBadgeList(event, className = "") {
  const badges = getApplicationBadges(event);
  if (!badges.length) return null;
  return el("span", { className: ["application-kind-badges", className].filter(Boolean).join(" ") }, (
    badges.map((badge) => el("span", { className: `application-kind-badge ${badge.className}` }, badge.label))
  ));
}

function applicationBadgeListForEntries(entries, className = "") {
  const seen = new Set();
  const badges = [];
  for (const entry of entries || []) {
    if (!shouldShowApplicationKindOnCalendar(entry)) continue;
    const entryBadges = getApplicationBadgesForEntry(entry);
    for (const badge of entryBadges) {
      if (seen.has(badge.label)) continue;
      seen.add(badge.label);
      badges.push(badge);
    }
  }
  if (!badges.length) return null;
  return el("span", { className: ["application-kind-badges", className].filter(Boolean).join(" ") }, (
    badges.map((badge) => el("span", { className: `application-kind-badge ${badge.className}` }, badge.label))
  ));
}

function getApplicationBadgesForEntry(entry) {
  if (entry.deadline_kind === "lotteryDeadline") {
    return [{ label: "抽選申込締切", className: "application-kind-lottery" }];
  }
  if (entry.deadline_kind === "firstComeDeadline") {
    return [{ label: "先着申込締切", className: "application-kind-first" }];
  }
  return [];
}

function getApplicationBadges(event) {
  const haystack = applicationSearchText(event);
  const badges = [];
  if (/(抽選|先行抽選|抽選販売|lottery)/i.test(haystack)) {
    badges.push({ label: "抽選申込締切", className: "application-kind-lottery" });
  }
  if (/(先着|一般販売|一般|販売中|受付中|first[\s-]?come)/i.test(haystack)) {
    badges.push({ label: "先着申込締切", className: "application-kind-first" });
  }
  return badges;
}

function applicationSearchText(event) {
  const fields = [
    event.next_ticket_sale_type,
    event.next_ticket_label,
    event.sale_type,
    event.ticket_type,
    event.priority_type,
    event.application_type,
    event.sale_period,
    event.application_start,
    event.application_deadline,
    event.ticket_info,
    event.application_info,
    event.ticket_summary,
    event.application_summary,
    event.notes,
    event.ticket_status,
  ];
  if (Array.isArray(event.ticket_sales)) {
    for (const sale of event.ticket_sales) {
      fields.push(
        sale.sale_type,
        sale.ticket_name,
        sale.ticket_tier,
        sale.status,
        sale.notes,
        sale.start_at,
        sale.deadline_at,
      );
    }
  }
  return fields.filter(Boolean).join(" ");
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
  const actions = [];
  const link = el("a", { className: "ticket-button" }, event.ticket_url ? "チケットURL" : "URL未取得");
  if (event.ticket_url) {
    link.href = event.ticket_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  } else {
    link.setAttribute("aria-disabled", "true");
  }
  actions.push(link);
  const sourceUrl = sourceUrlForEvent(event);
  if (sourceUrl) {
    const sourceLink = el("a", { className: "source-button" }, "告知ポスト");
    sourceLink.href = sourceUrl;
    sourceLink.target = "_blank";
    sourceLink.rel = "noopener noreferrer";
    actions.push(sourceLink);
  }
  return el("div", { className: "card-actions" }, actions);
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
