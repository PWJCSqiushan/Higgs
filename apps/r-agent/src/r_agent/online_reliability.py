# ruff: noqa: RUF001, SIM105
"""QQ online-state transitions and redacted PushPlus incident notifications."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib import error, parse, request

from r_agent.health import HealthReporter

if TYPE_CHECKING:
    from r_agent.risk_ledger import RiskLedger


class NotificationError(RuntimeError):
    """A notification could not be delivered."""


class PushPlusNotifier:
    """Small PushPlus client that never logs or returns the configured token."""

    def __init__(self, token: str | None, *, timeout_seconds: float = 10.0) -> None:
        self._token = (token or "").strip()
        self.timeout_seconds = timeout_seconds

    @property
    def enabled(self) -> bool:
        return bool(self._token)

    def send(self, *, title: str, content: str) -> None:
        if not self._token:
            return
        body = parse.urlencode(
            {"token": self._token, "title": title[:100], "content": content[:1000]}
        ).encode("utf-8")
        req = request.Request(
            "https://www.pushplus.plus/send",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read(64_001))
        except (error.URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
            raise NotificationError("PushPlus request failed") from exc
        if not isinstance(payload, dict) or payload.get("code") not in {200, "200"}:
            raise NotificationError("PushPlus rejected notification")


@dataclass(frozen=True, slots=True)
class OnlineSnapshot:
    transport_connected: bool
    qq_online: bool
    qq_state: str
    incident_id: int
    changed_at_ms: int
    reason: str


class OnlineState:
    """Thread-safe two-layer state with exactly-once incident/recovery alerts."""

    def __init__(
        self,
        health: HealthReporter,
        notifier: PushPlusNotifier,
        *,
        risk_ledger: RiskLedger | None = None,
    ) -> None:
        self.health = health
        self.notifier = notifier
        self.risk_ledger = risk_ledger
        self._transport = False
        self._online = False
        self._state = "pending"
        self._incident_id = 0
        self._changed_at_ms = int(time.time() * 1000)
        self._reason = "startup"
        self._lock = threading.Lock()

    def snapshot(self) -> OnlineSnapshot:
        with self._lock:
            return OnlineSnapshot(
                self._transport,
                self._online,
                self._state,
                self._incident_id,
                self._changed_at_ms,
                self._reason,
            )

    async def set_transport(self, connected: bool) -> None:
        with self._lock:
            self._transport = connected
            if not connected:
                self._state = "pending"
        self.health.set_transport_connected(connected)
        if not connected:
            await self.set_qq_state("pending", reason="transport_disconnected")

    async def set_qq_online(self, online: bool, *, reason: str) -> None:
        await self.set_qq_state("verified" if online else "rejected", reason=reason)

    async def set_qq_state(self, state: str, *, reason: str) -> None:
        if state not in {"pending", "verified", "rejected"}:
            raise ValueError("QQ state must be pending, verified, or rejected")
        alert: tuple[str, str] | None = None
        now_ms = int(time.time() * 1000)
        online = state == "verified"
        with self._lock:
            previous = self._online
            self._online = online
            self._reason = reason[:120]
            self._state = state
            if previous != online:
                self._changed_at_ms = now_ms
                if not online:
                    self._incident_id += 1
                    alert = (
                        "Higgs QQ 已离线",
                        f"事故 #{self._incident_id}。普通回复与提醒发送已暂停；后台与备份仍运行。",
                    )
                elif self._incident_id > 0:
                    alert = (
                        "Higgs QQ 已恢复",
                        f"事故 #{self._incident_id} 已恢复，待发送提醒将按规则补发。",
                    )
        self.health.set_qq_state(self._state, reason=reason)
        if self.risk_ledger is not None:
            await asyncio.to_thread(
                self.risk_ledger.record_online_transition,
                online=online,
                reason=reason,
                now_ms=now_ms,
            )
        if alert is not None and self.notifier.enabled:
            try:
                await asyncio.to_thread(
                    self.notifier.send,
                    title=alert[0],
                    content=alert[1],
                )
            except NotificationError:
                pass


def onebot_online_hint(payload: object) -> tuple[bool, str] | None:
    """Interpret lifecycle/heartbeat hints without trusting them over active probes."""
    if not isinstance(payload, dict):
        return None
    if payload.get("post_type") == "meta_event" and payload.get("meta_event_type") == "heartbeat":
        status = payload.get("status")
        if isinstance(status, dict) and status.get("online") is False:
            return False, "onebot_heartbeat_offline"
        if isinstance(status, dict) and status.get("online") is True:
            return True, "onebot_heartbeat_online"
    if payload.get("post_type") == "meta_event" and payload.get("meta_event_type") == "lifecycle":
        sub_type = str(payload.get("sub_type", ""))
        if sub_type in {"connect", "enable"}:
            return True, f"onebot_lifecycle_{sub_type}"
    if payload.get("post_type") == "notice":
        notice_type = str(payload.get("notice_type", "")).casefold()
        sub_type = str(payload.get("sub_type", "")).casefold()
        event_type = str(payload.get("event_type", payload.get("type", ""))).casefold()
        marker = " ".join((notice_type, sub_type, event_type))
        if "kick" in marker:
            return False, "KickedOffLine"
        if notice_type in {"bot_offline", "client_offline", "offline"}:
            return False, f"onebot_notice_{notice_type}"
    return None
