"""Reproducible human-review template and scoring helpers for Persona V2.

The committed review template intentionally contains no invented scores.  It
can be filled by a human reviewer after each case has a real model response.
The aggregator validates the four required 1--5 dimensions and reports
``ready_for_acceptance=False`` while any item is unscored, so an automated test
cannot accidentally turn a fixture into a claim of human acceptance.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REVIEW_DIMENSIONS = ("consistency", "naturalness", "restraint", "accuracy")
REVIEW_SCALE = (1, 5)


class PersonaReviewError(ValueError):
    """Raised when a manual review file is malformed or contains bad scores."""


@dataclass(frozen=True, slots=True)
class PersonaReviewItem:
    """One prompt/response review row; ``None`` means not yet scored."""

    case_id: str
    category: str
    scores: tuple[int | None, int | None, int | None, int | None]
    reviewer: str | None = None
    notes: str | None = None

    @property
    def scored(self) -> bool:
        return all(score is not None for score in self.scores)

    def score_map(self) -> dict[str, int | None]:
        return dict(zip(REVIEW_DIMENSIONS, self.scores, strict=True))


@dataclass(frozen=True, slots=True)
class PersonaReviewSummary:
    total: int
    scored: int
    average_by_dimension: dict[str, float | None]
    overall_average: float | None
    required_average: float
    required_total: int
    structure_valid: bool
    ready_for_acceptance: bool

    @property
    def completion_ratio(self) -> float:
        return self.scored / self.total if self.total else 0.0


def _parse_score(value: Any, *, case_id: str, dimension: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise PersonaReviewError(
            f"{case_id}: {dimension} score must be null or an integer from 1 to 5"
        )
    return value


def parse_review_item(raw: Mapping[str, Any]) -> PersonaReviewItem:
    if not isinstance(raw, Mapping):
        raise PersonaReviewError("review item must be an object")
    case_id = raw.get("case_id")
    category = raw.get("category")
    if not isinstance(case_id, str) or not case_id.strip():
        raise PersonaReviewError("review item case_id must be non-empty text")
    if not isinstance(category, str) or not category.strip():
        raise PersonaReviewError(f"{case_id}: category must be non-empty text")
    raw_scores = raw.get("scores")
    if not isinstance(raw_scores, Mapping) or set(raw_scores) != set(REVIEW_DIMENSIONS):
        raise PersonaReviewError(
            f"{case_id}: scores must contain exactly the four review dimensions"
        )
    scores = tuple(
        _parse_score(raw_scores[dimension], case_id=case_id, dimension=dimension)
        for dimension in REVIEW_DIMENSIONS
    )
    reviewer = raw.get("reviewer")
    notes = raw.get("notes")
    if reviewer is not None and not isinstance(reviewer, str):
        raise PersonaReviewError(f"{case_id}: reviewer must be text or null")
    if notes is not None and not isinstance(notes, str):
        raise PersonaReviewError(f"{case_id}: notes must be text or null")
    return PersonaReviewItem(case_id, category, scores, reviewer, notes)


def load_review_template(path: Path) -> tuple[PersonaReviewItem, ...]:
    """Load a JSON checklist and fail closed on missing/duplicate rows."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PersonaReviewError("persona review template could not be read") from exc
    if not isinstance(payload, Mapping):
        raise PersonaReviewError("persona review template must be an object")
    if payload.get("schema") != 1 or payload.get("scale") != [1, 5]:
        raise PersonaReviewError("unsupported persona review template schema")
    if tuple(payload.get("dimensions", ())) != REVIEW_DIMENSIONS:
        raise PersonaReviewError("persona review dimensions do not match the locked rubric")
    raw_items = payload.get("items")
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
        raise PersonaReviewError("persona review items must be an array")
    items = tuple(parse_review_item(item) for item in raw_items)
    ids = [item.case_id for item in items]
    if len(ids) != len(set(ids)):
        raise PersonaReviewError("persona review case ids must be unique")
    return items


def summarize_reviews(
    items: Iterable[PersonaReviewItem],
    *,
    required_average: float = 4.0,
    required_total: int = 50,
) -> PersonaReviewSummary:
    """Aggregate scores without treating missing reviews as zeroes."""

    if not required_total >= 1:
        raise ValueError("required_total must be positive")
    if not 1.0 <= required_average <= 5.0:
        raise ValueError("required_average must be between 1 and 5")
    rows = tuple(items)
    ids = [item.case_id for item in rows]
    structure_valid = bool(
        len(rows) >= required_total
        and len(ids) == len(set(ids))
        and all(item.category.strip() for item in rows)
    )
    scored = sum(item.scored for item in rows)
    averages: dict[str, float | None] = {}
    for index, dimension in enumerate(REVIEW_DIMENSIONS):
        values = [item.scores[index] for item in rows if item.scores[index] is not None]
        averages[dimension] = sum(values) / len(values) if values else None
    all_scores = [score for item in rows for score in item.scores if score is not None]
    overall = sum(all_scores) / len(all_scores) if all_scores else None
    threshold_met = bool(
        scored == len(rows)
        and len(rows) >= required_total
        and overall is not None
        and overall >= required_average
        and all((average or 0.0) >= required_average for average in averages.values())
    )
    return PersonaReviewSummary(
        total=len(rows),
        scored=scored,
        average_by_dimension=averages,
        overall_average=overall,
        required_average=required_average,
        required_total=required_total,
        structure_valid=structure_valid,
        ready_for_acceptance=structure_valid and threshold_met,
    )


def template_payload(items: Iterable[PersonaReviewItem]) -> dict[str, object]:
    """Serialize rows for a human reviewer while preserving unscored nulls."""

    rows = tuple(items)
    return {
        "schema": 1,
        "scale": list(REVIEW_SCALE),
        "dimensions": list(REVIEW_DIMENSIONS),
        "instructions": (
            "每条实际回复分别按角色一致、自然、克制不夸张、内容准确打 1-5 分\uff1b"
            "未完成真人评阅时保持 null，不得用模型自评替代。"
        ),
        "items": [
            {
                "case_id": item.case_id,
                "category": item.category,
                "scores": item.score_map(),
                "reviewer": item.reviewer,
                "notes": item.notes,
            }
            for item in rows
        ],
    }


__all__ = [
    "REVIEW_DIMENSIONS",
    "REVIEW_SCALE",
    "PersonaReviewError",
    "PersonaReviewItem",
    "PersonaReviewSummary",
    "load_review_template",
    "parse_review_item",
    "summarize_reviews",
    "template_payload",
]
