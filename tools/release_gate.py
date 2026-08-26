"""Fail-closed repository and release-archive checks for Higgs CI."""

from __future__ import annotations

import io
import re
import subprocess
import tarfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_SUFFIXES = frozenset(
    {".db", ".key", ".log", ".p12", ".pem", ".pfx", ".sqlite", ".sqlite3"}
)
FORBIDDEN_PARTS = frozenset({"secrets"})
SECRET_PATTERNS = (
    ("private-key", re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("openai-key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("tencent-secret-id", re.compile(r"AKID[A-Za-z0-9]{13,}")),
    ("slack-token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}")),
)


def _git(*arguments: str) -> bytes:
    return subprocess.check_output(("git", *arguments), cwd=ROOT)


def _tracked_files() -> tuple[PurePosixPath, ...]:
    raw = _git("ls-files", "-z")
    return tuple(PurePosixPath(item.decode("utf-8")) for item in raw.split(b"\0") if item)


def _path_error(path: PurePosixPath) -> str | None:
    lowered = tuple(part.casefold() for part in path.parts)
    if any(part in FORBIDDEN_PARTS for part in lowered):
        return "private directory is tracked"
    if path.name.casefold() == ".env":
        return "runtime .env is tracked"
    if path.suffix.casefold() in FORBIDDEN_SUFFIXES:
        return f"private/runtime suffix is tracked: {path.suffix}"
    if len(lowered) >= 2 and lowered[0] == "runtime" and lowered[1] == "napcat":
        return "NapCat runtime/login state is tracked"
    return None


def _scan_index(paths: tuple[PurePosixPath, ...]) -> list[str]:
    errors: list[str] = []
    for path in paths:
        path_error = _path_error(path)
        if path_error is not None:
            errors.append(f"{path}: {path_error}")
            continue
        try:
            payload = _git("show", f":{path.as_posix()}")
        except subprocess.CalledProcessError:
            continue
        if path.suffix.casefold() == ".sh" and b"\r" in payload:
            errors.append(f"{path}: shell script is not LF-only")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in SECRET_PATTERNS:
            match = pattern.search(text)
            if match is not None:
                line = text.count("\n", 0, match.start()) + 1
                errors.append(f"{path}:{line}: high-confidence {label} pattern")
    return errors


def _scan_archive() -> tuple[int, list[str]]:
    archive = _git("archive", "--format=tar", "HEAD")
    errors: list[str] = []
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        members = bundle.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            path_error = _path_error(path)
            if path_error is not None:
                errors.append(f"archive:{path}: {path_error}")
            if path.is_absolute() or ".." in path.parts:
                errors.append(f"archive:{path}: unsafe archive path")
    return len(members), errors


def main() -> int:
    paths = _tracked_files()
    archive_count, archive_errors = _scan_archive()
    errors = [*_scan_index(paths), *archive_errors]
    if errors:
        print("release-gate=failed")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        "release-gate=passed "
        f"tracked_files={len(paths)} archive_members={archive_count} "
        "secret_patterns=clean shell_lf=clean"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
