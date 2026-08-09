"""Consent-gated Amap Web Service client with bounded responses and no secret logging."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from urllib import error, parse, request


class AmapError(RuntimeError):
    """Amap could not provide one unambiguous and usable route."""


@dataclass(frozen=True, slots=True)
class GeocodeCandidate:
    name: str
    display_address: str
    location: str
    provider_id: str | None = None


@dataclass(frozen=True, slots=True)
class RouteDuration:
    duration_seconds: int
    distance_meters: int | None


class AmapRouteClient:
    """Minimal HTTPS-only adapter. Callers must enforce consent and quotas."""

    BASE_URL = "https://restapi.amap.com"

    def __init__(self, api_key: str, *, timeout_seconds: float = 8.0) -> None:
        if not api_key.strip():
            raise AmapError("未配置高德 Web Service API Key")
        if not 1 <= timeout_seconds <= 20:
            raise AmapError("地图请求超时时间无效")
        self._api_key = api_key.strip()
        self._timeout_seconds = timeout_seconds

    async def geocode_candidates(
        self, address: str, *, city: str = ""
    ) -> tuple[GeocodeCandidate, ...]:
        clean = " ".join(address.split())
        if not 2 <= len(clean) <= 160:
            raise AmapError("地点长度必须为 2 到 160 字")
        payload = await self._get_json(
            "/v3/geocode/geo",
            {"address": clean, "city": city, "batch": "false"},
        )
        raw = payload.get("geocodes")
        if not isinstance(raw, list):
            raise AmapError("地图没有返回可用地点")
        candidates: list[GeocodeCandidate] = []
        for item in raw[:5]:
            if not isinstance(item, dict):
                continue
            location = item.get("location")
            formatted = item.get("formatted_address")
            if not isinstance(location, str) or not isinstance(formatted, str):
                continue
            candidates.append(
                GeocodeCandidate(
                    name=clean,
                    display_address=formatted[:200],
                    location=location,
                    provider_id=str(item.get("adcode")) if item.get("adcode") else None,
                )
            )
        if not candidates:
            raise AmapError("地图没有找到该地点")
        return tuple(candidates)

    async def route_duration(
        self,
        origin: str,
        destination: str,
        *,
        mode: str,
    ) -> RouteDuration:
        if mode not in {"walking", "driving", "bicycling", "electrobike", "transit"}:
            raise AmapError("不支持该交通方式")
        if mode == "walking":
            path = "/v3/direction/walking"
        elif mode == "driving":
            path = "/v3/direction/driving"
        elif mode == "transit":
            path = "/v3/direction/transit/integrated"
        else:
            path = f"/v5/direction/{mode}"
        payload = await self._get_json(
            path,
            {"origin": origin, "destination": destination},
        )
        route = payload.get("route")
        if not isinstance(route, dict):
            raise AmapError("地图没有返回路线")
        paths = route.get("paths") or route.get("transits")
        if not isinstance(paths, list) or not paths or not isinstance(paths[0], dict):
            raise AmapError("地图没有返回路线")
        first = paths[0]
        duration = first.get("duration")
        distance = first.get("distance")
        try:
            duration_seconds = int(float(str(duration)))
            distance_meters = int(float(str(distance))) if distance is not None else None
        except (TypeError, ValueError) as exc:
            raise AmapError("地图路线字段无效") from exc
        if not 1 <= duration_seconds <= 24 * 3600:
            raise AmapError("地图路线时长无效")
        return RouteDuration(duration_seconds, distance_meters)

    async def _get_json(self, path: str, params: dict[str, str]) -> dict[str, object]:
        query = parse.urlencode({**params, "key": self._api_key})
        url = f"{self.BASE_URL}{path}?{query}"

        def perform() -> dict[str, object]:
            req = request.Request(url, headers={"User-Agent": "Higgs/1 daily-plan"})
            try:
                with request.urlopen(req, timeout=self._timeout_seconds) as response:
                    raw = response.read(500_001)
                if len(raw) > 500_000:
                    raise AmapError("地图响应过大")
                payload = json.loads(raw)
            except AmapError:
                raise
            except (error.URLError, TimeoutError, UnicodeError, json.JSONDecodeError) as exc:
                raise AmapError("地图服务暂时不可用") from exc
            if not isinstance(payload, dict) or str(payload.get("status")) != "1":
                raise AmapError("地图服务拒绝了本次请求")
            return payload

        return await asyncio.to_thread(perform)
