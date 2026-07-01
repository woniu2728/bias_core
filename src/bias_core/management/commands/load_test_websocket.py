from __future__ import annotations

import asyncio
import json
import math
import time
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.management.base import BaseCommand, CommandError, CommandParser


class Command(BaseCommand):
    help = "Run an external WebSocket load test against a running Bias site."
    requires_system_checks = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--url", help="完整 WebSocket URL，例如 wss://forum.example.com/ws/forum/")
        parser.add_argument("--base-url", help="站点 HTTP/HTTPS 基础 URL；未传 --url 时会转换为 ws/wss")
        parser.add_argument("--path", default="/ws/forum/", help="WebSocket path，默认 /ws/forum/")
        parser.add_argument("--connections", type=int, default=5, help="WebSocket 连接数")
        parser.add_argument("--discussion-id", type=int, default=101, help="订阅和广播使用的讨论 ID")
        parser.add_argument("--timeout", type=float, default=5.0, help="单步等待超时秒数")
        parser.add_argument("--header", action="append", default=[], help="附加握手 header，格式 Name: Value")
        parser.add_argument("--auth-token", help="Bearer token，等同于 Authorization: Bearer <token>")
        parser.add_argument("--bearer-token", help="Bearer token，等同于 --auth-token")
        parser.add_argument("--p95-threshold-ms", type=float, default=1000.0, help="connect/subscribe P95 阈值")
        parser.add_argument("--broadcast-p95-threshold-ms", type=float, default=1000.0, help="广播接收 P95 阈值")
        parser.add_argument(
            "--skip-channel-broadcast",
            action="store_true",
            help="只验证外部 connect/subscribe，不通过当前 channel layer 广播 forum_event",
        )
        parser.add_argument("--fail-on-threshold", action="store_true")
        parser.add_argument("--format", choices=("text", "json"), default="text")

    def handle(self, *args, **options):
        websocket_url = resolve_websocket_url(
            url=str(options.get("url") or "").strip(),
            base_url=str(options.get("base_url") or "").strip(),
            path=str(options.get("path") or "/ws/forum/"),
        )
        payload = async_to_sync(run_external_websocket_load_test)(
            url=websocket_url,
            connections=max(1, int(options.get("connections") or 1)),
            discussion_id=int(options.get("discussion_id") or 101),
            timeout=max(0.1, float(options.get("timeout") or 5.0)),
            headers=parse_headers(
                options.get("header") or [],
                auth_token=str(options.get("auth_token") or options.get("bearer_token") or "").strip(),
            ),
            p95_threshold_ms=float(options.get("p95_threshold_ms") or 1000.0),
            broadcast_p95_threshold_ms=float(options.get("broadcast_p95_threshold_ms") or 1000.0),
            channel_broadcast=not bool(options.get("skip_channel_broadcast")),
        )

        if options["format"] == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self._write_text(payload)

        if options.get("fail_on_threshold") and not payload["summary"]["ok"]:
            raise CommandError("External WebSocket load test failed thresholds")

    def _write_text(self, payload: dict[str, Any]) -> None:
        summary = payload["summary"]
        self.stdout.write(
            f"External WebSocket load test: {'OK' if summary['ok'] else 'FAILED'}, "
            f"connections={summary['connection_count']}/{summary['expected_connection_count']}, "
            f"broadcast_p95={summary['broadcast_p95_ms']:.1f}ms"
        )
        for issue in payload.get("issues", []):
            self.stdout.write(f"- {issue}")


