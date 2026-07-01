from __future__ import annotations

import json
import math
import time
from importlib import import_module
from typing import Any
from unittest.mock import patch

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.test.utils import override_settings

from bias_core.extensions.bootstrap import get_extension_host
from bias_core.testing import build_extension_test_host


class Command(BaseCommand):
    help = "Run an in-process realtime WebSocket connect/subscribe/broadcast smoke."
    requires_system_checks = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--connections", type=int, default=5, help="WebSocket 连接数")
        parser.add_argument("--discussion-id", type=int, default=101, help="订阅和广播使用的讨论 ID")
        parser.add_argument("--timeout", type=float, default=5.0, help="单步等待超时秒数")
        parser.add_argument("--p95-threshold-ms", type=float, default=1000.0, help="广播延迟 P95 阈值")
        parser.add_argument("--format", choices=("text", "json"), default="text")

    def handle(self, *args, **options):
        route, used_workspace_fallback = resolve_realtime_forum_route()
        if route is None:
            raise CommandError("未找到 realtime.forum WebSocket route，请确认 realtime 扩展已启用。")
        consumer = getattr(route.consumer, "as_asgi", lambda: route.consumer)()
        consumer_module_name = route.consumer.__module__
        payload = async_to_sync(run_realtime_websocket_smoke)(
            consumer=consumer,
            consumer_module_name=consumer_module_name,
            used_workspace_fallback=used_workspace_fallback,
            connections=max(1, int(options.get("connections") or 1)),
            discussion_id=int(options.get("discussion_id") or 101),
            timeout=max(0.1, float(options.get("timeout") or 5.0)),
            p95_threshold_ms=float(options.get("p95_threshold_ms") or 1000.0),
        )

        if options["format"] == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self._write_text(payload)

        if not payload["summary"]["ok"]:
            raise CommandError("Realtime WebSocket smoke failed")

    def _write_text(self, payload: dict[str, Any]) -> None:
        summary = payload["summary"]
        self.stdout.write(
            f"Realtime WebSocket smoke: {'OK' if summary['ok'] else 'FAILED'}, "
            f"connections={summary['connection_count']}, "
            f"broadcast_p95={summary['broadcast_p95_ms']:.1f}ms"
        )
        for issue in payload.get("issues", []):
            self.stdout.write(f"- {issue}")


async def run_realtime_websocket_smoke(
    *,
    consumer: Any,
    consumer_module_name: str,
    used_workspace_fallback: bool,
    connections: int,
    discussion_id: int,
    timeout: float,
    p95_threshold_ms: float,
) -> dict[str, Any]:
    timings: dict[str, list[float]] = {
        "connect_ms": [],
        "subscribe_ms": [],
        "broadcast_ms": [],
    }
    issues: list[str] = []
    communicators: list[WebsocketCommunicator] = []

    with override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}):
        consumer_module = import_module(consumer_module_name)
        visibility_patch = (
            patch.object(consumer_module, "resolve_realtime_visible_discussion_ids", return_value=[discussion_id])
            if hasattr(consumer_module, "resolve_realtime_visible_discussion_ids")
            else _NullContext()
        )
        with visibility_patch:
            try:
                for _index in range(connections):
                    communicator = WebsocketCommunicator(consumer, "/ws/forum/")
                    communicator.scope["user"] = _AnonymousUser()
                    started = time.perf_counter()
                    connected, _subprotocol = await communicator.connect(timeout=timeout)
                    timings["connect_ms"].append(_elapsed_ms(started))
                    if not connected:
                        issues.append("WebSocket connect failed")
                        continue
                    initial = await communicator.receive_json_from(timeout=timeout)
                    if initial.get("type") != "connection_established":
                        issues.append(f"unexpected initial message: {initial!r}")

                    started = time.perf_counter()
                    await communicator.send_json_to({
                        "type": "subscribe_discussions",
                        "discussion_ids": [discussion_id],
                    })
                    subscribed = await communicator.receive_json_from(timeout=timeout)
                    timings["subscribe_ms"].append(_elapsed_ms(started))
                    if subscribed.get("type") != "subscribed" or discussion_id not in subscribed.get("discussion_ids", []):
                        issues.append(f"unexpected subscribe message: {subscribed!r}")
                    communicators.append(communicator)

                channel_layer = get_channel_layer()
                if channel_layer is None:
                    issues.append("channel layer unavailable")
                elif communicators:
                    started = time.perf_counter()
                    await channel_layer.group_send(
                        f"discussion_{discussion_id}",
                        {
                            "type": "forum_event_message",
                            "event": {
                                "scope": "discussion",
                                "discussion_id": discussion_id,
                                "event_type": "load.smoke",
                                "payload": {"ok": True},
                            },
                        },
                    )
                    for communicator in communicators:
                        event_message = await communicator.receive_json_from(timeout=timeout)
                        latency = _elapsed_ms(started)
                        timings["broadcast_ms"].append(latency)
                        if event_message.get("type") != "forum_event":
                            issues.append(f"unexpected broadcast message: {event_message!r}")
                        elif event_message.get("event", {}).get("event_type") != "load.smoke":
                            issues.append(f"unexpected broadcast event: {event_message!r}")
            finally:
                for communicator in communicators:
                    try:
                        await communicator.disconnect()
                    except Exception:
                        pass

    broadcast_p95 = percentile(timings["broadcast_ms"], 95)
    return {
        "mode": "in_process_channels",
        "workspace_fallback": used_workspace_fallback,
        "discussion_id": discussion_id,
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
            "ok": not issues and len(communicators) == connections and broadcast_p95 <= p95_threshold_ms,
            "connection_count": len(communicators),
            "expected_connection_count": connections,
            "broadcast_p95_ms": broadcast_p95,
            "broadcast_threshold_ms": p95_threshold_ms,
        },
    }


def _find_realtime_forum_route(host):
    if host is None:
        return None
    for route in host.get_websocket_routes():
        if getattr(route, "name", "") == "realtime.forum":
            return route
    return None


def resolve_realtime_forum_route():
    host = get_extension_host(force=True)
    route = _find_realtime_forum_route(host)
    if route is not None:
        return route, False
    host = build_extension_test_host("realtime")
    return _find_realtime_forum_route(host), True


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


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


class _AnonymousUser:
    is_authenticated = False
    is_anonymous = True
    id = None
    username = ""


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False
