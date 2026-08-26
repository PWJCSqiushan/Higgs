import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from r_agent.tool_governance import (
    ToolDecision,
    ToolExecutionResult,
    ToolGovernance,
    ToolReceiptState,
    ToolRequest,
    ToolRequestSource,
    ToolSpec,
    ToolValidationError,
    canonical_parameters,
    normalize_parameters,
    parameter_approval_hash,
)


def make_tool(
    tmp_path: Path,
    handler,
    *,
    timeout_seconds: float = 1.0,
    rate_limit_per_minute: int = 6,
) -> ToolGovernance:
    governance = ToolGovernance(audit_path=tmp_path / "tool-audit.sqlite")
    governance.register(
        ToolSpec(
            name="test_read",
            description="A bounded test reader",
            input_schema={
                "type": "object",
                "required": ["value"],
                "properties": {"value": {"type": "string", "maxLength": 100}},
                "additionalProperties": False,
            },
            enabled=True,
            timeout_seconds=timeout_seconds,
            rate_limit_per_minute=rate_limit_per_minute,
        ),
        handler,
    )
    return governance


def request(
    *,
    value: str = "safe",
    actor_role: str = "owner",
    source: str = ToolRequestSource.OWNER_COMMAND.value,
    idem: str | None = None,
) -> ToolRequest:
    return ToolRequest(
        tool_name="test_read",
        parameters={"value": value},
        actor_role=actor_role,
        actor_id="principal-owner",
        source=source,
        surface="owner_command_private",
        idempotency_key=idem,
    )


def approved(governance: ToolGovernance, item: ToolRequest):
    return governance.decide(item, approved=True, approved_by="principal-owner")


@pytest.mark.asyncio
async def test_default_deny_and_model_shadow_never_call_handler(tmp_path: Path) -> None:
    called: list[dict] = []

    async def handler(parameters):
        called.append(dict(parameters))
        return {"ok": True}

    governance = make_tool(tmp_path, handler)
    item = request()
    denied = await governance.execute(item)
    assert denied.state is ToolReceiptState.DENIED
    assert denied.reason == "default_deny"
    assert called == []

    shadow = request(source=ToolRequestSource.MODEL_SHADOW.value)
    shadow_decision = governance.decide(shadow, approved=True, approved_by="model")
    shadow_receipt = await governance.execute(shadow, decision=shadow_decision)
    assert shadow_receipt.state is ToolReceiptState.DENIED
    assert shadow_receipt.reason == "model_shadow_only"
    assert called == []


@pytest.mark.asyncio
async def test_non_owner_and_unknown_surface_cannot_escalate(tmp_path: Path) -> None:
    called = False

    def handler(parameters):
        nonlocal called
        called = True
        return parameters

    governance = make_tool(tmp_path, handler)
    non_owner = request(actor_role="user")
    decision = governance.decide(non_owner, approved=True, approved_by="user")
    receipt = await governance.execute(non_owner, decision=decision)
    assert receipt.state is ToolReceiptState.DENIED
    assert receipt.reason == "caller_role_not_allowed"
    assert not called

    wrong_surface = ToolRequest(
        tool_name="test_read",
        parameters={"value": "safe"},
        actor_role="owner",
        actor_id="principal-owner",
        source=ToolRequestSource.OWNER_COMMAND.value,
        surface="model_prompt",
    )
    assert governance.decide(wrong_surface, approved=True, approved_by="owner").reason == (
        "surface_not_allowed"
    )


@pytest.mark.asyncio
async def test_caller_built_allowed_decision_is_revalidated(tmp_path: Path) -> None:
    called = False

    def handler(parameters):
        nonlocal called
        called = True
        return parameters

    governance = make_tool(tmp_path, handler)
    item = request()
    forged = ToolDecision(
        request_id=item.request_id,
        tool_name=item.tool_name,
        allowed=True,
        reason="forged",
        parameter_sha256=item.parameter_sha256,
        approved_by="not-the-actor",
    )
    receipt = await governance.execute(item, decision=forged)
    assert receipt.state is ToolReceiptState.DENIED
    assert receipt.reason == "approval_principal_mismatch"
    assert not called


def test_parameter_normalization_and_hash_are_order_stable() -> None:
    left = {"b": ["\uff45\uff58\uff41\uff4d\uff50\uff4c\uff45"], "a": 1}
    right = {"a": 1, "b": ["example"]}
    assert normalize_parameters(left) == normalize_parameters(right)
    assert canonical_parameters(left) == '{"a":1,"b":["example"]}'
    assert parameter_approval_hash("test_read", left) == parameter_approval_hash("test_read", right)
    with pytest.raises(ToolValidationError):
        normalize_parameters({"value": float("nan")})
    with pytest.raises(ToolValidationError):
        normalize_parameters({"__proto__": "injection"})


@pytest.mark.asyncio
async def test_timeout_is_a_terminal_non_success_receipt(tmp_path: Path) -> None:
    called = False

    async def handler(parameters):
        nonlocal called
        called = True
        await asyncio.sleep(0.05)
        return parameters

    governance = make_tool(tmp_path, handler, timeout_seconds=0.01)
    item = request()
    receipt = await governance.execute(item, decision=approved(governance, item))
    assert called
    assert receipt.state is ToolReceiptState.TIMED_OUT
    assert not receipt.successful


@pytest.mark.asyncio
async def test_rate_limit_is_checked_before_handler(tmp_path: Path) -> None:
    calls = 0

    def handler(parameters):
        nonlocal calls
        calls += 1
        return parameters

    governance = make_tool(tmp_path, handler, rate_limit_per_minute=1)
    first = request(idem="first")
    second = request(idem="second")
    assert (await governance.execute(first, decision=approved(governance, first))).successful
    limited = await governance.execute(second, decision=approved(governance, second))
    assert limited.state is ToolReceiptState.RATE_LIMITED
    assert calls == 1


@pytest.mark.asyncio
async def test_restart_keeps_idempotency_and_never_reexecutes(tmp_path: Path) -> None:
    calls = 0

    def handler(parameters):
        nonlocal calls
        calls += 1
        return {"value": parameters["value"]}

    audit_path = tmp_path / "tool-audit.sqlite"
    first_governance = make_tool(tmp_path, handler)
    first = request(idem="stable-id")
    first_receipt = await first_governance.execute(
        first,
        decision=approved(first_governance, first),
    )
    assert first_receipt.successful

    second_governance = make_tool(tmp_path, handler)
    second = request(idem="stable-id")
    duplicate = await second_governance.execute(
        second,
        decision=approved(second_governance, second),
    )
    assert duplicate.state is ToolReceiptState.DUPLICATE
    assert duplicate.prior_state is ToolReceiptState.SUCCEEDED
    assert calls == 1
    with sqlite3.connect(audit_path) as connection:
        rows = connection.execute("SELECT * FROM tool_audit_events").fetchall()
    assert rows
    assert b"safe" not in json.dumps(rows, ensure_ascii=False).encode()


@pytest.mark.asyncio
async def test_unknown_handler_receipt_is_preserved_as_unknown(tmp_path: Path) -> None:
    def handler(parameters):
        return ToolExecutionResult(
            state=ToolReceiptState.UNKNOWN,
            error_code="provider_receipt_unknown",
        )

    governance = make_tool(tmp_path, handler)
    item = request()
    receipt = await governance.execute(item, decision=approved(governance, item))
    assert receipt.state is ToolReceiptState.UNKNOWN
    assert not receipt.successful
    assert receipt.error_code == "provider_receipt_unknown"


@pytest.mark.asyncio
async def test_invalid_handler_result_fails_closed(tmp_path: Path) -> None:
    def handler(parameters):
        return {"not_json": object()}

    governance = make_tool(tmp_path, handler)
    item = request()
    receipt = await governance.execute(item, decision=approved(governance, item))
    assert receipt.state is ToolReceiptState.FAILED
    assert receipt.reason == "invalid_tool_result"
