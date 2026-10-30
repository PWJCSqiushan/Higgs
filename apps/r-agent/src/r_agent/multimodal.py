"""Multimodal helpers (Higgs 3.0 M6): image captions and multi-bubble replies."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from urllib import error, request

from r_agent.events import InboundEvent
from r_agent.safe_tools import NetworkPolicy, SafeNetworkClient, SafeToolError, SocketHttpTransport

_log = logging.getLogger(__name__)

MSG_BREAK = "[MSG_BREAK]"
BUBBLE_GUIDE = (
    "- 群聊或私聊里想分开说的话，可以用 [MSG_BREAK] 隔开，最多分成三条短消息，"
    "像真人一样连发，没必要时就只发一条。"
)
_IMAGE_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp")


def split_bubbles(text: str, *, max_bubbles: int = 3, max_chars: int = 1_500) -> list[str]:
    """Split on ``[MSG_BREAK]`` (bounded), then hard-wrap anything too long."""
    parts = [part.strip() for part in text.split(MSG_BREAK)]
    parts = [part for part in parts if part]
    if not parts:
        return []
    if len(parts) > max_bubbles:
        parts = [*parts[: max_bubbles - 1], "\n".join(parts[max_bubbles - 1 :])]
    bubbles: list[str] = []
    for part in parts:
        while len(part) > max_chars:
            cut = max(part.rfind("\n", 0, max_chars), part.rfind("。", 0, max_chars))
            cut = cut + 1 if cut > max_chars // 2 else max_chars
            bubbles.append(part[:cut].strip())
            part = part[cut:].strip()
        if part:
            bubbles.append(part)
    return bubbles


@dataclass(slots=True)
class RecentImageCache:
    """In-memory, short-lived record of each sender's last image message.

    Lets "send the picture, then @Higgs in a separate message" work.  URLs
    never leave process memory and expire after ``max_age_seconds``.
    """

    max_age_seconds: float = 180.0
    max_entries: int = 500
    _items: dict[tuple[str, str, str], tuple[float, str, tuple[str, ...]]] = field(
        default_factory=dict
    )

    @staticmethod
    def _key(event: InboundEvent) -> tuple[str, str, str]:
        return (event.channel, event.conversation_id, event.sender_id)

    def remember(self, event: InboundEvent, *, now: float | None = None) -> None:
        if not event.image_urls:
            return
        stamp = time.monotonic() if now is None else now
        if len(self._items) >= self.max_entries:
            oldest = min(self._items, key=lambda k: self._items[k][0])
            self._items.pop(oldest, None)
        self._items[self._key(event)] = (stamp, event.message_id, event.image_urls[:2])

    def take(
        self, event: InboundEvent, *, now: float | None = None
    ) -> tuple[str, tuple[str, ...]] | None:
        """Pop the sender's recent image (other than this message), if still fresh."""
        item = self._items.get(self._key(event))
        if item is None:
            return None
        stamp, message_id, urls = item
        current = time.monotonic() if now is None else now
        if message_id == event.message_id or message_id in event.merged_message_ids:
            return None
        self._items.pop(self._key(event), None)
        if current - stamp > self.max_age_seconds:
            return None
        return message_id, urls


def strip_breaks(text: str) -> str:
    return re.sub(r"\s*\[MSG_BREAK\]\s*", "\n", text).strip()


