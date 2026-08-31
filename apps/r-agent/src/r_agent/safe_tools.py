"""Fail-closed read-only web and document tools.

This module is deliberately independent from the official QQ adapters.  It
provides the first safe-tool boundary, but no caller is allowed to turn model
JSON into an invocation automatically.  Production registration is disabled
by default; a trusted command/approval path must create a
``ToolCallContext`` and explicitly opt in.

The network implementation resolves a host before every request and passes the
approved address set to the transport.  The default transport is disabled;
the optional socket transport connects to an already-resolved IP and sends a
normal Host/SNI value, so a DNS answer cannot be silently re-resolved by the
HTTP client.  Tests and future adapters inject a transport and resolver.

Fetched web pages and attached documents are untrusted data.  They are
returned with an explicit marker and prompt-injection observation; no text is
ever interpreted as instructions by this module, and the metadata audit trail
stores hashes/counts only.
"""

from __future__ import annotations

import hashlib
import http.client
import io
import ipaddress
import json
import os
import re
import shutil
import socket
import sqlite3
import ssl
import stat
import threading
import time
import unicodedata
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path, PurePath
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

from r_agent.events import AttachmentRef, InboundEvent
from r_agent.tool_governance import (
    ToolBudget,
    ToolExecutionResult,
    ToolReceipt,
    ToolReceiptState,
    ToolSpec,
    _schema_matches,
    normalize_parameters,
    parameter_approval_hash,
)


class SafeToolError(ValueError):
    """Base class for a rejected or unavailable safe-tool operation."""


class NetworkDisabledError(SafeToolError):
    """Real network execution is not enabled for this process."""


class UnsafeUrlError(SafeToolError):
    """A URL, redirect, DNS answer, or port violates the egress policy."""


class NetworkRequestError(SafeToolError):
    """The injected transport could not provide a trustworthy response."""


class ResponseTooLargeError(NetworkRequestError):
    """The response exceeded the configured in-memory limit."""


class UnsupportedContentTypeError(NetworkRequestError):
    """The provider returned a media type outside the allowlist."""


class DocumentSecurityError(SafeToolError):
    """An attachment is not a safe, isolated, supported document."""


class BudgetExceededError(SafeToolError):
    """A user or session tool budget was exhausted."""


class IdempotencyConflictError(SafeToolError):
    """An idempotency key was reused for a different scoped request."""


_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INJECTION_RE = re.compile(
    r"(?:ignore\s+(?:all\s+)?(?:previous|prior)|system\s+prompt|developer\s+message|"
    r"disregard\s+instructions|忽略(?:之前|上面|以上).{0,20}(?:指令|提示|规则)|"
    r"系统提示词|开发者消息)",
    re.IGNORECASE,
)
_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
_DEFAULT_SCHEMES = frozenset({"http", "https"})
_DEFAULT_PORTS = frozenset({80, 443})
_SUPPORTED_DOCUMENT_SUFFIXES = frozenset(
    {".txt", ".md", ".markdown", ".json", ".csv", ".html", ".htm", ".docx"}
)
_MAX_URL_LENGTH = 4_096
_MAX_QUERY_LENGTH = 512
_MAX_TITLE_LENGTH = 512
_MAX_SNIPPET_LENGTH = 2_000
_MAX_FILE_BYTES = 5 * 1024 * 1024
_MAX_DOCUMENT_TEXT = 120_000
_MAX_ZIP_ENTRIES = 256
_MAX_ZIP_UNCOMPRESSED = 20 * 1024 * 1024
_MAX_ZIP_MEMBER = 10 * 1024 * 1024
_MAX_ZIP_RATIO = 100


