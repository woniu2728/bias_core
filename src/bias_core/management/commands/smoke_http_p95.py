from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx
from django.core.management.base import BaseCommand, CommandError, CommandParser


DEFAULT_TARGETS = (
    ("/api/forum", 300.0),
    ("/api/discussions/?limit=20", 300.0),
    ("/api/search?q=smoke", 800.0),
    ("/api/tags", 300.0),
    ("/api/notifications", 300.0),
)


@dataclass(frozen=True)
class SmokeTarget:
    path: str
    threshold_ms: float | None = None


class Command(BaseCommand):
    help = "Run a lightweight HTTP P95 smoke check against a running Bias site."
    requires_system_checks = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="站点基础 URL")
        parser.add_argument(
            "--path",
            action="append",
            default=[],
            help="要压测的路径，可写成 /api/forum 或 /api/forum=300。可重复传入。",
        )
        parser.add_argument("--requests", type=int, default=20, help="每个路径正式请求次数，默认 20")
        parser.add_argument("--warmup", type=int, default=2, help="每个路径预热请求次数，默认 2")
        parser.add_argument("--timeout", type=float, default=10.0, help="单次请求超时秒数，默认 10")
        parser.add_argument("--header", action="append", default=[], help="附加 HTTP header，格式 Name: Value，可重复传入")
        parser.add_argument("--fail-on-threshold", action="store_true", help="任一路径 P95 超过阈值时返回失败")
        parser.add_argument("--format", choices=("text", "json"), default="text")

    def handle(self, *args, **options):
        payload = run_http_p95_smoke(
            base_url=str(options.get("base_url") or ""),
            target_specs=options.get("path") or [],
            requests=int(options.get("requests") or 20),
            warmup=int(options.get("warmup") or 2),
            timeout=float(options.get("timeout") or 10.0),
            header_specs=options.get("header") or [],
        )

        if options["format"] == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self._write_text(payload)

        if options.get("fail_on_threshold") and not payload["summary"]["ok"]:
            failed = ", ".join(item["path"] for item in payload["targets"] if not item["ok"])
            raise CommandError(f"HTTP P95 smoke check failed: {failed}")

    def _write_text(self, payload: dict[str, Any]) -> None:
        marker = "OK" if payload["summary"]["ok"] else "FAILED"
        self.stdout.write(f"HTTP P95 smoke: {marker}")
        for target in payload["targets"]:
            threshold = target.get("threshold_ms")
            threshold_label = f" <= {threshold:.1f}ms" if threshold is not None else ""
            self.stdout.write(
                f"- {target['path']}: p95={target['p95_ms']:.1f}ms{threshold_label}, "
                f"status={target['status_code_counts']}"
            )


def run_http_p95_smoke(
    *,
    base_url: str,
    target_specs: list[str],
    requests: int,
    warmup: int,
    timeout: float,
    header_specs: list[str],
) -> dict[str, Any]:
    base_url = (base_url or "").strip()
    if not base_url:
        raise CommandError("缺少 --base-url")
    request_count = max(1, requests)
    warmup_count = max(0, warmup)
    targets = parse_targets(target_specs)
    headers = parse_headers(header_specs)

    results = []
    with httpx.Client(base_url=base_url, timeout=timeout, headers=headers, follow_redirects=False) as client:
        for target in targets:
            results.append(_measure_target(client, base_url, target, request_count, warmup_count))

    return {
        "base_url": base_url,
        "requests_per_target": request_count,
        "warmup_per_target": warmup_count,
        "targets": results,
        "summary": {
            "ok": all(item["ok"] for item in results),
            "target_count": len(results),
            "failed_count": sum(1 for item in results if not item["ok"]),
        },
        "note": "轻量 smoke 只验证当前运行环境的关键路径 P95；正式容量验收仍需使用生产等价数据量和并发模型。",
    }


def parse_targets(target_specs: list[str]) -> list[SmokeTarget]:
    if not target_specs:
        return [SmokeTarget(path=path, threshold_ms=threshold) for path, threshold in DEFAULT_TARGETS]

    targets: list[SmokeTarget] = []
    for spec in target_specs:
        raw = str(spec or "").strip()
        if not raw:
            continue
        path = raw
        threshold = None
        if "=" in raw:
            path, raw_threshold = raw.rsplit("=", 1)
            try:
                threshold = float(raw_threshold)
            except ValueError as exc:
                raise CommandError(f"无效的 P95 阈值: {raw}") from exc
        path = path.strip()
        if not path:
            raise CommandError(f"无效的路径: {raw}")
        targets.append(SmokeTarget(path=path, threshold_ms=threshold))
    if not targets:
        raise CommandError("至少需要一个 HTTP path")
    return targets


def parse_headers(header_specs: list[str]) -> dict[str, str]:
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
    return headers


def _measure_target(
    client: httpx.Client,
    base_url: str,
    target: SmokeTarget,
    request_count: int,
    warmup_count: int,
) -> dict[str, Any]:
    url = _target_url(base_url, target.path)
    for _ in range(warmup_count):
        client.get(url)

    durations: list[float] = []
    status_counts: dict[str, int] = {}
    error_count = 0
    for _ in range(request_count):
        started = time.perf_counter()
        try:
            response = client.get(url)
            duration_ms = (time.perf_counter() - started) * 1000
            durations.append(duration_ms)
            status_counts[str(response.status_code)] = status_counts.get(str(response.status_code), 0) + 1
            if response.status_code >= 500:
                error_count += 1
        except httpx.HTTPError:
            duration_ms = (time.perf_counter() - started) * 1000
            durations.append(duration_ms)
            error_count += 1
            status_counts["error"] = status_counts.get("error", 0) + 1

    p95 = percentile(durations, 95)
    threshold = target.threshold_ms
    ok = error_count == 0 and (threshold is None or p95 <= threshold)
    return {
        "path": target.path,
        "url": url,
        "request_count": request_count,
        "error_count": error_count,
        "status_code_counts": status_counts,
        "min_ms": min(durations) if durations else 0,
        "max_ms": max(durations) if durations else 0,
        "average_ms": sum(durations) / len(durations) if durations else 0,
        "p95_ms": p95,
        "threshold_ms": threshold,
        "ok": ok,
    }


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


def _target_url(base_url: str, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))

