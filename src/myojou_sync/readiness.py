from __future__ import annotations

from dataclasses import dataclass
import re

from .models import CanonicalEvent
from .normalization import normalize_text


_PROFILE_MEMBER_NAMES = ("薄倉りな", "栗原ここね", "真希しの", "姫乃るか", "澪奈ゆん", "日陽みう")


@dataclass(frozen=True)
class PublicReadiness:
    public_ready: bool
    reasons: list[str]


def public_readiness(event: CanonicalEvent) -> PublicReadiness:
    reasons: list[str] = []
    event_name = (event.event_name or "").strip()
    combined_text = normalize_text(
        "\n".join(
            value
            for value in (
                event_name,
                event.venue or "",
                event.notes or "",
                event.source_text or "",
                event.source_summary or "",
            )
            if value
        )
    )

    if not event.event_date:
        reasons.append("missing event_date")
    if not event_name:
        reasons.append("missing event_name")

    non_live_reason = _non_live_reason(combined_text)
    if non_live_reason:
        reasons.append(non_live_reason)

    has_ticket_info = bool(
        event.ticket_url
        or event.ticket_sales
        or event.general_ticket_price is not None
        or event.priority_ticket_price is not None
        or event.same_day_ticket_price is not None
        or event.ticket_application_deadline_at
        or event.ticket_application_start_at
    )
    has_time_info = bool(
        event.open_time
        or event.start_time
        or event.myojou_performance_time
        or event.benefit_event_time
    )
    has_public_structure = bool(event.venue or event.ticket_url or event.open_time or event.start_time or has_ticket_info)

    if event.myojou_performance_time and not any((event.event_date, event_name, event.venue)):
        reasons.append("only performance time without event/date/venue context")
    if event.venue is None and not (event.ticket_url or event.open_time or event.start_time or has_ticket_info):
        reasons.append("missing venue and no strong live structure")
    if event.event_date and event_name and not has_public_structure and not has_time_info:
        reasons.append("insufficient live structure")

    reasons = list(dict.fromkeys(reasons))
    return PublicReadiness(public_ready=not reasons, reasons=reasons)


def _non_live_reason(text: str) -> str | None:
    checks = (
        ("profile/member introduction", ("profile01", "profile02", "profile03", "profile04", "profile05", "profile06")),
        ("radio/non-live", ("ラジオ配信", "radio")),
        ("teaser/coming soon", ("comingsoon", "coming soon", "近日公開", "近日解禁", "teaser")),
        ("campaign-like post", ("キャンペーン", "ミョージョーサマーキャンペーン")),
        ("online signing/benefit-detail content", ("ニックネーム", "サイン", "日付", "コメント")),
        ("content/MV-like post", ("アンチコンプリート", "mv", "musicvideo", "ミュージックビデオ")),
        ("content program, not live schedule", ("学力テスト", "直前sp")),
        ("live digest recap", ("livedigest", "live digest")),
        ("thank-you/recap post", ("御礼", "ありがとうございました", "ありがとう")),
    )
    if re.search(r"\bprofile\s*0?[1-9]\b", text, flags=re.I):
        return "profile/member introduction"
    if any(token in text for token in ("プロフィール", "自己紹介", "メンバー紹介", "NAME┊", "NAME｜", "name┊", "name｜")):
        return "profile/member introduction"
    if any(name in text for name in _PROFILE_MEMBER_NAMES) and not any(
        token in text
        for token in ("ライブ", "live", "公演", "出演", "会場", "場所", "開場", "開演", "チケット", "ticket")
    ):
        return "profile/member introduction"
    for reason, tokens in checks:
        if reason == "online signing/benefit-detail content":
            if all(token in text for token in tokens):
                return reason
            continue
        if any(token in text for token in tokens):
            return reason
    return None
