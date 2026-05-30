from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, time, timedelta, timezone

from .models import (
    ClassificationConfidence,
    ExtractedEvent,
    PostClassification,
    PostClassificationResult,
    SourceKind,
    TicketSalePeriod,
    XPost,
)
from .normalization import normalize_price, normalize_spaces, normalize_time, normalize_time_range, parse_event_date


LIVE_KEYWORDS = (
    "next live",
    "ライブ",
    "live",
    "LIVE",
    "出演",
    "日付",
    "場所",
    "公演",
    "イベント",
    "タイムテーブル",
    "特典会",
    "会場",
    "開場",
    "開演",
    "チケット",
    "TicketDive",
    "TIGET",
    "LivePocket",
    "ticketdive.com",
    "t.livepocket.jp",
    "tiget.net",
    "抽選",
    "先着",
    "一般販売",
    "当日券",
    "本日",
    "明日",
    "明後日",
)

NON_EVENT_KEYWORDS = (
    "グッズ",
    "goods",
    "通販",
    "MV",
    "music video",
    "楽曲配信",
    "サブスク",
    "写真",
    "オフショット",
    "メンバー投稿",
)

_URL_RE = re.compile(r"https?://[^\s)）]+")
_TIME_RE = re.compile(r"\d{1,2}(?:[:：]\d{2}|時\d{0,2}分?)")
_JST = timezone(timedelta(hours=9))


