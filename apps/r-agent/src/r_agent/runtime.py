"""Read-only OneBot WebSocket listener with bounded reconnect backoff."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any

from r_agent.ingest import IngestService
from r_agent.onebot import OneBotParseError, parse_message_event

_log = logging.getLogger(__name__)


async def listen_forever(
    *,
    ws_url: str,
    access_token: str | None,
    ingest: IngestService,
) -> None:
    import websockets

    headers = {"Authorization": f"Bearer {access_token}"} if access_token else None
    delay = 1.0
    while True:
        try:
            async with websockets.connect(
                ws_url,
                additional_headers=headers,
                max_size=2 * 1024 * 1024,
                max_queue=64,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
            ) as socket:
                _log.info("onebot_connected")
                delay = 1.0
                async for frame in socket:
                    if not isinstance(frame, str):
                        continue
                    try:
                        raw: Any = json.loads(frame)
                        if not isinstance(raw, Mapping) or raw.get("post_type") != "message":
                            continue
                        event = parse_message_event(raw)
                        result = await asyncio.to_thread(ingest.ingest, event)
                        _log.info(
                            "event_processed decision=%s stored=%s duplicate=%s",
                            result.decision,
                            result.stored,
                            result.duplicate,
                        )
                    except (json.JSONDecodeError, OneBotParseError) as exc:
                        _log.warning("onebot_event_rejected type=%s", type(exc).__name__)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.warning(
                "onebot_disconnected type=%s retry_seconds=%.1f",
                type(exc).__name__,
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)
