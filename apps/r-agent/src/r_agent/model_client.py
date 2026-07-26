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