class PostParser:
    def __init__(self, username: str = "info_myojou") -> None:
        self.username = username

    def parse_post(self, post: XPost, classification: PostClassificationResult | None = None) -> ExtractedEvent | None:
        text = post.text
        classification = classification or self.classify_post(post)
        if classification.classification == PostClassification.NON_EVENT:
            return None

        source_kind = classification.source_kind
        event_date = self.extract_event_date(text, post.created_at, source_kind)
        event_name = self.extract_event_name(text)
        venue = self.extract_venue(text)
        open_time = self.extract_labeled_time(text, ("open", "開場"))
        start_time = self.extract_labeled_time(text, ("start", "開演"))
        performance_time = self.extract_context_time(text, ("出演時間", "出演", "出番", "myojou", "ミョウジョウ", "ライブ"))
        benefit_time = self.extract_context_time(text, ("特典会", "物販"))
        ticket_url = self.extract_ticket_url(text)
        general_price = self.extract_price(text, ("一般", "前売", "通常"))
        priority_name, priority_price = self.extract_priority_ticket(text)
        same_day_price = self.extract_price(text, ("当日", "当日券"))
        ticket_application_start = self.extract_labeled_datetime(text, ("申込開始", "受付開始", "販売開始"), post.created_at)
        ticket_application_deadline = self.extract_labeled_datetime(text, ("申込締切", "受付締切", "販売終了"), post.created_at)
        lottery_result = self.extract_labeled_datetime(text, ("当落発表",), post.created_at)
        payment_deadline = self.extract_labeled_datetime(text, ("支払期限", "入金期限"), post.created_at)
        ticket_sale_type = self.extract_ticket_sale_type(text)
        ticket_status = self.extract_ticket_status(text)
        notes = self.extract_notes(text, source_kind)
        source_url = self.source_url_for_post(post)
        ticket_sales = self.extract_ticket_sales(
            text,
            post.created_at,
            source_url=source_url,
            source_post_id=post.id,
            ticket_sale_type=ticket_sale_type,
            ticket_status=ticket_status,
            general_price=general_price,
            priority_name=priority_name,
            priority_price=priority_price,
            same_day_price=same_day_price,
            ticket_application_start=ticket_application_start,
            ticket_application_deadline=ticket_application_deadline,
            lottery_result=lottery_result,
            payment_deadline=payment_deadline,
        )

        confidence = self.calculate_confidence(
            event_date=event_date,
            event_name=event_name,
            venue=venue,
            open_time=open_time,
            start_time=start_time,
            performance_time=performance_time,
            benefit_time=benefit_time,
            ticket_url=ticket_url,
            source_kind=source_kind,
        )
        if classification.classification == PostClassification.NEEDS_REVIEW:
            confidence = min(confidence, 0.55)

        return ExtractedEvent(
            event_date=event_date,
            event_name=event_name,
            venue=venue,
            open_time=open_time,
            start_time=start_time,
            myojou_performance_time=performance_time,
            benefit_event_time=benefit_time,
            ticket_url=ticket_url,
            general_ticket_price=general_price,
            priority_ticket_name=priority_name,
            priority_ticket_price=priority_price,
            same_day_ticket_price=same_day_price,
            ticket_application_start_at=ticket_application_start,
            ticket_application_deadline_at=ticket_application_deadline,
            lottery_result_at=lottery_result,
            payment_deadline_at=payment_deadline,
            ticket_sale_type=ticket_sale_type,
            ticket_sales=ticket_sales,
            ticket_status=ticket_status,
            notes=notes,
            source_url=source_url,
            source_post_id=post.id,
            source_posted_at=post.created_at,
            source_text=text,
            source_kind=source_kind,
            extraction_confidence=confidence,
            classification=classification.classification,
            classification_confidence=classification.confidence,
            classification_reason=classification.reason,
        )

    def is_live_event_post(self, text: str) -> bool:
        return self.classify_post(XPost(id="classification_probe", text=text, created_at=datetime.now(_JST))).classification != PostClassification.NON_EVENT

    def classify_post(self, post: XPost) -> PostClassificationResult:
        text = post.text
        normalized = _normalize(text)
        compact = normalized.casefold()
        source_kind = self.classify_source_kind(text)
        event_date = self.extract_event_date(text, post.created_at, source_kind)
        event_name = self.extract_event_name(text)
        venue = self.extract_venue(text)
        ticket_url = self.extract_ticket_url(text)
        has_time = bool(self.extract_labeled_time(text, ("open", "開場")) or self.extract_labeled_time(text, ("start", "開演")))
        has_performance = bool(self.extract_context_time(text, ("出演時間", "出演", "出番", "myojou", "ミョウジョウ", "ライブ")))
        positive_count = sum(1 for keyword in LIVE_KEYWORDS if keyword.casefold() in compact)
        ticket_domain = any(domain in compact for domain in ("ticketdive.com", "t.livepocket.jp", "livepocket", "tiget.net"))
        non_event_signal = self.is_obvious_non_event_post(normalized)
        structured_count = sum(bool(value) for value in (event_date, event_name, venue, ticket_url, has_time, has_performance))

        if non_event_signal and not any((ticket_url, venue, has_time, has_performance, ticket_domain)):
            return PostClassificationResult(
                classification=PostClassification.NON_EVENT,
                confidence=ClassificationConfidence.HIGH,
                reason="strong non-event keyword without live structure",
                source_kind=source_kind,
            )

        if self._looks_image_dependent_reminder(compact) and structured_count < 3:
            return PostClassificationResult(
                classification=PostClassification.NEEDS_REVIEW,
                confidence=ClassificationConfidence.LOW,
                reason="本日/明日 reminder appears image-dependent",
                source_kind=source_kind,
            )

        if ticket_url and not (event_date or event_name):
            return PostClassificationResult(
                classification=PostClassification.NEEDS_REVIEW,
                confidence=ClassificationConfidence.LOW,
                reason="ticket URL exists but date or event name is missing",
                source_kind=source_kind,
            )

        if source_kind in {SourceKind.TIMETABLE_UPDATE, SourceKind.CORRECTION} and structured_count < 2:
            return PostClassificationResult(
                classification=PostClassification.NEEDS_REVIEW,
                confidence=ClassificationConfidence.LOW,
                reason=f"{source_kind} lacks enough target event information",
                source_kind=source_kind,
            )

        if structured_count >= 3 or (event_date and (event_name or venue or ticket_url)):
            return PostClassificationResult(
                classification=PostClassification.EVENT,
                confidence=ClassificationConfidence.HIGH,
                reason="live post has date and structured event fields",
                source_kind=source_kind,
            )

        if positive_count >= 2 and structured_count >= 1:
            return PostClassificationResult(
                classification=PostClassification.EVENT,
                confidence=ClassificationConfidence.MEDIUM,
                reason="live keywords with partial structured information",
                source_kind=source_kind,
            )

        if positive_count > 0:
            return PostClassificationResult(
                classification=PostClassification.NEEDS_REVIEW,
                confidence=ClassificationConfidence.LOW,
                reason="event-like words but insufficient structured information",
                source_kind=source_kind,
            )

        return PostClassificationResult(
            classification=PostClassification.NON_EVENT,
            confidence=ClassificationConfidence.HIGH,
            reason="no live-event signal",
            source_kind=source_kind,
        )

    def source_url_for_post(self, post: XPost) -> str:
        return str(post.raw.get("url") or f"https://x.com/{self.username}/status/{post.id}")

    def is_obvious_non_event_post(self, normalized_text: str) -> bool:
        compact = normalized_text.casefold()
        if any(word.casefold() in compact for word in NON_EVENT_KEYWORDS):
            return True
        if any(word in compact for word in ("新商品", "配信開始")):
            return True
        if any(word in compact for word in ("リリース", "配信開始", "mv公開", "music video")):
            return True
        if any(word in compact for word in ("オフショット", "自撮り", "写真", "フォト")):
            return True
        if any(word in compact for word in ("ありがとうございました", "ありがとう")) and not any(
            word in compact
            for word in ("チケット", "開場", "開演", "出演時間", "特典会", "申込", "受付", "販売開始", "販売中")
        ):
            return True
        if "お知らせ" in compact and not any(
            word in compact
            for word in ("ライブ", "live", "公演", "出演", "チケット", "開場", "開演", "申込", "受付", "販売")
        ):
            return True
        return False

    def _looks_image_dependent_reminder(self, compact_text: str) -> bool:
        if not any(word in compact_text for word in ("本日はこちら", "明日はこちら", "本日のライブはこちら", "明日のライブはこちら")):
            return False
        return not any(
            word.casefold() in compact_text
            for word in ("会場", "場所", "開場", "開演", "チケット", "出演時間", "特典会", "http", "livepocket", "tiget")
        )

    def classify_source_kind(self, text: str) -> SourceKind:
        normalized = _normalize(text).casefold()
        if any(word in normalized for word in ("訂正", "修正", "変更", "お詫び", "誤り")):
            return SourceKind.CORRECTION
        if any(word in normalized for word in ("sold out", "soldout", "完売", "売り切れ")):
            return SourceKind.SOLD_OUT
        if "本日" in normalized:
            return SourceKind.SAME_DAY_REMINDER
        if "明日" in normalized:
            return SourceKind.DAY_BEFORE_REMINDER
        if any(word in normalized for word in ("タイムテーブル", "出演時間", "出番", "tt解禁", "特典会時間")):
            return SourceKind.TIMETABLE_UPDATE
        if any(word in normalized for word in ("next live", "ライブ出演", "出演決定", "出演情報", "情報解禁", "公演決定")):
            return SourceKind.INITIAL_ANNOUNCEMENT
        if any(word in normalized for word in ("チケット", "当日券", "販売", "予約", "発売", "受付")):
            return SourceKind.TICKET_UPDATE
        if any(word in normalized for word in ("ライブ", "live", "公演")):
            return SourceKind.INITIAL_ANNOUNCEMENT
        return SourceKind.OTHER

    def extract_event_date(
        self,
        text: str,
        posted_at: datetime,
        source_kind: SourceKind | None = None,
    ) -> date | None:
        normalized = _normalize(text)
        parsed = parse_event_date(normalized, posted_at.date())
        if parsed:
            return parsed

        if source_kind == SourceKind.SAME_DAY_REMINDER or "本日" in normalized:
            return posted_at.date()
        if source_kind == SourceKind.DAY_BEFORE_REMINDER or "明日" in normalized:
            return posted_at.date() + timedelta(days=1)
        return None

    def extract_event_name(self, text: str) -> str | None:
        for line in _lines(text):
            label_match = re.search(r"(?:イベント名|公演名|タイトル)\s*[:：]\s*(?P<name>.+)", line, flags=re.I)
            if label_match:
                return _clean_value(label_match.group("name"))

        for left, right in (("『", "』"), ("「", "」"), ("“", "”"), ('"', '"')):
            pattern = re.escape(left) + r"(?P<name>[^" + re.escape(right) + r"]{2,80})" + re.escape(right)
            match = re.search(pattern, text)
            if match:
                candidate = _clean_value(match.group("name"))
                if candidate and not any(word in candidate for word in ("ライブ出演情報", "タイムテーブル")):
                    return candidate

        for line in _lines(text):
            cleaned = _clean_value(line)
            if not cleaned or _is_metadata_line(cleaned):
                continue
            if any(word in cleaned for word in ("LIVE", "Live", "ライブ", "公演", "FES", "フェス")) and len(cleaned) <= 80:
                return cleaned
        return None

    def extract_venue(self, text: str) -> str | None:
        for line in _lines(text):
            label_match = re.search(r"(?:会場|場所|VENUE)\s*[:：]\s*(?P<venue>.+)", line, flags=re.I)
            if label_match:
                return _clean_value(label_match.group("venue"))

            stripped = line.strip()
            if stripped.startswith("@") and not stripped.startswith("@info_"):
                return _clean_value(stripped[1:])

            at_match = re.search(r"(?:^|\s)@(?P<venue>[^#\n]+)", line)
            if at_match and "info_myojou" not in at_match.group("venue"):
                return _clean_value(at_match.group("venue"))
        return None

    def extract_labeled_time(self, text: str, labels: tuple[str, ...]) -> str | None:
        for line in _lines(text):
            normalized_line = _normalize(line).casefold()
            if not any(label.casefold() in normalized_line for label in labels):
                continue
            label_pattern = "|".join(re.escape(label) for label in labels)
            match = re.search(rf"(?:{label_pattern})\s*[:：]?\s*(?P<time>{_TIME_RE.pattern})", line, flags=re.I)
            if match:
                return normalize_time(match.group("time"))
        return None

    def extract_context_time(self, text: str, keywords: tuple[str, ...]) -> str | None:
        for line in _lines(text):
            normalized_line = _normalize(line).casefold()
            if not any(keyword.casefold() in normalized_line for keyword in keywords):
                continue
            if any(skip in normalized_line for skip in ("開場", "開演", "open", "start")):
                continue
            time_range = normalize_time_range(line)
            if time_range:
                return time_range
        return None

    def extract_ticket_url(self, text: str) -> str | None:
        urls = _URL_RE.findall(text)
        if not urls:
            return None
        ticket_urls = [url for url in urls if any(word in url.casefold() for word in ("ticket", "livepocket", "tiget", "eplus", "pia"))]
        return (ticket_urls or urls)[0].rstrip(").,、。")

    def extract_price(self, text: str, labels: tuple[str, ...]) -> int | None:
        for line in _lines(text):
            normalized_line = _normalize(line).casefold()
            if not any(label.casefold() in normalized_line for label in labels):
                continue
            price = normalize_price(line)
            if price is not None:
                return price
        return None

    def extract_priority_ticket(self, text: str) -> tuple[str | None, int | None]:
        for line in _lines(text):
            if not any(label in _normalize(line) for label in ("優先", "前方", "Sチケット", "優先エリア")):
                continue
            price = normalize_price(line)
            name_match = re.search(r"(?P<name>(?:優先|前方|Sチケット|優先エリア)[^:：\d¥￥円]*)", line)
            name = _clean_value(name_match.group("name")) if name_match else "優先"
            return name or "優先", price
        return None, None

    def extract_labeled_datetime(
        self,
        text: str,
        labels: tuple[str, ...],
        posted_at: datetime,
    ) -> datetime | None:
        posted_date = _local_posted_date(posted_at)
        label_pattern = "|".join(re.escape(label) for label in labels)
        for line in _lines(text):
            normalized_line = _normalize(line).casefold()
            if not any(label.casefold() in normalized_line for label in labels):
                continue
            match = re.search(rf"(?:{label_pattern})\s*[:：]?\s*(?P<value>.+)", line, flags=re.I)
            candidates = [match.group("value")] if match else []
            candidates.append(line)
            for candidate in candidates:
                parsed_date = parse_event_date(candidate, posted_date)
                if not parsed_date:
                    continue
                parsed_time = normalize_time(candidate)
                parsed_clock = time.fromisoformat(parsed_time) if parsed_time else time(0, 0)
                return datetime.combine(parsed_date, parsed_clock, tzinfo=_JST)
        return None

    def extract_ticket_sales(
        self,
        text: str,
        posted_at: datetime,
        *,
        source_url: str,
        source_post_id: str,
        ticket_sale_type: str | None,
        ticket_status: str | None,
        general_price: int | None,
        priority_name: str | None,
        priority_price: int | None,
        same_day_price: int | None,
        ticket_application_start: datetime | None,
        ticket_application_deadline: datetime | None,
        lottery_result: datetime | None,
        payment_deadline: datetime | None,
    ) -> list[TicketSalePeriod]:
        periods: list[TicketSalePeriod] = []
        for line in _lines(text):
            period = self._ticket_sale_period_from_line(line, posted_at, source_url, source_post_id)
            if period:
                periods.append(period)

        for period in periods:
            if period.sale_type == "抽選":
                period.result_at = period.result_at or lottery_result
                period.payment_deadline_at = period.payment_deadline_at or payment_deadline
            if period.price is None:
                if period.ticket_tier in {"一般", "不明"} and general_price is not None:
                    period.price = general_price
                    if not period.ticket_name:
                        period.ticket_name = "一般"
                    if period.ticket_tier == "不明":
                        period.ticket_tier = "一般"
                elif period.ticket_tier in {"優先", "VIP", "SS", "前方"} and priority_price is not None:
                    period.price = priority_price
                    period.ticket_name = period.ticket_name or priority_name or period.ticket_tier

        if ticket_application_start or ticket_application_deadline or lottery_result or payment_deadline:
            base_type = ticket_sale_type or "不明"
            status = ticket_status_label_for_period(ticket_status)
            if priority_price is not None or priority_name:
                periods.append(
                    TicketSalePeriod(
                        sale_type=base_type,
                        ticket_name=priority_name or "優先",
                        ticket_tier=_ticket_tier(priority_name or "優先"),
                        price=priority_price,
                        start_at=ticket_application_start,
                        deadline_at=ticket_application_deadline,
                        result_at=lottery_result,
                        payment_deadline_at=payment_deadline,
                        status=status,
                        source_url=source_url,
                        source_post_id=source_post_id,
                    )
                )
            if general_price is not None or not periods:
                periods.append(
                    TicketSalePeriod(
                        sale_type=base_type,
                        ticket_name="一般" if general_price is not None else None,
                        ticket_tier="一般" if general_price is not None else "不明",
                        price=general_price,
                        start_at=ticket_application_start,
                        deadline_at=ticket_application_deadline,
                        result_at=lottery_result,
                        payment_deadline_at=payment_deadline,
                        status=status,
                        source_url=source_url,
                        source_post_id=source_post_id,
                    )
                )

        if same_day_price is not None and not any(period.sale_type == "当日券" for period in periods):
            periods.append(
                TicketSalePeriod(
                    sale_type="当日券",
                    ticket_name="当日券",
                    ticket_tier="一般",
                    price=same_day_price,
                    status=ticket_status_label_for_period(ticket_status or "same_day"),
                    source_url=source_url,
                    source_post_id=source_post_id,
                )
            )

        targeted_status = self._targeted_status_period(text, ticket_status, source_url, source_post_id)
        if targeted_status:
            periods.append(targeted_status)

        return _dedupe_ticket_periods(periods)

    def _ticket_sale_period_from_line(
        self,
        line: str,
        posted_at: datetime,
        source_url: str,
        source_post_id: str,
    ) -> TicketSalePeriod | None:
        normalized = _normalize(line)
        if any(label in normalized for label in ("当落発表", "支払期限", "入金期限")):
            return None
        sale_type = _sale_type_from_text(normalized)
        if sale_type is None:
            return None
        if sale_type == "無料" and "販売方式" not in normalized and not _extract_datetimes(normalized, posted_at) and normalize_price(normalized) is None:
            return None
        if sale_type == "無料" and "販売方式" in normalized and "無料" in normalized:
            return TicketSalePeriod(
                sale_type="無料",
                ticket_name="無料",
                ticket_tier="一般",
                price=0,
                status="販売中",
                source_url=source_url,
                source_post_id=source_post_id,
            )

        datetimes = _extract_datetimes(normalized, posted_at)
        start_at = datetimes[0] if datetimes else None
        deadline_at = datetimes[1] if len(datetimes) >= 2 else None
        price = normalize_price(normalized)
        ticket_tier = _ticket_tier(normalized)
        ticket_name = _ticket_name_from_line(normalized, ticket_tier)
        status = ticket_status_label_for_period(self.extract_ticket_status(normalized))
        if not any((start_at, deadline_at, price)) and sale_type not in {"当日券", "無料"}:
            return None
        if not any((start_at, deadline_at, price, ticket_name)) and sale_type not in {"当日券", "無料"}:
            return None
        return TicketSalePeriod(
            sale_type=sale_type,
            ticket_name=ticket_name,
            ticket_tier=ticket_tier,
            price=price,
            start_at=start_at,
            deadline_at=deadline_at,
            status=status,
            source_url=source_url,
            source_post_id=source_post_id,
        )

    def _targeted_status_period(
        self,
        text: str,
        ticket_status: str | None,
        source_url: str,
        source_post_id: str,
    ) -> TicketSalePeriod | None:
        status = ticket_status_label_for_period(ticket_status)
        if status not in {"完売", "販売終了"}:
            return None
        normalized = _normalize(text)
        tier = _ticket_tier(normalized)
        sale_type = _sale_type_from_text(normalized) or "不明"
        if tier == "不明" and sale_type == "不明":
            return None
        ticket_name = None if tier == "不明" else tier
        return TicketSalePeriod(
            sale_type=sale_type,
            ticket_name=ticket_name,
            ticket_tier=tier,
            status=status,
            source_url=source_url,
            source_post_id=source_post_id,
        )

    def extract_ticket_sale_type(self, text: str) -> str | None:
        normalized = _normalize(text)
        for line in _lines(normalized):
            if "販売方式" not in line:
                continue
            label_match = re.search(r"販売方式\s*[:：]\s*(?P<value>.+)", line)
            candidate = _sale_type_from_text(label_match.group("value") if label_match else line)
            if candidate:
                return candidate
        if "無料" in normalized:
            return "無料"
        if "当日券" in normalized:
            return "当日券"
        if "一般販売" in normalized or "一般受付" in normalized:
            return "一般"
        if "抽選" in normalized or "当落" in normalized:
            return "抽選"
        if "先着" in normalized:
            return "先着"
        return None

    def extract_ticket_status(self, text: str) -> str | None:
        normalized = _normalize(text).casefold()
        if _has_ended_ticket_status(normalized):
            return "ended"
        if any(word in normalized for word in ("sold out", "soldout", "完売", "売り切れ")):
            return "sold_out"
        if any(word in normalized for word in ("当日券あり", "当日券販売", "当日券ございます")):
            return "same_day"
        if any(word in normalized for word in ("受付中", "発売中", "予約受付中", "販売中")):
            return "on_sale"
        if any(word in normalized for word in ("販売前", "発売前", "予約開始前")):
            return "upcoming"
        return None

    def extract_notes(self, text: str, source_kind: SourceKind) -> str | None:
        note_lines: list[str] = []
        for line in _lines(text):
            normalized = _normalize(line)
            if source_kind in {SourceKind.CORRECTION, SourceKind.SOLD_OUT}:
                if any(word in normalized for word in ("訂正", "修正", "変更", "お詫び", "完売", "売り切れ", "受付終了")):
                    note_lines.append(_clean_value(line))
            elif line.strip().startswith(("※", "*")):
                note_lines.append(_clean_value(line))
        return "\n".join(note_lines) if note_lines else None

    def calculate_confidence(self, **values: object) -> float:
        score = 0.2
        if values.get("event_date"):
            score += 0.2
        if values.get("event_name"):
            score += 0.2
        if values.get("venue"):
            score += 0.15
        if values.get("open_time") or values.get("start_time"):
            score += 0.1
        if values.get("performance_time") or values.get("benefit_time"):
            score += 0.1
        if values.get("ticket_url"):
            score += 0.05
        if values.get("source_kind") in {
            SourceKind.TIMETABLE_UPDATE,
            SourceKind.DAY_BEFORE_REMINDER,
            SourceKind.SAME_DAY_REMINDER,
        }:
            score += 0.05
        return min(round(score, 2), 0.95)


