from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid", "gclid", "xclid"}
_PRICE_RE = re.compile(r"(?:¥|￥)?\s*(?P<price>\d{1,3}(?:,\d{3})+|\d{3,7})\s*(?:円|yen)?", re.I)
_TIME_RE = re.compile(
    r"(?P<hour>\d{1,2})(?:[:：](?P<minute>\d{2})|時(?P<minute_jp>\d{1,2})?分?)"
)
_DATE_PATTERNS = (
    re.compile(r"(?P<year>20\d{2})[年/\-.](?P<month>\d{1,2})[月/\-.](?P<day>\d{1,2})(?:日)?"),
    re.compile(r"(?<!\d)(?P<month>\d{1,2})月(?P<day>\d{1,2})日?(?!\d)"),
    re.compile(r"(?<!\d)(?P<month>\d{1,2})/(?P<day>\d{1,2})(?!\d)"),
    re.compile(r"(?<!\d)(?P<month>\d{1,2})\.(?P<day>\d{1,2})(?!\d)"),
)


def normalize_spaces(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("\u3000", " ")
    return re.sub(r"[ \t\r\f\v]+", " ", normalized).strip()


def normalize_text(value: str | None) -> str:
    normalized = normalize_spaces(value).casefold()
    return re.sub(r"\s+", "", normalized)


def normalize_event_name(value: str | None) -> str:
    normalized = normalize_text(value)
    normalized = re.sub(r"[#＃【】\[\]『』「」\"'“”’、。.!！?？:：/／・|｜\-ー〜~～]", "", normalized)
    return normalized


def normalize_venue(value: str | None) -> str:
    normalized = normalize_text(value)
    normalized = re.sub(r"[【】\[\]『』「」\"'、。:：/／・|｜\-ー〜~～]", "", normalized)
    return normalized


def normalize_url(value: str | None) -> str:
    if not value:
        return ""
    url = value.strip().rstrip(").,、。")
    parts = urlsplit(url)
    query = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if key not in _TRACKING_KEYS and not key.startswith(_TRACKING_PREFIXES)
    ]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))


def compact_for_compare(value: str | None) -> str:
    return re.sub(r"\W+", "", normalize_text(value))


def normalize_price(value: str | None) -> int | None:
    if not value:
        return None
    normalized = normalize_spaces(value).replace(",", "")
    match = _PRICE_RE.search(normalized)
    if not match:
        return None
    return int(match.group("price").replace(",", ""))


def normalize_time(value: str | None) -> str | None:
    if not value:
        return None
    normalized = normalize_spaces(value)
    match = _TIME_RE.search(normalized)
    if not match:
        return None
    hour = int(match.group("hour"))
    minute = match.group("minute") or match.group("minute_jp") or "00"
    if hour > 29 or int(minute) > 59:
        return None
    return f"{hour:02d}:{int(minute):02d}"


def normalize_time_range(value: str | None) -> str | None:
    if not value:
        return None
    normalized = normalize_spaces(value)
    matches = list(_TIME_RE.finditer(normalized))
    times: list[str] = []
    for match in matches:
        parsed = normalize_time(match.group(0))
        if parsed:
            times.append(parsed)
    if not times:
        return None
    if len(times) >= 2:
        return f"{times[0]}-{times[1]}"
    return times[0]


def parse_event_date(value: str | None, posted_date: date) -> date | None:
    if not value:
        return None
    normalized = normalize_spaces(value)
    for pattern in _DATE_PATTERNS:
        match = pattern.search(normalized)
        if not match:
            continue
        year = int(match.groupdict().get("year") or posted_date.year)
        month = int(match.group("month"))
        day = int(match.group("day"))
        parsed = _safe_date(year, month, day)
        if not parsed:
            continue
        if "year" not in match.groupdict() or not match.groupdict().get("year"):
            return _infer_year(month, day, posted_date)
        return parsed
    return None


def _infer_year(month: int, day: int, posted_date: date) -> date | None:
    candidate = _safe_date(posted_date.year, month, day)
    if candidate is None:
        return None
    if candidate < posted_date - timedelta(days=30):
        return _safe_date(posted_date.year + 1, month, day)
    return candidate


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None
