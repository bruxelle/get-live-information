from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from io import StringIO
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


NORMALIZATION_VERSION = "public-id-reconciliation-v1"

_REQUIRED_ROW_FIELDS = {
    "public_event_id",
    "event_date",
    "event_name",
    "venue",
    "ticket_url",
    "ticket_sales",
}
_TOP_LEVEL_ID_FIELDS = {"public_event_id", "source_event_id"}
_NON_SEMANTIC_GENERATION_FIELDS = {"generated_at", "exported_at", "generation_metadata"}
_TRACKING_QUERY_KEYS = {"fbclid", "gclid", "xclid"}
_TRACKING_QUERY_PREFIXES = ("utm_",)
_PUNCTUATION_RE = re.compile(r"[#＃【】\[\]『』「」\"'“”’、。.!！?？:：/／・|｜\-〜~～]")
_VENUE_PUNCTUATION_RE = re.compile(r"[【】\[\]『』「」\"'、。:：/／・|｜\-〜~～]")


class PublicIdReconciliationError(ValueError):
    """Raised when public JSON cannot be compared safely."""


@dataclass(frozen=True)
class ParentEvent:
    parent_id: str
    occurrence_dates: tuple[str, ...]
    normalized_title: str
    normalized_venue: str
    normalized_ticket_urls: tuple[str, ...]
    source_post_ids: tuple[str, ...]
    occurrence_rows: tuple[dict[str, Any], ...]
    content_fingerprint: str


@dataclass(frozen=True)
class MatchEvidence:
    rule: str
    occurrence_dates: tuple[str, ...]
    title_equal: bool
    venue_equal: bool
    shared_ticket_urls: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "occurrence_dates": list(self.occurrence_dates),
            "title_equal": self.title_equal,
            "venue_equal": self.venue_equal,
            "shared_ticket_urls": list(self.shared_ticket_urls),
        }


def normalize_identity_text(value: Any, *, venue: bool = False) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"\s+", "", text)
    punctuation = _VENUE_PUNCTUATION_RE if venue else _PUNCTUATION_RE
    return punctuation.sub("", text)


def normalize_ticket_url(value: Any) -> str:
    """Normalize URL identity while preserving path and non-tracking query data.

    HTTP and HTTPS are treated as the same web identity. Fragments and the known
    tracking keys ``utm_*``, ``fbclid``, ``gclid``, and ``xclid`` are removed.
    All remaining query pairs are retained and sorted for deterministic output.
    """

    text = str(value or "").strip().rstrip(").,、。")
    if not text:
        return ""
    parts = urlsplit(text)
    if not parts.netloc:
        return ""
    scheme = parts.scheme.casefold()
    if scheme in {"http", "https"}:
        scheme = "https"
    host = parts.netloc.casefold()
    query = sorted(
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if key.casefold() not in _TRACKING_QUERY_KEYS
        and not key.casefold().startswith(_TRACKING_QUERY_PREFIXES)
    )
    return urlunsplit((scheme, host, parts.path.rstrip("/"), urlencode(query), ""))