def _clean_text(value: str, *, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise SafeToolError(f"{label} must be text")
    normalized = unicodedata.normalize("NFKC", value)
    if not normalized or len(normalized) > maximum:
        raise SafeToolError(f"{label} is empty or too long")
    if _CONTROL_RE.search(normalized):
        raise SafeToolError(f"{label} contains control characters")
    return normalized


def _safe_untrusted_text(value: str, *, maximum: int) -> tuple[str, bool]:
    # Keep line breaks and tabs for readable model context, but remove other
    # controls.  This is presentation sanitization, not an instruction parser.
    normalized = unicodedata.normalize("NFKC", value)
    normalized = "".join(
        character
        for character in normalized
        if character in {"\n", "\r", "\t"} or ord(character) >= 0x20
    )
    clipped = normalized[:maximum]
    return clipped, bool(_INJECTION_RE.search(clipped))


def _sha256(value: str | bytes) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    """Strict public-egress and in-memory response policy."""

    allow_network: bool = False
    allowed_schemes: frozenset[str] = _DEFAULT_SCHEMES
    allowed_ports: frozenset[int] = _DEFAULT_PORTS
    timeout_seconds: float = 10.0
    max_redirects: int = 3
    max_response_bytes: int = 1_048_576
    max_text_chars: int = 120_000
    max_search_results: int = 10

    def __post_init__(self) -> None:
        if not isinstance(self.allow_network, bool):
            raise SafeToolError("network allow flag is invalid")
        if isinstance(self.allowed_schemes, (str, bytes)):
            raise SafeToolError("network policy schemes must be a set")
        try:
            schemes = frozenset(
                item.casefold() if isinstance(item, str) else item for item in self.allowed_schemes
            )
        except (TypeError, ValueError) as exc:
            raise SafeToolError("network policy schemes are invalid") from exc
        if not schemes or not schemes <= _DEFAULT_SCHEMES:
            raise SafeToolError("network policy schemes must be http/https")
        if isinstance(self.allowed_ports, (str, bytes)):
            raise SafeToolError("network policy ports must be a set")
        try:
            ports = frozenset(self.allowed_ports)
        except (TypeError, ValueError) as exc:
            raise SafeToolError("network policy ports are invalid") from exc
        if (
            not ports
            or any(isinstance(item, bool) or not isinstance(item, int) for item in ports)
            or not ports <= _DEFAULT_PORTS
        ):
            raise SafeToolError("network policy ports must be 80/443")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 0.1 <= float(self.timeout_seconds) <= 30
        ):
            raise SafeToolError("network timeout must be between 0.1 and 30 seconds")
        if (
            isinstance(self.max_redirects, bool)
            or not isinstance(self.max_redirects, int)
            or not 0 <= self.max_redirects <= 5
        ):
            raise SafeToolError("network redirect budget is invalid")
        if (
            isinstance(self.max_response_bytes, bool)
            or not isinstance(self.max_response_bytes, int)
            or not (1_024 <= self.max_response_bytes <= 16 * 1024 * 1024)
        ):
            raise SafeToolError("network response budget is invalid")
        if (
            isinstance(self.max_text_chars, bool)
            or not isinstance(self.max_text_chars, int)
            or not 1_000 <= self.max_text_chars <= 500_000
        ):
            raise SafeToolError("network text budget is invalid")
        if (
            isinstance(self.max_search_results, bool)
            or not isinstance(self.max_search_results, int)
            or not 1 <= self.max_search_results <= 50
        ):
            raise SafeToolError("network search result budget is invalid")
        object.__setattr__(self, "allowed_schemes", schemes)
        object.__setattr__(self, "allowed_ports", ports)

    def as_mapping(self) -> dict[str, Any]:
        return {
            "allow_network": self.allow_network,
            "allowed_schemes": sorted(self.allowed_schemes),
            "allowed_ports": sorted(self.allowed_ports),
            "timeout_seconds": self.timeout_seconds,
            "max_redirects": self.max_redirects,
            "max_response_bytes": self.max_response_bytes,
            "max_text_chars": self.max_text_chars,
            "max_search_results": self.max_search_results,
        }


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Small transport-neutral response object; body is never persisted."""

    status_code: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""

    def __post_init__(self) -> None:
        if isinstance(self.status_code, bool) or not 100 <= self.status_code <= 599:
            raise NetworkRequestError("HTTP status is invalid")
        if not isinstance(self.body, bytes):
            raise NetworkRequestError("HTTP response body must be bytes")
        normalized: dict[str, str] = {}
        for key, value in self.headers.items():
            clean_key = _clean_text(str(key), label="HTTP header name", maximum=128).casefold()
            clean_value = _clean_text(str(value), label="HTTP header value", maximum=4_096)
            normalized[clean_key] = clean_value
        object.__setattr__(self, "headers", normalized)

    def header(self, name: str) -> str | None:
        return self.headers.get(name.casefold())


class HttpTransport(Protocol):
    """Injected request transport; it must honor ``allowed_addresses``."""

    def request(
        self,
        method: str,
        url: str,
        *,
        timeout_seconds: float,
        allowed_addresses: Sequence[str],
    ) -> HttpResponse: ...


class DnsResolver(Protocol):
    """Resolver abstraction used twice immediately before every request."""

    def resolve(self, hostname: str) -> Sequence[str]: ...


class DisabledNetworkTransport:
    """Default transport: no real network access is possible."""

    def request(
        self,
        method: str,
        url: str,
        *,
        timeout_seconds: float,
        allowed_addresses: Sequence[str],
    ) -> HttpResponse:
        raise NetworkDisabledError("network execution is disabled")


class SystemDnsResolver:
    """Resolve stream addresses without exposing resolver details to callers."""

    def resolve(self, hostname: str) -> Sequence[str]:
        try:
            results = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise UnsafeUrlError("hostname resolution failed") from exc
        addresses = tuple(dict.fromkeys(str(item[4][0]) for item in results))
        if not addresses:
            raise UnsafeUrlError("hostname has no addresses")
        return addresses


class SocketHttpTransport:
    """Minimal transport that connects only to the already-approved IPs."""

    requires_network_permission = True

    def request(
        self,
        method: str,
        url: str,
        *,
        timeout_seconds: float,
        allowed_addresses: Sequence[str],
    ) -> HttpResponse:
        parts = urlsplit(url)
        hostname = parts.hostname
        if hostname is None:
            raise NetworkRequestError("transport URL has no hostname")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        host_header = hostname
        if (parts.scheme == "https" and port != 443) or (parts.scheme == "http" and port != 80):
            host_header = f"{hostname}:{port}"
        last_error: OSError | None = None
        addresses = tuple(allowed_addresses)
        if not addresses or any(
            not isinstance(address, str) or not _safe_ip_address(address) for address in addresses
        ):
            raise UnsafeUrlError("transport received a non-public address")
        for address in addresses:
            sock: socket.socket | None = None
            try:
                sock = socket.create_connection((address, port), timeout=timeout_seconds)
                if parts.scheme == "https":
                    context = ssl.create_default_context()
                    sock = context.wrap_socket(sock, server_hostname=hostname)
                try:
                    request_bytes = (
                        f"{method} {path} HTTP/1.1\r\n"
                        f"Host: {host_header}\r\n"
                        "Accept: text/html, text/plain, application/json\r\n"
                        "Connection: close\r\n\r\n"
                    ).encode("ascii")
                except UnicodeEncodeError as exc:
                    raise NetworkRequestError(
                        "request URL contains unsupported characters"
                    ) from exc
                sock.sendall(request_bytes)
                response = http.client.HTTPResponse(sock)
                response.begin()
                body = response.read(16 * 1024 * 1024 + 1)
                headers = {str(key): str(value) for key, value in response.getheaders()}
                if len(body) > 16 * 1024 * 1024:
                    raise ResponseTooLargeError("HTTP response is too large")
                return HttpResponse(response.status, headers, body)
            except ResponseTooLargeError:
                raise
            except (OSError, http.client.HTTPException) as exc:
                last_error = exc if isinstance(exc, OSError) else OSError(str(exc))
            finally:
                if sock is not None:
                    with suppress(OSError):
                        sock.close()
        raise NetworkRequestError("all approved network addresses failed") from last_error


def _safe_ip_address(value: str) -> bool:
    try:
        # Zone identifiers are local-routing metadata, not a public address.
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return bool(
        address.is_global
        and not address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_reserved
        and not address.is_multicast
        and not address.is_unspecified
    )


@dataclass(frozen=True, slots=True)
class ValidatedUrl:
    url: str
    scheme: str
    hostname: str
    port: int


def validate_public_url(url: str, *, policy: NetworkPolicy | None = None) -> ValidatedUrl:
    """Validate and normalize a public HTTP(S) URL without performing DNS."""

    active_policy = policy or NetworkPolicy()
    if not isinstance(url, str) or not url or len(url) > _MAX_URL_LENGTH:
        raise UnsafeUrlError("URL is empty or too long")
    if _CONTROL_RE.search(url):
        raise UnsafeUrlError("URL contains control characters")
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise UnsafeUrlError("URL cannot be parsed") from exc
    scheme = parts.scheme.casefold()
    if scheme not in active_policy.allowed_schemes:
        raise UnsafeUrlError("URL scheme is not allowed")
    if parts.username is not None or parts.password is not None:
        raise UnsafeUrlError("URL user information is not allowed")
    if parts.fragment:
        raise UnsafeUrlError("URL fragments are not allowed")
    raw_hostname = parts.hostname
    if raw_hostname is None or raw_hostname != raw_hostname.strip() or not raw_hostname:
        raise UnsafeUrlError("URL hostname is invalid")
    try:
        hostname = raw_hostname.rstrip(".").encode("idna").decode("ascii").casefold()
    except UnicodeError as exc:
        raise UnsafeUrlError("URL hostname is invalid") from exc
    if not hostname or hostname in {".", ".."}:
        raise UnsafeUrlError("URL hostname is invalid")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeUrlError("URL port is invalid") from exc
    if port not in active_policy.allowed_ports:
        raise UnsafeUrlError("URL port is not allowed")
    if parts.query and len(parts.query) > _MAX_URL_LENGTH:
        raise UnsafeUrlError("URL query is too long")
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if scheme == "https" else 80
    if port != default_port:
        netloc = f"{netloc}:{port}"
    normalized = urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))
    return ValidatedUrl(normalized, scheme, hostname, port)


class SafeNetworkClient:
    """Redirect- and DNS-rebinding-aware bounded network client."""

    def __init__(
        self,
        *,
        policy: NetworkPolicy | None = None,
        transport: HttpTransport | None = None,
        resolver: DnsResolver | None = None,
    ) -> None:
        self.policy = policy or NetworkPolicy()
        self.transport = transport or DisabledNetworkTransport()
        self.resolver = resolver or SystemDnsResolver()

    def _resolve_public(self, hostname: str) -> tuple[str, ...]:
        try:
            literal = ipaddress.ip_address(hostname)
        except ValueError:
            literal = None
        if literal is not None:
            addresses = (hostname,)
        else:
            try:
                addresses = tuple(
                    dict.fromkeys(str(item) for item in self.resolver.resolve(hostname))
                )
            except (OSError, TypeError, ValueError) as exc:
                raise UnsafeUrlError("hostname resolution failed") from exc
        if not addresses or any(not _safe_ip_address(address) for address in addresses):
            raise UnsafeUrlError("hostname resolves to a non-public address")
        return addresses

    @staticmethod
    def _content_type(response: HttpResponse) -> str:
        value = response.header("content-type")
        if value is None:
            raise UnsupportedContentTypeError("response content type is missing")
        media_type = value.split(";", 1)[0].strip().casefold()
        if not media_type or _CONTROL_RE.search(media_type):
            raise UnsupportedContentTypeError("response content type is invalid")
        return media_type

    def fetch(
        self,
        url: str,
        *,
        allowed_content_types: Iterable[str] | None = None,
    ) -> tuple[ValidatedUrl, HttpResponse, str]:
        """Fetch one final response, validating every redirect hop."""

        if isinstance(self.transport, DisabledNetworkTransport):
            raise NetworkDisabledError("network execution is disabled")
        if (
            getattr(self.transport, "requires_network_permission", False)
            and not self.policy.allow_network
        ):
            raise NetworkDisabledError("network execution is disabled")
        allowed = (
            frozenset(item.casefold() for item in allowed_content_types)
            if allowed_content_types is not None
            else None
        )
        current = url
        for hop in range(self.policy.max_redirects + 1):
            validated = validate_public_url(current, policy=self.policy)
            # First lookup is the preflight view.  A second lookup is performed
            # immediately before opening the socket and every answer must stay
            # public; the transport receives exactly that second set.
            self._resolve_public(validated.hostname)
            final_addresses = self._resolve_public(validated.hostname)
            response = self.transport.request(
                "GET",
                validated.url,
                timeout_seconds=float(self.policy.timeout_seconds),
                allowed_addresses=final_addresses,
            )
            content_length = response.header("content-length")
            if content_length is not None:
                try:
                    declared_length = int(content_length)
                except ValueError as exc:
                    raise NetworkRequestError("content length is invalid") from exc
                if declared_length < 0 or declared_length > self.policy.max_response_bytes:
                    raise ResponseTooLargeError("response exceeds configured limit")
            if len(response.body) > self.policy.max_response_bytes:
                raise ResponseTooLargeError("response exceeds configured limit")
            if response.status_code in _REDIRECT_CODES:
                location = response.header("location")
                if not location or len(location) > _MAX_URL_LENGTH:
                    raise NetworkRequestError("redirect location is missing or too long")
                if hop >= self.policy.max_redirects:
                    raise NetworkRequestError("redirect limit exceeded")
                current = urljoin(validated.url, location)
                # Validate before the next network operation so a malformed
                # redirect cannot reach a resolver or transport.
                validate_public_url(current, policy=self.policy)
                continue
            if not 200 <= response.status_code < 300:
                raise NetworkRequestError("HTTP response was not successful")
            media_type = self._content_type(response)
            if allowed is not None and media_type not in allowed:
                raise UnsupportedContentTypeError("response content type is not allowed")
            return validated, response, media_type
        raise NetworkRequestError("redirect processing failed")


class _HtmlTextParser(HTMLParser):
    _SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "head"})

    def __init__(self, *, maximum: int) -> None:
        super().__init__(convert_charrefs=True)
        self.maximum = maximum
        self._skip_depth = 0
        self._title_depth = 0
        self.title_parts: list[str] = []
        self.body_parts: list[str] = []
        self._size = 0

    def _append(self, target: list[str], data: str) -> None:
        if self._size >= self.maximum:
            return
        bounded = data[: self.maximum - self._size]
        target.append(bounded)
        self._size += len(bounded)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.casefold()
        if normalized in self._SKIP_TAGS:
            self._skip_depth += 1
        if normalized == "title":
            self._title_depth += 1

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if normalized in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if normalized == "title" and self._title_depth:
            self._title_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._title_depth:
            self._append(self.title_parts, data)
        if self._skip_depth:
            return
        self._append(self.body_parts, data + "\n")


def _extract_html(body: bytes, *, maximum: int) -> tuple[str, str]:
    try:
        decoded = body.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        decoded = body.decode("utf-8", errors="replace")
    parser = _HtmlTextParser(maximum=maximum)
    try:
        parser.feed(decoded)
        parser.close()
    except Exception as exc:
        raise NetworkRequestError("HTML parsing failed") from exc
    title, _ = _safe_untrusted_text(" ".join(parser.title_parts), maximum=512)
    text, _ = _safe_untrusted_text("".join(parser.body_parts), maximum=maximum)
    return title.strip(), text.strip()


def _parse_json_bytes(body: bytes) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NetworkRequestError("JSON response is invalid") from exc


def _search_endpoint_with_query(endpoint: ValidatedUrl, query: str) -> str:
    parts = urlsplit(endpoint.url)
    existing = parse_qsl(parts.query, keep_blank_values=True)
    existing.append(("q", query))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(existing), ""))


def _parse_search_results(payload: Any, *, maximum: int) -> tuple[list[dict[str, Any]], bool]:
    items = payload.get("results") if isinstance(payload, Mapping) else payload
    if not isinstance(items, list):
        raise NetworkRequestError("search response results are invalid")
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    injection = False
    for item in items[: maximum + 1]:
        if not isinstance(item, Mapping):
            raise NetworkRequestError("search result item is invalid")
        title_value = item.get("title", "")
        if not isinstance(title_value, str):
            raise NetworkRequestError("search result title is invalid")
        title = _clean_text(
            title_value,
            label="search result title",
            maximum=_MAX_TITLE_LENGTH,
        )
        raw_url = item.get("url")
        if not isinstance(raw_url, str):
            raise NetworkRequestError("search result URL is invalid")
        validated_result = validate_public_url(raw_url)
        try:
            literal_result = ipaddress.ip_address(validated_result.hostname)
        except ValueError:
            literal_result = None
        if literal_result is not None and not _safe_ip_address(validated_result.hostname):
            raise UnsafeUrlError("search result URL resolves to a non-public address")
        result_url = validated_result.url
        if result_url in seen:
            continue
        snippet_value = item.get("snippet", "")
        if not isinstance(snippet_value, str):
            raise NetworkRequestError("search result snippet is invalid")
        snippet, flagged = _safe_untrusted_text(snippet_value, maximum=_MAX_SNIPPET_LENGTH)
        injection = injection or flagged
        seen.add(result_url)
        results.append({"title": title, "url": result_url, "snippet": snippet})
        if len(results) >= maximum:
            break
    if len(items) > maximum:
        # Truncation is safe and explicit; the provider cannot make the model
        # consume an unbounded result set.
        pass
    return results, injection


def _prompt_safe_payload(text: str, *, maximum: int) -> tuple[str, bool]:
    payload, flagged = _safe_untrusted_text(text, maximum=maximum)
    return payload, flagged


@dataclass(frozen=True, slots=True)
class ToolCallContext:
    """Trusted caller context supplied by the deterministic adapter."""

    actor_role: str
    principal_id: str
    session_id: str
    surface: str
    source: str = "owner_command"
    data_scope: str = "conversation"

    def __post_init__(self) -> None:
        for name, value, maximum in (
            ("actor_role", self.actor_role, 32),
            ("principal_id", self.principal_id, 256),
            ("session_id", self.session_id, 256),
            ("surface", self.surface, 64),
            ("source", self.source, 32),
            ("data_scope", self.data_scope, 64),
        ):
            _clean_text(value, label=f"tool context {name}", maximum=maximum)
        if not self.principal_id or not self.session_id:
            raise SafeToolError("tool caller and session identity are required")
        if self.source not in {"owner_command", "model_shadow", "system"}:
            raise SafeToolError("tool context source is invalid")
        scope = _clean_text(self.data_scope, label="tool context data scope", maximum=64).casefold()
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", scope):
            raise SafeToolError("tool context data scope is invalid")
        object.__setattr__(self, "data_scope", scope)


class MetadataAuditTrail:
    """Hash/count-only audit trail for direct safe-tool adapters."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path.expanduser().resolve() if path is not None else None
        self._lock = threading.RLock()
        self._events: list[dict[str, Any]] = []
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path) as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS safe_tool_audit (
                        audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tool_name TEXT NOT NULL,
                        actor_sha256 TEXT NOT NULL,
                        session_sha256 TEXT NOT NULL,
                        parameter_sha256 TEXT NOT NULL,
                        outcome TEXT NOT NULL,
                        byte_count INTEGER NOT NULL,
                        created_at_ms INTEGER NOT NULL
                    )
                    """
                )
            with suppress(OSError):
                self.path.chmod(0o600)

    def record(
        self,
        *,
        tool_name: str,
        actor_id: str,
        session_id: str,
        parameter_sha256: str,
        outcome: ToolReceiptState,
        byte_count: int,
        created_at_ms: int | None = None,
    ) -> None:
        if isinstance(byte_count, bool) or not 0 <= byte_count <= 16 * 1024 * 1024:
            raise SafeToolError("audit byte count is invalid")
        now = created_at_ms or int(time.time() * 1000)
        payload = {
            "tool_name": tool_name,
            "actor_sha256": _sha256(actor_id),
            "session_sha256": _sha256(session_id),
            "parameter_sha256": parameter_sha256,
            "outcome": outcome.value,
            "byte_count": byte_count,
            "created_at_ms": now,
        }
        if self.path is None:
            with self._lock:
                self._events.append(payload)
            return
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO safe_tool_audit(
                    tool_name, actor_sha256, session_sha256, parameter_sha256,
                    outcome, byte_count, created_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(payload.values()),
            )

    def events(self) -> tuple[dict[str, Any], ...]:
        if self.path is None:
            with self._lock:
                return tuple(dict(item) for item in self._events)
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute("SELECT * FROM safe_tool_audit ORDER BY audit_id").fetchall()
        return tuple(dict(item) for item in rows)


class BudgetLedger:
    """Process-local user/session request budget with hashed identities."""

    def __init__(self, *, clock_ms: Any | None = None) -> None:
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._lock = threading.RLock()
        self._events: list[tuple[str, str, str, int, int]] = []

    def reserve(
        self,
        *,
        tool_name: str,
        actor_id: str,
        session_id: str,
        budget: ToolBudget | None,
        input_bytes: int,
    ) -> None:
        if budget is None:
            return
        now = int(self._clock_ms())
        actor_hash = _sha256(actor_id)
        session_hash = _sha256(session_id)
        with self._lock:
            self._events = [item for item in self._events if now - item[3] < 60_000]
            actor_count = sum(
                item[0] == tool_name and item[1] == actor_hash for item in self._events
            )
            session_count = sum(
                item[0] == tool_name and item[2] == session_hash for item in self._events
            )
            if (
                budget.max_requests_per_actor_per_minute is not None
                and actor_count >= budget.max_requests_per_actor_per_minute
            ):
                raise BudgetExceededError("tool actor budget exceeded")
            if (
                budget.max_requests_per_session_per_minute is not None
                and session_count >= budget.max_requests_per_session_per_minute
            ):
                raise BudgetExceededError("tool session budget exceeded")
            if budget.max_input_bytes is not None and input_bytes > budget.max_input_bytes:
                raise BudgetExceededError("tool input budget exceeded")
            self._events.append((tool_name, actor_hash, session_hash, now, input_bytes))


class DownloadIsolation:
    """Isolated download area with reversible 24-hour recycle handling."""

    def __init__(
        self,
        root: Path,
        recycle_root: Path,
        *,
        max_age_seconds: int = 24 * 3600,
        max_file_bytes: int = _MAX_FILE_BYTES,
    ) -> None:
        self.root = Path(os.path.abspath(root.expanduser()))
        self.recycle_root = Path(os.path.abspath(recycle_root.expanduser()))
        if (
            self.root == self.recycle_root
            or self.recycle_root.is_relative_to(self.root)
            or self.root.is_relative_to(self.recycle_root)
        ):
            raise SafeToolError("download recycle root must be separate")
        if isinstance(max_age_seconds, bool) or not 60 <= max_age_seconds <= 30 * 24 * 3600:
            raise SafeToolError("download retention is invalid")
        if isinstance(max_file_bytes, bool) or not 1 <= max_file_bytes <= 16 * 1024 * 1024:
            raise SafeToolError("download file limit is invalid")
        self.max_age_seconds = max_age_seconds
        self.max_file_bytes = max_file_bytes
        self.root.mkdir(parents=True, exist_ok=True)
        self.recycle_root.mkdir(parents=True, exist_ok=True)
        self._assert_directory(self.root)
        self._assert_directory(self.recycle_root)

    @staticmethod
    def _assert_directory(path: Path) -> None:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise SafeToolError("download isolation directory is unsafe")

    def _safe_name(self, name: str) -> str:
        clean = _clean_text(name, label="download name", maximum=160)
        if PurePath(clean).name != clean or clean in {".", ".."} or "/" in clean or "\\" in clean:
            raise SafeToolError("download name must be a plain file name")
        return clean

    def write(self, name: str, content: bytes) -> Path:
        clean = self._safe_name(name)
        if not isinstance(content, bytes) or len(content) > self.max_file_bytes:
            raise ResponseTooLargeError("download exceeds configured limit")
        target = self.root / clean
        try:
            target.lstat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise SafeToolError("download target is unavailable") from exc
        else:
            raise SafeToolError("download target already exists")
        temporary = self.root / f".{_sha256(clean)[:16]}.part"
        with open(temporary, "xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.replace(temporary, target)
        except Exception:
            # Keep failed temporary content recoverable as well.  The project
            # contract forbids permanently deleting material from the tool
            # area; the recycle directory is the only cleanup destination.
            failed = self.recycle_root / f"failed-{_sha256(clean + str(time.time_ns()))[:24]}.part"
            with suppress(OSError):
                shutil.move(str(temporary), str(failed))
            raise
        with suppress(OSError):
            target.chmod(0o600)
        return target

    def purge_expired(self, *, now: float | None = None) -> tuple[Path, ...]:
        current = time.time() if now is None else float(now)
        moved: list[Path] = []
        for candidate in self.root.rglob("*"):
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise SafeToolError("download isolation contains a symlink")
            if not stat.S_ISREG(info.st_mode):
                continue
            if current - info.st_mtime < self.max_age_seconds:
                continue
            destination = (
                self.recycle_root
                / f"{_sha256(str(candidate.relative_to(self.root)))[:24]}{candidate.suffix}"
            )
            if destination.exists():
                destination = self.recycle_root / (
                    f"{_sha256(str(candidate) + str(current))[:24]}{candidate.suffix}"
                )
            shutil.move(str(candidate), str(destination))
            moved.append(destination)
        return tuple(moved)

    cleanup = purge_expired


@dataclass(frozen=True, slots=True)
class _AttachmentBinding:
    event_key: tuple[str, str, str]
    account_id: str
    sender_id: str
    session_id: str
    principal_id: str
    attachment_id: str
    relative_path: str
    expires_at_ms: int


class AttachmentHandleStore:
    """In-memory binding for opaque, event/session-scoped file handles.

    A trusted ingress creates the handle before constructing ``InboundEvent``;
    the document reader can then verify that the same Bot account, event,
    session, and principal are presenting it.  Raw paths are never accepted
    from a tool request.  The store is intentionally non-persistent and
    expires handles so a copied token cannot be used indefinitely.
    """

    def __init__(self, *, ttl_seconds: int = 24 * 3600, clock_ms: Any | None = None) -> None:
        if isinstance(ttl_seconds, bool) or not 60 <= ttl_seconds <= 7 * 24 * 3600:
            raise SafeToolError("attachment handle TTL is invalid")
        self.ttl_seconds = ttl_seconds
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._lock = threading.RLock()
        self._handles: dict[str, _AttachmentBinding] = {}

    @staticmethod
    def _opaque(value: str, *, label: str) -> str:
        clean = _clean_text(value, label=label, maximum=256)
        if len(clean) < 16 or any(character.isspace() for character in clean):
            raise DocumentSecurityError(f"{label} is not an opaque handle")
        return clean

    def bind(
        self,
        event: InboundEvent,
        attachment: AttachmentRef,
        *,
        session_id: str,
        principal_id: str,
    ) -> None:
        if not isinstance(event, InboundEvent) or not isinstance(attachment, AttachmentRef):
            raise DocumentSecurityError("attachment binding is invalid")
        if attachment not in event.attachments or attachment.attachment_id is None:
            raise DocumentSecurityError("attachment is not part of the current event")
        handle = self._opaque(attachment.attachment_id, label="attachment handle")
        relative_path = attachment.relative_path
        if relative_path is None:
            raise DocumentSecurityError("attachment has no isolated path")
        session = _clean_text(session_id, label="attachment session", maximum=256)
        principal = _clean_text(principal_id, label="attachment principal", maximum=256)
        expires = int(self._clock_ms()) + self.ttl_seconds * 1000
        binding = _AttachmentBinding(
            event_key=event.source_key,
            account_id=event.account_id,
            sender_id=event.sender_id,
            session_id=session,
            principal_id=principal,
            attachment_id=handle,
            relative_path=relative_path,
            expires_at_ms=expires,
        )
        with self._lock:
            self._handles[_sha256(handle)] = binding

    register = bind

    def verify(
        self,
        event: InboundEvent,
        handle: str,
        *,
        session_id: str,
        principal_id: str,
    ) -> str:
        clean_handle = self._opaque(handle, label="attachment handle")
        now = int(self._clock_ms())
        with self._lock:
            binding = self._handles.get(_sha256(clean_handle))
            if binding is None or binding.expires_at_ms < now:
                raise DocumentSecurityError("attachment handle is unknown or expired")
            if (
                binding.event_key != event.source_key
                or binding.account_id != event.account_id
                or binding.sender_id != event.sender_id
                or binding.session_id != session_id
                or binding.principal_id != principal_id
            ):
                raise DocumentSecurityError("attachment handle scope mismatch")
            if not any(item.attachment_id == clean_handle for item in event.attachments):
                raise DocumentSecurityError("attachment handle is not in the current event")
            return binding.relative_path


def _safe_relative_path(root: Path, relative_path: str) -> Path:
    clean = _clean_text(relative_path, label="attachment relative path", maximum=512)
    if "\\" in clean or Path(clean).is_absolute() or PurePath(clean).anchor:
        raise DocumentSecurityError("attachment path must be relative")
    parts = PurePath(clean).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise DocumentSecurityError("attachment path contains traversal")
    candidate = Path(os.path.abspath(root / Path(*parts)))
    if not candidate.is_relative_to(root):
        raise DocumentSecurityError("attachment path escapes isolation root")
    return candidate


def _open_attachment(root: Path, relative_path: str) -> tuple[Path, bytes]:
    root_abs = Path(os.path.abspath(root.expanduser()))
    try:
        root_info = root_abs.lstat()
    except OSError as exc:
        raise DocumentSecurityError("attachment root is unavailable") from exc
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise DocumentSecurityError("attachment root is unsafe")
    target = _safe_relative_path(root_abs, relative_path)
    current = root_abs
    for part in target.relative_to(root_abs).parts:
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise DocumentSecurityError("attachment is unavailable") from exc
        if stat.S_ISLNK(info.st_mode):
            raise DocumentSecurityError("attachment path contains a symlink")
    try:
        info = target.lstat()
    except OSError as exc:
        raise DocumentSecurityError("attachment is unavailable") from exc
    if not stat.S_ISREG(info.st_mode):
        raise DocumentSecurityError("attachment is not a regular file")
    if info.st_size > _MAX_FILE_BYTES:
        raise ResponseTooLargeError("document exceeds configured limit")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(target, flags)
    except OSError as exc:
        raise DocumentSecurityError("attachment could not be opened") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size > _MAX_FILE_BYTES:
            raise DocumentSecurityError("attachment changed or is too large")
        content = os.read(descriptor, _MAX_FILE_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(content) > _MAX_FILE_BYTES:
        raise ResponseTooLargeError("document exceeds configured limit")
    return target, content


def _read_docx(content: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_ZIP_ENTRIES:
                raise DocumentSecurityError("document archive has too many members")
            names: set[str] = set()
            total = 0
            for info in infos:
                name = info.filename
                if (
                    name in names
                    or not name
                    or name.startswith(("/", "\\"))
                    or "\\" in name
                    or PurePath(name).anchor
                    or ":" in PurePath(name).parts[0]
                ):
                    raise DocumentSecurityError("document archive member path is unsafe")
                names.add(name)
                path = PurePath(name)
                if any(part in {"", ".", ".."} for part in path.parts):
                    raise DocumentSecurityError("document archive contains traversal")
                if info.flag_bits & 0x1:
                    raise DocumentSecurityError("encrypted documents are not supported")
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise DocumentSecurityError("document archive symlinks are not supported")
                if info.file_size > _MAX_ZIP_MEMBER:
                    raise ResponseTooLargeError("document archive member is too large")
                total += info.file_size
                if total > _MAX_ZIP_UNCOMPRESSED:
                    raise ResponseTooLargeError("document archive expands too far")
                if info.file_size > _MAX_ZIP_RATIO and info.compress_size == 0:
                    raise ResponseTooLargeError("document archive compression is unsafe")
                if info.compress_size and info.file_size / info.compress_size > _MAX_ZIP_RATIO:
                    raise ResponseTooLargeError("document archive compression ratio is unsafe")
                lowered = name.casefold()
                if "vbaproject" in lowered or lowered.endswith(
                    (
                        ".bin",
                        ".exe",
                        ".dll",
                        ".com",
                        ".cmd",
                        ".bat",
                        ".js",
                        ".jse",
                        ".vbs",
                        ".vbe",
                        ".ps1",
                        ".scr",
                        ".msi",
                        ".jar",
                    )
                ):
                    raise DocumentSecurityError(
                        "macro or executable archive member is not supported"
                    )
            if "word/document.xml" not in names:
                raise DocumentSecurityError("DOCX main document is missing")
            for name in names:
                if name.casefold().endswith(".rels"):
                    rels = archive.read(name).casefold()
                    if b'targetmode="external"' in rels or b"targetmode='external'" in rels:
                        raise DocumentSecurityError(
                            "external document relationships are not supported"
                        )
            xml_content = archive.read("word/document.xml")
    except (zipfile.BadZipFile, OSError, KeyError) as exc:
        raise DocumentSecurityError("DOCX archive is invalid") from exc
    try:
        root = ElementTree.fromstring(xml_content)
    except ElementTree.ParseError as exc:
        raise DocumentSecurityError("DOCX XML is invalid") from exc
    text_parts: list[str] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "t" and element.text:
            text_parts.append(element.text)
        elif element.tag.rsplit("}", 1)[-1] in {"br", "p"}:
            text_parts.append("\n")
    return "".join(text_parts)


def _read_document_content(path: Path, content: bytes) -> tuple[str, str]:
    suffix = path.suffix.casefold()
    if suffix not in _SUPPORTED_DOCUMENT_SUFFIXES:
        raise DocumentSecurityError("document type is not supported")
    if suffix == ".docx":
        text = _read_docx(content)
        format_name = "docx"
    elif suffix in {".html", ".htm"}:
        _, text = _extract_html(content, maximum=_MAX_DOCUMENT_TEXT)
        format_name = "html"
    else:
        try:
            text = content.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise DocumentSecurityError("document must be UTF-8 text") from exc
        format_name = suffix.lstrip(".")
    return format_name, text


class SafeReadOnlyTools:
    """Web/document handlers plus explicit policy and caller gates."""

    USER_SURFACES = frozenset({"private", "group"})

    def __init__(
        self,
        *,
        network: SafeNetworkClient | None = None,
        search_endpoint: str | None = None,
        document_root: Path | None = None,
        attachment_handles: AttachmentHandleStore | None = None,
        audit: MetadataAuditTrail | None = None,
        budget_ledger: BudgetLedger | None = None,
        enabled: bool = False,
    ) -> None:
        self.network = network or SafeNetworkClient()
        self.search_endpoint = (
            validate_public_url(search_endpoint, policy=self.network.policy)
            if search_endpoint is not None
            else None
        )
        self.document_root = (
            Path(os.path.abspath(document_root.expanduser())) if document_root is not None else None
        )
        self.attachment_handles = attachment_handles
        self.audit = audit or MetadataAuditTrail()
        self.budget_ledger = budget_ledger or BudgetLedger()
        self.enabled = bool(enabled)
        self._idempotency_lock = threading.RLock()
        self._idempotency: dict[str, tuple[str, str, ToolReceipt]] = {}

    @staticmethod
    def specs(
        *, enabled: bool = False, policy: NetworkPolicy | None = None
    ) -> tuple[ToolSpec, ...]:
        active_policy = policy or NetworkPolicy()
        common = {
            "caller_roles": frozenset({"owner", "user"}),
            "surfaces": SafeReadOnlyTools.USER_SURFACES,
            "allowed_roles": frozenset({"owner", "user"}),
            "allowed_surfaces": SafeReadOnlyTools.USER_SURFACES,
            "allowed_data_scopes": frozenset({"conversation", "public_web"}),
            "enabled": enabled,
            "requires_explicit_approval": True,
            "allow_model_execution": False,
            "timeout_seconds": active_policy.timeout_seconds,
            "rate_limit_per_minute": 12,
            "persist_result": False,
            "network_policy": active_policy.as_mapping(),
            "result_retention_seconds": 0,
            "budget": ToolBudget(
                max_requests_per_actor_per_minute=12,
                max_requests_per_session_per_minute=6,
                max_input_bytes=16 * 1024,
                max_output_bytes=active_policy.max_response_bytes,
            ),
        }
        document_common = dict(common)
        document_common["allowed_data_scopes"] = frozenset({"attachment"})
        return (
            ToolSpec(
                name="web_search",
                description=(
                    "Search the configured public web provider and return untrusted snippets."
                ),
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string", "minLength": 1, "maxLength": _MAX_QUERY_LENGTH}
                    },
                    "additionalProperties": False,
                },
                **common,
            ),
            ToolSpec(
                name="read_url",
                description="Read bounded text from one public HTTP(S) URL as untrusted data.",
                input_schema={
                    "type": "object",
                    "required": ["url"],
                    "properties": {
                        "url": {"type": "string", "minLength": 1, "maxLength": _MAX_URL_LENGTH}
                    },
                    "additionalProperties": False,
                },
                **common,
            ),
            ToolSpec(
                name="document_read",
                description=(
                    "Read one explicitly attached document from the isolated session directory."
                ),
                input_schema={
                    "type": "object",
                    "required": ["attachment_id"],
                    "properties": {
                        "attachment_id": {"type": "string", "minLength": 1, "maxLength": 256},
                    },
                    "additionalProperties": False,
                },
                **{key: value for key, value in document_common.items() if key != "network_policy"},
                network_policy={"local_only": True},
            ),
        )

    def web_search(self, query: str) -> dict[str, Any]:
        if self.search_endpoint is None:
            raise NetworkDisabledError("search provider is not configured")
        clean_query = _clean_text(query, label="search query", maximum=_MAX_QUERY_LENGTH)
        request_url = _search_endpoint_with_query(self.search_endpoint, clean_query)
        _, response, _ = self.network.fetch(
            request_url,
            allowed_content_types={"application/json"},
        )
        results, injection = _parse_search_results(
            _parse_json_bytes(response.body),
            maximum=self.network.policy.max_search_results,
        )
        return {
            "query": clean_query,
            "results": results,
            "untrusted": True,
            "prompt_injection_detected": injection,
        }

    def read_url(self, url: str) -> dict[str, Any]:
        validated, response, media_type = self.network.fetch(
            url,
            allowed_content_types={"text/html", "application/xhtml+xml", "text/plain"},
        )
        if media_type in {"text/html", "application/xhtml+xml"}:
            title, text = _extract_html(response.body, maximum=self.network.policy.max_text_chars)
        else:
            try:
                raw_text = response.body.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise NetworkRequestError("plain-text response is not UTF-8") from exc
            title = ""
            text = raw_text
        safe_text, injection = _prompt_safe_payload(
            text,
            maximum=self.network.policy.max_text_chars,
        )
        return {
            "url": validated.url,
            "title": title,
            "text": safe_text,
            "content_type": media_type,
            "untrusted": True,
            "prompt_injection_detected": injection,
        }

    def document_read(
        self,
        event: InboundEvent,
        *,
        attachment_id: str | None = None,
        attachment_index: int | None = None,
        session_id: str | None = None,
        principal_id: str | None = None,
    ) -> dict[str, Any]:
        if self.document_root is None:
            raise DocumentSecurityError("document isolation is not configured")
        if not isinstance(event, InboundEvent):
            raise DocumentSecurityError("document event is invalid")
        if self.attachment_handles is None:
            raise DocumentSecurityError("opaque attachment handle verifier is required")
        attachments = tuple(event.attachments)
        if attachment_index is not None:
            raise DocumentSecurityError("opaque attachment handle is required")
        if attachment_id is None:
            raise DocumentSecurityError("opaque attachment handle is required")
        if attachment_id is not None:
            clean_id = _clean_text(attachment_id, label="attachment id", maximum=256)
            matches = [item for item in attachments if item.attachment_id == clean_id]
            if len(matches) != 1:
                raise DocumentSecurityError("attachment id is not present in the current event")
            attachment = matches[0]
        else:  # pragma: no cover - guarded above; kept for type narrowing.
            raise DocumentSecurityError("opaque attachment handle is required")
        if not isinstance(attachment, AttachmentRef) or attachment.kind.casefold() not in {
            "document",
            "file",
        }:
            raise DocumentSecurityError("attachment is not a document")
        if attachment.relative_path is None:
            raise DocumentSecurityError("attachment has no isolated local path")
        if session_id is None or principal_id is None:
            raise DocumentSecurityError("attachment caller scope is required")
        verified_path = self.attachment_handles.verify(
            event,
            attachment.attachment_id or "",
            session_id=session_id,
            principal_id=principal_id,
        )
        if verified_path != attachment.relative_path:
            raise DocumentSecurityError("attachment handle path mismatch")
        path, content = _open_attachment(self.document_root, attachment.relative_path)
        if attachment.declared_size_bytes is not None and (
            isinstance(attachment.declared_size_bytes, bool)
            or attachment.declared_size_bytes != len(content)
        ):
            raise DocumentSecurityError("attachment declared size does not match")
        if (
            attachment.file_name is not None
            and Path(attachment.file_name).name != attachment.file_name
        ):
            raise DocumentSecurityError("attachment file name is invalid")
        format_name, raw_text = _read_document_content(path, content)
        text, injection = _prompt_safe_payload(raw_text, maximum=_MAX_DOCUMENT_TEXT)
        return {
            "file_name": attachment.file_name or path.name,
            "format": format_name,
            "text": text,
            "sha256": _sha256(content),
            "size_bytes": len(content),
            "untrusted": True,
            "prompt_injection_detected": injection,
        }

    def _receipt(
        self,
        *,
        context: ToolCallContext,
        tool_name: str,
        parameters: Mapping[str, Any],
        state: ToolReceiptState,
        reason: str,
        result: Any = None,
        error_code: str | None = None,
        request_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ToolReceipt:
        try:
            parameter_sha = parameter_approval_hash(
                tool_name,
                {
                    "parameters": normalize_parameters(parameters),
                    "session_id": context.session_id or "unbound-session",
                    "data_scope": context.data_scope,
                },
            )
        except (TypeError, ValueError, SafeToolError):
            # A malformed direct-call payload must still produce a bounded,
            # non-throwing denial.  Never include that payload in the fallback
            # digest or in the receipt.
            parameter_sha = _sha256(
                f"invalid\0{tool_name!s}\0{context.session_id}\0{context.data_scope}"
            )
        receipt_key = idempotency_key
        if receipt_key is None:
            receipt_key = _sha256(f"{context.session_id}\0{tool_name!s}\0{parameter_sha}")[:48]
        else:
            try:
                receipt_key = _clean_text(
                    receipt_key,
                    label="tool idempotency key",
                    maximum=256,
                )
            except SafeToolError:
                receipt_key = _sha256(f"{context.session_id}\0{tool_name!s}\0{parameter_sha}")[:48]
        return ToolReceipt(
            request_id=request_id or _sha256(str(time.time_ns()))[:32],
            tool_name=tool_name,
            state=state,
            idempotency_key=receipt_key,
            parameter_sha256=parameter_sha,
            reason=reason,
            result=result,
            error_code=error_code,
            completed_at_ms=int(time.time() * 1000),
        )

    def invoke(
        self,
        context: ToolCallContext,
        tool_name: str,
        parameters: Mapping[str, Any],
        *,
        approved: bool = False,
        idempotency_key: str | None = None,
        event: InboundEvent | None = None,
    ) -> ToolReceipt:
        """Execute one explicitly approved call with caller/session isolation."""

        try:
            spec = next(item for item in self.specs(enabled=self.enabled) if item.name == tool_name)
        except StopIteration:
            return self._receipt(
                context=context,
                tool_name=tool_name,
                parameters=parameters,
                state=ToolReceiptState.DENIED,
                reason="unknown_tool",
                error_code="unknown_tool",
            )
        if not self.enabled:
            return self._receipt(
                context=context,
                tool_name=tool_name,
                parameters=parameters,
                state=ToolReceiptState.DENIED,
                reason="tool_disabled",
                error_code="tool_disabled",
            )
        if context.source == "model_shadow":
            return self._receipt(
                context=context,
                tool_name=tool_name,
                parameters=parameters,
                state=ToolReceiptState.DENIED,
                reason="model_shadow_only",
                error_code="model_shadow_only",
            )
        if context.actor_role not in spec.caller_roles or context.surface not in spec.surfaces:
            return self._receipt(
                context=context,
                tool_name=tool_name,
                parameters=parameters,
                state=ToolReceiptState.DENIED,
                reason="caller_or_surface_not_allowed",
                error_code="caller_or_surface_not_allowed",
            )
        if (
            spec.allowed_data_scopes is not None
            and context.data_scope not in spec.allowed_data_scopes
        ):
            return self._receipt(
                context=context,
                tool_name=tool_name,
                parameters=parameters,
                state=ToolReceiptState.DENIED,
                reason="data_scope_not_allowed",
                error_code="data_scope_not_allowed",
                idempotency_key=idempotency_key,
            )
        if not approved:
            return self._receipt(
                context=context,
                tool_name=tool_name,
                parameters=parameters,
                state=ToolReceiptState.DENIED,
                reason="default_deny",
                error_code="default_deny",
                idempotency_key=idempotency_key,
            )
        try:
            normalized = normalize_parameters(parameters)
            if not _schema_matches(normalized, spec.input_schema):
                raise SafeToolError("tool parameters are invalid")
            parameter_json = json.dumps(
                normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        except (TypeError, ValueError, SafeToolError):
            return self._receipt(
                context=context,
                tool_name=tool_name,
                parameters={},
                state=ToolReceiptState.FAILED,
                reason="invalid_parameters",
                error_code="invalid_parameters",
            )
        parameter_sha = parameter_approval_hash(
            tool_name,
            {
                "parameters": normalized,
                "session_id": context.session_id,
                "data_scope": context.data_scope,
            },
        )
        if idempotency_key:
            try:
                idem = _clean_text(
                    idempotency_key,
                    label="tool idempotency key",
                    maximum=256,
                )
            except SafeToolError:
                return self._receipt(
                    context=context,
                    tool_name=tool_name,
                    parameters=normalized,
                    state=ToolReceiptState.DENIED,
                    reason="invalid_idempotency_key",
                    error_code="invalid_idempotency_key",
                )
        else:
            idem = _sha256(f"{context.session_id}\0{parameter_sha}")[:48]
        with self._idempotency_lock:
            prior = self._idempotency.get(idem)
            if prior is not None:
                prior_tool, prior_sha, prior_receipt = prior
                if prior_tool != tool_name or prior_sha != parameter_sha:
                    return self._receipt(
                        context=context,
                        tool_name=tool_name,
                        parameters=normalized,
                        state=ToolReceiptState.DENIED,
                        reason="idempotency_key_reused_for_different_request",
                        error_code="idempotency_conflict",
                        idempotency_key=idem,
                    )
                return self._receipt(
                    context=context,
                    tool_name=tool_name,
                    parameters=normalized,
                    state=ToolReceiptState.DUPLICATE,
                    reason="idempotency_key_already_seen",
                    result=prior_receipt.result,
                    error_code=prior_receipt.error_code,
                    request_id=prior_receipt.request_id,
                    idempotency_key=idem,
                )
        try:
            self.budget_ledger.reserve(
                tool_name=tool_name,
                actor_id=context.principal_id,
                session_id=context.session_id,
                budget=spec.budget,
                input_bytes=len(parameter_json.encode("utf-8")),
            )
            if tool_name == "web_search":
                result = self.web_search(str(normalized.get("query", "")))
            elif tool_name == "read_url":
                result = self.read_url(str(normalized.get("url", "")))
            elif tool_name == "document_read":
                if event is None:
                    raise DocumentSecurityError("document event is required")
                result = self.document_read(
                    event,
                    attachment_id=normalized.get("attachment_id"),
                    attachment_index=normalized.get("attachment_index"),
                    session_id=context.session_id,
                    principal_id=context.principal_id,
                )
            else:
                raise SafeToolError("unknown tool")
            result_json = json.dumps(
                result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            if (
                spec.budget
                and spec.budget.max_output_bytes is not None
                and len(result_json.encode("utf-8")) > spec.budget.max_output_bytes
            ):
                raise ResponseTooLargeError("tool output exceeds configured limit")
            receipt = self._receipt(
                context=context,
                tool_name=tool_name,
                parameters=normalized,
                state=ToolReceiptState.SUCCEEDED,
                reason="execution_completed",
                result=result,
                idempotency_key=idem,
            )
        except TimeoutError:
            receipt = self._receipt(
                context=context,
                tool_name=tool_name,
                parameters=normalized,
                state=ToolReceiptState.TIMED_OUT,
                reason="tool_timeout",
                error_code="timeout",
                idempotency_key=idem,
            )
        except BudgetExceededError:
            receipt = self._receipt(
                context=context,
                tool_name=tool_name,
                parameters=normalized,
                state=ToolReceiptState.RATE_LIMITED,
                reason="tool_budget_exceeded",
                error_code="budget",
                idempotency_key=idem,
            )
        except NetworkDisabledError:
            receipt = self._receipt(
                context=context,
                tool_name=tool_name,
                parameters=normalized,
                state=ToolReceiptState.UNKNOWN,
                reason="network_disabled",
                error_code="network_disabled",
                idempotency_key=idem,
            )
        except SafeToolError as exc:
            receipt = self._receipt(
                context=context,
                tool_name=tool_name,
                parameters=normalized,
                state=ToolReceiptState.FAILED,
                reason="tool_failed",
                error_code=type(exc).__name__.casefold(),
                idempotency_key=idem,
            )
        self.audit.record(
            tool_name=tool_name,
            actor_id=context.principal_id,
            session_id=context.session_id,
            parameter_sha256=parameter_sha,
            outcome=receipt.state,
            byte_count=len(json.dumps(receipt.result, ensure_ascii=False, default=str).encode())
            if receipt.result is not None
            else 0,
        )
        with self._idempotency_lock:
            self._idempotency[idem] = (tool_name, parameter_sha, receipt)
        return receipt


def register_safe_tools(governance: Any, service: SafeReadOnlyTools) -> None:
    """Register disabled descriptors without exposing caller context to JSON.

    The actual deterministic adapter should call ``SafeReadOnlyTools.invoke``
    after it has authenticated the caller and current session.  Registry
    handlers intentionally fail closed because a generic governance handler
    cannot safely invent an ``InboundEvent`` or caller context.
    """

    for spec in service.specs(enabled=service.enabled):
        if getattr(governance.registry, "has", lambda _name: False)(spec.name):
            continue

        def _missing_context(_parameters: Mapping[str, Any], *, _name: str = spec.name) -> Any:
            return ToolExecutionResult(
                state=ToolReceiptState.UNKNOWN,
                error_code=f"{_name}_caller_context_required",
            )

        governance.register(spec, _missing_context)


# Friendly aliases for adapters/tests that use the names from the phase plan.
SafeNetworkPolicy = NetworkPolicy
SafeWebClient = SafeNetworkClient
DocumentReader = SafeReadOnlyTools
DownloadSandbox = DownloadIsolation


__all__ = [
    "AttachmentHandleStore",
    "BudgetExceededError",
    "DocumentReader",
    "DocumentSecurityError",
    "DownloadIsolation",
    "DownloadSandbox",
    "HttpResponse",
    "HttpTransport",
    "MetadataAuditTrail",
    "NetworkDisabledError",
    "NetworkPolicy",
    "NetworkRequestError",
    "SafeNetworkClient",
    "SafeNetworkPolicy",
    "SafeReadOnlyTools",
    "SafeToolError",
    "SafeWebClient",
    "SocketHttpTransport",
    "ToolCallContext",
    "UnsafeUrlError",
    "ValidatedUrl",
    "register_safe_tools",
    "validate_public_url",
]