async def run_external_websocket_load_test(
    *,
    url: str,
    connections: int,
    discussion_id: int,
    timeout: float,
    headers: dict[str, str],
    p95_threshold_ms: float,
    broadcast_p95_threshold_ms: float,
    channel_broadcast: bool = True,
) -> dict[str, Any]:
    timings: dict[str, list[float]] = {
        "connect_ms": [],
        "initial_message_ms": [],
        "subscribe_ms": [],
        "broadcast_ms": [],
    }
    issues: list[str] = []
    websockets: list[Any] = []

    try:
        for index in range(connections):
            try:
                started = time.perf_counter()
                websocket = await _connect_websocket(url, headers=headers, timeout=timeout)
                timings["connect_ms"].append(_elapsed_ms(started))
                initial = await _receive_json(websocket, timeout=timeout)
                timings["initial_message_ms"].append(_elapsed_ms(started))
                if initial.get("type") != "connection_established":
                    issues.append(f"connection {index} unexpected initial message: {initial!r}")

                started = time.perf_counter()
                await websocket.send(json.dumps({
                    "type": "subscribe_discussions",
                    "discussion_ids": [discussion_id],
                }))
                subscribed = await _receive_json(websocket, timeout=timeout)
                timings["subscribe_ms"].append(_elapsed_ms(started))
                if subscribed.get("type") != "subscribed" or discussion_id not in subscribed.get("discussion_ids", []):
                    issues.append(f"connection {index} unexpected subscribe message: {subscribed!r}")
                websockets.append(websocket)
            except Exception as exc:
                issues.append(f"connection {index} failed: {_format_exception(exc)}")

        if channel_broadcast:
            if websockets:
                await _broadcast_forum_event(discussion_id=discussion_id)
                started = time.perf_counter()
                for index, websocket in enumerate(websockets):
                    try:
                        message = await _receive_json_until(websocket, expected_type="forum_event", timeout=timeout)
                        timings["broadcast_ms"].append(_elapsed_ms(started))
                        event = message.get("event") or {}
                        if event.get("event_type") != "load.external.websocket":
                            issues.append(f"connection {index} unexpected broadcast event: {message!r}")
                    except Exception as exc:
                        issues.append(f"connection {index} broadcast receive failed: {_format_exception(exc)}")
            else:
                issues.append("no connected websocket clients for broadcast")
    finally:
        for websocket in websockets:
            try:
                await websocket.close()
            except Exception:
                pass

    connect_p95 = percentile(timings["connect_ms"], 95)
    subscribe_p95 = percentile(timings["subscribe_ms"], 95)
    broadcast_p95 = percentile(timings["broadcast_ms"], 95)
    expected_broadcast_count = len(websockets) if channel_broadcast else 0
    broadcast_ok = (not channel_broadcast) or (
        len(timings["broadcast_ms"]) == expected_broadcast_count and broadcast_p95 <= broadcast_p95_threshold_ms
    )
    return {
        "mode": "external_websocket",
        "url": url,
        "discussion_id": discussion_id,
        "channel_broadcast": channel_broadcast,
        "timings": {
            key: {
                "count": len(values),
                "p50_ms": percentile(values, 50),
                "p95_ms": percentile(values, 95),
                "p99_ms": percentile(values, 99),
                "max_ms": max(values) if values else 0.0,
            }
            for key, values in timings.items()
        },
        "issues": issues,
        "summary": {
            "ok": (
                not issues
                and len(websockets) == connections
                and connect_p95 <= p95_threshold_ms
                and subscribe_p95 <= p95_threshold_ms
                and broadcast_ok
            ),
            "connection_count": len(websockets),
            "expected_connection_count": connections,
            "connect_p95_ms": connect_p95,
            "subscribe_p95_ms": subscribe_p95,
            "p95_threshold_ms": p95_threshold_ms,
            "broadcast_count": len(timings["broadcast_ms"]),
            "expected_broadcast_count": expected_broadcast_count,
            "broadcast_p95_ms": broadcast_p95,
            "broadcast_threshold_ms": broadcast_p95_threshold_ms,
        },
    }


def resolve_websocket_url(*, url: str = "", base_url: str = "", path: str = "/ws/forum/") -> str:
    if url:
        parsed = urlparse(url)
        if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
            raise CommandError(f"无效的 WebSocket URL: {url}")
        return url
    if not base_url:
        raise CommandError("缺少 --url 或 --base-url")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https", "ws", "wss"} or not parsed.netloc:
        raise CommandError(f"无效的 base URL: {base_url}")
    scheme = {"http": "ws", "https": "wss"}.get(parsed.scheme, parsed.scheme)
    ws_base = urlunparse((scheme, parsed.netloc, "/", "", "", ""))
    return urljoin(ws_base, path.lstrip("/"))


def parse_headers(header_specs: list[str], *, auth_token: str = "") -> dict[str, str]:
    headers: dict[str, str] = {}
    for spec in header_specs:
        raw = str(spec or "")
        if ":" not in raw:
            raise CommandError(f"无效的 header，格式应为 Name: Value: {raw}")
        name, value = raw.split(":", 1)
        name = name.strip()
        if not name:
            raise CommandError(f"无效的 header 名称: {raw}")
        headers[name] = value.strip()
    if auth_token and not any(name.lower() == "authorization" for name in headers):
        headers["Authorization"] = f"Bearer {auth_token}"
    return headers


async def _connect_websocket(url: str, *, headers: dict[str, str], timeout: float):
    try:
        import websockets
    except ImportError as exc:
        raise CommandError("缺少 websockets 依赖，请安装 bias-core 的最新运行依赖。") from exc
    return await websockets.connect(url, extra_headers=headers or None, open_timeout=timeout, close_timeout=timeout)


async def _receive_json(websocket, *, timeout: float) -> dict[str, Any]:
    raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CommandError(f"WebSocket 收到非 JSON 消息: {raw!r}") from exc
    if not isinstance(data, dict):
        raise CommandError(f"WebSocket 收到非 object JSON 消息: {data!r}")
    return data


async def _receive_json_until(websocket, *, expected_type: str, timeout: float) -> dict[str, Any]:
    deadline = time.perf_counter() + timeout
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise TimeoutError(f"等待 {expected_type} 消息超时")
        message = await _receive_json(websocket, timeout=remaining)
        if message.get("type") == expected_type:
            return message


async def _broadcast_forum_event(*, discussion_id: int) -> None:
    channel_layer = get_channel_layer()
    if channel_layer is None:
        raise CommandError("channel layer unavailable，无法广播 forum_event")
    await channel_layer.group_send(
        f"discussion_{discussion_id}",
        {
            "type": "forum_event_message",
            "event": {
                "scope": "discussion",
                "discussion_id": discussion_id,
                "event_type": "load.external.websocket",
                "payload": {"ok": True},
            },
        },
    )


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def _format_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return f"{exc.__class__.__name__}: {message}"
    return exc.__class__.__name__


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight
