"""Validated OpenAI-compatible embedding client."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib import error, request
from urllib.parse import urlsplit


class EmbeddingError(RuntimeError):
    """Embedding configuration, transport, or response validation failed."""


class EmbeddingClient(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]: ...

    async def embed_one(self, text: str) -> tuple[float, ...]: ...


@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    base_url: str
    model: str
    api_key: str
    dimensions: int = 256
    timeout_seconds: float = 20.0


class OpenAICompatibleEmbeddingClient:
    """Dependency-free `/embeddings` client with strict bounded validation."""

    def __init__(self, config: EmbeddingConfig) -> None:
        parsed = urlsplit(config.base_url.strip())
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise EmbeddingError("embedding base URL must be HTTPS without credentials")
        if not config.model.strip():
            raise EmbeddingError("embedding model is missing")
        if not config.api_key.strip():
            raise EmbeddingError("embedding API key is missing")
        if config.dimensions not in {256, 512, 1024, 2048}:
            raise EmbeddingError("embedding dimensions must be 256, 512, 1024, or 2048")
        if not 1 <= config.timeout_seconds <= 60:
            raise EmbeddingError("embedding timeout must be between 1 and 60 seconds")
        self.config = config

    async def embed_one(self, text: str) -> tuple[float, ...]:
        return (await self.embed((text,)))[0]

    async def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        if not 1 <= len(texts) <= 64:
            raise EmbeddingError("embedding batch must contain between 1 and 64 texts")
        normalized: list[str] = []
        for text in texts:
            if not isinstance(text, str) or not text.strip():
                raise EmbeddingError("embedding input must not be empty")
            clean = text.strip()
            if len(clean) > 8_000:
                raise EmbeddingError("embedding input exceeded 8000 characters")
            normalized.append(clean)
        payload = json.dumps(
            {
                "model": self.config.model,
                "input": normalized,
                "dimensions": self.config.dimensions,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        req = request.Request(
            f"{self.config.base_url.rstrip('/')}/embeddings",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        def perform() -> list[tuple[float, ...]]:
            try:
                with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                    raw_body = response.read(4_000_001)
                if len(raw_body) > 4_000_000:
                    raise EmbeddingError("embedding response exceeded size limit")
                body = json.loads(raw_body)
            except EmbeddingError:
                raise
            except (error.URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
                raise EmbeddingError("embedding provider request failed") from exc
            if not isinstance(body, Mapping) or not isinstance(body.get("data"), list):
                raise EmbeddingError("embedding provider response was malformed")
            ordered: list[tuple[float, ...] | None] = [None] * len(normalized)
            for item in body["data"]:
                if not isinstance(item, Mapping):
                    raise EmbeddingError("embedding item was malformed")
                index = item.get("index")
                raw_vector = item.get("embedding")
                if (
                    not isinstance(index, int)
                    or isinstance(index, bool)
                    or not 0 <= index < len(ordered)
                    or ordered[index] is not None
                    or not isinstance(raw_vector, list)
                    or len(raw_vector) != self.config.dimensions
                ):
                    raise EmbeddingError("embedding item was malformed")
                vector: list[float] = []
                for value in raw_vector:
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        raise EmbeddingError("embedding vector contained a non-number")
                    number = float(value)
                    if not math.isfinite(number):
                        raise EmbeddingError("embedding vector contained a non-finite number")
                    vector.append(number)
                if not any(vector):
                    raise EmbeddingError("embedding vector must not be all zero")
                ordered[index] = tuple(vector)
            if any(item is None for item in ordered):
                raise EmbeddingError("embedding response omitted an input")
            return [item for item in ordered if item is not None]

        return await asyncio.to_thread(perform)
