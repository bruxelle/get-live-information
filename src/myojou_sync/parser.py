from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta

from .models import ExtractedEvent, SourceKind, XPost
from .normalization import normalize_price, normalize_spaces, normalize_time, normalize_time_range, parse_event_date


LIVE_KEYWORDS = (
    "ライブ",
    "live",
    "出演",
    "公演",
    "イベント",
    "タイムテーブル",
    "特典会",
    "会場",
    "開場",
    "開演",
    "チケット",
    "本日",
    "明日",
)

_URL_RE = re.compile(r"https?://[^\s)）]+")
_TIME_RE = re.compile(r"\d{1,2}(?:[:：]\d{2}|時\d{0,2}分?)")


class PostParser:
    def __init__(self, username: str = "info_myojou") -> None:
        self.username = username

    def parse_post(self, post: XPost) -> ExtractedEvent | None:
        text = post.text
        if not self.is_live_event_post(text):
            return None

        source_kind = self.classify_source_kind(text)
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
        ticket_status = self.extract_ticket_status(text)
        notes = self.extract_notes(text, source_kind)

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
            ticket_status=ticket_status,
            notes=notes,
            source_url=f"https://x.com/{self.username}/status/{post.id}",
            source_post_id=post.id,
            source_posted_at=post.created_at,
            source_text=text,
            source_kind=source_kind,
            extraction_confidence=confidence,
        )

    def is_live_event_post(self, text: str) -> bool:
        normalized = _normalize(text)
        if any(keyword.casefold() in normalized.casefold() for keyword in LIVE_KEYWORDS):
            return True
        return bool(_URL_RE.search(text) and self.extract_event_date(text, datetime.now()) is not None)

    def classify_source_kind(self, text: str) -> SourceKind:
        normalized = _normalize(text).casefold()
        if any(word in normalized for word in ("訂正", "修正", "変更", "お詫び", "誤り")):
            return SourceKind.CORRECTION
        if any(word in normalized for word in ("sold out", "soldout", "完売", "売り切れ", "受付終了")):
            return SourceKind.SOLD_OUT
        if "本日" in normalized:
            return SourceKind.SAME_DAY_REMINDER
        if "明日" in normalized:
            return SourceKind.DAY_BEFORE_REMINDER
        if any(word in normalized for word in ("タイムテーブル", "出演時間", "出番", "tt解禁", "特典会時間")):
            return SourceKind.TIMETABLE_UPDATE
        if any(word in normalized for word in ("ライブ出演", "出演決定", "出演情報", "情報解禁", "公演決定")):
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

    def extract_ticket_status(self, text: str) -> str | None:
        normalized = _normalize(text).casefold()
        if any(word in normalized for word in ("sold out", "soldout", "完売", "売り切れ", "受付終了")):
            return "sold_out"
        if any(word in normalized for word in ("当日券あり", "当日券販売", "当日券ございます")):
            return "same_day_available"
        if any(word in normalized for word in ("受付中", "発売中", "予約受付中", "販売中")):
            return "on_sale"
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
        )
    )

