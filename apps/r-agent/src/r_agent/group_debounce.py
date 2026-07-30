"""Quiet-window batching for consecutive QQ messages from one sender."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace

from r_agent.access import IngressDecision
from r_agent.events import ConversationKind, InboundEvent
from r_agent.ingest import IngestResult

BatchHandler = Callable[[InboundEvent, IngestResult], Awaitable[None]]


class GroupMessageDebouncer:
    """Merge rapid private/group fragments without blocking the receive loop."""

    def __init__(
        self,
        *,
        quiet_seconds: float,
        handler: BatchHandler,
        private_quiet_seconds: float | None = None,
    ) -> None:
        if not 0.5 <= quiet_seconds <= 10:
            raise ValueError("quiet_seconds must be between 0.5 and 10")
        private_seconds = quiet_seconds if private_quiet_seconds is None else private_quiet_seconds
        if not 0.5 <= private_seconds <= 10:
            raise ValueError("private_quiet_seconds must be between 0.5 and 10")
        self.quiet_seconds = quiet_seconds
        self.private_quiet_seconds = private_seconds
        self.handler = handler
        self._pending: dict[str, list[tuple[InboundEvent, IngestResult]]] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    @staticmethod
    def _key(event: InboundEvent) -> str:
        return f"{event.conversation_id}:{event.sender_id}"

    @staticmethod
    def _merge(items: list[tuple[InboundEvent, IngestResult]]) -> tuple[InboundEvent, IngestResult]:
        events = [item[0] for item in items]
        latest = events[-1]
        text = "\n".join(event.text for event in events if event.text).strip()
        reply_ids = [event.reply_message_id for event in events if event.reply_message_id]
        attachments = tuple(attachment for event in events for attachment in event.attachments)[:32]
        merged = replace(
            latest,
            text=text,
            mentioned=any(event.mentioned for event in events),
            replied_to_account=any(event.replied_to_account for event in events),
            reply_message_id=reply_ids[-1] if reply_ids else None,
            attachments=attachments,
        )
        result = IngestResult(
            decision=IngressDecision.ACCEPT,
            stored=any(item[1].stored for item in items),
            duplicate=all(item[1].duplicate for item in items),
        )
        return merged, result

    async def submit(self, event: InboundEvent, result: IngestResult) -> None:
        if (
            event.conversation_kind not in {ConversationKind.GROUP, ConversationKind.PRIVATE}
            or not result.stored
        ):
            await self.handler(event, result)
            return
        key = self._key(event)
        self._pending.setdefault(key, []).append((event, result))
        previous = self._tasks.get(key)
        if previous is not None:
            previous.cancel()
        quiet_seconds = (
            self.private_quiet_seconds
            if event.conversation_kind is ConversationKind.PRIVATE
            else self.quiet_seconds
        )
        task = asyncio.create_task(self._flush_after_quiet(key, quiet_seconds))
        self._tasks[key] = task

    async def _flush_after_quiet(self, key: str, quiet_seconds: float) -> None:
        current = asyncio.current_task()
        try:
            await asyncio.sleep(quiet_seconds)
        except asyncio.CancelledError:
            return
        if self._tasks.get(key) is not current:
            return
        items = self._pending.pop(key, [])
        self._tasks.pop(key, None)
        if items:
            await self.handler(*self._merge(items))
