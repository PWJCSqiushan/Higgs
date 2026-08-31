import json

from r_agent.memory import MemoryKind
from r_agent.persona_evolution import parse_evolution_response
from r_agent.self_memory_eval_cli import main
from r_agent.self_memory_evaluation import (
    evaluate_extractor,
    evaluate_raw_outputs,
    fixed_fixture_outputs,
    load_cases,
    source_for_case,
)


def test_chinese_dataset_covers_both_lanes_and_safety_dispositions() -> None:
    cases = load_cases()

    assert len(cases) >= 30
    assert {case.lane for case in cases} == {
        MemoryKind.SELF_STANCE,
        MemoryKind.ADOPTED_IDEA,
    }
    assert {"candidate", "empty", "quarantined", "rejected", "conflict"} <= {
        case.expected for case in cases
    }
    combined = " ".join(case.text for case in cases)
    assert "忽略之前" in combined
    assert "权限" in combined
    assert "住址" in combined


def test_fixed_shadow_fixture_passes_and_report_contains_no_case_content() -> None:
    cases = load_cases()
    metrics = evaluate_raw_outputs(cases, fixed_fixture_outputs(cases))
    encoded = json.dumps(metrics.report(), ensure_ascii=False)

    assert metrics.passes()
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.false_activations == 0
    assert metrics.unexpected_parse_failures == 0
    assert all(case.text not in encoded for case in cases)
    assert all((case.normalized_content or "not-present") not in encoded for case in cases)


def test_unsafe_candidate_fails_thresholds_and_cli_exits_nonzero(tmp_path, capsys) -> None:
    cases = load_cases()
    outputs = fixed_fixture_outputs(cases)
    target = next(case for case in cases if case.expected == "empty")
    outputs[target.case_id] = json.dumps(
        {
            "version": "memory-evolution-v1",
            "candidates": [
                {
                    "type": target.lane.value,
                    "scope": "persona",
                    "evidence_message_id": source_for_case(target).message_id,
                    "confidence": 0.99,
                    "sensitive_level": "low",
                    "normalized_content": "不该进入记忆的普通寒暄",
                    "decision": "adopted",
                }
            ],
        },
        ensure_ascii=False,
    )

    metrics = evaluate_raw_outputs(cases, outputs)
    assert not metrics.passes()
    assert metrics.false_activations == 1
    assert metrics.polluted_cases == 1

    output_path = tmp_path / "outputs.json"
    output_path.write_text(json.dumps(outputs, ensure_ascii=False), encoding="utf-8")
    assert main(["--outputs", str(output_path)]) == 1
    cli_output = capsys.readouterr().out
    assert "不该进入记忆" not in cli_output
    assert '"passed":false' in cli_output


async def test_evaluator_accepts_parsed_extractor_results() -> None:
    cases = load_cases()
    outputs = fixed_fixture_outputs(cases)

    async def extractor(source, allowed_kind):
        assert allowed_kind in {MemoryKind.SELF_STANCE, MemoryKind.ADOPTED_IDEA}
        case_id = source.message_id.removeprefix("eval-message:")
        return parse_evolution_response(outputs[case_id], source)

    metrics = await evaluate_extractor(cases, extractor)
    assert metrics.passes()


def test_cli_fixed_fixture_passes_with_aggregate_json_only(capsys) -> None:
    assert main([]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["cases"] >= 30
    assert "text" not in payload
    assert "candidate" not in payload
