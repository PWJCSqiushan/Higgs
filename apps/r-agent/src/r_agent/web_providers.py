"""Web search / page reading providers for agent tools (M2).

* ``ZhipuWebSearch`` uses the Zhipu ``/web_search`` API with the same key as GLM.
* ``SearxngSearch`` queries a self-hosted SearXNG ``?format=json`` endpoint.
* ``SafePageReader`` reuses ``SafeNetworkClient`` (public-IP only, DNS-rebinding
  and redirect checks, size/content-type limits) to read a page's text.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from r_agent.safe_tools import (
    NetworkPolicy,
    SafeNetworkClient,
    SafeToolError,
    SocketHttpTransport,
    _extract_html,
    _safe_untrusted_text,
)

_SNIPPET = 300


def _clean(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text, _ = _safe_untrusted_text(" ".join(value.split()), maximum=limit)
    return text


class ZhipuWebSearch:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://open.bigmodel.cn/api/paas/v4",
        engine: str = "search_std",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.engine = engine
        self.transport = transport

    async def search(self, query: str) -> list[dict[str, str]]:
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            response = await client.post(
                f"{self.base_url}/web_search",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"search_engine": self.engine, "search_query": query[:120]},
            )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("search_result") if isinstance(payload, dict) else None
        results = []
        for item in (items or [])[:8]:
            if not isinstance(item, dict):
                continue
            results.append(
                {
                    "title": _clean(item.get("title"), 200),
                    "url": _clean(item.get("link"), 500),
                    "snippet": _clean(item.get("content"), _SNIPPET),
                    "site": _clean(item.get("media"), 60),
                }
            )
        return results


class SearxngSearch:
    def __init__(self, *, endpoint: str, transport: httpx.AsyncBaseTransport | None = None):
        self.endpoint = endpoint
        self.transport = transport

    async def search(self, query: str) -> list[dict[str, str]]:
        async with httpx.AsyncClient(timeout=20, transport=self.transport) as client:
            response = await client.get(
                self.endpoint, params={"q": query[:120], "format": "json", "language": "zh-CN"}
            )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("results") if isinstance(payload, dict) else None
        return [
            {
                "title": _clean(item.get("title"), 200),
                "url": _clean(item.get("url"), 500),
                "snippet": _clean(item.get("content"), _SNIPPET),
            }
            for item in (items or [])[:8]
            if isinstance(item, dict)
        ]


class SafePageReader:
    def __init__(self, client: SafeNetworkClient | None = None, *, max_chars: int = 2_500):
        self.client = client or SafeNetworkClient(
            policy=NetworkPolicy(allow_network=True, timeout_seconds=10.0),
            transport=SocketHttpTransport(),
        )
        self.max_chars = max_chars

    async def read(self, url: str) -> dict[str, str]:
        def perform() -> dict[str, str]:
            try:
                validated, response, media_type = self.client.fetch(
                    url, allowed_content_types=("text/html", "text/plain", "application/xhtml+xml")
                )
            except SafeToolError as exc:
                return {"error": f"无法读取：{type(exc).__name__}"}
            if media_type == "text/plain":
                text = _clean(response.body.decode("utf-8", "replace"), self.max_chars)
                return {"url": validated.url, "title": "", "text": text}
            title, text = _extract_html(response.body, maximum=self.max_chars * 2)
            return {
                "url": validated.url,
                "title": title[:200],
                "text": _clean(text, self.max_chars),
            }

        return await asyncio.to_thread(perform)
