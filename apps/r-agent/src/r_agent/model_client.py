"""OpenAI-compatible model adapter for OpenAI, GLM, and DeepSeek."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib import error, request
from urllib.parse import urlsplit


class ModelError(RuntimeError):
    """A provider request failed or returned an unusable response."""


@dataclass(frozen=True, slots=True)
class ModelConfig:
    provider: str
    base_url: str
    model: str
    api_key: str
    timeout_seconds: float = 20.0
    thinking: str | None = None


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class ChatResult:
    content: str | None
    tool_calls: tuple[ToolCall, ...] = ()

    def assistant_message(self) -> dict[str, object]:
        message: dict[str, object] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.call_id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in self.tool_calls
            ]
        return message


def parse_chat_body(body: object) -> ChatResult:
    """Normalize an OpenAI-compatible ``/chat/completions`` body."""
    if not isinstance(body, Mapping):
        raise ModelError("model provider response was malformed")
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelError("model provider response was malformed") from exc
    if not isinstance(message, Mapping):
        raise ModelError("model provider response was malformed")
    content = message.get("content")
    text = content.strip()[:4000] if isinstance(content, str) and content.strip() else None
    calls: list[ToolCall] = []
    raw_calls = message.get("tool_calls") or []
    if not isinstance(raw_calls, list):
        raise ModelError("model provider tool calls were malformed")
    for index, raw in enumerate(raw_calls[:8]):
        if not isinstance(raw, Mapping) or not isinstance(raw.get("function"), Mapping):
            raise ModelError("model provider tool call was malformed")
        function = raw["function"]
        name = function.get("name")
        arguments = function.get("arguments", "{}")
        if isinstance(arguments, Mapping):
            arguments = json.dumps(arguments, ensure_ascii=False)
        if not isinstance(name, str) or not name or not isinstance(arguments, str):
            raise ModelError("model provider tool call was malformed")
        call_id = raw.get("id") if isinstance(raw.get("id"), str) else f"call_{index}"
        calls.append(ToolCall(call_id=call_id, name=name[:64], arguments=arguments[:8000]))
    if text is None and not calls:
        raise ModelError("model provider returned empty content")
    return ChatResult(content=text, tool_calls=tuple(calls))


class OpenAICompatibleClient:
    """Minimal dependency-free chat client using the common /chat/completions API."""

    def __init__(self, config: ModelConfig) -> None:
        if not config.provider.strip():
            raise ModelError("model provider is missing")
        parsed = urlsplit(config.base_url.strip())
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ModelError("model base URL must be an HTTPS URL without credentials")
        if not config.model.strip():
            raise ModelError("model name is missing")
        if not config.api_key.strip():
            raise ModelError("model API key is missing")
        if config.thinking not in {None, "enabled", "disabled"}:
            raise ModelError("model thinking mode must be enabled or disabled")
        self.config = config

    async def complete(self, *, system: str, user: str, max_tokens: int = 400) -> str:
        return await self.complete_messages(
            messages=(
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ),
            max_tokens=max_tokens,
        )

    async def complete_messages(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        max_tokens: int = 400,
    ) -> str:
        if not 2 <= len(messages) <= 42:
            raise ModelError("model context must contain between 2 and 42 messages")
        normalized: list[dict[str, str]] = []
        total_chars = 0
        for index, message in enumerate(messages):
            role = message.get("role")
            content = message.get("content")
            if role not in {"system", "user", "assistant"}:
                raise ModelError("model context contains an unsupported role")
            if not isinstance(content, str) or not content.strip():
                raise ModelError("model prompts must not be empty")
            if index == 0 and role != "system":
                raise ModelError("model context must start with a system message")
            if len(content) > 32_000:
                raise ModelError("one model message exceeded the size limit")
            total_chars += len(content)
            normalized.append({"role": role, "content": content})
        if total_chars > 64_000:
            raise ModelError("model context exceeded the total size limit")
        payload_data: dict[str, object] = {
            "model": self.config.model,
            "messages": normalized,
            "temperature": 0.4,
            "max_tokens": max(1, min(max_tokens, 1200)),
        }
        if self.config.thinking is not None:
            payload_data["thinking"] = {"type": self.config.thinking}
        payload = json.dumps(payload_data, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            f"{self.config.base_url.rstrip('/')}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        def perform() -> str:
            try:
                with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                    raw_body = response.read(1_000_001)
                if len(raw_body) > 1_000_000:
                    raise ModelError("model provider response exceeded size limit")
                body = json.loads(raw_body)
            except ModelError:
                raise
            except (error.URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
                raise ModelError("model provider request failed") from exc
            if not isinstance(body, Mapping):
                raise ModelError("model provider response was malformed")
            try:
                content = body["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise ModelError("model provider response was malformed") from exc
            if not isinstance(content, str) or not content.strip():
                raise ModelError("model provider returned empty content")
            return content.strip()[:4000]

        return await asyncio.to_thread(perform)

    async def chat(
        self,
        *,
        messages: Sequence[Mapping[str, object]],
        tools: Sequence[Mapping[str, object]] | None = None,
        max_tokens: int = 600,
        temperature: float = 0.5,
    ) -> ChatResult:
        """One function-calling turn; messages may include tool/assistant tool_calls."""
        if not 2 <= len(messages) <= 80:
            raise ModelError("model context must contain between 2 and 80 messages")
        total = sum(len(json.dumps(item, ensure_ascii=False)) for item in messages)
        if total > 120_000:
            raise ModelError("model context exceeded the total size limit")
        payload_data: dict[str, object] = {
            "model": self.config.model,
            "messages": [dict(item) for item in messages],
            "temperature": temperature,
            "max_tokens": max(1, min(max_tokens, 2000)),
        }
        if tools:
            payload_data["tools"] = [dict(item) for item in tools]
            payload_data["tool_choice"] = "auto"
        if self.config.thinking is not None:
            payload_data["thinking"] = {"type": self.config.thinking}
        payload = json.dumps(payload_data, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            f"{self.config.base_url.rstrip('/')}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        def perform() -> ChatResult:
            try:
                with request.urlopen(req, timeout=self.config.timeout_seconds * 2) as response:
                    raw_body = response.read(2_000_001)
                if len(raw_body) > 2_000_000:
                    raise ModelError("model provider response exceeded size limit")
                body = json.loads(raw_body)
            except ModelError:
                raise
            except (error.URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
                raise ModelError("model provider request failed") from exc
            return parse_chat_body(body)

        return await asyncio.to_thread(perform)
