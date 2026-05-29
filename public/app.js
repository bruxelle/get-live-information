const state = {
  events: [],
  filter: "upcoming",
  sortMode: "event-date",
};

const filterButtons = Array.from(document.querySelectorAll(".filter-button"));
const sortButtons = Array.from(document.querySelectorAll(".sort-button"));
const eventList = document.querySelector("#eventList");
const emptyState = document.querySelector("#emptyState");
const eventCount = document.querySelector("#eventCount");

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

  render();
}

function render() {
  const events = filteredEvents(state.events);
  eventList.replaceChildren(...groupedEvents(events));
  emptyState.hidden = events.length !== 0;
  eventCount.textContent = `${events.length}件`;
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
  Object.assign(node, props);
  const list = Array.isArray(children) ? children : [children];
  for (const child of list) {
    if (child === null || child === undefined) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
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
