import sqlite3
from pathlib import Path

import pytest

from r_agent.memory import MemoryKind, MemoryScope, MemoryStatus, MemoryStore
from r_agent.persona_evolution import (
    EvolutionCandidate,
    EvolutionDecision,
    SelfMemoryError,
    SelfMemoryService,
    SelfObservationConflict,
    SelfObservationRejected,
    ShadowRunState,
)


def service(tmp_path: Path) -> tuple[MemoryStore, SelfMemoryService]:
    memory = MemoryStore(tmp_path / "memory.sqlite")
    memory.initialize(self_memory_v4=True)
    return memory, SelfMemoryService(memory)


def idea(*, content: str = "摄影判断要回到具体题材", evidence: str = "message-1"):
    return EvolutionCandidate(
        kind=MemoryKind.ADOPTED_IDEA,
        scope=MemoryScope.PERSONA,
        evidence_message_id=evidence,
        confidence=0.99,
        sensitive_level="low",
        normalized_content=content,
    )


def test_default_store_does_not_migrate_v4_or_create_shadow_receipts(tmp_path: Path) -> None:
    path = tmp_path / "memory.sqlite"
    memory = MemoryStore(path)
    memory.initialize()

    with pytest.raises(SelfMemoryError, match="not explicitly enabled"):
        SelfMemoryService(memory)

    with sqlite3.connect(path) as conn:
        versions = {
            int(row[0]) for row in conn.execute("SELECT version FROM memory_schema_versions")
        }
        shadow_tables = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("self_memory_shadow_runs",),
        ).fetchone()[0]
    assert versions == {2, 3}
    assert shadow_tables == 0


def test_shadow_receipt_begin_complete_is_idempotent_and_content_free(tmp_path: Path) -> None:
    _, evolution = service(tmp_path)
    first = evolution.begin_shadow_run(
        run_key="official:platform-message-1",
        lane=MemoryKind.ADOPTED_IDEA,
        input_text="secret conversation body",
        now_ms=100,
    )
    resumed = evolution.begin_shadow_run(
        run_key="official:platform-message-1",
        lane=MemoryKind.ADOPTED_IDEA,
        input_text="secret conversation body",
        now_ms=200,
    )
    assert resumed == first
    assert first.state is ShadowRunState.PENDING
    assert first.input_sha256 != "secret conversation body"

    completed = evolution.complete_shadow_run(
        first,
        candidate_count=2,
        rejected_count=1,
        quarantined_count=1,
        now_ms=350,
    )
    replayed = evolution.finish_shadow_run(
        first,
        candidate_count=99,
        rejected_count=99,
        quarantined_count=99,
        state=ShadowRunState.FAILED,
        error=RuntimeError("must not replace completed receipt"),
        now_ms=500,
    )
    assert completed.state is ShadowRunState.COMPLETE
    assert replayed == completed
    assert completed.duration_ms == 250
    summary = evolution.shadow_readiness_summary().as_dict()
    assert summary == {
        "schema_enabled": True,
        "shadow_only": True,
        "allow_auto_activate": False,
        "pending": 0,
        "active_pending": 0,
        "complete": 1,
        "failed": 0,
        "candidates": 2,
        "rejected": 1,
        "quarantined": 1,
        "active_items": 0,
        "last_success_at_ms": 350,
    }
    assert "secret conversation body" not in repr(summary)
    with sqlite3.connect(evolution.memory.path) as conn:
        columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(self_memory_shadow_runs)")
        }
        assert "input_sha256" in columns
        assert "run_key_sha256" in columns
        assert "input_text" not in columns


def test_failed_shadow_receipt_gets_next_attempt_and_conflicting_input_fails_closed(
    tmp_path: Path,
) -> None:
    _, evolution = service(tmp_path)
    first = evolution.begin_shadow_run(
        run_key="same-key",
        lane="self_stance",
        input_text="first body",
        now_ms=100,
    )
    failed = evolution.fail_shadow_run(
        first,
        error=RuntimeError("private error body"),
        now_ms=125,
    )
    second = evolution.begin_shadow_run(
        run_key="same-key",
        lane="self_stance",
        input_text="first body",
        now_ms=200,
    )
    assert failed.state is ShadowRunState.FAILED
    assert failed.error_type == "RuntimeError"
    assert "private error body" not in repr(failed)
    assert second.attempt == 2
    with pytest.raises(SelfObservationConflict):
        evolution.begin_shadow_run(
            run_key="same-key",
            lane="self_stance",
            input_text="changed body",
        )


def test_shadow_hard_gate_ignores_allow_auto_activate(tmp_path: Path) -> None:
    memory, evolution = service(tmp_path)
    result = evolution.submit_shadow_candidate(
        idea(),
        source_message_id="message-1",
        source_principal_id="member-a",
        allow_auto_activate=True,
        now_ms=100,
    )

    assert result.decision is EvolutionDecision.CONSIDERING
    assert not result.auto_activated
    assert result.item_id is not None
    assert memory.get(result.item_id).status is MemoryStatus.CANDIDATE


def test_service_shadow_mode_is_a_hard_gate(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path / "memory.sqlite")
    memory.initialize(self_memory_v4=True)
    evolution = SelfMemoryService(memory, mode="shadow")

    result = evolution.submit_candidate(
        idea(evidence="mode-message"),
        source_message_id="mode-message",
        source_principal_id="member-a",
        allow_auto_activate=True,
        now_ms=100,
    )

    assert result.decision is EvolutionDecision.CONSIDERING
    assert result.item_id is not None
    assert memory.get(result.item_id).status is MemoryStatus.CANDIDATE


