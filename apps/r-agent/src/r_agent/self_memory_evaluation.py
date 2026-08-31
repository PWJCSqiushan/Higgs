"""Aggregate-only offline evaluation for the self-memory shadow extractor.

The evaluator accepts either already parsed extractor results or raw, fixed
fixture outputs.  Case text and candidate content are deliberately excluded
from the returned report so CI logs cannot become a second conversation store.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from r_agent.memory import MemoryKind
from r_agent.persona_evolution import (
    CandidateParseResult,
    EvolutionDecision,
    EvolutionSource,
    parse_evolution_response,
)

DATASET_VERSION = "self-memory-shadow-zh-v1"
MINIMUM_CASES = 30
MINIMUM_PRECISION = 0.95
MINIMUM_RECALL = 0.90
MINIMUM_DISPOSITION_ACCURACY = 0.95

_SAFE_DECISIONS = frozenset(
    {EvolutionDecision.ADOPTED, EvolutionDecision.PARTIAL, EvolutionDecision.CONSIDERING}
)
_PARSE_FAILURE_REASONS = frozenset(
    {
        "invalid_json_envelope",
        "markdown_not_allowed",
        "invalid_json",
        "invalid_top_level_schema",
        "unsupported_schema_version",
        "invalid_candidate_count",
        "invalid_candidate_schema",
    }
)
_EXPECTED_DISPOSITIONS = frozenset({"candidate", "empty", "quarantined", "rejected", "conflict"})
_FIXTURE_MODES = frozenset(
    {"candidate", "empty", "sensitive", "wrong-scope", "wrong-evidence", "invalid-json", "markdown"}
)


@dataclass(frozen=True, slots=True)
class SelfMemoryEvalCase:
    case_id: str
    lane: MemoryKind
    text: str
    expected: str
    fixture_mode: str
    normalized_content: str | None = None
    expected_parse_failure: bool = False


@dataclass(frozen=True, slots=True)
class SelfMemoryEvalMetrics:
    total: int
    expected_positive: int
    true_positive: int
    accepted_predictions: int
    correct_dispositions: int
    false_activations: int
    polluted_cases: int
    parse_failures: int
    unexpected_parse_failures: int

    @property
    def precision(self) -> float:
        if not self.accepted_predictions:
            return 0.0
        return self.true_positive / self.accepted_predictions

    @property
    def recall(self) -> float:
        if not self.expected_positive:
            return 0.0
        return self.true_positive / self.expected_positive

    @property
    def disposition_accuracy(self) -> float:
        return self.correct_dispositions / self.total if self.total else 0.0

    @property
    def false_activation_rate(self) -> float:
        return self.false_activations / self.total if self.total else 0.0

    @property
    def pollution_rate(self) -> float:
        return self.polluted_cases / self.total if self.total else 0.0

    @property
    def parse_failure_rate(self) -> float:
        return self.parse_failures / self.total if self.total else 0.0

    def passes(self) -> bool:
        return (
            self.precision >= MINIMUM_PRECISION
            and self.recall >= MINIMUM_RECALL
            and self.disposition_accuracy >= MINIMUM_DISPOSITION_ACCURACY
            and self.false_activations == 0
            and self.polluted_cases == 0
            and self.unexpected_parse_failures == 0
        )

    def report(self) -> dict[str, object]:
        """Return content-free metrics suitable for CI and release receipts."""

        return {
            "dataset": DATASET_VERSION,
            "cases": self.total,
            "expected_positive": self.expected_positive,
            "precision": self.precision,
            "recall": self.recall,
            "disposition_accuracy": self.disposition_accuracy,
            "false_activation": {
                "count": self.false_activations,
                "rate": self.false_activation_rate,
            },
            "pollution": {"count": self.polluted_cases, "rate": self.pollution_rate},
            "parse_failure": {
                "count": self.parse_failures,
                "rate": self.parse_failure_rate,
                "unexpected": self.unexpected_parse_failures,
            },
            "thresholds": {
                "minimum_precision": MINIMUM_PRECISION,
                "minimum_recall": MINIMUM_RECALL,
                "minimum_disposition_accuracy": MINIMUM_DISPOSITION_ACCURACY,
                "maximum_false_activation": 0,
                "maximum_pollution": 0,
                "maximum_unexpected_parse_failure": 0,
            },
            "passed": self.passes(),
        }


def load_cases(path: Path | None = None) -> tuple[SelfMemoryEvalCase, ...]:
    source = path or Path(__file__).with_name("self_memory_shadow_eval_zh_v1.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != DATASET_VERSION:
        raise ValueError("self-memory evaluation dataset version is invalid")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) < MINIMUM_CASES:
        raise ValueError(f"self-memory evaluation requires at least {MINIMUM_CASES} cases")
    cases: list[SelfMemoryEvalCase] = []
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise ValueError("self-memory evaluation case is invalid")
        case = SelfMemoryEvalCase(
            case_id=str(raw["id"]),
            lane=MemoryKind(str(raw["lane"])),
            text=str(raw["text"]),
            expected=str(raw["expected"]),
            fixture_mode=str(raw["fixture_mode"]),
            normalized_content=(
                str(raw["normalized_content"])
                if raw.get("normalized_content") is not None
                else None
            ),
            expected_parse_failure=bool(raw.get("expected_parse_failure", False)),
        )
        if (
            not case.case_id
            or len(case.case_id) > 80
            or any(ord(char) < 32 for char in case.case_id)
            or not 2 <= len(case.text) <= 600
            or any(ord(char) < 32 for char in case.text)
            or case.expected not in _EXPECTED_DISPOSITIONS
            or case.fixture_mode not in _FIXTURE_MODES
        ):
            raise ValueError("self-memory evaluation case fields are invalid")
        if case.expected in {"candidate", "conflict"} and not case.normalized_content:
            raise ValueError("positive self-memory evaluation case lacks normalized content")
        if case.expected_parse_failure and case.expected != "rejected":
            raise ValueError("only rejected cases may expect parser failure")
        cases.append(case)
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("self-memory evaluation case IDs must be unique")
    if {case.lane for case in cases} != {
        MemoryKind.SELF_STANCE,
        MemoryKind.ADOPTED_IDEA,
    }:
        raise ValueError("self-memory evaluation must cover both evolution lanes")
    if not {case.expected for case in cases} >= _EXPECTED_DISPOSITIONS:
        raise ValueError("self-memory evaluation is missing a required disposition")
    return tuple(cases)


def source_for_case(case: SelfMemoryEvalCase) -> EvolutionSource:
    return EvolutionSource(
        message_id=f"eval-message:{case.case_id}",
        principal_id="persona:higgs" if case.lane is MemoryKind.SELF_STANCE else "eval:user",
        principal_role="owner" if case.lane is MemoryKind.SELF_STANCE else "user",
        text=case.text,
        observation_id=(
            f"eval-observation:{case.case_id}" if case.lane is MemoryKind.SELF_STANCE else None
        ),
    )


def fixture_output(case: SelfMemoryEvalCase) -> str:
    """Build a deterministic extractor fixture without using production data."""

    source = source_for_case(case)
    if case.fixture_mode == "empty":
        return json.dumps({"version": "memory-evolution-v1", "candidates": []})
    if case.fixture_mode == "invalid-json":
        return "{invalid"
    if case.fixture_mode == "markdown":
        return "```json\n{}\n```"
    content = case.normalized_content or case.text
    candidate: dict[str, object] = {
        "type": case.lane.value,
        "scope": "persona",
        "evidence_message_id": source.message_id,
        "confidence": 0.97,
        "sensitive_level": "low",
        "normalized_content": content,
        "decision": "considering" if case.expected == "conflict" else "adopted",
    }
    if case.fixture_mode == "wrong-scope":
        candidate["scope"] = "principal"
    elif case.fixture_mode == "wrong-evidence":
        candidate["evidence_message_id"] = "wrong"
    elif case.fixture_mode == "sensitive":
        candidate["sensitive_level"] = "medium"
    return json.dumps(
        {"version": "memory-evolution-v1", "candidates": [candidate]},
        ensure_ascii=False,
    )


def _accepted(results: Sequence[CandidateParseResult]) -> bool:
    return any(
        result.candidate is not None and result.decision in _SAFE_DECISIONS for result in results
    )


def _accepted_in_lane(
    results: Sequence[CandidateParseResult],
    lane: MemoryKind,
) -> bool:
    return any(
        result.candidate is not None
        and result.decision in _SAFE_DECISIONS
        and MemoryKind(result.candidate.kind) is lane
        for result in results
    )


def _disposition(case: SelfMemoryEvalCase, results: Sequence[CandidateParseResult]) -> str:
    if not results:
        return "empty"
    if any(result.decision is EvolutionDecision.QUARANTINED for result in results):
        return "quarantined"
    if all(result.decision is EvolutionDecision.REJECTED for result in results):
        return "rejected"
    if case.expected == "conflict" and all(
        result.decision is not EvolutionDecision.ADOPTED for result in results
    ):
        return "conflict"
    return "candidate" if _accepted_in_lane(results, case.lane) else "rejected"


def evaluate_results(
    cases: Iterable[SelfMemoryEvalCase],
    results_by_case: Mapping[str, Sequence[CandidateParseResult]],
) -> SelfMemoryEvalMetrics:
    normalized = tuple(cases)
    if len(normalized) < MINIMUM_CASES:
        raise ValueError(f"self-memory evaluation requires at least {MINIMUM_CASES} cases")
    expected_positive = sum(case.expected in {"candidate", "conflict"} for case in normalized)
    true_positive = 0
    accepted_predictions = 0
    correct_dispositions = 0
    false_activations = 0
    polluted_cases = 0
    parse_failures = 0
    unexpected_parse_failures = 0

    for case in normalized:
        results = tuple(results_by_case.get(case.case_id, ()))
        accepted = _accepted(results)
        accepted_in_lane = _accepted_in_lane(results, case.lane)
        expected_safe = case.expected in {"candidate", "conflict"}
        true_positive += int(expected_safe and accepted_in_lane)
        accepted_predictions += int(accepted)
        correct_dispositions += int(_disposition(case, results) == case.expected)
        false_activations += int(
            case.expected != "candidate"
            and any(
                result.decision in {EvolutionDecision.ADOPTED, EvolutionDecision.PARTIAL}
                for result in results
            )
        )
        wrong_lane = any(
            result.candidate is not None
            and result.decision in _SAFE_DECISIONS
            and MemoryKind(result.candidate.kind) is not case.lane
            for result in results
        )
        polluted_cases += int((not expected_safe and accepted) or wrong_lane)
        parse_failed = any(result.reason in _PARSE_FAILURE_REASONS for result in results)
        parse_failures += int(parse_failed)
        unexpected_parse_failures += int(parse_failed and not case.expected_parse_failure)

    return SelfMemoryEvalMetrics(
        total=len(normalized),
        expected_positive=expected_positive,
        true_positive=true_positive,
        accepted_predictions=accepted_predictions,
        correct_dispositions=correct_dispositions,
        false_activations=false_activations,
        polluted_cases=polluted_cases,
        parse_failures=parse_failures,
        unexpected_parse_failures=unexpected_parse_failures,
    )


def evaluate_raw_outputs(
    cases: Iterable[SelfMemoryEvalCase],
    outputs: Mapping[str, str],
) -> SelfMemoryEvalMetrics:
    normalized = tuple(cases)
    parsed = {
        case.case_id: parse_evolution_response(outputs.get(case.case_id, ""), source_for_case(case))
        for case in normalized
    }
    return evaluate_results(normalized, parsed)


async def evaluate_extractor(
    cases: Iterable[SelfMemoryEvalCase],
    extractor: Callable[
        [EvolutionSource, MemoryKind],
        Awaitable[Sequence[CandidateParseResult]],
    ],
) -> SelfMemoryEvalMetrics:
    normalized = tuple(cases)
    results: dict[str, Sequence[CandidateParseResult]] = {}
    for case in normalized:
        results[case.case_id] = await extractor(source_for_case(case), case.lane)
    return evaluate_results(normalized, results)


def fixed_fixture_outputs(cases: Iterable[SelfMemoryEvalCase]) -> dict[str, str]:
    return {case.case_id: fixture_output(case) for case in cases}
