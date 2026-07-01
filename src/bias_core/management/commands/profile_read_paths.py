from __future__ import annotations

import json
import re
import statistics
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext


DEFAULT_TARGETS = (
    "/api/forum",
    "/api/discussions/?limit=20",
    "/api/search?q=loadtest-discussion-00000001",
    "/api/tags",
)


@dataclass(frozen=True)
class ProfileTarget:
    index: int
    method: str
    path: str

    @property
    def label(self) -> str:
        return f"{self.method} {self.path}"


class Command(BaseCommand):
    help = "Profile Bias read paths with query counts, slow SQL samples and optional SQL explain."
    requires_system_checks = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--base-url", help="站点基础 URL；不传时只支持 --in-process")
        parser.add_argument(
            "--in-process",
            action="store_true",
            help="使用 Django test client 在当前进程采样，并捕获 SQL query count",
        )
        parser.add_argument(
            "--path",
            action="append",
            default=[],
            help="要画像的路径，可写成 /api/forum 或 GET /api/forum。可重复传入。",
        )
        parser.add_argument("--repeat", type=int, default=3, help="每个路径正式采样次数")
        parser.add_argument("--warmup", type=int, default=1, help="每个路径预热次数")
        parser.add_argument("--timeout", type=float, default=10.0, help="外部 HTTP 单次请求超时秒数")
        parser.add_argument("--host", default="127.0.0.1", help="--in-process 请求使用的 HTTP_HOST")
        parser.add_argument("--header", action="append", default=[], help="外部 HTTP header，格式 Name: Value")
        parser.add_argument("--explain", action="store_true", help="对慢 SELECT SQL 输出 explain")
        parser.add_argument("--top-queries", type=int, default=10, help="每个路径保留的慢 SQL 数量")
        parser.add_argument("--format", choices=("text", "json"), default="text")

    def handle(self, *args, **options):
        payload = profile_read_paths(
            base_url=str(options.get("base_url") or "").strip(),
            in_process=bool(options.get("in_process")),
            target_specs=options.get("path") or [],
            repeat=max(1, int(options.get("repeat") or 1)),
            warmup=max(0, int(options.get("warmup") or 0)),
            timeout=float(options.get("timeout") or 10.0),
            host=str(options.get("host") or "127.0.0.1").strip(),
            header_specs=options.get("header") or [],
            explain=bool(options.get("explain")),
            top_queries=max(1, int(options.get("top_queries") or 1)),
        )

        if options["format"] == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self._write_text(payload)

    def _write_text(self, payload: dict[str, Any]) -> None:
        summary = payload["summary"]
        self.stdout.write(
            f"Read path profile: mode={payload['mode']}, "
            f"targets={summary['target_count']}, errors={summary['error_count']}"
        )
        for target in payload["targets"]:
            self.stdout.write(
                f"- {target['method']} {target['path']}: "
                f"total_p50={target['total_p50_ms']:.1f}ms, "
                f"total_p95={target['total_p95_ms']:.1f}ms, "
                f"queries={target['query_count_average']:.1f}, "
                f"duplicate_queries={target['duplicate_query_count_average']:.1f}"
            )


def profile_read_paths(
    *,
    base_url: str,
    in_process: bool,
    target_specs: list[str],
    repeat: int,
    warmup: int,
    timeout: float,
    host: str,
    header_specs: list[str],
    explain: bool,
    top_queries: int,
) -> dict[str, Any]:
    if not in_process and not base_url:
        raise CommandError("缺少 --base-url；或使用 --in-process 在当前 Django 进程中采样")

    targets = parse_targets(target_specs)
    headers = parse_headers(header_specs)
    mode = "in-process" if in_process else "external-http"
    started = time.perf_counter()
    if in_process:
        target_payloads = [
            _profile_in_process_target(target, repeat=repeat, warmup=warmup, host=host, explain=explain, top_queries=top_queries)
            for target in targets
        ]
    else:
        target_payloads = [
            _profile_external_target(target, base_url=base_url, repeat=repeat, warmup=warmup, timeout=timeout, headers=headers)
            for target in targets
        ]
    elapsed = max(time.perf_counter() - started, 0.000001)
    error_count = sum(target["error_count"] for target in target_payloads)
    return {
        "mode": mode,
        "base_url": base_url or None,
        "repeat": repeat,
        "warmup": warmup,
        "host": host if in_process else None,
        "explain": bool(explain and in_process),
        "targets": target_payloads,
        "summary": {
            "ok": error_count == 0,
            "target_count": len(target_payloads),
            "error_count": error_count,
            "duration_seconds": elapsed,
        },
    }