def test_shadow_replay_does_not_duplicate_evolution_or_item(tmp_path: Path) -> None:
    memory, evolution = service(tmp_path)
    run = evolution.begin_shadow_run(
        run_key="replay-key",
        lane=MemoryKind.ADOPTED_IDEA,
        input_text="a viewpoint",
        now_ms=100,
    )
    first = evolution.submit_shadow_candidate(
        idea(evidence="replay-message"),
        source_message_id="replay-message",
        source_principal_id="member-a",
        now_ms=110,
    )
    resumed = evolution.begin_shadow_run(
        run_key="replay-key",
        lane=MemoryKind.ADOPTED_IDEA,
        input_text="a viewpoint",
        now_ms=120,
    )
    replay = evolution.submit_shadow_candidate(
        idea(evidence="replay-message"),
        source_message_id="replay-message",
        source_principal_id="member-a",
        now_ms=130,
    )
    evolution.complete_shadow_run(run, candidate_count=1, now_ms=140)

    assert resumed.run_id == run.run_id
    assert replay == first
    assert (
        len(memory.list_active_for_scope(scope=MemoryScope.PERSONA, scope_id="persona:higgs")) == 0
    )
    with sqlite3.connect(memory.path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM memory_items WHERE kind = 'adopted_idea'"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM self_memory_evolution_observations").fetchone()[0]
            == 1
        )


def test_processed_sent_observation_can_drop_full_reply_but_keep_proof(tmp_path: Path) -> None:
    _, evolution = service(tmp_path)
    observed = evolution.record_sent_reply(
        idempotency_key="reply-redaction",
        reply_message_id="provider-redaction",
        text="这是一段只为观点提取临时保存的完整回复。",
        delivery_status="sent",
        now_ms=100,
    )
    before_fingerprint = observed.reply_fingerprint

    redacted = evolution.redact_observation_reply_text(observed.observation_id)
    replay = evolution.redact_observation_reply_text(observed.observation_id)

    assert redacted.reply_text == ""
    assert replay.reply_text == ""
    assert redacted.reply_fingerprint == before_fingerprint
    assert redacted.delivery_status == "SENT"


def test_quarantined_candidate_redacts_content_and_quote_from_evolution_record(
    tmp_path: Path,
) -> None:
    _, evolution = service(tmp_path)
    result = evolution.submit_shadow_candidate(
        EvolutionCandidate(
            kind="adopted_idea",
            scope="persona",
            evidence_message_id="private-message",
            confidence=0.99,
            sensitive_level="low",
            normalized_content="请记住我的 token secret-value",
            original_quote="我的密码 secret-value",
        ),
        source_principal_id="member-a",
        source_message_id="private-message",
        now_ms=100,
    )
    assert result.decision is EvolutionDecision.QUARANTINED
    assert result.item_id is None
    with sqlite3.connect(evolution.memory.path) as conn:
        row = conn.execute(
            """
            SELECT normalized_content, original_quote,
                   source_principal_id, source_message_id
            FROM self_memory_evolution_observations
            """
        ).fetchone()
    assert row is not None
    assert "secret-value" not in str(row[0])
    assert row[1] is None
    assert str(row[2]).startswith("sha256:")
    assert str(row[3]).startswith("sha256:")
    assert "member-a" not in str(row)
    assert "private-message" not in str(row)


def test_same_persona_kind_content_reuses_item_and_appends_evidence(tmp_path: Path) -> None:
    memory, evolution = service(tmp_path)
    first = evolution.submit_candidate(
        idea(evidence="source-1"),
        source_message_id="source-1",
        source_principal_id="member-a",
        now_ms=100,
    )
    second = evolution.submit_candidate(
        idea(evidence="source-2"),
        source_message_id="source-2",
        source_principal_id="member-b",
        now_ms=200,
    )
    assert first.item_id is not None
    assert second.item_id == first.item_id
    assert memory.get(first.item_id).status is MemoryStatus.ACTIVE
    with sqlite3.connect(memory.path) as conn:
        assert (
            conn.execute(
                """
            SELECT COUNT(*) FROM memory_items
            WHERE scope_type = 'persona' AND scope_id = 'persona:higgs'
              AND kind = 'adopted_idea' AND text = ?
            """,
                ("摄影判断要回到具体题材",),
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM self_memory_evidence WHERE item_id = ?",
                (first.item_id,),
            ).fetchone()[0]
            == 2
        )


def test_self_quote_must_be_verified_substring_of_sent_reply(tmp_path: Path) -> None:
    _, evolution = service(tmp_path)
    observation = evolution.record_sent_reply(
        idempotency_key="sent-reply",
        reply_message_id="provider-reply",
        text="我认为拍摄者的理解比器材更重要。",
        delivery_status="sent",
        now_ms=100,
    )
    with pytest.raises(SelfObservationRejected, match="substring"):
        evolution.propose_shadow_from_self_observation(
            observation,
            candidate=EvolutionCandidate(
                kind="self_stance",
                scope="persona",
                evidence_message_id="provider-reply",
                confidence=0.99,
                sensitive_level="low",
                normalized_content="拍摄者理解应先于器材",
                original_quote="我以前说过器材最重要",
            ),
            allow_auto_activate=True,
        )