def _normalize(value: str) -> str:
    return normalize_spaces(unicodedata.normalize("NFKC", value))


_DATETIME_RE = re.compile(
    r"(?:(?P<year>20\d{2})[年/\-.])?(?P<month>\d{1,2})(?:月|[/\.])(?P<day>\d{1,2})日?"
    r"\s*(?P<time>\d{1,2}(?:[:：]\d{2}|時\d{0,2}分?))?"
)


def _extract_datetimes(value: str, posted_at: datetime) -> list[datetime]:
    posted_date = _local_posted_date(posted_at)
    parsed: list[datetime] = []
    for match in _DATETIME_RE.finditer(value):
        date_part = match.group(0)
        parsed_date = parse_event_date(date_part, posted_date)
        if not parsed_date:
            continue
        parsed_time = normalize_time(match.group("time") or "")
        parsed_clock = time.fromisoformat(parsed_time) if parsed_time else time(0, 0)
        parsed.append(datetime.combine(parsed_date, parsed_clock, tzinfo=_JST))
    return parsed


def _sale_type_from_text(value: str) -> str | None:
    normalized = _normalize(value)
    if "無料" in normalized:
        return "無料"
    if "当日券" in normalized:
        return "当日券"
    if any(word in normalized for word in ("一般販売", "一般受付")):
        return "一般"
    if any(word in normalized for word in ("抽選受付", "抽選販売", "先行抽選", "抽選", "当落")):
        return "抽選"
    if any(word in normalized for word in ("先着販売", "先着", "受付開始", "受付締切", "販売開始", "販売終了")):
        return "先着"
    return None


def _ticket_tier(value: str | None) -> str:
    normalized = _normalize(value or "")
    if any(word in normalized for word in ("VIP", "vip")):
        return "VIP"
    if "SS" in normalized:
        return "SS"
    if "カメラ" in normalized:
        return "カメラ"
    if "前方" in normalized:
        return "前方"
    if "優先" in normalized:
        return "優先"
    if "一般" in normalized or "通常" in normalized or "前売" in normalized:
        return "一般"
    if "当日券" in normalized or "当日" in normalized:
        return "一般"
    return "不明"


def _ticket_name_from_line(value: str, ticket_tier: str) -> str | None:
    if ticket_tier != "不明":
        return ticket_tier if ticket_tier != "一般" else "一般"
    match = re.search(r"(?P<name>(?:優先|前方|VIP|SS|カメラ|一般|当日券)[^:：\d¥￥円]*)", value)
    return _clean_value(match.group("name")) if match else None


def ticket_status_label_for_period(status: str | None) -> str:
    if not status:
        return "不明"
    mapping = {
        "on_sale": "販売中",
        "same_day": "販売中",
        "same_day_available": "販売中",
        "upcoming": "未販売",
        "sold_out": "完売",
        "ended": "販売終了",
        "販売中": "販売中",
        "未販売": "未販売",
        "完売": "完売",
        "販売終了": "販売終了",
        "不明": "不明",
    }
    return mapping.get(status, status)


