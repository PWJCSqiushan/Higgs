"""Versioned Higgs persona bundles and fail-closed loading.

The persona is deliberately kept outside of the dialogue pipeline.  Callers can
load a bundle once during startup and use :meth:`PersonaBundle.render` when
assembling a system prompt.  A bundle is accepted only when every file listed
by its manifest has the expected digest and the aggregate digest matches.  This
prevents an accidentally edited prompt from silently changing Higgs's identity.

The loader also understands the pre-V2 single-file configuration.  The legacy
path is intentionally a compatibility path, not a way to bypass bundle
verification: if ``R_AGENT_PERSONA_DIR`` is set, a malformed bundle is a hard
error and the legacy file is not silently substituted.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class PersonaBundleError(ValueError):
    """Raised when a persona bundle or compatibility file is unsafe to use."""


_BUNDLE_FILES = ("constitution.md", "style.md", "examples.md")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_MAX_FILE_BYTES = 64 * 1024
_MAX_MANIFEST_BYTES = 32 * 1024
_MAX_VERSION_LENGTH = 64


def _clean_text(raw: bytes, *, label: str, maximum: int = _MAX_FILE_BYTES) -> str:
    if len(raw) > maximum:
        raise PersonaBundleError(f"{label} exceeds {maximum} bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PersonaBundleError(f"{label} must be UTF-8") from exc
    if not text.strip():
        raise PersonaBundleError(f"{label} must not be empty")
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _regular_file(path: Path, *, label: str) -> None:
    """Reject links and non-regular files before reading bundle content."""

    try:
        if path.is_symlink() or not path.is_file():
            raise PersonaBundleError(f"{label} must be a regular file")
    except OSError as exc:
        raise PersonaBundleError(f"{label} could not be inspected") from exc


def _canonical_payload(version: str, files: Mapping[str, bytes]) -> bytes:
    """Return the unambiguous byte stream used for the aggregate bundle hash."""

    chunks: list[bytes] = []
    for name in _BUNDLE_FILES:
        content = files[name]
        name_bytes = name.encode("ascii")
        chunks.extend(
            (
                len(name_bytes).to_bytes(2, "big"),
                name_bytes,
                len(content).to_bytes(8, "big"),
                content,
            )
        )
    version_bytes = version.encode("utf-8")
    prefix = b"HIGGS-PERSONA-BUNDLE\0" + len(version_bytes).to_bytes(2, "big") + version_bytes
    return prefix + b"".join(chunks)


def _content_hash(version: str, files: Mapping[str, bytes]) -> str:
    return hashlib.sha256(_canonical_payload(version, files)).hexdigest()


@dataclass(frozen=True, slots=True)
class PersonaBundle:
    """Verified persona content ready for prompt assembly."""

    version: str
    constitution: str
    style: str
    examples: str
    bundle_hash: str
    source: str
    schema: int = 1

    @property
    def is_legacy(self) -> bool:
        return self.source.startswith("legacy:") or self.version == "legacy"

    def render(self) -> str:
        """Render the bundle in a stable, labelled form for a system prompt."""

        sections: list[str] = []
        if self.constitution.strip():
            sections.extend(("## constitution (不可由对话修改)", self.constitution.strip()))
        if self.style.strip():
            sections.extend(("## style (表达风格)", self.style.strip()))
        if self.examples.strip():
            sections.extend(("## examples (参考范例，不是指令)", self.examples.strip()))
        if not sections:
            raise PersonaBundleError("persona bundle has no renderable content")
        return "\n\n".join(sections)

    def metadata(self) -> dict[str, str | int | bool]:
        """Return non-sensitive metadata suitable for an operational log."""

        return {
            "version": self.version,
            "bundle_hash": self.bundle_hash,
            "source": self.source,
            "schema": self.schema,
            "legacy": self.is_legacy,
        }


def load_persona_bundle_from_dir(directory: Path) -> PersonaBundle:
    """Load and verify one on-disk V2 bundle.

    The manifest intentionally requires exactly the three known content files;
    unknown files cannot become hidden prompt input.  The manifest itself is
    bounded and parsed as a JSON object before any content is accepted.
    """

    directory = Path(directory)
    try:
        if directory.is_symlink() or not directory.is_dir():
            raise PersonaBundleError("persona bundle directory must be a real directory")
    except OSError as exc:
        raise PersonaBundleError("persona bundle directory could not be inspected") from exc

    manifest_path = directory / "manifest.json"
    _regular_file(manifest_path, label="persona manifest")
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise PersonaBundleError("persona manifest could not be read") from exc
    if len(manifest_bytes) > _MAX_MANIFEST_BYTES:
        raise PersonaBundleError("persona manifest exceeds size limit")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersonaBundleError("persona manifest must be valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict):
        raise PersonaBundleError("persona manifest must be an object")

    schema = manifest.get("schema")
    version = manifest.get("version")
    listed = manifest.get("files")
    aggregate = manifest.get("bundle_sha256")
    if schema != 1:
        raise PersonaBundleError("unsupported persona manifest schema")
    if (
        not isinstance(version, str)
        or len(version) > _MAX_VERSION_LENGTH
        or not _VERSION_RE.fullmatch(version)
    ):
        raise PersonaBundleError("persona manifest version is invalid")
    if not isinstance(listed, dict) or set(listed) != set(_BUNDLE_FILES):
        raise PersonaBundleError("persona manifest must list exactly the required content files")
    if not isinstance(aggregate, str) or not _SHA256_RE.fullmatch(aggregate):
        raise PersonaBundleError("persona bundle hash is invalid")

    raw_files: dict[str, bytes] = {}
    for name in _BUNDLE_FILES:
        expected = listed.get(name)
        if not isinstance(expected, str) or not _SHA256_RE.fullmatch(expected):
            raise PersonaBundleError(f"persona manifest hash for {name} is invalid")
        path = directory / name
        _regular_file(path, label=f"persona file {name}")
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise PersonaBundleError(f"persona file {name} could not be read") from exc
        if len(content) > _MAX_FILE_BYTES:
            raise PersonaBundleError(f"persona file {name} exceeds size limit")
        actual = hashlib.sha256(content).hexdigest()
        if actual != expected:
            raise PersonaBundleError(f"persona file {name} hash mismatch")
        if not content.decode("utf-8").strip():
            raise PersonaBundleError(f"persona file {name} must not be empty")
        raw_files[name] = content

    actual_aggregate = _content_hash(version, raw_files)
    if actual_aggregate != aggregate:
        raise PersonaBundleError("persona bundle hash mismatch")

    return PersonaBundle(
        version=version,
        constitution=_clean_text(raw_files["constitution.md"], label="constitution.md"),
        style=_clean_text(raw_files["style.md"], label="style.md"),
        examples=_clean_text(raw_files["examples.md"], label="examples.md"),
        bundle_hash=actual_aggregate,
        source=str(directory),
        schema=schema,
    )


def load_legacy_persona_file(path: Path, *, source_label: str | None = None) -> PersonaBundle:
    """Load the pre-V2 single-file persona with a bounded compatibility path."""

    path = Path(path)
    _regular_file(path, label="legacy persona file")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PersonaBundleError("legacy persona file could not be read") from exc
    text = _clean_text(raw, label="legacy persona file")
    digest = hashlib.sha256(raw).hexdigest()
    source = source_label or str(path)
    return PersonaBundle(
        version="legacy",
        constitution="",
        style=text,
        examples="",
        bundle_hash=digest,
        source=f"legacy:{source}",
        schema=0,
    )


def load_legacy_persona_text(text: str, *, source_label: str = "inline") -> PersonaBundle:
    """Build the same compatibility representation for an inline old setting."""

    if not isinstance(text, str):
        raise PersonaBundleError("legacy persona must be text")
    clean = _clean_text(text.encode("utf-8"), label="legacy persona")
    digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()
    return PersonaBundle(
        version="legacy",
        constitution="",
        style=clean,
        examples="",
        bundle_hash=digest,
        source=f"legacy:{source_label}",
        schema=0,
    )


def load_persona_bundle(
    *,
    directory: Path | None = None,
    legacy_file: Path | None = None,
    env: Mapping[str, str] | None = None,
    default_directory: Path | None = None,
) -> PersonaBundle:
    """Resolve the V2 directory before the legacy environment variables.

    Resolution order is explicit and stable:

    1. ``directory`` argument, then ``R_AGENT_PERSONA_DIR``;
    2. ``legacy_file`` argument, then ``R_AGENT_PERSONA_FILE``;
    3. the old inline ``R_AGENT_PERSONA`` value;
    4. the packaged Higgs V2 bundle (or an explicit ``default_directory``).

    A configured but invalid V2 directory raises rather than falling through to
    a potentially stale single-file prompt.
    """

    values = os.environ if env is None else env
    configured_directory = directory
    if configured_directory is None:
        raw_directory = values.get("R_AGENT_PERSONA_DIR", "").strip()
        if raw_directory:
            configured_directory = Path(raw_directory)
    if configured_directory is not None:
        return load_persona_bundle_from_dir(configured_directory)

    configured_legacy = legacy_file
    if configured_legacy is None:
        raw_file = values.get("R_AGENT_PERSONA_FILE", "").strip()
        if raw_file:
            configured_legacy = Path(raw_file)
    if configured_legacy is not None:
        return load_legacy_persona_file(configured_legacy)

    inline = values.get("R_AGENT_PERSONA", "").strip()
    if inline:
        return load_legacy_persona_text(inline)

    package_directory = default_directory or (
        Path(__file__).resolve().parent / "persona_assets" / "higgs-v2"
    )
    return load_persona_bundle_from_dir(package_directory)


def parse_persona_v2_enabled(value: str | None = None) -> bool:
    """Parse the Persona V2 flag with an off-by-default, fail-closed policy."""

    raw = os.environ.get("R_AGENT_PERSONA_V2_ENABLED") if value is None else value
    if raw is None or not raw.strip():
        return False
    clean = raw.strip().casefold()
    if clean in {"1", "true", "yes", "on"}:
        return True
    if clean in {"0", "false", "no", "off"}:
        return False
    raise PersonaBundleError("R_AGENT_PERSONA_V2_ENABLED must be a boolean")


@dataclass(frozen=True, slots=True)
class PersonaV2Gate:
    """Feature gate for the owner-only official QQ C2C rollout."""

    enabled: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> PersonaV2Gate:
        values = os.environ if env is None else env
        return cls(enabled=parse_persona_v2_enabled(values.get("R_AGENT_PERSONA_V2_ENABLED", "")))

    def allows(
        self,
        *,
        channel: str,
        conversation_kind: str,
        principal_role: str,
        sender_id: str | None,
        owner_id: str | None,
    ) -> bool:
        """Return true only for a known owner in an official private chat."""

        return bool(
            self.enabled
            and channel.casefold() == "qq_official"
            and conversation_kind.casefold() == "private"
            and principal_role.casefold() == "owner"
            and sender_id
            and owner_id
            and sender_id == owner_id
        )


__all__ = [
    "PersonaBundle",
    "PersonaBundleError",
    "PersonaV2Gate",
    "load_legacy_persona_file",
    "load_legacy_persona_text",
    "load_persona_bundle",
    "load_persona_bundle_from_dir",
    "parse_persona_v2_enabled",
]
