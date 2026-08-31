import sqlite3
from pathlib import Path

import pytest

from r_agent.identity import Principal
from r_agent.memory import (
    MemoryKind,
    MemoryStatus,
    MemoryStore,
    MemoryTransitionError,
)
from r_agent.principal_memory import (
    PersonalMemoryIntent,
    PersonalMemoryMode,
    PersonalMemoryRequest,
    PersonalMemoryService,
)


def _memory(tmp_path: Path, *, v5: bool = True) -> MemoryStore:
    memory = MemoryStore(tmp_path / "memory.sqlite")
    memory.initialize(personal_memory_v5=v5)
    return memory


def _request(
    *,
    message_id: str,
    text: str = "我喜欢清晨跑步",
    intent: PersonalMemoryIntent = PersonalMemoryIntent.EXPLICIT_REMEMBER,
    kind: MemoryKind = MemoryKind.PREFERENCE,
    principal_id: str = "principal-a",
    account_id: str = "official-bot-a",
    channel: str = "qq_official",
    principal_role: str = "user",
    confidence: float = 0.99,
    target_query: str | None = None,
    observation_id: str | None = None,
    **kwargs,
) -> PersonalMemoryRequest:
    return PersonalMemoryRequest(
        intent=intent,
        kind=kind,
        text=text,
        confidence=confidence,
        target_query=target_query,
        principal_id=principal_id,
        principal_role=principal_role,
        source_channel=channel,
        source_account_id=account_id,
        source_message_id=message_id,
        observation_id=observation_id,
        occurred_at_ms=1_767_225_600_000,
        **kwargs,
    )


def _tables(memory: MemoryStore) -> set[str]:
    with sqlite3.connect(memory.path) as conn:
        return {
            str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


def test_v5_is_opt_in_and_independent_from_v4(tmp_path: Path) -> None:
    legacy = _memory(tmp_path / "legacy", v5=False)
    assert "personal_memory_intents" not in _tables(legacy)
    with sqlite3.connect(legacy.path) as conn:
        assert [row[0] for row in conn.execute("SELECT version FROM memory_schema_versions")] == [
            2,
            3,
        ]

    memory = MemoryStore(tmp_path / "direct-v5" / "memory.sqlite")
    memory.initialize(personal_memory_v5=True)
    assert {"personal_memory_intents", "personal_memory_evidence"} <= _tables(memory)
    with sqlite3.connect(memory.path) as conn:
        versions = {
            int(row[0]) for row in conn.execute("SELECT version FROM memory_schema_versions")
        }
    assert {2, 3, 5} <= versions
    assert "self_memory_metadata" not in _tables(memory)


def test_off_is_side_effect_free_even_without_migration(tmp_path: Path) -> None:
    memory = _memory(tmp_path, v5=False)
    service = PersonalMemoryService(memory, mode=PersonalMemoryMode.OFF)
    outcome = service.submit(_request(message_id="off-1"))
    assert outcome.decision == "disabled"
    assert "personal_memory_intents" not in _tables(memory)


def test_shadow_records_intent_without_changing_memory_items(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    service = PersonalMemoryService(memory, mode=PersonalMemoryMode.SHADOW)
    outcome = service.submit(_request(message_id="shadow-1"))
    assert outcome.decision == "shadow"
    assert outcome.item_id is None
    with sqlite3.connect(memory.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM personal_memory_intents").fetchone()[0] == 1


def test_explicit_remember_activates_once_and_replays_idempotently(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    service = PersonalMemoryService(memory, mode=PersonalMemoryMode.ACTIVE)
    request = _request(message_id="explicit-1")
    first = service.submit(request)
    replay = service.submit(request)
    assert first.decision == replay.decision == "activated"
    assert first.item_id == replay.item_id
    assert first.intent_id == replay.intent_id
    assert memory.get(first.item_id or "").status is MemoryStatus.ACTIVE
    with sqlite3.connect(memory.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM personal_memory_evidence").fetchone()[0] == 1


def test_repeated_observation_requires_two_distinct_messages(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    service = PersonalMemoryService(memory, mode=PersonalMemoryMode.ACTIVE)
    first = service.submit(
        _request(
            message_id="repeat-1",
            text="我喜欢在清晨跑步",
            intent=PersonalMemoryIntent.REPEATED_OBSERVATION,
        )
    )
    assert first.decision == "candidate"
    assert memory.get(first.item_id or "").status is MemoryStatus.CANDIDATE

    low = service.submit(
        _request(
            message_id="repeat-low",
            text="我喜欢在清晨跑步",
            intent=PersonalMemoryIntent.REPEATED_OBSERVATION,
            confidence=0.93,
        )
    )
    assert low.decision == "rejected"

    second = service.submit(
        _request(
            message_id="repeat-2",
            text="我喜欢在清晨跑步",
            intent=PersonalMemoryIntent.REPEATED_OBSERVATION,
        )
    )
    assert second.decision == "activated"
    assert second.item_id == first.item_id
    assert memory.get(first.item_id or "").status is MemoryStatus.ACTIVE
    with sqlite3.connect(memory.path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM personal_memory_evidence WHERE item_id=?",
                (first.item_id,),
            ).fetchone()[0]
            == 2
        )


def test_repeated_observation_same_message_is_idempotent_and_collision_rejected(
    tmp_path: Path,
) -> None:
    memory = _memory(tmp_path)
    service = PersonalMemoryService(memory, mode=PersonalMemoryMode.ACTIVE)
    request = _request(
        message_id="repeat-idempotent",
        text="我喜欢安静的清晨",
        intent=PersonalMemoryIntent.REPEATED_OBSERVATION,
    )
    first = service.submit(request)
    replay = service.submit(request)
    assert replay.intent_id == first.intent_id
    assert replay.item_id == first.item_id
    conflict = service.submit(
        _request(
            message_id="repeat-idempotent",
            text="我更喜欢热闹的夜晚",
            intent=PersonalMemoryIntent.REPEATED_OBSERVATION,
        )
    )
    assert conflict.decision == "rejected"
    assert conflict.reason == "idempotency_conflict"


def test_sensitive_and_blocked_content_is_quarantined(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    service = PersonalMemoryService(memory, mode=PersonalMemoryMode.ACTIVE)
    sensitive = service.submit(_request(message_id="secret-1", text="我的密码是abc"))
    assert sensitive.decision == "quarantined"
    blocked = service.submit(
        _request(
            message_id="blocked-1",
            principal_id="blocked-principal",
            text="普通偏好",
            principal_role="blocked",
        )
    )
    assert blocked.decision == "rejected"
    with sqlite3.connect(memory.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0] == 0


def test_correction_is_unique_and_creates_successor(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    service = PersonalMemoryService(memory, mode=PersonalMemoryMode.ACTIVE)
    old = service.submit(_request(message_id="corr-old", text="我喜欢早晨跑步"))
    corrected = service.submit(
        _request(
            message_id="corr-new",
            text="我现在更喜欢晚上跑步",
            intent=PersonalMemoryIntent.CORRECTION,
            target_query="我喜欢早晨跑步",
        )
    )
    assert corrected.decision == "superseded"
    assert corrected.item_id != old.item_id
    assert memory.get(old.item_id or "").status is MemoryStatus.INVALIDATED
    successor = memory.get(corrected.item_id or "")
    assert successor.status is MemoryStatus.ACTIVE
    assert successor.supersedes_item_id == old.item_id


def test_correction_without_target_uses_only_one_current_active_item(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    service = PersonalMemoryService(memory, mode=PersonalMemoryMode.ACTIVE)
    old = service.submit(_request(message_id="natural-old", text="我喜欢长跑"))
    corrected = service.submit(
        _request(
            message_id="natural-new",
            text="我现在更喜欢短跑",
            intent=PersonalMemoryIntent.CORRECTION,
        )
    )
    assert corrected.decision == "superseded"
    assert memory.get(old.item_id or "").status is MemoryStatus.INVALIDATED
    assert memory.get(corrected.item_id or "").supersedes_item_id == old.item_id


def test_owner_uses_governance_path_not_personal_user_lane(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    service = PersonalMemoryService(memory, mode=PersonalMemoryMode.ACTIVE)
    owner = service.submit(
        _request(message_id="owner-1", principal_id="owner", principal_role="owner")
    )
    assert owner.decision == "rejected"
    assert owner.reason == "owner_requires_governance"


def test_correction_no_match_and_ambiguous_are_fail_closed(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    service = PersonalMemoryService(memory, mode=PersonalMemoryMode.ACTIVE)
    no_match = service.submit(
        _request(
            message_id="corr-no-match",
            text="新的偏好",
            intent=PersonalMemoryIntent.CORRECTION,
            target_query="不存在的偏好",
        )
    )
    assert no_match.decision == "no_match"

    service.submit(_request(message_id="amb-1", text="我喜欢摄影"))
    service.submit(_request(message_id="amb-2", text="我喜欢摄影2"))
    # Deliberately create a second active item with identical text using a
    # distinct source account, then switch both records to the same account
    # inside the test database to model legacy duplicate data.
    with sqlite3.connect(memory.path) as conn:
        conn.execute("UPDATE memory_items SET text='我喜欢摄影' WHERE source_message_id='amb-2'")
    ambiguous = service.submit(
        _request(
            message_id="corr-ambiguous",
            text="新的摄影偏好",
            intent=PersonalMemoryIntent.CORRECTION,
            target_query="我喜欢摄影",
        )
    )
    assert ambiguous.decision == "ambiguous"


def test_forget_is_logical_and_no_match_is_safe(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    service = PersonalMemoryService(memory, mode=PersonalMemoryMode.ACTIVE)
    item = service.submit(_request(message_id="forget-old", text="我喜欢胶片摄影"))
    forgotten = service.submit(
        _request(
            message_id="forget-new",
            text="",
            intent=PersonalMemoryIntent.FORGET_REQUEST,
            target_query="我喜欢胶片摄影",
        )
    )
    assert forgotten.decision == "forgotten"
    assert forgotten.item_id == item.item_id
    assert memory.get(item.item_id or "").status is MemoryStatus.INVALIDATED
    with sqlite3.connect(memory.path) as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM memory_items WHERE item_id=?", (item.item_id,)
            ).fetchone()[0]
            == 1
        )
    no_match = service.submit(
        _request(
            message_id="forget-none",
            text="",
            intent=PersonalMemoryIntent.FORGET_REQUEST,
            target_query="不存在",
        )
    )
    assert no_match.decision == "no_match"


def test_restore_cannot_reactivate_predecessor_with_active_successor(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    service = PersonalMemoryService(memory, mode=PersonalMemoryMode.ACTIVE)
    old = service.submit(_request(message_id="restore-old", text="我喜欢山地摄影"))
    new = service.submit(
        _request(
            message_id="restore-new",
            text="我现在更喜欢海边摄影",
            intent=PersonalMemoryIntent.CORRECTION,
            target_query="我喜欢山地摄影",
        )
    )
    assert new.item_id
    with pytest.raises(MemoryTransitionError, match="active successor"):
        memory.restore(old.item_id or "", actor=Principal("owner", "owner"), reason="restore")


def test_cross_account_and_principal_memory_isolation(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    service = PersonalMemoryService(memory, mode=PersonalMemoryMode.ACTIVE)
    a = service.submit(
        _request(message_id="a-1", text="我喜欢茶", principal_id="a", account_id="bot-a")
    )
    b = service.submit(
        _request(message_id="b-1", text="我喜欢茶", principal_id="b", account_id="bot-a")
    )
    c = service.submit(
        _request(message_id="c-1", text="我喜欢茶", principal_id="a", account_id="bot-b")
    )
    assert len({a.item_id, b.item_id, c.item_id}) == 3
    assert all(item_id for item_id in (a.item_id, b.item_id, c.item_id))


def test_target_item_id_is_never_an_authority_token(tmp_path: Path) -> None:
    memory = _memory(tmp_path)
    service = PersonalMemoryService(memory, mode=PersonalMemoryMode.ACTIVE)
    with pytest.raises(Exception, match="target_item_id"):
        service.submit(_request(message_id="bad-target", target_item_id="some-item"))