def parse_targets(target_specs: list[str]) -> list[ProfileTarget]:
    specs = target_specs or list(DEFAULT_TARGETS)
    targets: list[ProfileTarget] = []
    for index, spec in enumerate(specs):
        raw = str(spec or "").strip()
        if not raw:
            continue
        method, path = _split_method(raw)
        if method != "GET":
            raise CommandError(f"profile_read_paths 目前只支持 GET 读路径: {raw}")
        if not path.startswith("/") and not path.startswith("http://") and not path.startswith("https://"):
            raise CommandError(f"无效路径，应以 /、http:// 或 https:// 开头: {raw}")
        targets.append(ProfileTarget(index=index, method=method, path=path))
    if not targets:
        raise CommandError("至少需要一个 path")
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


def _profile_in_process_target(
    target: ProfileTarget,
    *,
    repeat: int,
    warmup: int,
    host: str,
    explain: bool,
    top_queries: int,
) -> dict[str, Any]:
    client = Client()
    for _ in range(warmup):
        client.get(target.path, HTTP_HOST=host)

    samples: list[dict[str, Any]] = []
    for _ in range(repeat):
        samples.append(_measure_in_process_once(client, target, host=host, explain=explain, top_queries=top_queries))
    return _summarize_target_samples(target, samples, include_queries=True, top_queries=top_queries)


def _measure_in_process_once(
    client: Client,
    target: ProfileTarget,
    *,
    host: str,
    explain: bool,
    top_queries: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    with CaptureQueriesContext(connection) as queries:
        response = client.get(target.path, HTTP_HOST=host)
    total_ms = (time.perf_counter() - started) * 1000
    captured = list(queries.captured_queries)
    query_payloads = [_serialize_query(query) for query in captured]
    db_ms = sum(query["duration_ms"] for query in query_payloads)
    slow_queries = sorted(query_payloads, key=lambda item: item["duration_ms"], reverse=True)[:top_queries]
    if explain:
        for query in slow_queries:
            query["explain"] = explain_sql(query["sql"])
    duplicate_count = _duplicate_query_count(query_payloads)
    status_code = int(response.status_code)
    return {
        "total_ms": total_ms,
        "db_ms": db_ms,
        "serialize_ms": max(total_ms - db_ms, 0.0),
        "query_count": len(query_payloads),
        "duplicate_query_count": duplicate_count,
        "slow_queries": slow_queries,
        "status_code": status_code,
        "error": status_code >= 400,
        "error_message": "" if status_code < 400 else f"HTTP {status_code}",
    }


def _profile_external_target(
    target: ProfileTarget,
    *,
    base_url: str,
    repeat: int,
    warmup: int,
    timeout: float,
    headers: dict[str, str],
) -> dict[str, Any]:
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=False) as client:
        for _ in range(warmup):
            client.get(_target_url(base_url, target.path))
        samples = [_measure_external_once(client, target, base_url=base_url) for _ in range(repeat)]
    return _summarize_target_samples(target, samples, include_queries=False, top_queries=0)


def _measure_external_once(client: httpx.Client, target: ProfileTarget, *, base_url: str) -> dict[str, Any]:
    url = _target_url(base_url, target.path)
    started = time.perf_counter()
    try:
        response = client.get(url)
        total_ms = (time.perf_counter() - started) * 1000
        status_code = int(response.status_code)
        return {
            "total_ms": total_ms,
            "db_ms": 0.0,
            "serialize_ms": 0.0,
            "query_count": 0,
            "duplicate_query_count": 0,
            "slow_queries": [],
            "status_code": status_code,
            "error": status_code >= 400,
            "error_message": "" if status_code < 400 else f"HTTP {status_code}",
        }
    except httpx.HTTPError as exc:
        return {
            "total_ms": (time.perf_counter() - started) * 1000,
            "db_ms": 0.0,
            "serialize_ms": 0.0,
            "query_count": 0,
            "duplicate_query_count": 0,
            "slow_queries": [],
            "status_code": None,
            "error": True,
            "error_message": str(exc),
        }


def _summarize_target_samples(
    target: ProfileTarget,
    samples: list[dict[str, Any]],
    *,
    include_queries: bool,
    top_queries: int,
) -> dict[str, Any]:
    total_values = [float(sample["total_ms"]) for sample in samples]
    db_values = [float(sample["db_ms"]) for sample in samples]
    serialize_values = [float(sample["serialize_ms"]) for sample in samples]
    query_values = [int(sample["query_count"]) for sample in samples]
    duplicate_values = [int(sample["duplicate_query_count"]) for sample in samples]
    status_counts: dict[str, int] = {}
    for sample in samples:
        key = str(sample["status_code"]) if sample["status_code"] is not None else "error"
        status_counts[key] = status_counts.get(key, 0) + 1
    merged_slow_queries = _merge_slow_queries(samples, top_queries=top_queries) if include_queries else []
    error_samples = [
        {
            "status_code": sample["status_code"],
            "error_message": sample["error_message"],
            "total_ms": sample["total_ms"],
        }
        for sample in samples
        if sample["error"]
    ][:5]
    return {
        "method": target.method,
        "path": target.path,
        "target": target.label,
        "sample_count": len(samples),
        "error_count": sum(1 for sample in samples if sample["error"]),
        "status_code_counts": status_counts,
        "total_min_ms": min(total_values) if total_values else 0.0,
        "total_average_ms": _average(total_values),
        "total_p50_ms": percentile(total_values, 50),
        "total_p95_ms": percentile(total_values, 95),
        "total_p99_ms": percentile(total_values, 99),
        "db_average_ms": _average(db_values),
        "db_p95_ms": percentile(db_values, 95),
        "serialize_average_ms": _average(serialize_values),
        "serialize_p95_ms": percentile(serialize_values, 95),
        "query_count_average": _average(query_values),
        "query_count_max": max(query_values) if query_values else 0,
        "duplicate_query_count_average": _average(duplicate_values),
        "duplicate_query_count_max": max(duplicate_values) if duplicate_values else 0,
        "slow_queries": merged_slow_queries,
        "errors": error_samples,
    }


def _serialize_query(query: dict[str, Any]) -> dict[str, Any]:
    raw_time = query.get("time", 0) or 0
    try:
        duration_ms = float(raw_time) * 1000
    except (TypeError, ValueError):
        duration_ms = 0.0
    sql = str(query.get("sql") or "")
    return {
        "sql": sql,
        "normalized_sql": normalize_sql(sql),
        "duration_ms": duration_ms,
    }


def _merge_slow_queries(samples: list[dict[str, Any]], *, top_queries: int) -> list[dict[str, Any]]:
    queries: dict[str, dict[str, Any]] = {}
    for sample in samples:
        for query in sample.get("slow_queries", []):
            key = str(query.get("normalized_sql") or query.get("sql") or "")
            existing = queries.setdefault(
                key,
                {
                    "sql": query.get("sql", ""),
                    "normalized_sql": key,
                    "count": 0,
                    "total_duration_ms": 0.0,
                    "max_duration_ms": 0.0,
                    "explain": query.get("explain"),
                },
            )
            existing["count"] += 1
            duration = float(query.get("duration_ms") or 0.0)
            existing["total_duration_ms"] += duration
            existing["max_duration_ms"] = max(existing["max_duration_ms"], duration)
            if existing.get("explain") is None and query.get("explain") is not None:
                existing["explain"] = query.get("explain")
    merged = []
    for query in queries.values():
        count = max(int(query["count"]), 1)
        item = dict(query)
        item["average_duration_ms"] = float(query["total_duration_ms"]) / count
        merged.append(item)
    return sorted(merged, key=lambda item: item["max_duration_ms"], reverse=True)[:top_queries]


def explain_sql(sql: str) -> dict[str, Any] | None:
    normalized = sql.strip().rstrip(";")
    if not normalized.lower().startswith("select"):
        return {"ok": False, "skipped": True, "reason": "not_select"}
    if ";" in normalized:
        return {"ok": False, "skipped": True, "reason": "multiple_statements"}
    vendor = connection.vendor
    try:
        with connection.cursor() as cursor:
            if vendor == "postgresql":
                cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {normalized}")
                rows = cursor.fetchall()
                return {"ok": True, "vendor": vendor, "plan": rows[0][0] if rows else None}
            cursor.execute(f"EXPLAIN QUERY PLAN {normalized}")
            rows = cursor.fetchall()
            return {"ok": True, "vendor": vendor, "plan": rows}
    except Exception as exc:
        return {"ok": False, "vendor": vendor, "error": str(exc)}


def normalize_sql(sql: str) -> str:
    normalized = re.sub(r"'([^']|'')*'", "?", sql)
    normalized = re.sub(r"\b\d+\b", "?", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _duplicate_query_count(queries: list[dict[str, Any]]) -> int:
    counts: dict[str, int] = {}
    for query in queries:
        key = str(query.get("normalized_sql") or "")
        counts[key] = counts.get(key, 0) + 1
    return sum(count - 1 for count in counts.values() if count > 1)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _average(values) -> float:
    values = list(values)
    return float(statistics.fmean(values)) if values else 0.0


def _split_method(raw: str) -> tuple[str, str]:
    upper = raw.upper()
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        prefix = f"{method} "
        if upper.startswith(prefix):
            return method, raw[len(prefix):].strip()
    return "GET", raw


def _target_url(base_url: str, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