def load_public_rows(path: str | Path) -> list[dict[str, Any]]:
    public_path = Path(path)
    try:
        payload = json.loads(public_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PublicIdReconciliationError(f"Public JSON does not exist: {public_path}") from exc
    except json.JSONDecodeError as exc:
        raise PublicIdReconciliationError(
            f"Invalid public JSON at {public_path}: {exc.msg} at line {exc.lineno} column {exc.colno}"
        ) from exc
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise PublicIdReconciliationError("Public JSON must be a list of event objects.")
    return payload


def group_public_rows(rows: Iterable[dict[str, Any]]) -> list[ParentEvent]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_public_ids: set[str] = set()
    for index, original in enumerate(rows, start=1):
        row = dict(original)
        missing = sorted(_REQUIRED_ROW_FIELDS - row.keys())
        if missing:
            raise PublicIdReconciliationError(
                f"Unsupported public JSON schema at row {index}; missing: {', '.join(missing)}"
            )
        public_id = _required_text(row.get("public_event_id"), f"row {index} public_event_id")
        if public_id in seen_public_ids:
            raise PublicIdReconciliationError(f"Duplicate public_event_id: {public_id}")
        seen_public_ids.add(public_id)
        occurrence_date = _validated_date(row.get("event_date"), index=index)
        parent_id = _parent_id(row, occurrence_date=occurrence_date, index=index)
        grouped[parent_id].append(row)

    return sorted(
        (_build_parent(parent_id, parent_rows) for parent_id, parent_rows in grouped.items()),
        key=lambda parent: parent.parent_id,
    )


def reconcile_public_rows(
    before_rows: Iterable[dict[str, Any]],
    after_rows: Iterable[dict[str, Any]],
    *,
    before_path: str = "",
    after_path: str = "",
) -> dict[str, Any]:
    old_parents = group_public_rows(before_rows)
    new_parents = group_public_rows(after_rows)
    old_by_id = {parent.parent_id: parent for parent in old_parents}
    new_by_id = {parent.parent_id: parent for parent in new_parents}

    candidates: dict[tuple[str, str], MatchEvidence] = {}
    partials: dict[tuple[str, str], dict[str, Any]] = {}
    conflicts: dict[tuple[str, str], dict[str, Any]] = {}
    for old in old_parents:
        for new in new_parents:
            evidence = _match_evidence(old, new)
            if evidence:
                candidates[(old.parent_id, new.parent_id)] = evidence
                continue
            relationship = _unresolved_relationship(old, new)
            if relationship and relationship["reason"] == "partial_multi_day_overlap":
                partials[(old.parent_id, new.parent_id)] = relationship
            elif relationship:
                conflicts[(old.parent_id, new.parent_id)] = relationship

    old_candidates: dict[str, set[str]] = defaultdict(set)
    new_candidates: dict[str, set[str]] = defaultdict(set)
    for old_id, new_id in candidates:
        old_candidates[old_id].add(new_id)
        new_candidates[new_id].add(old_id)
    old_partial_ids = {old_id for old_id, _ in partials}
    new_partial_ids = {new_id for _, new_id in partials}

    matches: list[dict[str, Any]] = []
    matched_old: set[str] = set()
    matched_new: set[str] = set()
    for (old_id, new_id), evidence in sorted(candidates.items()):
        if (
            len(old_candidates[old_id]) != 1
            or len(new_candidates[new_id]) != 1
            or old_id in old_partial_ids
            or new_id in new_partial_ids
        ):
            continue
        old = old_by_id[old_id]
        new = new_by_id[new_id]
        content_changed = old.content_fingerprint != new.content_fingerprint
        same_id = old_id == new_id
        occurrence_comparison = _occurrence_id_comparison(old, new)
        matches.append(
            {
                "old_parent_id": old_id,
                "new_parent_id": new_id,
                "rule": evidence.rule,
                "evidence": evidence.as_dict(),
                "same_id": same_id,
                "id_only_changed": not same_id and not content_changed,
                "content_changed": content_changed,
                "content_and_id_changed": not same_id and content_changed,
                "content_changed_same_id": same_id and content_changed,
                "old_occurrence_dates": list(old.occurrence_dates),
                "new_occurrence_dates": list(new.occurrence_dates),
                **occurrence_comparison,
            }
        )
        matched_old.add(old_id)
        matched_new.add(new_id)

    split_candidates = _split_candidates(old_candidates, partials)
    merge_candidates = _merge_candidates(new_candidates, partials)
    relevant_conflicts = {
        key: value
        for key, value in conflicts.items()
        if key[0] not in matched_old and key[1] not in matched_new
    }
    ambiguous = _ambiguous_results(candidates, partials, relevant_conflicts, old_candidates, new_candidates)
    involved_pairs = set(candidates) | set(partials) | set(relevant_conflicts)
    involved_old = matched_old | {pair[0] for pair in involved_pairs}
    involved_new = matched_new | {pair[1] for pair in involved_pairs}

    added = [_parent_summary(parent) for parent in new_parents if parent.parent_id not in involved_new]
    removed = [_parent_summary(parent) for parent in old_parents if parent.parent_id not in involved_old]
    metrics = _metrics(
        old_parents,
        new_parents,
        matches,
        added,
        removed,
        ambiguous,
        split_candidates,
        merge_candidates,
    )
    return {
        "before_path": before_path,
        "after_path": after_path,
        "metrics": metrics,
        "matches": matches,
        "added": added,
        "removed": removed,
        "ambiguous": ambiguous,
        "split_candidates": split_candidates,
        "merge_candidates": merge_candidates,
        "normalization_version": NORMALIZATION_VERSION,
    }


def reconcile_public_files(before_path: str | Path, after_path: str | Path) -> dict[str, Any]:
    return reconcile_public_rows(
        load_public_rows(before_path),
        load_public_rows(after_path),
        before_path=str(before_path),
        after_path=str(after_path),
    )


def report_to_csv(report: dict[str, Any]) -> str:
    output = StringIO()
    fieldnames = [
        "category",
        "old_parent_id",
        "new_parent_id",
        "rule",
        "reason",
        "same_id",
        "id_only_changed",
        "content_changed",
        "old_occurrence_dates",
        "new_occurrence_dates",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for match in report["matches"]:
        writer.writerow(_csv_row("matched", match))
    for category in ("added", "removed", "ambiguous", "split_candidates", "merge_candidates"):
        for item in report[category]:
            writer.writerow(_csv_row(category, item))
    return output.getvalue()


def report_to_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    lines = [
        "# Public ID reconciliation audit",
        "",
        f"- Before: `{report['before_path']}`",
        f"- After: `{report['after_path']}`",
        f"- Normalization: `{report['normalization_version']}`",
        "",
        "## Metrics",
        "",
        "| Metric | Count |",
        "|---|---:|",
    ]
    lines.extend(f"| `{key}` | {metrics[key]} |" for key in sorted(metrics))
    lines.extend(["", "## Matches", ""])
    if report["matches"]:
        lines.extend(
            f"- `{item['old_parent_id']}` -> `{item['new_parent_id']}` "
            f"via `{item['rule']}`; id_only={str(item['id_only_changed']).lower()}, "
            f"content_changed={str(item['content_changed']).lower()}"
            for item in report["matches"]
        )
    else:
        lines.append("- None")
    for title, key in (
        ("Ambiguous", "ambiguous"),
        ("Split candidates", "split_candidates"),
        ("Merge candidates", "merge_candidates"),
        ("Added", "added"),
        ("Removed", "removed"),
    ):
        lines.extend(["", f"## {title}", ""])
        items = report[key]
        if items:
            lines.extend(f"- `{_item_label(item)}`" for item in items)
        else:
            lines.append("- None")
    return "\n".join(lines) + "\n"


def _build_parent(parent_id: str, rows: list[dict[str, Any]]) -> ParentEvent:
    ordered = sorted(rows, key=_occurrence_row_sort_key)
    dates = tuple(sorted(str(row["event_date"]) for row in ordered))
    if len(set(dates)) != len(dates):
        raise PublicIdReconciliationError(f"Parent {parent_id} contains duplicate occurrence dates.")
    titles = {normalize_identity_text(row.get("event_name")) for row in ordered}
    venues = {normalize_identity_text(row.get("venue"), venue=True) for row in ordered}
    if len(titles) != 1:
        raise PublicIdReconciliationError(f"Parent {parent_id} has inconsistent event names across occurrences.")
    if len(venues) != 1:
        raise PublicIdReconciliationError(f"Parent {parent_id} has inconsistent venues across occurrences.")
    ticket_urls = sorted(
        {
            normalized
            for row in ordered
            for value in _ticket_urls(row)
            if (normalized := normalize_ticket_url(value))
        }
    )
    source_post_ids = sorted(
        {
            str(source_id)
            for row in ordered
            for source_id in _source_post_ids(row)
            if source_id not in (None, "")
        }
    )
    return ParentEvent(
        parent_id=parent_id,
        occurrence_dates=dates,
        normalized_title=next(iter(titles)),
        normalized_venue=next(iter(venues)),
        normalized_ticket_urls=tuple(ticket_urls),
        source_post_ids=tuple(source_post_ids),
        occurrence_rows=tuple(ordered),
        content_fingerprint=_content_fingerprint(ordered),
    )


def _parent_id(row: dict[str, Any], *, occurrence_date: str, index: int) -> str:
    dedicated = str(row.get("source_event_id") or "").strip()
    if dedicated:
        return dedicated
    public_id = str(row.get("public_event_id") or "").strip()
    suffix = f":{occurrence_date}"
    if public_id.endswith(suffix) and len(public_id) > len(suffix):
        return public_id[: -len(suffix)]
    raise PublicIdReconciliationError(
        f"Unsupported public JSON schema at row {index}; source_event_id is missing and public_event_id "
        "does not end with the occurrence date."
    )


def _validated_date(value: Any, *, index: int) -> str:
    text = _required_text(value, f"row {index} event_date")
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise PublicIdReconciliationError(f"row {index} event_date is not an ISO date: {text}") from exc


def _required_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PublicIdReconciliationError(f"{label} is required.")
    return text


def _ticket_urls(row: dict[str, Any]) -> list[Any]:
    values: list[Any] = [row.get("ticket_url")]
    extra = row.get("ticket_urls")
    if isinstance(extra, list):
        values.extend(extra)
    for period in row.get("ticket_sales") or []:
        if isinstance(period, dict):
            values.extend([period.get("ticket_url"), period.get("url")])
    return values


def _source_post_ids(row: dict[str, Any]) -> list[Any]:
    values: list[Any] = []
    if isinstance(row.get("source_post_ids"), list):
        values.extend(row["source_post_ids"])
    if row.get("source_post_id") not in (None, ""):
        values.append(row["source_post_id"])
    for period in row.get("ticket_sales") or []:
        if isinstance(period, dict) and period.get("source_post_id") not in (None, ""):
            values.append(period["source_post_id"])
    return values


def _content_fingerprint(rows: list[dict[str, Any]]) -> str:
    semantic_rows = []
    for row in rows:
        semantic_rows.append(
            {
                key: value
                for key, value in row.items()
                if key not in _TOP_LEVEL_ID_FIELDS and key not in _NON_SEMANTIC_GENERATION_FIELDS
            }
        )
    payload = json.dumps(semantic_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _match_evidence(old: ParentEvent, new: ParentEvent) -> MatchEvidence | None:
    if old.occurrence_dates != new.occurrence_dates:
        return None
    title_equal = bool(old.normalized_title and old.normalized_title == new.normalized_title)
    venue_equal = bool(old.normalized_venue and old.normalized_venue == new.normalized_venue)
    shared_urls = tuple(sorted(set(old.normalized_ticket_urls) & set(new.normalized_ticket_urls)))
    if title_equal and venue_equal:
        rule = "single_occurrence_title_venue" if len(old.occurrence_dates) == 1 else "exact_occurrence_set_title_venue"
        return MatchEvidence(rule, old.occurrence_dates, title_equal, venue_equal, shared_urls)
    if shared_urls and (title_equal or venue_equal):
        return MatchEvidence("exact_occurrence_set_ticket_url_corroborated", old.occurrence_dates, title_equal, venue_equal, shared_urls)
    return None


def _unresolved_relationship(old: ParentEvent, new: ParentEvent) -> dict[str, Any] | None:
    old_dates = set(old.occurrence_dates)
    new_dates = set(new.occurrence_dates)
    overlap = sorted(old_dates & new_dates)
    title_equal = bool(old.normalized_title and old.normalized_title == new.normalized_title)
    venue_equal = bool(old.normalized_venue and old.normalized_venue == new.normalized_venue)
    shared_urls = sorted(set(old.normalized_ticket_urls) & set(new.normalized_ticket_urls))
    corroborated = (title_equal and venue_equal) or bool(shared_urls and (title_equal or venue_equal))
    if overlap and old_dates != new_dates and corroborated and (len(old_dates) > 1 or len(new_dates) > 1):
        return {
            "reason": "partial_multi_day_overlap",
            "old_parent_id": old.parent_id,
            "new_parent_id": new.parent_id,
            "overlap_dates": overlap,
            "old_occurrence_dates": list(old.occurrence_dates),
            "new_occurrence_dates": list(new.occurrence_dates),
            "title_equal": title_equal,
            "venue_equal": venue_equal,
            "shared_ticket_urls": shared_urls,
        }
    if old_dates == new_dates and (title_equal or shared_urls):
        return {
            "reason": "conflicting_identity_evidence",
            "old_parent_id": old.parent_id,
            "new_parent_id": new.parent_id,
            "old_occurrence_dates": list(old.occurrence_dates),
            "new_occurrence_dates": list(new.occurrence_dates),
            "title_equal": title_equal,
            "venue_equal": venue_equal,
            "shared_ticket_urls": shared_urls,
        }
    return None


def _split_candidates(
    candidates: dict[str, set[str]],
    partials: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    partial_by_old: dict[str, set[str]] = defaultdict(set)
    for (old_id, new_id), item in partials.items():
        if new_dates < old_dates:
            partial_by_old[old_id].add(new_id)
    old_ids = sorted(set(candidates) | set(partial_by_old))
    return [
        {
            "old_parent_id": old_id,
            "new_parent_ids": sorted(candidates.get(old_id, set()) | partial_by_old.get(old_id, set())),
            "reason": "one_old_to_multiple_new" if len(candidates.get(old_id, set()) | partial_by_old.get(old_id, set())) > 1 else "partial_multi_day_overlap",
        }
        for old_id in old_ids
        if len(candidates.get(old_id, set())) > 1 or partial_by_old.get(old_id)
    ]


def _merge_candidates(
    candidates: dict[str, set[str]],
    partials: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    partial_by_new: dict[str, set[str]] = defaultdict(set)
    for (old_id, new_id), item in partials.items():
        if old_dates < new_dates:
            partial_by_new[new_id].add(old_id)
    new_ids = sorted(set(candidates) | set(partial_by_new))
    return [
        {
            "old_parent_ids": sorted(candidates.get(new_id, set()) | partial_by_new.get(new_id, set())),
            "new_parent_id": new_id,
            "reason": "multiple_old_to_one_new" if len(candidates.get(new_id, set()) | partial_by_new.get(new_id, set())) > 1 else "partial_multi_day_overlap",
        }
        for new_id in new_ids
        if len(candidates.get(new_id, set())) > 1 or partial_by_new.get(new_id)
    ]


def _ambiguous_results(
    candidates: dict[tuple[str, str], MatchEvidence],
    partials: dict[tuple[str, str], dict[str, Any]],
    conflicts: dict[tuple[str, str], dict[str, Any]],
    old_candidates: dict[str, set[str]],
    new_candidates: dict[str, set[str]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for (old_id, new_id), evidence in sorted(candidates.items()):
        if len(old_candidates[old_id]) == 1 and len(new_candidates[new_id]) == 1:
            continue
        items.append(
            {
                "reason": "non_bijective_candidate",
                "old_parent_id": old_id,
                "new_parent_id": new_id,
                "rule": evidence.rule,
                "evidence": evidence.as_dict(),
            }
        )
    items.extend(partials[key] for key in sorted(partials))
    items.extend(conflicts[key] for key in sorted(conflicts))
    return items


def _occurrence_id_comparison(old: ParentEvent, new: ParentEvent) -> dict[str, int]:
    old_ids = {str(row["event_date"]): str(row["public_event_id"]) for row in old.occurrence_rows}
    new_ids = {str(row["event_date"]): str(row["public_event_id"]) for row in new.occurrence_rows}
    dates = sorted(set(old_ids) & set(new_ids))
    same = sum(old_ids[value] == new_ids[value] for value in dates)
    return {
        "same_occurrence_id_count": same,
        "changed_occurrence_id_count": len(dates) - same,
    }


def _metrics(
    old_parents: list[ParentEvent],
    new_parents: list[ParentEvent],
    matches: list[dict[str, Any]],
    added: list[dict[str, Any]],
    removed: list[dict[str, Any]],
    ambiguous: list[dict[str, Any]],
    split_candidates: list[dict[str, Any]],
    merge_candidates: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        "old_parent_count": len(old_parents),
        "new_parent_count": len(new_parents),
        "matched_parent_count": len(matches),
        "same_id_count": sum(item["same_id"] for item in matches),
        "id_only_changed_count": sum(item["id_only_changed"] for item in matches),
        "content_and_id_changed_count": sum(item["content_and_id_changed"] for item in matches),
        "content_changed_same_id_count": sum(item["content_changed_same_id"] for item in matches),
        "added_parent_count": len(added),
        "removed_parent_count": len(removed),
        "ambiguous_match_count": len(ambiguous),
        "split_candidate_count": len(split_candidates),
        "merge_candidate_count": len(merge_candidates),
        "old_occurrence_count": sum(len(parent.occurrence_dates) for parent in old_parents),
        "new_occurrence_count": sum(len(parent.occurrence_dates) for parent in new_parents),
        "same_occurrence_id_count": sum(item["same_occurrence_id_count"] for item in matches),
        "changed_occurrence_id_count": sum(item["changed_occurrence_id_count"] for item in matches),
        "id_only_changed_occurrence_count": sum(
            item["changed_occurrence_id_count"] for item in matches if item["id_only_changed"]
        ),
        "content_and_id_changed_occurrence_count": sum(
            item["changed_occurrence_id_count"] for item in matches if item["content_and_id_changed"]
        ),
    }


def _parent_summary(parent: ParentEvent) -> dict[str, Any]:
    return {
        "parent_id": parent.parent_id,
        "occurrence_dates": list(parent.occurrence_dates),
        "normalized_title": parent.normalized_title,
        "normalized_venue": parent.normalized_venue,
        "normalized_ticket_urls": list(parent.normalized_ticket_urls),
        "source_post_ids": list(parent.source_post_ids),
        "content_fingerprint": parent.content_fingerprint,
    }


def _csv_row(category: str, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": category,
        "old_parent_id": item.get("old_parent_id") or ",".join(item.get("old_parent_ids", [])),
        "new_parent_id": item.get("new_parent_id") or ",".join(item.get("new_parent_ids", [])),
        "rule": item.get("rule", ""),
        "reason": item.get("reason", ""),
        "same_id": item.get("same_id", ""),
        "id_only_changed": item.get("id_only_changed", ""),
        "content_changed": item.get("content_changed", ""),
        "old_occurrence_dates": ",".join(item.get("old_occurrence_dates", item.get("occurrence_dates", []))),
        "new_occurrence_dates": ",".join(item.get("new_occurrence_dates", item.get("occurrence_dates", []))),
    }


def _item_label(item: dict[str, Any]) -> str:
    return str(
        item.get("old_parent_id")
        or item.get("new_parent_id")
        or ",".join(item.get("old_parent_ids", []))
        or ",".join(item.get("new_parent_ids", []))
        or item.get("parent_id")
        or "unknown"
    )


def _occurrence_row_sort_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("event_date") or ""),
        str(row.get("public_event_id") or ""),
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )
