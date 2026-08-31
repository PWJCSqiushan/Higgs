from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "deploy"
    / "existing-server"
    / "validate_official_channels.py"
)
SPEC = importlib.util.spec_from_file_location("validate_official_channels", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


def _base() -> tuple[dict[str, str], dict[str, str]]:
    agent = {
        "R_AGENT_OFFICIAL_QQ_ENABLED": "true",
        "R_AGENT_OFFICIAL_QQ_REPLY_ENABLED": "true",
        "R_AGENT_OFFICIAL_QQ_OWNER_OPENID": "owner-openid",
        "R_AGENT_IDENTITY_SCHEMA_V2_ENABLED": "false",
    }
    sidecar = {
        "HIGGS_OFFICIAL_QQ_SIDECAR_ENABLED": "true",
        "HIGGS_OFFICIAL_QQ_CAPTURE_ONLY": "false",
        "HIGGS_OFFICIAL_QQ_OWNER_OPENID": "owner-openid",
    }
    return agent, sidecar


def test_owner_only_contract_does_not_require_identity_or_allowlist_migration() -> None:
    agent, sidecar = _base()
    CONTRACT.validate(agent, sidecar, release=True)


def test_ordinary_contract_requires_matching_versioned_metadata_and_identity_schema() -> None:
    agent, sidecar = _base()
    agent.update(
        {
            "R_AGENT_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED": "true",
            "R_AGENT_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS": "member-openid",
            "R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_VERSION": "2",
            "R_AGENT_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT": "a" * 64,
        }
    )
    sidecar.update(
        {
            "HIGGS_OFFICIAL_QQ_ORDINARY_PRIVATE_ENABLED": "true",
            "HIGGS_OFFICIAL_QQ_ALLOWED_PRIVATE_OPENIDS": "member-openid",
            "HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_VERSION": "2",
            "HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT": "a" * 64,
        }
    )

    with pytest.raises(CONTRACT.ContractError, match="identity schema v2"):
        CONTRACT.validate(agent, sidecar, release=False)

    agent["R_AGENT_IDENTITY_SCHEMA_V2_ENABLED"] = "true"
    CONTRACT.validate(agent, sidecar, release=False)

    sidecar["HIGGS_OFFICIAL_QQ_PRIVATE_ALLOWLIST_FINGERPRINT"] = "b" * 64
    with pytest.raises(CONTRACT.ContractError, match="metadata differs"):
        CONTRACT.validate(agent, sidecar, release=False)


def test_persona_surface_gate_cannot_widen_a_closed_channel() -> None:
    agent, sidecar = _base()
    agent["R_AGENT_PERSONA_V2_ORDINARY_PRIVATE_ENABLED"] = "true"

    with pytest.raises(CONTRACT.ContractError, match="ordinary Persona V2"):
        CONTRACT.validate(agent, sidecar, release=False)


def test_ordinary_proactive_requires_matching_dual_gates_and_private_channel() -> None:
    agent, sidecar = _base()
    agent["R_AGENT_OFFICIAL_QQ_ORDINARY_PROACTIVE_ENABLED"] = "true"
    with pytest.raises(CONTRACT.ContractError, match="ordinary proactive switches differ"):
        CONTRACT.validate(agent, sidecar, release=False)

    sidecar["HIGGS_OFFICIAL_QQ_ORDINARY_PROACTIVE_ENABLED"] = "true"
    with pytest.raises(CONTRACT.ContractError, match="ordinary proactive requires"):
        CONTRACT.validate(agent, sidecar, release=False)


def test_group_contract_requires_matching_versioned_metadata_and_identity_schema() -> None:
    agent, sidecar = _base()
    agent.update(
        {
            "R_AGENT_OFFICIAL_QQ_GROUP_ENABLED": "true",
            "R_AGENT_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS": "group-openid",
            "R_AGENT_OFFICIAL_QQ_GROUP_ALLOWLIST_VERSION": "3",
            "R_AGENT_OFFICIAL_QQ_GROUP_ALLOWLIST_FINGERPRINT": "c" * 64,
        }
    )
    sidecar.update(
        {
            "HIGGS_OFFICIAL_QQ_GROUP_ENABLED": "true",
            "HIGGS_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS": "group-openid",
            "HIGGS_OFFICIAL_QQ_GROUP_ALLOWLIST_VERSION": "3",
            "HIGGS_OFFICIAL_QQ_GROUP_ALLOWLIST_FINGERPRINT": "c" * 64,
        }
    )

    with pytest.raises(CONTRACT.ContractError, match="identity schema v2"):
        CONTRACT.validate(agent, sidecar, release=False)

    agent["R_AGENT_IDENTITY_SCHEMA_V2_ENABLED"] = "true"
    CONTRACT.validate(agent, sidecar, release=False)

    sidecar["HIGGS_OFFICIAL_QQ_GROUP_ALLOWLIST_VERSION"] = "4"
    with pytest.raises(CONTRACT.ContractError, match="group allowlist metadata differs"):
        CONTRACT.validate(agent, sidecar, release=False)
