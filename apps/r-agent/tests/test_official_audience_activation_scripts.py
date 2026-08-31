from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEPLOY = ROOT / "deploy" / "existing-server"


def test_shared_audience_activation_backs_up_identity_and_never_rebuilds_napcat() -> None:
    script = (DEPLOY / "activate_official_audience.sh").read_text(encoding="utf-8")

    assert "ACTIVATE_VERSIONED_OFFICIAL_AUDIENCE" in script
    assert "PRODUCTION_AUDIENCE_CONFIRMED" in script
    assert "HIGGS_RECYCLE_ROOT" in script
    assert "higgs-official-audience-" in script
    assert "identity.sqlite" in script
    assert "prepare_official_audience_activation.py" in script
    assert "--check-only" in script
    assert "--session-state" in script
    assert "activation_started_ms" in script
    assert ".official-private-capture.lock" in script
    assert ".official-private-freeze.lock" in script
    assert ".official-group-capture.lock" in script
    assert ".official-group-freeze.lock" in script
    assert "sidecar intake did not quiesce" in script
    assert "wait_for_verified_transport" in script
    assert "validate_official_channels.py" in script
    assert "--force-recreate official-qq-sidecar" in script
    assert "--force-recreate agent" in script
    assert "--force-recreate napcat" not in script
    assert "NapCat changed unexpectedly" in script


def test_surface_wrappers_require_explicit_versioned_confirmation() -> None:
    private = (DEPLOY / "activate_official_ordinary_private.sh").read_text(encoding="utf-8")
    group = (DEPLOY / "activate_official_test_group.sh").read_text(encoding="utf-8")

    assert "ACTIVATE_VERSIONED_ORDINARY_PRIVATE" in private
    assert "ACTIVATE_VERSIONED_TEST_GROUP" in group
    assert "legacy fixed-stability activation is disabled" in group
    assert "ACTIVATE_VERSIONED_OFFICIAL_AUDIENCE private" in private
    assert "ACTIVATE_VERSIONED_OFFICIAL_AUDIENCE group" in group
    assert 'exec sh "$script_dir/activate_official_audience.sh"' in private
    assert 'exec sh "$script_dir/activate_official_audience.sh"' in group
