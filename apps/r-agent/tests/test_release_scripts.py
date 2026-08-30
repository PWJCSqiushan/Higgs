"""Regression tests for the secret-free immutable-release shell scripts."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTIVATE = REPO_ROOT / "deploy" / "server" / "activate_release.sh"
ROLLBACK = REPO_ROOT / "deploy" / "server" / "rollback_release.sh"
OWNER_CAPTURE = REPO_ROOT / "deploy" / "existing-server" / "run_official_owner_capture.sh"
PROACTIVE_ACTIVATE = (
    REPO_ROOT / "deploy" / "existing-server" / "activate_official_owner_proactive.sh"
)


def _bash_path() -> str | None:
    """Return a Bash executable on Linux or an installed Git Bash on Windows."""

    candidates = [shutil.which("bash")]
    if os.name == "nt":
        candidates.extend(
            [
                r"D:\Git\bin\bash.exe",
                r"C:\Program Files\Git\bin\bash.exe",
            ]
        )
    valid_candidates = (
        candidate for candidate in candidates if candidate and Path(candidate).exists()
    )
    return next(valid_candidates, None)


def _bash_arg(value: Path, bash: str) -> str:
    """Convert a Windows path for Git Bash while leaving POSIX paths unchanged."""

    if os.name != "nt":
        return str(value)
    cygpath = Path(bash).parent.parent / "usr" / "bin" / "cygpath.exe"
    if not cygpath.exists():
        return str(value).replace("\\", "/")
    converted = subprocess.run(
        [str(cygpath), "-u", str(value)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return converted.stdout.strip()


@pytest.fixture
def bash() -> str:
    executable = _bash_path()
    if executable is None:
        pytest.skip("Bash is required for release-script integration tests")
    return executable


def _archive(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "release-content"
    source.mkdir()
    (source / "ready.txt").write_text("release-ready\n", encoding="utf-8")
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(source / "ready.txt", arcname="payload/ready.txt")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    return archive, digest


def _run(
    script: Path,
    bash: str,
    root: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["HIGGS_ROOT"] = _bash_arg(root, bash)
    return subprocess.run(
        [bash, _bash_arg(script, bash), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )


def _directory_symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks are unavailable: {error}")


def test_shell_attributes_force_lf_and_changed_scripts_have_no_crlf() -> None:
    attributes = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "*.sh text eol=lf" in attributes
    for script in (ACTIVATE, ROLLBACK, OWNER_CAPTURE, PROACTIVE_ACTIVATE):
        assert b"\r\n" not in script.read_bytes()


def test_owner_capture_runner_is_single_use_and_agent_only() -> None:
    script = OWNER_CAPTURE.read_text(encoding="utf-8")

    assert "ONLY_OWNER_IS_TEST_USER" in script
    assert "flock -n" in script
    assert "run --rm --no-deps" in script
    assert "R_AGENT_OFFICIAL_QQ_ENABLED" in script
    assert "R_AGENT_OFFICIAL_QQ_OWNER_OPENID" in script
    assert " up " not in script
    assert "restart" not in script


def test_checksum_mismatch_fails_before_creating_release_tree(tmp_path: Path, bash: str) -> None:
    archive, _digest = _archive(tmp_path)
    commit = "a" * 40
    result = _run(ACTIVATE, bash, tmp_path / "srv", commit, _bash_arg(archive, bash), "0" * 64)

    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr
    assert not (tmp_path / "srv" / "releases").exists()


def test_existing_immutable_target_fails_closed(tmp_path: Path, bash: str) -> None:
    archive, digest = _archive(tmp_path)
    commit = "b" * 40
    release = tmp_path / "srv" / "releases" / commit
    release.mkdir(parents=True)
    sentinel = release / "sentinel.txt"
    sentinel.write_text("keep\n", encoding="utf-8")

    result = _run(ACTIVATE, bash, tmp_path / "srv", commit, _bash_arg(archive, bash), digest)

    assert result.returncode != 0
    assert "already exists" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "keep\n"


def test_activation_moves_current_to_trash_and_verifies_link(tmp_path: Path, bash: str) -> None:
    archive, digest = _archive(tmp_path)
    commit = "c" * 40
    root = tmp_path / "srv"
    old_release = root / "releases" / ("d" * 40)
    old_release.mkdir(parents=True)
    (old_release / "old.txt").write_text("old\n", encoding="utf-8")
    current = root / "apps" / "higgs" / "current"
    current.parent.mkdir(parents=True)
    _directory_symlink(current, old_release)

    result = _run(ACTIVATE, bash, root, commit, _bash_arg(archive, bash), digest)
    new_release = root / "releases" / commit
    trashed = list((root / "trash").glob("higgs-current-*"))

    assert result.returncode == 0, result.stderr
    assert current.is_symlink()
    assert current.resolve() == new_release.resolve()
    assert (new_release / "payload" / "ready.txt").read_text(encoding="utf-8") == (
        "release-ready\n"
    )
    assert len(trashed) == 1
    assert trashed[0].is_symlink()
    assert trashed[0].resolve() == old_release.resolve()


def test_rollback_moves_replaced_current_to_trash_and_verifies_link(
    tmp_path: Path, bash: str
) -> None:
    archive, digest = _archive(tmp_path)
    commit = "e" * 40
    root = tmp_path / "srv"
    old_release = root / "releases" / ("f" * 40)
    old_release.mkdir(parents=True)
    current = root / "apps" / "higgs" / "current"
    current.parent.mkdir(parents=True)
    _directory_symlink(current, old_release)

    activated = _run(ACTIVATE, bash, root, commit, _bash_arg(archive, bash), digest)
    assert activated.returncode == 0, activated.stderr
    time.sleep(1.1)

    result = _run(ROLLBACK, bash, root)
    new_release = root / "releases" / commit
    trashed = list((root / "trash").glob("higgs-current-*"))
    resolved_targets = {entry.resolve() for entry in trashed}

    assert result.returncode == 0, result.stderr
    assert current.is_symlink()
    assert current.resolve() == old_release.resolve()
    assert old_release.resolve() in resolved_targets
    assert new_release.resolve() in resolved_targets
