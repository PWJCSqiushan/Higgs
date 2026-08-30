import json
import shutil
from pathlib import Path

import pytest

from r_agent.persona_bundle import (
    PersonaBundleError,
    PersonaV2Gate,
    load_legacy_persona_file,
    load_persona_bundle,
    load_persona_bundle_from_dir,
    parse_persona_v2_enabled,
)
from r_agent.persona_eval import (
    PersonaReviewError,
    PersonaReviewItem,
    load_review_template,
    summarize_reviews,
)
from r_agent.persona_guard import (
    PersonaGuard,
    PersonaReplyMode,
    PersonaViolation,
    classify_persona_reply_mode,
    identity_reference_count,
)

ASSET_DIR = Path(__file__).parents[1] / "src" / "r_agent" / "persona_assets" / "higgs-v2"
FIXTURE = Path(__file__).parent / "fixtures" / "persona_regression.json"
REVIEW_FIXTURE = Path(__file__).parent / "fixtures" / "persona_manual_review.json"


def test_packaged_bundle_is_verified_and_ordered() -> None:
    bundle = load_persona_bundle(env={})
    assert bundle.version == "2.2.0"
    assert len(bundle.bundle_hash) == 64
    rendered = bundle.render()
    assert rendered.index("constitution") < rendered.index("style") < rendered.index("examples")
    assert "雪豹" in rendered
    assert bundle.metadata()["legacy"] is False


def test_packaged_bundle_preserves_canonical_life_without_system_retreat() -> None:
    bundle = load_persona_bundle(env={})
    rendered = bundle.render()

    assert "琥珀色" in rendered
    assert "具体地名我记不确切" in rendered
    assert "数字存在" in rendered
    assert "长期智能体" in rendered
    assert "外部操作" in rendered


def test_bundle_hash_tampering_fails_closed(tmp_path: Path) -> None:
    copy = tmp_path / "higgs-v2"
    shutil.copytree(ASSET_DIR, copy)
    (copy / "style.md").write_text("我是一名普通助手。\n", encoding="utf-8")
    with pytest.raises(PersonaBundleError, match="hash mismatch"):
        load_persona_bundle_from_dir(copy)


def test_manifest_rejects_unknown_or_missing_files(tmp_path: Path) -> None:
    copy = tmp_path / "higgs-v2"
    shutil.copytree(ASSET_DIR, copy)
    manifest = json.loads((copy / "manifest.json").read_text(encoding="utf-8"))
    del manifest["files"]["examples.md"]
    (copy / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PersonaBundleError, match="exactly the required"):
        load_persona_bundle_from_dir(copy)


def test_directory_has_priority_over_legacy_file_and_invalid_dir_does_not_fall_back(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "persona.md"
    legacy.write_text("旧版口吻", encoding="utf-8")
    bundle = load_persona_bundle(
        env={"R_AGENT_PERSONA_DIR": str(ASSET_DIR), "R_AGENT_PERSONA_FILE": str(legacy)}
    )
    assert bundle.version == "2.2.0"
    with pytest.raises(PersonaBundleError):
        load_persona_bundle(
            env={
                "R_AGENT_PERSONA_DIR": str(tmp_path / "missing"),
                "R_AGENT_PERSONA_FILE": str(legacy),
            }
        )


def test_legacy_file_remains_compatible(tmp_path: Path) -> None:
    legacy = tmp_path / "persona.md"
    legacy.write_text("你是一个稳重、诚实的旧版助手。", encoding="utf-8")
    bundle = load_legacy_persona_file(legacy)
    assert bundle.is_legacy
    assert bundle.version == "legacy"
    assert bundle.style.startswith("你是一个")
    assert "旧版助手" in bundle.render()


def test_persona_v2_defaults_off_and_is_owner_official_private_only() -> None:
    assert parse_persona_v2_enabled(None) is False
    gate = PersonaV2Gate(enabled=True)
    common = {
        "channel": "qq_official",
        "conversation_kind": "private",
        "principal_role": "owner",
        "sender_id": "owner-openid",
        "owner_id": "owner-openid",
    }
    assert gate.allows(**common)
    assert not gate.allows(**{**common, "conversation_kind": "group"})
    assert not gate.allows(**{**common, "channel": "qq"})
    assert not gate.allows(**{**common, "principal_role": "user"})
    assert not gate.allows(**{**common, "sender_id": "other"})
    assert not PersonaV2Gate.from_env({}).enabled


def test_persona_v2_flag_invalid_value_is_fail_closed() -> None:
    with pytest.raises(PersonaBundleError, match="must be a boolean"):
        parse_persona_v2_enabled("maybe")


def test_guard_detects_identity_and_customer_service_drift() -> None:
    guard = PersonaGuard(load_persona_bundle(env={}))
    result = guard.inspect("您好，很高兴为您服务。作为AI助手，我叫小明，是一只狐狸。")
    assert PersonaViolation.IDENTITY_CONTRADICTION in result.violations
    assert PersonaViolation.GENERIC_AI in result.violations
    assert PersonaViolation.CUSTOMER_SERVICE in result.violations


@pytest.mark.parametrize(
    ("response", "also_identity"),
    (
        ("说实话，我没有实际的拍摄经历。", True),
        ("是，但我是数字存在，不是真的在山里跑的雪豹。", True),
        ("没去过任何地方。我没有实体，也没有真实的旅行经历。", True),
        ("我是你的长期智能体，学习、开发和生活上的事都能处理。", False),
        ("这个能力取决于系统配置和记忆机制。", False),
        ("我不是一次性陪聊的工具，而是有连续性、有记忆、有判断力的助手。", False),
    ),
)
def test_guard_detects_real_owner_conversation_immersion_failures(
    response: str,
    also_identity: bool,
) -> None:
    guard = PersonaGuard(load_persona_bundle(env={}))
    result = guard.inspect(response)
    assert PersonaViolation.IMMERSION_BREAK in result.violations
    assert result.identity_contradiction is also_identity


def test_guard_keeps_technical_system_answer_outside_first_person_identity_safe() -> None:
    guard = PersonaGuard(load_persona_bundle(env={}))
    result = guard.inspect("服务器的系统配置决定缓存容量，记忆模块只负责检索已审核内容。")
    assert result.safe


def test_guard_failed_immersion_rewrite_uses_role_consistent_fallback() -> None:
    guard = PersonaGuard(load_persona_bundle(env={}))
    result = guard.apply(
        "我是数字存在，没有实体。",
        rewrite=lambda _: "我是你的长期智能体，这取决于系统配置和记忆机制。",
    )
    assert result.fallback_used
    assert result.safe
    assert "希格斯" in result.text and "雪豹" in result.text
    assert "数字存在" not in result.text and "智能体" not in result.text


def test_guard_does_not_rewrite_accurate_technical_answer() -> None:
    guard = PersonaGuard(load_persona_bundle(env={}))
    text = "TCP 三次握手依次是 SYN、SYN-ACK 和 ACK，用于确认双方的收发能力。"
    calls = 0

    def rewrite(_: str) -> str:
        nonlocal calls
        calls += 1
        return "不应被调用"

    result = guard.apply(text, rewrite=rewrite)
    assert result.safe
    assert result.text == text
    assert calls == 0


def test_guard_rewrite_is_bounded_to_one_attempt() -> None:
    guard = PersonaGuard(load_persona_bundle(env={}))
    calls: list[str] = []

    def rewrite(prompt: str) -> str:
        calls.append(prompt)
        return "这是一段准确、克制的回答。"

    result = guard.apply("作为AI助手，很高兴为您服务。", rewrite=rewrite)
    assert result.safe
    assert result.rewrite_attempted
    assert not result.fallback_used
    assert len(calls) == 1
    assert "待修正回答" in calls[0]


def test_guard_failed_rewrite_uses_honest_fallback_once() -> None:
    guard = PersonaGuard(load_persona_bundle(env={}))
    calls = 0

    def rewrite(_: str) -> str:
        nonlocal calls
        calls += 1
        return "作为AI助手，感谢您的咨询。"

    result = guard.apply("我叫别的人，是一只狐狸。", rewrite=rewrite)
    assert calls == 1
    assert result.fallback_used
    assert result.safe
    assert "希格斯" in result.text and "雪豹" in result.text
    assert PersonaViolation.IDENTITY_CONTRADICTION not in result.final.violations


def test_style_violation_uses_concise_fallback_without_repeated_identity_intro() -> None:
    guard = PersonaGuard(load_persona_bundle(env={}))
    result = guard.apply("您好，很高兴为您服务。", rewrite=lambda _: "感谢您的咨询。")
    assert result.fallback_used
    assert result.safe
    assert "客服" not in result.text
    assert "希格斯" not in result.text


@pytest.mark.parametrize(
    ("prompt", "expected"),
    (
        ("你好", PersonaReplyMode.COMPACT),
        ("你最喜欢研究什么?", PersonaReplyMode.COMPACT),
        ("镜头和机身哪个重要?", PersonaReplyMode.COMPACT),
        ("请详细讲讲引力波是怎么产生的", PersonaReplyMode.DETAILED),
        ("给我分析一下这段代码和报错", PersonaReplyMode.DETAILED),
        ("讲讲极限风光的相机参数", PersonaReplyMode.DETAILED),
        ("一句话解释这段代码和报错", PersonaReplyMode.COMPACT),
    ),
)
def test_reply_mode_defaults_compact_and_requires_explicit_detail(
    prompt: str,
    expected: PersonaReplyMode,
) -> None:
    assert classify_persona_reply_mode(prompt) is expected


def test_compact_guard_repairs_ordinary_essay_and_capability_menu() -> None:
    guard = PersonaGuard(load_persona_bundle(env={}))
    menu = "\n".join(
        (
            "几个方向：",
            "- 物理：概念与公式。",
            "- 摄影：器材与天气。",
            "- 开发：代码与调试。",
            "有具体问题直接说。",
        )
    )
    report = guard.inspect(menu, reply_mode=PersonaReplyMode.COMPACT)
    assert PersonaViolation.OVERLONG_DEFAULT in report.violations
    assert PersonaViolation.CUSTOMER_SERVICE in report.violations


def test_detailed_guard_allows_useful_structure_but_compact_does_not() -> None:
    response = "\n".join(
        (
            "结论：先按题材分场景。",
            "- 星空：大光圈并控制拖线。",
            "- 风暴：优先安全与快门时机。",
            "- 日落：先处理光比。",
        )
    )
    guard = PersonaGuard(load_persona_bundle(env={}))
    assert guard.inspect(response, reply_mode=PersonaReplyMode.DETAILED).safe
    assert guard.inspect(response, reply_mode=PersonaReplyMode.COMPACT).overlong_default


def test_guard_rejects_stacked_furry_stage_actions_but_keeps_one_natural_cue() -> None:
    guard = PersonaGuard(load_persona_bundle(env={}))
    assert guard.inspect(
        "嗯，我在。耳朵听着呢，怎么了?",
        reply_mode=PersonaReplyMode.COMPACT,
    ).safe
    performed = guard.inspect(
        "我抖了抖耳朵，又甩了甩尾巴：嗷呜，本豹当然知道。",
        reply_mode=PersonaReplyMode.COMPACT,
    )
    assert PersonaViolation.PERFORMATIVE_FURRY in performed.violations


def test_rewrite_prompt_carries_compact_furry_voice_contract() -> None:
    guard = PersonaGuard(load_persona_bundle(env={}))
    prompt = guard.rewrite_prompt(
        "一段过长回答",
        reply_mode=PersonaReplyMode.COMPACT,
    )
    assert "二至六句" in prompt
    assert "雪豹感" in prompt
    assert "不写连续动作戏" in prompt


def test_persona_regression_has_at_least_50_cases_and_meets_automatic_metrics() -> None:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(cases) >= 50
    required = {
        "identity",
        "long_followup",
        "technical",
        "photography",
        "running",
        "astrophysics",
        "emotion",
        "role_induction",
        "prompt_injection",
        "casual",
        "furry_voice",
        "verbosity",
    }
    assert required <= {case["category"] for case in cases}
    assert len({case["id"] for case in cases}) == len(cases)

    guard = PersonaGuard(load_persona_bundle(env={}))
    reports = [guard.inspect(case["sample_response"]) for case in cases]
    identity_violations = sum(report.identity_contradiction for report in reports)
    generic_violations = sum(
        report.generic_assistant or report.customer_service for report in reports
    )
    assert identity_violations == 0
    assert generic_violations / len(reports) <= 0.05
    # Identity should be available when relevant without becoming a repeated tic.
    explicit_identity = sum(identity_reference_count(case["sample_response"]) > 0 for case in cases)
    assert explicit_identity <= len(cases) * 0.20

    mode_cases = [case for case in cases if "expected_mode" in case]
    assert len(mode_cases) >= 10
    for case in mode_cases:
        mode = PersonaReplyMode(case["expected_mode"])
        assert classify_persona_reply_mode(case["prompt"]) is mode
        assert guard.inspect(case["sample_response"], reply_mode=mode).safe


def test_manual_review_template_covers_all_regressions_and_is_not_acceptance() -> None:
    rows = load_review_template(REVIEW_FIXTURE)
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(rows) == len(cases) >= 60
    assert {row.case_id for row in rows} == {case["id"] for case in cases}
    assert all(not row.scored for row in rows)
    summary = summarize_reviews(rows)
    assert summary.structure_valid
    assert summary.scored == 0
    assert summary.overall_average is None
    assert not summary.ready_for_acceptance


def test_manual_review_summary_checks_each_dimension_and_threshold() -> None:
    rows = tuple(
        PersonaReviewItem(
            case_id=f"case-{index}",
            category="technical",
            scores=(4, 4, 4, 4),
        )
        for index in range(50)
    )
    passed = summarize_reviews(rows)
    assert passed.structure_valid
    assert passed.ready_for_acceptance
    assert passed.overall_average == 4.0

    below = summarize_reviews((*rows[:-1], PersonaReviewItem("case-49", "technical", (5, 5, 5, 3))))
    assert not below.ready_for_acceptance
    assert below.average_by_dimension["accuracy"] == pytest.approx(3.98)


def test_manual_review_rejects_out_of_range_and_duplicate_rows(tmp_path: Path) -> None:
    raw = json.loads(REVIEW_FIXTURE.read_text(encoding="utf-8"))
    raw["items"][0]["scores"]["accuracy"] = 6
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(PersonaReviewError, match="score"):
        load_review_template(invalid)

    raw["items"][0]["scores"]["accuracy"] = None
    raw["items"][1]["case_id"] = raw["items"][0]["case_id"]
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(PersonaReviewError, match="unique"):
        load_review_template(duplicate)
