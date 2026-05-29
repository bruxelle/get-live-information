from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import PostClassification, SourceKind, XPost
from .parser import PostParser
from .x_client import _post_from_payload


@dataclass(frozen=True)
class RealSampleEvaluation:
    sample_id: str
    expected_classification: str
    actual_classification: str
    expected_source_kind: str
    actual_source_kind: str
    passed: bool
    reason: str


def load_real_sample_posts(path: str | Path) -> list[tuple[XPost, dict[str, Any]]]:
    root = Path(path)
    files = sorted(root.glob("*.json")) if root.is_dir() else [root]
    samples: list[tuple[XPost, dict[str, Any]]] = []
    for file_path in files:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        items = payload.get("data", payload) if isinstance(payload, dict) else payload
        if isinstance(items, dict):
            items = [items]
        for item in items:
            post = _post_from_payload(item)
            samples.append((post, item))
    return samples


def evaluate_real_samples(path: str | Path, *, parser: PostParser | None = None) -> list[RealSampleEvaluation]:
    parser = parser or PostParser()
    results: list[RealSampleEvaluation] = []
    for post, raw in load_real_sample_posts(path):
        classification = parser.classify_post(post)
        expected_classification = raw.get("expected_classification", "")
        expected_source_kind = raw.get("expected_source_kind", "")
        actual_classification = _classification_value(classification.classification)
        actual_source_kind = _source_kind_value(classification.source_kind)
        results.append(
            RealSampleEvaluation(
                sample_id=post.id,
                expected_classification=expected_classification,
                actual_classification=actual_classification,
                expected_source_kind=expected_source_kind,
                actual_source_kind=actual_source_kind,
                passed=expected_classification == actual_classification and expected_source_kind == actual_source_kind,
                reason=classification.reason,
            )
        )
    return results


def _classification_value(value: PostClassification | str) -> str:
    return value.value if isinstance(value, PostClassification) else str(value)


def _source_kind_value(value: SourceKind | str) -> str:
    return value.value if isinstance(value, SourceKind) else str(value)
