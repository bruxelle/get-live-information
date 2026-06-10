from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlsplit

from .models import (
    ClassificationConfidence,
    ExtractedEvent,
    PostClassification,
    PostClassificationResult,
    SourceKind,
    TicketSalePeriod,
    XPost,
)
from .normalization import normalize_price, normalize_spaces, normalize_time, normalize_time_range, parse_event_date, parse_event_dates


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
    "ラジオ配信",
    "coming soon",
    "キャンペーン",
    "ミョージョーサマーキャンペーン",
    "アンチコンプリート",
    "学力テスト",
    "LIVE DIGEST",
)

_URL_RE = re.compile(r"https?://[^\s)）]+")
_TIME_RE = re.compile(r"\d{1,2}(?:[:：]\d{2}|時\d{0,2}分?)")
_JST = timezone(timedelta(hours=9))
_TICKET_URL_DOMAINS = (
    "ticketdive.com",
    "t-dv.com",
    "tiget.net",
    "livepocket.jp",
    "ticketvillage.jp",
    "eplus.jp",
    "l-tike.com",
    "pia.jp",
    "zaiko.io",
)
_TICKET_URL_PATH_KEYWORDS = ("ticket", "tickets")
_STREAMING_URL_DOMAINS = ("nicovideo.jp", "youtube.com", "youtu.be", "twitcasting.tv")
_TICKET_TIER_KEYWORDS = (
    "前方",
    "優先",
    "VIP",
    "vip",
    "SS",
    "カメラ",
    "一般",
    "通常",
    "前売",
    "当日",
    "後方",
    "Tシャツ",
    "無料チケット",
)
_PROFILE_MEMBER_NAMES = ("薄倉りな", "栗原ここね", "真希しの", "姫乃るか", "澪奈ゆん", "日陽みう")


class PostParser:
    def __init__(self, username: str = "info_myojou") -> None:
        self.username = username

    def parse_post(self, post: XPost, classification: PostClassificationResult | None = None) -> ExtractedEvent | None:
        text = post.text
        classification = classification or self.classify_post(post)
        if classification.classification == PostClassification.NON_EVENT:
            return None

        source_kind = classification.source_kind
        event_dates = self.extract_event_dates(text, post.created_at, source_kind)
        event_date = event_dates[0] if event_dates else None
        event_name = self.extract_event_name(text)
        venue = self.extract_venue(text)
        open_time = self.extract_labeled_time(text, ("open", "開場"))
        start_time = self.extract_labeled_time(text, ("start", "開演"))
        performance_time = self.extract_context_time(text, ("出演時間", "出演", "出番", "myojou", "ミョウジョウ", "ライブ", "🎙"))
        benefit_time = self.extract_context_time(text, ("特典会", "物販", "📸"))
        ticket_url = self.extract_ticket_url(text, post.raw)
        general_price = self.extract_price(text, ("一般", "前売", "通常"))
        if general_price is None:
            general_price = self.extract_global_free_price(text)
        priority_name, priority_price = self.extract_priority_ticket(text)
        same_day_price = self.extract_price(text, ("当日", "当日券"))
        ticket_application_start = self.extract_labeled_datetime(text, ("申込開始", "受付開始", "販売開始"), post.created_at)
        ticket_application_deadline = self.extract_labeled_datetime(text, ("申込締切", "受付締切", "販売終了"), post.created_at)
        lottery_result = self.extract_labeled_datetime(text, ("当落発表",), post.created_at)
        payment_deadline = self.extract_labeled_datetime(text, ("支払期限", "支払い期限", "入金期限"), post.created_at)
        ticket_sale_type = self.extract_ticket_sale_type(text, general_price=general_price)
        ticket_status = self.extract_ticket_status(text)
        ticket_price_tiers = self.extract_ticket_price_tiers(text)
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
            ticket_price_tiers=ticket_price_tiers,
            ticket_application_start=ticket_application_start,
            ticket_application_deadline=ticket_application_deadline,
            lottery_result=lottery_result,
            payment_deadline=payment_deadline,
        )
        selected_sale = _selected_ticket_period_for_extracted_fields(ticket_sales)
        if selected_sale:
            ticket_application_start = ticket_application_start or selected_sale.start_at
            ticket_application_deadline = ticket_application_deadline or selected_sale.deadline_at
            lottery_result = lottery_result or selected_sale.result_at
            payment_deadline = payment_deadline or selected_sale.payment_deadline_at
            ticket_sale_type = ticket_sale_type or selected_sale.sale_type

        confidence = self.calculate_confidence(
            event_date=event_date,
            event_dates=event_dates,
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
            event_dates=event_dates,
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
            source_raw=post.raw,
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
        ticket_url = self.extract_ticket_url(text, post.raw)
        has_time = bool(self.extract_labeled_time(text, ("open", "開場")) or self.extract_labeled_time(text, ("start", "開演")))
        has_performance = bool(self.extract_context_time(text, ("出演時間", "出演", "出番", "myojou", "ミョウジョウ", "ライブ", "🎙")))
        positive_count = sum(1 for keyword in LIVE_KEYWORDS if keyword.casefold() in compact)
        ticket_domain = any(domain in compact for domain in ("ticketdive.com", "t.livepocket.jp", "livepocket", "tiget.net"))
        non_event_signal = self.is_obvious_non_event_post(normalized)
        structured_count = sum(bool(value) for value in (event_date, event_name, venue, ticket_url, has_time, has_performance))

        profile_reason = self.profile_member_non_event_reason(
            normalized,
            event_date=event_date,
            venue=venue,
            ticket_url=ticket_url,
            has_time=has_time,
            has_performance=has_performance,
        )
        if profile_reason:
            return PostClassificationResult(
                classification=PostClassification.NON_EVENT,
                confidence=ClassificationConfidence.HIGH,
                reason=profile_reason,
                source_kind=SourceKind.OTHER,
            )

        hard_non_event_reason = self.hard_non_event_reason(normalized)
        if hard_non_event_reason:
            return PostClassificationResult(
                classification=PostClassification.NON_EVENT,
                confidence=ClassificationConfidence.HIGH,
                reason=hard_non_event_reason,
                source_kind=SourceKind.OTHER,
            )

        if _is_live_digest_post(normalized) and not any((event_date, venue, has_time, ticket_url)):
            return PostClassificationResult(
                classification=PostClassification.NON_EVENT,
                confidence=ClassificationConfidence.HIGH,
                reason="live digest recap without structured event fields",
                source_kind=SourceKind.OTHER,
            )

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
            for word in ("チケット", "開場", "開演", "出演時間", "申込", "受付", "販売開始", "販売中")
        ):
            return True
        if "お知らせ" in compact and not any(
            word in compact
            for word in ("ライブ", "live", "公演", "出演", "チケット", "開場", "開演", "申込", "受付", "販売")
        ):
            return True
        return False

    def profile_member_non_event_reason(
        self,
        normalized_text: str,
        *,
        event_date,
        venue,
        ticket_url,
        has_time: bool,
        has_performance: bool,
    ) -> str | None:
        compact = normalize_spaces(normalized_text).casefold()
        compact_no_space = re.sub(r"\s+", "", compact)
        if re.search(r"\bprofile\s*0?[1-9]\b", compact, flags=re.I) or re.search(r"profile[0-9０-９]+", compact_no_space, flags=re.I):
            return "profile/member introduction"

        has_live_structure = bool(venue or ticket_url or has_time or has_performance)
        if has_live_structure:
            return None

        if any(token in compact for token in ("プロフィール", "自己紹介", "メンバー紹介", "name┊", "name｜")):
            return "profile/member introduction"

        meaningful_lines = [_clean_value(line) for line in _lines(normalized_text) if _clean_value(line)]
        if any(line in _PROFILE_MEMBER_NAMES for line in meaningful_lines):
            return "profile/member introduction"
        if any(name in compact for name in _PROFILE_MEMBER_NAMES) and not any(
            token in compact
            for token in ("ライブ", "live", "公演", "出演", "会場", "場所", "開場", "開演", "チケット", "ticket")
        ):
            return "profile/member introduction"
        return None

    def hard_non_event_reason(self, normalized_text: str) -> str | None:
        compact = normalize_spaces(normalized_text).casefold()
        compact_no_space = re.sub(r"\s+", "", compact)
        if re.search(r"\bprofile\s*0?[1-9]\b", compact, flags=re.I) or re.search(r"profile[0-9０-９]+", compact_no_space, flags=re.I):
            return "profile/member introduction"
        checks = (
            ("radio/non-live", ("ラジオ配信",)),
            ("teaser/coming soon", ("coming soon", "comingsoon", "近日公開", "近日解禁")),
            ("campaign-like post", ("キャンペーン", "ミョージョーサマーキャンペーン")),
            ("content/MV-like post", ("アンチコンプリート", "music video", "musicvideo", "mv公開")),
            ("content program, not live schedule", ("学力テスト", "直前sp")),
            ("live digest recap", ("live digest", "livedigest")),
        )
        for reason, tokens in checks:
            if any(token.casefold() in compact or token.casefold() in compact_no_space for token in tokens):
                return reason
        if all(token in compact for token in ("ニックネーム", "サイン", "日付", "コメント")):
            return "online signing/benefit-detail content"
        if any(word in compact for word in ("御礼", "ありがとうございました")):
            return "thank-you/recap post"
        return None

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
        if any(word in normalized for word in ("本日", "今日")):
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
        dates = self.extract_event_dates(text, posted_at, source_kind)
        return dates[0] if dates else None

    def extract_event_dates(
        self,
        text: str,
        posted_at: datetime,
        source_kind: SourceKind | None = None,
    ) -> list[date]:
        normalized = _normalize(text)
        posted_date = _local_posted_date(posted_at)
        appearance_dates: list[date] = []
        general_dates: list[date] = []
        pending_ticket_date_line = False
        for line in _lines(normalized):
            if not line:
                continue
            line_dates = parse_event_dates(line, posted_date)
            if _is_ticket_date_header(line):
                pending_ticket_date_line = True
                if line_dates:
                    continue
            elif pending_ticket_date_line and line_dates:
                pending_ticket_date_line = False
                continue
            else:
                pending_ticket_date_line = False

            if not line_dates or _should_skip_event_date_line(line):
                continue
            if _is_myojou_appearance_date_line(line):
                appearance_dates.extend(line_dates)
            else:
                general_dates.extend(line_dates)

        parsed_dates = _dedupe_dates(appearance_dates or general_dates)
        if parsed_dates:
            return parsed_dates

        if source_kind == SourceKind.SAME_DAY_REMINDER or any(word in normalized for word in ("本日", "今日")):
            return [posted_date]
        if source_kind == SourceKind.DAY_BEFORE_REMINDER or "明日" in normalized:
            return [posted_date + timedelta(days=1)]
        return []

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

        title_candidate = _title_from_header_block(text)
        if title_candidate:
            return title_candidate

        for line in _lines(text):
            cleaned = _clean_value(line)
            if not cleaned or _is_metadata_line(cleaned):
                continue
            if any(word in cleaned for word in ("LIVE", "Live", "ライブ", "公演", "FES", "フェス")) and len(cleaned) <= 80:
                return cleaned
            if "festival" in cleaned.casefold() and len(cleaned) <= 80:
                return cleaned
        return None

    def extract_venue(self, text: str) -> str | None:
        for line in _lines(text):
            label_match = re.search(r"(?:会場|場所|VENUE|place)\s*[:：]?\s*(?P<venue>.+)", line, flags=re.I)
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
            if "open/start" in normalized_line or "open / start" in normalized_line:
                time_range = normalize_time_range(line)
                if time_range and "-" in time_range:
                    open_time, start_time = time_range.split("-", 1)
                    if any(label.casefold() == "open" for label in labels):
                        return open_time
                    if any(label.casefold() == "start" for label in labels):
                        return start_time
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

    def extract_ticket_url(self, text: str, raw: dict | None = None) -> str | None:
        entity_urls = _urls_from_entities(raw)
        ticket_entity_urls = [url for url in entity_urls if _is_ticket_url(url)]
        if ticket_entity_urls:
            return ticket_entity_urls[0]
        urls = _URL_RE.findall(text)
        media_urls = _media_urls_from_entities(raw)
        cleaned_urls = [
            url.rstrip(").,、。")
            for url in urls
            if url.rstrip(").,、。") not in media_urls and not _is_media_url(url.rstrip(").,、。"))
        ]
        ticket_urls = [url for url in cleaned_urls if _is_ticket_url(url)]
        if ticket_urls:
            return ticket_urls[0]
        return None

    def extract_price(self, text: str, labels: tuple[str, ...]) -> int | None:
        for line in _lines(text):
            normalized_line = _normalize(line).casefold()
            if not any(label.casefold() in normalized_line for label in labels):
                continue
            labeled_price = _price_after_label(line, labels)
            if labeled_price is not None:
                return labeled_price
            free_price = _free_price_from_line(line)
            if free_price is not None:
                return free_price
            price = normalize_price(line)
            if price is not None:
                return price
        return None

    def extract_global_free_price(self, text: str) -> int | None:
        for line in _lines(text):
            if _is_global_free_price_line(line):
                return 0
        return None

    def extract_priority_ticket(self, text: str) -> tuple[str | None, int | None]:
        for line in _lines(text):
            if not any(label in _normalize(line) for label in ("優先", "前方", "Sチケット", "優先エリア", "VIP", "SS", "カメラ")):
                continue
            price = normalize_price(line)
            name_match = re.search(r"(?P<name>(?:優先|前方|Sチケット|優先エリア|VIP|SS|カメラ)[^:：\d¥￥円]*)", line)
            name = _clean_value(name_match.group("name")) if name_match else "優先"
            return name or "優先", price
        return None, None

    def extract_ticket_price_tiers(self, text: str) -> list[TicketSalePeriod]:
        tiers: list[TicketSalePeriod] = []
        for line in _lines(text):
            normalized = _normalize(line)
            if normalize_price(normalized) is None and _free_price_from_line(normalized) is None:
                continue
            for segment in _ticket_price_segments(normalized):
                price = normalize_price(segment)
                if price is None:
                    price = _free_price_from_line(segment)
                if price is None:
                    continue
                ticket_tier = _ticket_tier(segment)
                if ticket_tier == "不明":
                    continue
                sale_type = "当日券" if any(word in segment for word in ("当日券", "当日料金", "当日")) else "不明"
                ticket_name = _ticket_name_from_line(segment, ticket_tier)
                tiers.append(
                    TicketSalePeriod(
                        sale_type=sale_type,
                        ticket_name=ticket_name or ticket_tier,
                        ticket_tier=ticket_tier,
                        price=price,
                    )
                )
        return _dedupe_ticket_periods(tiers)

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
        ticket_price_tiers: list[TicketSalePeriod],
        ticket_application_start: datetime | None,
        ticket_application_deadline: datetime | None,
        lottery_result: datetime | None,
        payment_deadline: datetime | None,
    ) -> list[TicketSalePeriod]:
        periods: list[TicketSalePeriod] = []
        pending_sale_type: str | None = None
        for line in _lines(text):
            period = self._ticket_sale_period_from_line(line, posted_at, source_url, source_post_id)
            if period:
                periods.append(period)
                pending_sale_type = None
                continue
            datetimes = _extract_datetimes(_normalize(line), posted_at)
            if pending_sale_type and len(datetimes) >= 2:
                periods.append(
                    TicketSalePeriod(
                        sale_type=pending_sale_type,
                        ticket_tier="不明",
                        start_at=datetimes[0],
                        deadline_at=datetimes[1],
                        status=ticket_status_label_for_period(ticket_status),
                        source_url=source_url,
                        source_post_id=source_post_id,
                    )
                )
                pending_sale_type = None
                continue
            sale_type = _sale_type_from_text(line)
            if sale_type:
                pending_sale_type = sale_type

        periods = _expand_generic_dated_periods_with_price_tiers(periods, ticket_price_tiers)
        for period in periods:
            if period.sale_type == "抽選":
                period.result_at = period.result_at or lottery_result
                period.payment_deadline_at = period.payment_deadline_at or payment_deadline
            if period.price is None:
                tier_price = _matching_price_tier(period, ticket_price_tiers)
                if tier_price:
                    period.price = tier_price.price
                    period.ticket_name = period.ticket_name or tier_price.ticket_name
                    if period.ticket_tier == "不明":
                        period.ticket_tier = tier_price.ticket_tier
                elif period.ticket_tier in {"一般", "不明"} and general_price is not None:
                    period.price = general_price
                    if not period.ticket_name:
                        period.ticket_name = "一般"
                    if period.ticket_tier == "不明":
                        period.ticket_tier = "一般"
                elif _is_priority_like_tier(period.ticket_tier) and priority_price is not None:
                    period.price = priority_price
                    period.ticket_name = period.ticket_name or priority_name or period.ticket_tier

        if ticket_application_start or ticket_application_deadline or lottery_result or payment_deadline:
            base_type = ticket_sale_type or "不明"
            status = ticket_status_label_for_period(ticket_status)
            dated_price_tiers = [period for period in ticket_price_tiers if period.sale_type != "当日券"]
            if dated_price_tiers:
                for tier in dated_price_tiers:
                    periods.append(
                        TicketSalePeriod(
                            sale_type=base_type,
                            ticket_name=tier.ticket_name,
                            ticket_tier=tier.ticket_tier,
                            price=tier.price,
                            start_at=ticket_application_start,
                            deadline_at=ticket_application_deadline,
                            result_at=lottery_result,
                            payment_deadline_at=payment_deadline,
                            status=status,
                            source_url=source_url,
                            source_post_id=source_post_id,
                        )
                    )
            else:
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

        if not any(period.start_at or period.deadline_at for period in periods):
            for tier in ticket_price_tiers:
                if tier.sale_type == "当日券":
                    continue
                periods.append(
                    TicketSalePeriod(
                        sale_type=ticket_sale_type or tier.sale_type,
                        ticket_name=tier.ticket_name,
                        ticket_tier=tier.ticket_tier,
                        price=tier.price,
                        status=ticket_status_label_for_period(ticket_status),
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
        if any(label in normalized for label in ("当落発表", "支払期限", "支払い期限", "入金期限")):
            return None
        if _is_global_ticket_datetime_line(normalized):
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

    def extract_ticket_sale_type(self, text: str, *, general_price: int | None = None) -> str | None:
        normalized = _normalize(text)
        for line in _lines(normalized):
            if "販売方式" not in line:
                continue
            label_match = re.search(r"販売方式\s*[:：]\s*(?P<value>.+)", line)
            candidate = _sale_type_from_text(label_match.group("value") if label_match else line)
            if candidate:
                return candidate
        if general_price == 0 or _has_free_price_label(normalized):
            return "無料"
        if "当日券" in normalized:
            return "当日券"
        if "一般販売" in normalized or "一般発売" in normalized or "一般受付" in normalized:
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
            elif any(word in normalized for word in ("入場特典", "来場特典")):
                note_lines.append(_clean_value(line))
            elif "要予約" in normalized or _drink_note_from_line(line):
                if "要予約" in normalized:
                    note_lines.append("要予約")
                drink_note = _drink_note_from_line(line)
                if drink_note:
                    note_lines.append(drink_note)
            elif line.strip().startswith(("※", "*")):
                note_lines.append(_clean_value(line))
        note_lines = [line for line in dict.fromkeys(note_lines) if line]
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


def _urls_from_entities(raw: dict | None) -> list[str]:
    if not raw:
        return []
    extracted: list[str] = []
    for item in _url_entities(raw):
        if not isinstance(item, dict):
            continue
        url = item.get("expanded_url") or item.get("unwound_url") or item.get("url")
        if url and not _is_media_url(str(url), item):
            extracted.append(str(url).rstrip(").,、。"))
    return extracted


def _media_urls_from_entities(raw: dict | None) -> set[str]:
    if not raw:
        return set()
    media_urls: set[str] = set()
    for item in _url_entities(raw):
        if not isinstance(item, dict):
            continue
        candidates = (item.get("url"), item.get("expanded_url"), item.get("unwound_url"))
        if any(candidate and _is_media_url(str(candidate), item) for candidate in candidates):
            media_urls.update(str(candidate).rstrip(").,、。") for candidate in candidates if candidate)
    return media_urls


def _url_entities(raw: dict) -> list[dict]:
    entities: list[dict] = []
    raw_urls = raw.get("entities", {}).get("urls", [])
    if isinstance(raw_urls, list):
        entities.extend(item for item in raw_urls if isinstance(item, dict))
    note_tweet = raw.get("note_tweet")
    if isinstance(note_tweet, dict):
        note_urls = note_tweet.get("entities", {}).get("urls", [])
        if isinstance(note_urls, list):
            entities.extend(item for item in note_urls if isinstance(item, dict))
    return entities


def _is_ticket_url(url: str) -> bool:
    normalized = url.casefold()
    if _is_streaming_url(normalized):
        return False
    parts = urlsplit(normalized)
    host = parts.netloc.removeprefix("www.")
    path = parts.path
    if any(host == domain or host.endswith(f".{domain}") for domain in _TICKET_URL_DOMAINS):
        return True
    return any(keyword in path for keyword in _TICKET_URL_PATH_KEYWORDS)


def _is_streaming_url(url: str) -> bool:
    parts = urlsplit(url.casefold())
    host = parts.netloc.removeprefix("www.")
    return any(host == domain or host.endswith(f".{domain}") for domain in _STREAMING_URL_DOMAINS)


def _is_media_url(url: str, entity: dict | None = None) -> bool:
    normalized = url.casefold()
    display_url = str((entity or {}).get("display_url", "")).casefold()
    return bool(
        (entity or {}).get("media_key")
        or "pic.x.com" in normalized
        or display_url.startswith("pic.x.com")
        or "/photo/" in normalized
        or "/video/" in normalized
        or "pbs.twimg.com/media/" in normalized
    )


def _is_live_digest_post(text: str) -> bool:
    return "live digest" in _normalize(text).casefold()


def _is_ticket_date_header(line: str) -> bool:
    normalized = _normalize(line).casefold()
    return any(
        token in normalized
        for token in (
            "抽選販売",
            "抽選受付",
            "抽選申込",
            "先行抽選",
            "一般販売",
            "一般発売",
            "一般受付",
            "先着販売",
            "先着受付",
            "申込開始",
            "申込締切",
            "受付開始",
            "受付締切",
            "販売開始",
            "販売終了",
            "当落発表",
            "支払期限",
            "支払い期限",
            "入金期限",
        )
    )


def _should_skip_event_date_line(line: str) -> bool:
    normalized = _normalize(line).casefold()
    if _is_ticket_date_header(normalized):
        return True
    if any(token in normalized for token in ("price", "料金", "入場料", "¥", "￥", "円")):
        return True
    if any(token in normalized for token in ("チケット", "ticket")) and not _is_event_date_context_line(normalized):
        return True
    if _contains_date_time_range(normalized) and not _is_event_date_context_line(normalized):
        return True
    return False


def _is_myojou_appearance_date_line(line: str) -> bool:
    normalized = _normalize(line).casefold()
    return any(token in normalized for token in ("出演日", "出演", "出番", "myojou", "明星", "🎙"))


def _is_event_date_context_line(line: str) -> bool:
    normalized = _normalize(line).casefold()
    return any(
        token in normalized
        for token in (
            "date",
            "日付",
            "日程",
            "開催日",
            "公演日",
            "出演日",
            "ライブ",
            "live",
            "festival",
            "fes",
            "フェス",
            "イベント",
        )
    )


def _contains_date_time_range(line: str) -> bool:
    return bool(
        re.search(
            r"\d{1,2}(?:月|[/\.])\d{1,2}(?:日)?[（(]?[月火水木金土日]?[）)]?\s*\d{1,2}[:：]\d{2}"
            r"\s*(?:-|ー|–|〜|～|~)",
            line,
        )
    )


def _dedupe_dates(values: list[date]) -> list[date]:
    unique: list[date] = []
    seen: set[date] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _free_price_from_line(line: str) -> int | None:
    normalized = _normalize(line)
    if re.search(r"(?:¥|￥)\s*0(?:\D|$)", normalized) or re.search(r"(?:^|[:：\s])0\s*円", normalized):
        return 0
    if any(word in normalized.casefold() for word in ("無料", "free")):
        return 0
    return None


def _is_global_free_price_line(line: str) -> bool:
    normalized = _normalize(line)
    label_match = re.search(r"(?:price|料金|入場料|販売方式)\s*[:：]\s*(?P<value>.+)", normalized, flags=re.I)
    value = label_match.group("value") if label_match else normalized
    compact = re.sub(r"\s+", "", value).casefold()
    if not compact:
        return False
    if any(keyword.casefold() in compact for keyword in _TICKET_TIER_KEYWORDS):
        return False
    if re.search(r"(?:¥|￥)\s*0(?:\D|$)", value) or re.search(r"(?:^|[:：\s])0\s*円", value):
        return True
    if compact in {"無料", "入場無料", "観覧無料", "free", "¥0", "￥0", "0円"}:
        return True
    return bool(re.fullmatch(r"(?:入場|観覧)?無料(?:イベント|公演|ライブ)?", compact))


def _ticket_price_segments(line: str) -> list[str]:
    normalized = _normalize(line)
    label_match = re.search(r"(?:price|料金|入場料)\s*[:：]\s*(?P<value>.+)", normalized, flags=re.I)
    if label_match:
        normalized = label_match.group("value")
    return [segment.strip() for segment in re.split(r"[/／]", normalized) if segment.strip()]


def _price_after_label(line: str, labels: tuple[str, ...]) -> int | None:
    normalized = _normalize(line)
    for label in sorted(labels, key=len, reverse=True):
        pattern = re.compile(
            rf"{re.escape(label)}[^¥￥\d]*(?P<price>(?:¥|￥)?\s*\d{{1,3}}(?:,\d{{3}})*|\d{{1,7}})\s*(?:円|yen)?",
            flags=re.I,
        )
        match = pattern.search(normalized)
        if not match:
            continue
        value = match.group("price")
        if re.search(r"(?:¥|￥)\s*0$", value) or value.replace(",", "").strip() == "0":
            return 0
        parsed = normalize_price(value)
        if parsed is not None:
            return parsed
    return None


def _drink_note_from_line(line: str) -> str | None:
    normalized = _normalize(line)
    match = re.search(r"(?:各)?\+?\s*1D", normalized, flags=re.I)
    if match:
        return "ドリンク代: 各+1D" if "各" in match.group(0) or "各" in normalized else "ドリンク代: +1D"
    if "ドリンク" in normalized:
        return _clean_value(line)
    return None


def _has_free_price_label(text: str) -> bool:
    for line in _lines(text):
        if _is_global_free_price_line(line):
            return True
    return False


_DATETIME_RE = re.compile(
    r"(?:(?P<year>20\d{2})[年/\-.])?(?P<month>\d{1,2})(?:月|[/\.])(?P<day>\d{1,2})日?"
    r"(?:[（(][月火水木金土日][）)])?"
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
    if _is_global_free_price_line(normalized):
        return "無料"
    if "当日券" in normalized:
        return "当日券"
    if any(word in normalized for word in ("一般販売", "一般発売", "一般受付")):
        return "一般"
    if any(word in normalized for word in ("抽選受付", "抽選販売", "抽選申込", "先行抽選", "抽選", "当落")):
        return "抽選"
    if any(word in normalized for word in ("先着販売", "先着受付", "先着", "受付開始", "受付締切", "販売開始", "販売終了")):
        return "先着"
    return None


def _is_global_ticket_datetime_line(value: str) -> bool:
    normalized = _normalize(value)
    return bool(re.match(r"^(?:申込開始|受付開始|販売開始|申込締切|受付締切|販売終了)\s*[:：]", normalized))


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
    if "Tシャツ" in normalized or "無料チケット" in normalized:
        return "その他"
    if "後方" in normalized:
        return "その他"
    return "不明"


def _is_priority_like_tier(ticket_tier: str | None) -> bool:
    return ticket_tier in {"優先", "VIP", "SS", "前方", "カメラ"}


def _matching_price_tier(period: TicketSalePeriod, price_tiers: list[TicketSalePeriod]) -> TicketSalePeriod | None:
    for tier in price_tiers:
        if period.ticket_tier != "不明" and tier.ticket_tier == period.ticket_tier:
            return tier
        if period.ticket_name and tier.ticket_name and tier.ticket_name in period.ticket_name:
            return tier
    if period.ticket_tier in {"一般", "不明"}:
        return next((tier for tier in price_tiers if tier.ticket_tier == "一般"), None)
    if _is_priority_like_tier(period.ticket_tier):
        return next((tier for tier in price_tiers if _is_priority_like_tier(tier.ticket_tier)), None)
    return None


def _expand_generic_dated_periods_with_price_tiers(
    periods: list[TicketSalePeriod],
    price_tiers: list[TicketSalePeriod],
) -> list[TicketSalePeriod]:
    priced_tiers = [tier for tier in price_tiers if tier.sale_type != "当日券"]
    if not priced_tiers:
        return periods

    expanded: list[TicketSalePeriod] = []
    for period in periods:
        is_generic_dated_period = (
            period.sale_type != "当日券"
            and bool(period.start_at or period.deadline_at)
            and period.ticket_tier == "不明"
            and period.price is None
            and period.ticket_name is None
        )
        if not is_generic_dated_period:
            expanded.append(period)
            continue
        for tier in priced_tiers:
            expanded.append(
                period.model_copy(
                    update={
                        "ticket_name": tier.ticket_name,
                        "ticket_tier": tier.ticket_tier,
                        "price": tier.price,
                    }
                )
            )
    return expanded


def _ticket_name_from_line(value: str, ticket_tier: str) -> str | None:
    normalized = _normalize(value)
    named_ticket = re.search(r"(?P<name>[^:：\d¥￥円/／（）()]+チケット)", normalized)
    if named_ticket:
        return _clean_value(named_ticket.group("name"))
    if "後方観覧" in normalized:
        return "後方観覧"
    if "後方" in normalized:
        return "後方"
    if ticket_tier != "不明":
        return ticket_tier if ticket_tier != "一般" else "一般"
    match = re.search(r"(?P<name>(?:優先|前方|VIP|SS|カメラ|一般|当日券|後方観覧|後方)[^:：\d¥￥円]*)", value)
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
    ordered_periods = sorted(periods, key=lambda period: 0 if period.start_at or period.deadline_at else 1)
    for period in ordered_periods:
        if not (period.start_at or period.deadline_at):
            existing = _find_dated_period_for_price_only_period(deduped, period)
            if existing:
                if existing.price is None:
                    existing.price = period.price
                if existing.status == "不明" and period.status != "不明":
                    existing.status = period.status
                continue
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


def _selected_ticket_period_for_extracted_fields(periods: list[TicketSalePeriod]) -> TicketSalePeriod | None:
    dated = [period for period in periods if period.start_at or period.deadline_at or period.result_at or period.payment_deadline_at]
    if not dated:
        return None
    for sale_type in ("抽選", "一般", "先着", "当日券"):
        matching = [period for period in dated if period.sale_type == sale_type]
        if matching:
            return sorted(matching, key=_period_sort_key)[0]
    return sorted(dated, key=_period_sort_key)[0]


def _period_sort_key(period: TicketSalePeriod) -> tuple[str, str, str]:
    return (
        period.deadline_at.isoformat() if period.deadline_at else "9999-99-99T99:99:99",
        period.start_at.isoformat() if period.start_at else "9999-99-99T99:99:99",
        period.sale_type,
    )


def _find_dated_period_for_price_only_period(
    periods: list[TicketSalePeriod],
    price_only: TicketSalePeriod,
) -> TicketSalePeriod | None:
    for period in periods:
        if not (period.start_at or period.deadline_at):
            continue
        if period.sale_type != price_only.sale_type:
            continue
        if period.ticket_tier == price_only.ticket_tier or (
            period.ticket_name and price_only.ticket_name and period.ticket_name == price_only.ticket_name
        ):
            return period
    return None


def _lines(text: str) -> list[str]:
    return [normalize_spaces(line) for line in text.splitlines() if line.strip()]


def _clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _URL_RE.sub("", value)
    cleaned = re.sub(r"[#＃][^\s]+", "", cleaned)
    cleaned = cleaned.strip(" \t　:：-/／|｜📍🎫⏰🗓️")
    cleaned = normalize_spaces(cleaned)
    return cleaned or None


def _title_from_header_block(text: str) -> str | None:
    candidates: list[tuple[int, str]] = []
    for index, line in enumerate(_lines(text)):
        cleaned = _clean_value(line)
        if not cleaned:
            continue
        if _is_structured_field_line(cleaned):
            break
        if _is_decorative_line(cleaned) or _is_ignored_title_line(cleaned) or _is_metadata_line(cleaned):
            continue
        if len(cleaned) > 80:
            continue
        score = _title_candidate_score(cleaned, index)
        if score > 0:
            candidates.append((score, cleaned))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _title_candidate_score(value: str, index: int) -> int:
    normalized = _normalize(value)
    compact = normalized.casefold()
    if not _has_title_signal(normalized):
        return 0
    score = 20
    if any(word in compact for word in ("presents", "supported by", "presented by")):
        score -= 18
    if "live digest" in compact:
        score -= 25
    if any(word in compact for word in ("next live", "今日のmyojou", "明日のmyojou", "生配信決定", "御礼")):
        score -= 20
    if any(word in normalized for word in ("LIVE", "Live", "ライブ", "公演", "FES", "フェス", "festival")):
        score += 6
    if re.search(r"[ぁ-んァ-ン一-龯々〆ヶ]", normalized):
        score += 5
    if re.fullmatch(r"[A-Z0-9 &._'\"!?\-]+", normalized):
        score += 4
    score -= min(index, 8)
    return score


def _has_title_signal(value: str) -> bool:
    return bool(re.search(r"[A-Za-z0-9ぁ-んァ-ン一-龯々〆ヶ]", value))


def _is_decorative_line(value: str) -> bool:
    normalized = _normalize(value)
    compact = re.sub(r"\s+", "", normalized)
    if not compact:
        return True
    signal_chars = re.findall(r"[A-Za-z0-9ぁ-んァ-ン一-龯々〆ヶ]", compact)
    if not signal_chars:
        return True
    decorative_removed = re.sub(r"[•┈✮✯⟡☆★◇◆■□／/＼\\|｜\-_=~―ー─━<>〈〉《》【】\[\]().·*:+]+", "", compact)
    return not decorative_removed


def _is_ignored_title_line(value: str) -> bool:
    compact = _normalize(value).casefold()
    return any(
        phrase in compact
        for phrase in (
            "live digest",
            "next live",
            "今日のmyojou",
            "明日のmyojou",
            "the encore presents",
            "presents",
            "supported by",
            "presented by",
            "生配信決定",
            "御礼",
            "sold out",
        )
    )


def _is_structured_field_line(value: str) -> bool:
    normalized = _normalize(value)
    compact = normalized.casefold().lstrip("⟣▶︎▷・- ")
    if _is_metadata_line(compact):
        return True
    if normalize_time_range(normalized) and re.match(r"^[🎙📸⏰]", normalized):
        return True
    return bool(
        re.match(
            r"^(?:date|day|place|venue|open/start|open|start|price|ticket|url|link|"
            r"日付|場所|会場|開場|開演|料金|入場料|特典会|出演時間|"
            r"一般販売|一般発売|抽選受付|抽選販売|抽選申込|先行抽選|先着販売|先着受付|"
            r"受付開始|受付締切|販売開始|販売終了|申込開始|申込締切|当落発表|支払期限|入金期限)",
            compact,
            flags=re.I,
        )
    )


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
            "date",
            "day",
            "place",
            "venue",
            "price",
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