def _dedupe_ticket_periods(periods: list[TicketSalePeriod]) -> list[TicketSalePeriod]:
    deduped: list[TicketSalePeriod] = []
    seen: set[tuple[str, str, str, str]] = set()
    for period in periods:
        key = (
            period.sale_type,
            period.ticket_name or period.ticket_tier or "",
            period.start_at.isoformat() if period.start_at else "",
            period.deadline_at.isoformat() if period.deadline_at else "",
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(period)
    return deduped


def _lines(text: str) -> list[str]:
    return [normalize_spaces(line) for line in text.splitlines() if line.strip()]


def _clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _URL_RE.sub("", value)
    cleaned = re.sub(r"[#＃][^\s]+", "", cleaned)
    cleaned = cleaned.strip(" \t　:：-ー/／|｜📍🎫⏰🗓️")
    cleaned = normalize_spaces(cleaned)
    return cleaned or None


def _local_posted_date(posted_at: datetime) -> date:
    if posted_at.tzinfo is None:
        return posted_at.date()
    return posted_at.astimezone(_JST).date()


def _has_ended_ticket_status(normalized_text: str) -> bool:
    ended_phrases = (
        "販売終了しました",
        "販売は終了",
        "販売終了のお知らせ",
        "受付終了しました",
        "受付は終了",
        "受付終了のお知らせ",
        "予約終了しました",
        "予約は終了",
    )
    if any(phrase in normalized_text for phrase in ended_phrases):
        return True
    for label in ("販売終了", "受付終了", "予約終了"):
        if label in normalized_text and not re.search(rf"{label}\s*[:：]?\s*\d", normalized_text):
            return True
    return False


def _is_metadata_line(line: str) -> bool:
    normalized = _normalize(line).casefold()
    return any(
        token in normalized
        for token in (
            "開場",
            "開演",
            "open",
            "start",
            "会場",
            "場所",
            "チケット",
            "http",
            "出演時間",
            "特典会",
            "本日",
            "明日",
            "申込",
            "受付",
            "販売開始",
            "販売終了",
            "当落",
            "支払",
            "入金",
        )
    )