@dataclass(slots=True)
class VisionCaptioner:
    """Describe an inbound image with an OpenAI-compatible vision model (e.g. GLM-4V)."""

    base_url: str
    model: str
    api_key: str
    daily_limit: int = 100
    timeout_seconds: float = 30.0
    fetcher: SafeNetworkClient | None = None
    url_fallback: bool = True
    _used: deque[float] = field(default_factory=deque)

    def _fetch_data_url(self, url: str) -> str | None:
        client = self.fetcher or SafeNetworkClient(
            policy=NetworkPolicy(
                allow_network=True, timeout_seconds=10.0, max_response_bytes=4 * 1024 * 1024
            ),
            transport=SocketHttpTransport(),
        )
        try:
            _validated, response, media_type = client.fetch(url, allowed_content_types=_IMAGE_TYPES)
        except SafeToolError as exc:
            _log.info("vision_fetch_failed type=%s", type(exc).__name__)
            return None
        encoded = base64.b64encode(response.body).decode("ascii")
        return f"data:{media_type};base64,{encoded}"

    def _within_budget(self) -> bool:
        now = time.monotonic()
        while self._used and now - self._used[0] > 86_400:
            self._used.popleft()
        if len(self._used) >= self.daily_limit:
            return False
        self._used.append(now)
        return True

    def _ask(self, data_url: str) -> str | None:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "用不超过40个汉字客观描述这张图片的内容。"
                            "如果有文字，概括其中要点。"
                            "只输出描述。",
                        },
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "max_tokens": 120,
            "temperature": 0.2,
        }
        req = request.Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read(1_000_000))
            content = body["choices"][0]["message"]["content"]
        except (error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as exc:
            _log.info("vision_request_failed type=%s", type(exc).__name__)
            return None
        if not isinstance(content, str):
            return None
        clean = " ".join(content.split()).strip("。 ")
        for token in ("[", "]", "<", ">"):
            clean = clean.replace(token, "")
        return clean[:60] or None

    async def caption(self, url: str) -> str | None:
        if not self._within_budget():
            return None

        def perform() -> str | None:
            data_url = self._fetch_data_url(url)
            if data_url:
                return self._ask(data_url)
            # The QQ CDN sometimes refuses non-client downloads; let the vision
            # provider fetch the (short-lived, already https) URL itself.
            return self._ask(url) if self.url_fallback and url.startswith("https://") else None

        return await asyncio.to_thread(perform)

    async def annotate_quoted(self, event: InboundEvent) -> tuple[InboundEvent, list[str]]:
        """Caption images inside the message the asker quoted."""
        from dataclasses import replace

        quoted = event.quoted
        if quoted is None or not quoted.image_urls:
            return event, []
        captions = [c for url in quoted.image_urls[:2] if (c := await self.caption(url))]
        if not captions:
            return event, []
        text = quoted.text
        for caption in captions:
            if "[图片]" in text:
                text = text.replace("[图片]", f"[图片：{caption}]", 1)
            else:
                text = f"{text} [图片：{caption}]".strip()
        new_quoted = replace(quoted, text=text, image_urls=())
        note = "，".join(captions)
        return (
            replace(
                event,
                quoted=new_quoted,
                text=f"{event.text}\n（被引用的图片内容：{note}）",
                display_text=f"{event.timeline_text}（被引用的图片内容：{note}）",
            ),
            captions,
        )

    async def annotate_recent(
        self, event: InboundEvent, urls: tuple[str, ...]
    ) -> tuple[InboundEvent, list[str]]:
        """Caption an image the same person sent just before this text message."""
        from dataclasses import replace

        captions = [c for url in urls[:2] if (c := await self.caption(url))]
        if not captions:
            return event, []
        note = "，".join(captions)
        return (
            replace(
                event,
                text=f"{event.text}\n（对方刚才发的图片内容：{note}）",
                display_text=f"{event.timeline_text}（对方刚才发的图片内容：{note}）",
            ),
            captions,
        )

    async def annotate(self, event: InboundEvent) -> tuple[InboundEvent, list[str]]:
        """Return the event with ``[图片：…]`` captions folded into its text."""
        from dataclasses import replace

        captions: list[str] = []
        for url in event.image_urls[:2]:
            text = await self.caption(url)
            if text:
                captions.append(text)
        if not captions:
            return event, []
        display = event.timeline_text
        for caption in captions:
            display = display.replace("[图片]", f"[图片：{caption}]", 1)
        note = "，".join(captions)
        new_text = f"{event.text}\n（图片内容：{note}）".strip()
        return replace(event, text=new_text, display_text=display, image_urls=()), captions
