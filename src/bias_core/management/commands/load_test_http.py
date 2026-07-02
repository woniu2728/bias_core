from __future__ import annotations

import concurrent.futures
import itertools
import json
import math
import os
import string
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from bias_core.management.commands.prepare_load_test_actors import LOAD_TEST_NOTIFICATION_PREFERENCES


FORUM_MAIN_PROFILE = (
    ("GET", "/api/forum", None, 300.0),
    ("GET", "/api/discussions/?limit=20", None, 300.0),
    ("GET", "/api/search?q=loadtest-discussion-00000001", None, 800.0),
    ("GET", "/api/tags", None, 300.0),
)

FORUM_MAIN_AUTH_PROFILE = (
    ("GET", "/api/users/me", None, 300.0),
    ("GET", "/api/discussions/?filter=my&limit=20", None, 300.0),
    ("GET", "/api/discussions/?filter=unread&limit=20", None, 300.0),
    ("GET", "/api/notifications", None, 300.0),
)

FORUM_WRITE_PROFILE = (
    (
        "POST",
        "/api/discussions/{discussion_id}/posts",
        {"content": "Load test reply {sequence}"},
        500.0,
    ),
)

FORUM_WRITE_MIXED_PROFILE = (
    (
        "POST",
        "/api/discussions/",
        {
            "data": {
                "attributes": {
                    "title": "Load test discussion {sequence}",
                    "content": "Load test first post {sequence}",
                },
                "relationships": {
                    "tags": {
                        "data": [
                            {"type": "tag", "id": "{tag_id}"},
                        ],
                    },
                },
            },
        },
        500.0,
    ),
    ("PATCH", "/api/discussions/{discussion_id}", {"data": {"attributes": {"title": "Load test update {sequence}"}}}, 500.0),
    ("POST", "/api/discussions/{discussion_id}/read", {"last_read_post_number": 1}, 300.0),
    ("POST", "/api/posts/{like_post_id}/like", None, 500.0),
    ("DELETE", "/api/posts/{unlike_post_id}/like", None, 500.0),
    ("POST", "/api/discussions/{discussion_id}/subscribe", None, 300.0),
    ("DELETE", "/api/discussions/{discussion_id}/subscribe", None, 300.0),
)

FORUM_UPLOAD_PROFILE = (
    (
        "POST",
        "/api/uploads",
        {"field": "file", "filename": "load-test-{sequence}.txt", "content_type": "text/plain", "content": "load test upload {sequence}\n"},
        800.0,
    ),
)

FORUM_WRITE_MODERATION_PROFILE = (
    ("PATCH", "/api/posts/{edit_post_id}", {"content": "Load test edited post {sequence}"}, 500.0),
    ("POST", "/api/posts/{report_post_id}/report", {"reason": "spam", "message": "Load test report {sequence}"}, 300.0),
    ("POST", "/api/notifications/{notification_read_id}/read", None, 300.0),
    ("POST", "/api/posts/{hide_post_id}/hide", None, 300.0),
    ("POST", "/api/posts/{restore_post_id}/hide", None, 300.0),
    ("POST", "/api/notifications/read-filtered?type=postReply&discussion_id={discussion_id}", None, 300.0),
    ("DELETE", "/api/notifications/read/clear-filtered?type=postReply&discussion_id={discussion_id}", None, 300.0),
    ("DELETE", "/api/notifications/read/clear", None, 300.0),
    ("DELETE", "/api/posts/{delete_post_id}", None, 500.0),
)

_REQUEST_SEQUENCE_COUNTER = itertools.count(int(time.time() * 1000) * 1000)
DEFAULT_STATE_TRANSITION_POOL_SIZE = 2048
STATE_TRANSITION_POOL_SIZE_ENV = "BIAS_LOAD_TEST_STATE_POOL_SIZE"


@dataclass(frozen=True)
class LoadTarget:
    index: int
    method: str
    path: str
    json_body: dict[str, Any] | list[Any] | None = None
    multipart_file: dict[str, Any] | None = None
    threshold_ms: float | None = None
    path_template: str | None = None
    json_body_template: dict[str, Any] | list[Any] | str | None = None
    dynamic_values: dict[str, Any] | None = None

    @property
    def key(self) -> str:
        return f"{self.index}:{self.method} {self.path}"

    @property
    def label(self) -> str:
        return f"{self.method} {self.path}"


class Command(BaseCommand):
    help = "Run a concurrent HTTP load test against a running Bias site."
    requires_system_checks = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--base-url", required=True, help="站点基础 URL")
        parser.add_argument(
            "--profile",
            choices=(
                "forum-main",
                "forum-main-auth",
                "forum-write",
                "forum-write-mixed",
                "forum-upload",
                "forum-write-moderation",
            ),
            default="forum-main",
        )
        parser.add_argument(
            "--path",
            action="append",
            default=[],
            help="自定义目标，可写成 /api/forum、POST /api/x {\"content\":\"hi\"}=500、POST /api/uploads FILE file:a.txt:text/plain:hello=800",
        )
        parser.add_argument("--concurrency", type=int, default=20)
        parser.add_argument("--duration", type=float, default=300.0, help="压测持续秒数")
        parser.add_argument("--requests", type=int, default=0, help="请求总数；大于 0 时优先于 duration")
        parser.add_argument("--timeout", type=float, default=10.0)
        parser.add_argument("--header", action="append", default=[], help="附加 HTTP header，格式 Name: Value")
        parser.add_argument("--auth-token", help="Bearer token，等同于 Authorization: Bearer <token>")
        parser.add_argument("--bearer-token", help="Bearer token，等同于 --auth-token")
        parser.add_argument("--login-username", help="压测前通过 /api/users/login 登录的测试用户用户名或邮箱")
        parser.add_argument("--login-password", help="压测前通过 /api/users/login 登录的测试用户密码")
        parser.add_argument("--discussion-id", type=int, help="动态 profile 使用的讨论 ID；不传时从当前数据库选择最新讨论")
        parser.add_argument("--post-id", type=int, help="动态 profile 使用的帖子 ID；不传时从当前数据库选择最新帖子")
        parser.add_argument("--tag-id", type=int, help="动态 profile 使用的标签 ID；不传时从当前数据库选择最新标签")
        parser.add_argument("--notification-id", type=int, help="动态 profile 使用的通知 ID；不传时从当前数据库选择最新通知")
        parser.add_argument(
            "--prepare-isolated-targets",
            action="store_true",
            help="为写入 profile 自动创建隔离的 discussion/post/tag/notification 目标，避免误伤已有数据",
        )
        parser.add_argument(
            "--cleanup-isolated-targets",
            action="store_true",
            help="压测结束后清理本次 --prepare-isolated-targets 创建的隔离数据",
        )
        parser.add_argument(
            "--cleanup-isolated-prefix",
            help="清理指定 loadtest-isolated-* prefix 的隔离数据，可用于清理历史遗留数据",
        )
        parser.add_argument("--fail-on-threshold", action="store_true")
        parser.add_argument("--format", choices=("text", "json"), default="text")

    def handle(self, *args, **options):
        payload = run_http_load_test(
            base_url=str(options["base_url"]),
            profile=str(options.get("profile") or "forum-main"),
            target_specs=options.get("path") or [],
            concurrency=max(1, int(options.get("concurrency") or 1)),
            duration=max(0.0, float(options.get("duration") or 0.0)),
            request_limit=max(0, int(options.get("requests") or 0)),
            timeout=float(options.get("timeout") or 10.0),
            header_specs=options.get("header") or [],
            auth_token=str(options.get("auth_token") or options.get("bearer_token") or "").strip(),
            login_username=str(options.get("login_username") or "").strip(),
            login_password=str(options.get("login_password") or ""),
            discussion_id=options.get("discussion_id"),
            post_id=options.get("post_id"),
            tag_id=options.get("tag_id"),
            notification_id=options.get("notification_id"),
            prepare_isolated_targets=bool(options.get("prepare_isolated_targets")),
            cleanup_isolated_targets=bool(options.get("cleanup_isolated_targets")),
            cleanup_isolated_prefix=str(options.get("cleanup_isolated_prefix") or "").strip(),
        )

        if options["format"] == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self._write_text(payload)

        if options.get("fail_on_threshold") and not payload["summary"]["ok"]:
            raise CommandError("HTTP load test failed thresholds")

    def _write_text(self, payload: dict[str, Any]) -> None:
        summary = payload["summary"]
        self.stdout.write(
            f"HTTP load test: {'OK' if summary['ok'] else 'FAILED'}, "
            f"requests={summary['request_count']}, error_rate={summary['error_rate']:.4f}, "
            f"throughput={summary['requests_per_second']:.2f}/s"
        )
        for target in payload["targets"]:
            threshold = target.get("threshold_ms")
            threshold_label = f" <= {threshold:.1f}ms" if threshold is not None else ""
            self.stdout.write(
                f"- {target['method']} {target['path']}: p95={target['p95_ms']:.1f}ms, "
                f"p99={target['p99_ms']:.1f}ms{threshold_label}, "
                f"errors={target['error_count']}/{target['request_count']}"
            )


def run_http_load_test(
    *,
    base_url: str,
    profile: str,
    target_specs: list[str],
    concurrency: int,
    duration: float,
    request_limit: int,
    timeout: float,
    header_specs: list[str],
    auth_token: str = "",
    login_username: str = "",
    login_password: str = "",
    discussion_id: int | None = None,
    post_id: int | None = None,
    tag_id: int | None = None,
    notification_id: int | None = None,
    prepare_isolated_targets: bool = False,
    cleanup_isolated_targets: bool = False,
    cleanup_isolated_prefix: str = "",
) -> dict[str, Any]:
    base_url = (base_url or "").strip()
    if not base_url:
        raise CommandError("缺少 --base-url")
    if cleanup_isolated_prefix and prepare_isolated_targets:
        raise CommandError("--cleanup-isolated-prefix 不能和 --prepare-isolated-targets 同时使用")
    explicit_cleanup: dict[str, Any] | None = None
    if cleanup_isolated_prefix:
        explicit_cleanup = cleanup_isolated_targets_for_prefix(cleanup_isolated_prefix)
        if request_limit <= 0 and duration <= 0:
            return {
                "base_url": base_url,
                "profile": profile,
                "concurrency": concurrency,
                "duration_seconds": 0.0,
                "request_limit": request_limit,
                "dynamic_values": {},
                "isolated_targets": {},
                "cleanup": explicit_cleanup,
                "targets": [],
                "errors": [],
                "summary": {
                    "ok": bool(explicit_cleanup["ok"]),
                    "request_count": 0,
                    "error_count": 0,
                    "error_rate": 0.0,
                    "requests_per_second": 0.0,
                    "failed_threshold_count": 0,
                },
            }
    login_user_id = _resolve_login_user_id(login_username) if login_username else None
    dynamic_values = resolve_dynamic_values(
        profile=profile,
        discussion_id=discussion_id,
        post_id=post_id,
        tag_id=tag_id,
        notification_id=notification_id,
        prepare_isolated_targets=prepare_isolated_targets,
        actor_user_id=login_user_id,
    )
    isolated_targets = dynamic_values.get("isolated_targets", {})
    try:
        targets = parse_targets(target_specs, profile=profile, dynamic_values=dynamic_values)
        headers = parse_headers(header_specs, auth_token=auth_token)
        if login_username or login_password:
            if not login_username or not login_password:
                raise CommandError("--login-username 和 --login-password 必须同时提供")
            headers = bootstrap_login_headers(
                base_url=base_url,
                username=login_username,
                password=login_password,
                headers=headers,
                timeout=timeout,
            )
        started = time.perf_counter()
        deadline = started + max(duration, 1.0) if request_limit <= 0 else None

        results: list[dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            if request_limit > 0:
                futures = []
                worker_count = min(concurrency, request_limit)
                for worker_index in range(worker_count):
                    futures.append(
                        executor.submit(
                            _request_fixed_count,
                            base_url,
                            targets,
                            headers,
                            timeout,
                            request_limit,
                            worker_index,
                            worker_count,
                        )
                    )
                for future in concurrent.futures.as_completed(futures):
                    results.extend(future.result())
            else:
                futures = [
                    executor.submit(_request_until_deadline, base_url, targets, headers, timeout, deadline, worker_index)
                    for worker_index in range(concurrency)
                ]
                for future in concurrent.futures.as_completed(futures):
                    results.extend(future.result())

        elapsed = max(time.perf_counter() - started, 0.000001)
        target_payloads = [_summarize_target(target, results) for target in targets]
        request_count = len(results)
        error_count = sum(1 for result in results if result["error"])
        error_rate = error_count / request_count if request_count else 0.0
        failed_thresholds = [target for target in target_payloads if not target["ok"]]
        cleanup: dict[str, Any] | None = explicit_cleanup
        if cleanup_isolated_targets:
            if not isolated_targets:
                raise CommandError("--cleanup-isolated-targets 需要同时使用 --prepare-isolated-targets")
            cleanup = cleanup_isolated_targets_for_prefix(str(isolated_targets.get("prefix") or ""))

        payload = {
            "base_url": base_url,
            "profile": profile,
            "concurrency": concurrency,
            "duration_seconds": elapsed,
            "request_limit": request_limit,
            "dynamic_values": _public_dynamic_values(dynamic_values),
            "isolated_targets": isolated_targets,
            "targets": target_payloads,
            "errors": [result for result in results if result["error"]][:20],
            "summary": {
                "ok": error_rate < 0.005 and not failed_thresholds,
                "request_count": request_count,
                "error_count": error_count,
                "error_rate": error_rate,
                "requests_per_second": request_count / elapsed,
                "failed_threshold_count": len(failed_thresholds),
            },
        }
        if cleanup is not None:
            payload["cleanup"] = cleanup
        return payload
    except Exception:
        if cleanup_isolated_targets and isolated_targets:
            cleanup_isolated_targets_for_prefix(str(isolated_targets.get("prefix") or ""))
        raise


def _public_dynamic_values(values: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in values.items() if not str(key).startswith("_")}
    pools = values.get("_sequence_pools") or {}
    if isinstance(pools, dict):
        public["sequence_pools"] = {
            key: {
                "size": len(pool),
                "first": pool[0] if pool else None,
                "last": pool[-1] if pool else None,
            }
            for key, pool in pools.items()
            if isinstance(key, str) and isinstance(pool, (list, tuple))
        }
    return public


def parse_targets(
    target_specs: list[str],
    *,
    profile: str,
    dynamic_values: dict[str, Any] | None = None,
) -> list[LoadTarget]:
    specs = target_specs or _profile_specs(profile)
    values = dict(dynamic_values or {})
    if profile == "forum-write-mixed" and "post_id" in values:
        values.setdefault("like_post_id", values["post_id"])
        values.setdefault("unlike_post_id", values["post_id"])
    if profile == "forum-write-moderation" and "post_id" in values:
        values.setdefault("edit_post_id", values["post_id"])
        values.setdefault("report_post_id", values["post_id"])
        values.setdefault("hide_post_id", values["post_id"])
        values.setdefault("restore_post_id", values["post_id"])
        values.setdefault("delete_post_id", values["post_id"])
    if profile == "forum-write-moderation" and "notification_id" in values:
        values.setdefault("notification_read_id", values["notification_id"])
    targets: list[LoadTarget] = []
    _prepare_sequence_pool_counters(values)
    for index, spec in enumerate(specs):
        raw = str(spec or "").strip()
        if not raw:
            continue
        method, path_and_body = _split_method(raw)
        target_part = path_and_body
        threshold = None
        if "=" in path_and_body:
            target_part, raw_threshold = path_and_body.rsplit("=", 1)
            try:
                threshold = float(raw_threshold)
            except ValueError as exc:
                raise CommandError(f"无效的 P95 阈值: {raw}") from exc
        path, json_body = _split_path_and_json_body(target_part.strip())
        raw_path = path
        raw_json_body = json_body
        path = path.format(**values).strip()
        json_body = _format_json_body(json_body, values)
        if not path:
            raise CommandError(f"无效的路径: {raw}")
        multipart_file = json_body if _is_multipart_body(json_body) else None
        body = None if multipart_file is not None else json_body
        targets.append(
            LoadTarget(
                method=method,
                path=path,
                index=index,
                json_body=body,
                multipart_file=multipart_file,
                threshold_ms=threshold,
                path_template=raw_path,
                json_body_template=raw_json_body,
                dynamic_values=dict(values),
            )
        )
    if not targets:
        raise CommandError(f"profile {profile} 没有可执行 HTTP path")
    return targets


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


def bootstrap_login_headers(
    *,
    base_url: str,
    username: str,
    password: str,
    headers: dict[str, str],
    timeout: float,
) -> dict[str, str]:
    csrf_url = _target_url(base_url, "/api/csrf")
    login_url = _target_url(base_url, "/api/users/login")
    request_headers = dict(headers)
    with httpx.Client(timeout=timeout, headers=request_headers, follow_redirects=False) as client:
        csrf_response = client.get(csrf_url)
        if csrf_response.status_code >= 400:
            raise CommandError(f"登录 bootstrap 获取 CSRF 失败: HTTP {csrf_response.status_code}")
        try:
            csrf_token = str(csrf_response.json().get("csrfToken") or "").strip()
        except ValueError as exc:
            raise CommandError("登录 bootstrap 获取 CSRF 返回非 JSON") from exc
        if not csrf_token:
            raise CommandError("登录 bootstrap 未获得 csrfToken")
        login_response = client.post(
            login_url,
            json={
                "identification": username,
                "password": password,
            },
            headers={
                **request_headers,
                "X-CSRFToken": csrf_token,
            },
        )
        if login_response.status_code >= 400:
            raise CommandError(f"登录 bootstrap 失败: HTTP {login_response.status_code}")
        try:
            login_payload = login_response.json()
        except ValueError as exc:
            raise CommandError("登录 bootstrap 返回非 JSON") from exc
        access_token = str(login_payload.get("access") or "").strip()
        if not access_token:
            raise CommandError("登录 bootstrap 未获得 access token")
        cookie_header = _cookie_header_from_jar(client.cookies)

    merged = dict(headers)
    merged["Authorization"] = f"Bearer {access_token}"
    merged["X-CSRFToken"] = csrf_token
    if cookie_header:
        existing_cookie = merged.get("Cookie")
        merged["Cookie"] = f"{existing_cookie}; {cookie_header}" if existing_cookie else cookie_header
    return merged


def _cookie_header_from_jar(cookies) -> str:
    pairs = []
    for cookie in cookies.jar:
        pairs.append(f"{cookie.name}={cookie.value}")
    return "; ".join(pairs)


def _request_once(
    base_url: str,
    target: LoadTarget,
    headers: dict[str, str],
    timeout: float,
    client: httpx.Client | None = None,
    sequence: int | None = None,
) -> dict[str, Any]:
    rendered = _render_target_for_request(target, sequence=sequence)
    url = _target_url(base_url, rendered.path)
    started = time.perf_counter()
    try:
        request_kwargs = {}
        if rendered.multipart_file is not None:
            request_kwargs["files"] = _multipart_files_payload(rendered.multipart_file)
        elif rendered.json_body is not None:
            request_kwargs["json"] = rendered.json_body
        if client is None:
            with httpx.Client(timeout=timeout, headers=headers, follow_redirects=False) as scoped_client:
                response = scoped_client.request(rendered.method, url, **request_kwargs)
        else:
            response = client.request(rendered.method, url, **request_kwargs)
        duration_ms = (time.perf_counter() - started) * 1000
        error = response.status_code >= 400
        return {
            "method": rendered.method,
            "path": rendered.path,
            "target": target.key,
            "target_label": target.label,
            "url": url,
            "duration_ms": duration_ms,
            "status_code": response.status_code,
            "error": error,
            "error_message": "" if not error else f"HTTP {response.status_code}",
        }
    except httpx.HTTPError as exc:
        duration_ms = (time.perf_counter() - started) * 1000
        return {
            "method": target.method,
            "path": target.path,
            "target": target.key,
            "target_label": target.label,
            "url": url,
            "duration_ms": duration_ms,
            "status_code": None,
            "error": True,
            "error_message": str(exc),
        }


def _request_fixed_count(
    base_url: str,
    targets: list[LoadTarget],
    headers: dict[str, str],
    timeout: float,
    request_limit: int,
    worker_index: int,
    worker_count: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    sequence_counter = _request_sequence_counter()
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=False) as client:
        for index in range(worker_index, request_limit, worker_count):
            target = targets[index % len(targets)]
            results.append(_request_once(base_url, target, headers, timeout, client=client, sequence=next(sequence_counter)))
    return results


def _request_until_deadline(
    base_url: str,
    targets: list[LoadTarget],
    headers: dict[str, str],
    timeout: float,
    deadline: float | None,
    worker_index: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    index = worker_index
    sequence_counter = _request_sequence_counter()
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=False) as client:
        while deadline is None or time.perf_counter() < deadline:
            target = targets[index % len(targets)]
            results.append(_request_once(base_url, target, headers, timeout, client=client, sequence=next(sequence_counter)))
            index += 1
    return results


def _request_sequence_counter():
    return _REQUEST_SEQUENCE_COUNTER


def _render_target_for_request(target: LoadTarget, *, sequence: int | None = None) -> LoadTarget:
    values = dict(target.dynamic_values or {})
    if sequence is not None:
        values["sequence"] = int(sequence)
    _apply_sequence_pools(values, keys=_target_sequence_pool_keys(target))
    path_template = target.path_template or target.path
    body_template = target.json_body_template
    path = path_template.format(**values).strip()
    json_body = _format_json_body(body_template, values)
    multipart_file = json_body if _is_multipart_body(json_body) else None
    body = None if multipart_file is not None else json_body
    return LoadTarget(
        index=target.index,
        method=target.method,
        path=path,
        json_body=body,
        multipart_file=multipart_file,
        threshold_ms=target.threshold_ms,
        path_template=target.path_template,
        json_body_template=target.json_body_template,
        dynamic_values=target.dynamic_values,
    )


def _prepare_sequence_pool_counters(values: dict[str, Any]) -> None:
    pools = values.get("_sequence_pools") or {}
    if not isinstance(pools, dict):
        return
    counters = values.get("_sequence_pool_counters")
    if not isinstance(counters, dict):
        counters = {}
        values["_sequence_pool_counters"] = counters
    for key, pool in pools.items():
        if isinstance(key, str) and isinstance(pool, (list, tuple)) and pool and key not in counters:
            counters[key] = itertools.count()


def _apply_sequence_pools(values: dict[str, Any], *, keys: set[str] | None = None) -> None:
    pools = values.get("_sequence_pools") or {}
    if not isinstance(pools, dict):
        return
    counters = values.get("_sequence_pool_counters")
    if not isinstance(counters, dict):
        counters = {}
        values["_sequence_pool_counters"] = counters
    try:
        sequence = int(values.get("sequence") or 0)
    except (TypeError, ValueError):
        sequence = 0
    for key, pool in pools.items():
        if not isinstance(key, str) or not isinstance(pool, (list, tuple)) or not pool:
            continue
        if keys is not None and key not in keys:
            continue
        counter = counters.get(key)
        if counter is None:
            counter = itertools.count()
            counters[key] = counter
        values[key] = pool[next(counter) % len(pool)]


def _target_sequence_pool_keys(target: LoadTarget) -> set[str]:
    pools = (target.dynamic_values or {}).get("_sequence_pools") or {}
    if not isinstance(pools, dict):
        return set()
    pool_keys = {key for key in pools if isinstance(key, str)}
    if not pool_keys:
        return set()
    names = set()
    names.update(_template_field_names(target.path_template or target.path))
    names.update(_template_field_names(target.json_body_template))
    return pool_keys.intersection(names)


def _template_field_names(template: Any) -> set[str]:
    if template is None:
        return set()
    if isinstance(template, str):
        names = set()
        for _, field_name, _, _ in string.Formatter().parse(template):
            if field_name:
                names.add(field_name.split(".", 1)[0].split("[", 1)[0])
        return names
    if isinstance(template, dict):
        names = set()
        for key, value in template.items():
            names.update(_template_field_names(key))
            names.update(_template_field_names(value))
        return names
    if isinstance(template, (list, tuple)):
        names = set()
        for value in template:
            names.update(_template_field_names(value))
        return names
    return set()


def _summarize_target(target: LoadTarget, results: list[dict[str, Any]]) -> dict[str, Any]:
    target_results = [result for result in results if result["target"] == target.key]
    durations = [float(result["duration_ms"]) for result in target_results]
    status_counts: dict[str, int] = {}
    for result in target_results:
        key = str(result["status_code"]) if result["status_code"] is not None else "error"
        status_counts[key] = status_counts.get(key, 0) + 1
    error_count = sum(1 for result in target_results if result["error"])
    threshold = target.threshold_ms
    p95 = percentile(durations, 95)
    covered = bool(target_results)
    return {
        "method": target.method,
        "path": target.path,
        "target": target.key,
        "target_label": target.label,
        "has_json_body": target.json_body is not None,
        "has_multipart_file": target.multipart_file is not None,
        "covered": covered,
        "request_count": len(target_results),
        "error_count": error_count,
        "error_rate": error_count / len(target_results) if target_results else 0.0,
        "status_code_counts": status_counts,
        "min_ms": min(durations) if durations else 0.0,
        "max_ms": max(durations) if durations else 0.0,
        "average_ms": sum(durations) / len(durations) if durations else 0.0,
        "p50_ms": percentile(durations, 50),
        "p95_ms": p95,
        "p99_ms": percentile(durations, 99),
        "threshold_ms": threshold,
        "ok": covered and error_count == 0 and (threshold is None or p95 <= threshold),
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


def _profile_specs(profile: str) -> list[str]:
    if profile == "forum-main":
        entries = FORUM_MAIN_PROFILE
    elif profile == "forum-main-auth":
        entries = FORUM_MAIN_AUTH_PROFILE
    elif profile == "forum-write":
        entries = FORUM_WRITE_PROFILE
    elif profile == "forum-write-mixed":
        entries = FORUM_WRITE_MIXED_PROFILE
    elif profile == "forum-upload":
        entries = FORUM_UPLOAD_PROFILE
    elif profile == "forum-write-moderation":
        entries = FORUM_WRITE_MODERATION_PROFILE
    else:
        raise CommandError(f"未知 HTTP profile: {profile}")
    return [_profile_spec(method, path, body, threshold) for method, path, body, threshold in entries]


def _profile_spec(method: str, path: str, body: Any, threshold: float | None) -> str:
    threshold_part = "" if threshold is None else f"={threshold}"
    if _is_multipart_body(body):
        body_part = (
            " FILE "
            f"{body['field']}:{body['filename']}:{body['content_type']}:{body['content']}"
        )
    else:
        body_part = "" if body is None else f" {json.dumps(body, ensure_ascii=False, separators=(',', ':'))}"
    return f"{method} {path}{body_part}{threshold_part}"


def _split_method(raw: str) -> tuple[str, str]:
    upper = raw.upper()
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        prefix = f"{method} "
        if upper.startswith(prefix):
            return method, raw[len(prefix):].strip()
    return "GET", raw


def _split_path_and_json_body(raw: str) -> tuple[str, Any]:
    if " " not in raw:
        return raw, None
    path, body_text = raw.split(" ", 1)
    body_text = body_text.strip()
    if not body_text:
        return path, None
    if body_text.startswith("FILE "):
        return path, _parse_file_body(body_text[len("FILE "):])
    try:
        return path, json.loads(body_text)
    except json.JSONDecodeError as exc:
        raise CommandError(f"无效的 JSON body: {body_text}") from exc


def _format_json_body(body: Any, values: dict[str, Any]) -> Any:
    if isinstance(body, str):
        return body.format(**values)
    if isinstance(body, list):
        return [_format_json_body(item, values) for item in body]
    if isinstance(body, dict):
        return {key: _format_json_body(value, values) for key, value in body.items()}
    return body


def _is_multipart_body(body: Any) -> bool:
    return isinstance(body, dict) and {"field", "filename", "content_type", "content"}.issubset(body)


def _parse_file_body(raw: str) -> dict[str, Any]:
    parts = raw.split(":", 3)
    if len(parts) != 4:
        raise CommandError(f"无效的 FILE body，格式应为 field:filename:mime:content: {raw}")
    field, filename, content_type, content = (part.strip() for part in parts)
    if not field or not filename or not content_type:
        raise CommandError(f"无效的 FILE body，字段、文件名和 MIME 不能为空: {raw}")
    return {
        "field": field,
        "filename": filename,
        "content_type": content_type,
        "content": content,
    }


def _multipart_files_payload(file_spec: dict[str, Any]) -> dict[str, tuple[str, bytes, str]]:
    field = str(file_spec["field"])
    filename = str(file_spec["filename"])
    content_type = str(file_spec["content_type"])
    content = file_spec.get("content", b"")
    if isinstance(content, str):
        content_bytes = content.encode("utf-8")
    else:
        content_bytes = bytes(content)
    return {field: (filename, content_bytes, content_type)}


def resolve_dynamic_values(
    *,
    profile: str,
    discussion_id: int | None = None,
    post_id: int | None = None,
    tag_id: int | None = None,
    notification_id: int | None = None,
    prepare_isolated_targets: bool = False,
    actor_user_id: int | None = None,
) -> dict[str, Any]:
    values: dict[str, Any] = {"sequence": int(time.time() * 1000)}
    if prepare_isolated_targets:
        values.update(_prepare_isolated_targets(profile=profile, sequence=values["sequence"], actor_user_id=actor_user_id))
    if discussion_id is not None:
        values["discussion_id"] = int(discussion_id)
    if post_id is not None:
        values["post_id"] = int(post_id)
    if tag_id is not None:
        values["tag_id"] = int(tag_id)
    if notification_id is not None:
        values["notification_id"] = int(notification_id)

    if profile not in {"forum-write", "forum-write-mixed", "forum-write-moderation"}:
        return values

    if "discussion_id" not in values:
        discussion = _latest_model_row("content", "Discussion")
        if discussion is None:
            raise CommandError(f"{profile} profile 需要 --discussion-id 或数据库中已有 discussion")
        values["discussion_id"] = int(discussion.id)
    if profile in {"forum-write-mixed", "forum-write-moderation"} and "post_id" not in values:
        post = _latest_load_target_post(actor_user_id=actor_user_id) if profile == "forum-write-mixed" else _latest_model_row("content", "Post")
        if post is None:
            raise CommandError(f"{profile} profile 需要 --post-id 或数据库中已有 post")
        values["post_id"] = int(post.id)
        if profile == "forum-write-mixed":
            values.setdefault("like_post_id", values.get("post_id"))
            values.setdefault("unlike_post_id", values.get("post_id"))
    if profile == "forum-write-moderation":
        values.setdefault("edit_post_id", values.get("post_id"))
        values.setdefault("report_post_id", values.get("post_id"))
        values.setdefault("hide_post_id", values.get("post_id"))
        values.setdefault("restore_post_id", values.get("post_id"))
        values.setdefault("delete_post_id", values.get("post_id"))
    if profile == "forum-write-mixed" and "tag_id" not in values:
        tag = _latest_model_row("tags", "Tag")
        if tag is None:
            raise CommandError("forum-write-mixed profile 需要 --tag-id 或数据库中已有 tag")
        values["tag_id"] = int(tag.id)
    if profile == "forum-write-moderation" and "notification_id" not in values:
        notification = _latest_model_row("notifications", "Notification")
        if notification is None:
            raise CommandError("forum-write-moderation profile 需要 --notification-id 或数据库中已有 notification")
        values["notification_id"] = int(notification.id)
    if profile == "forum-write-moderation":
        values.setdefault("notification_read_id", values.get("notification_id"))
    return values


def _latest_model_row(app_label: str, model_name: str):
    try:
        model = apps.get_model(app_label, model_name)
    except LookupError:
        return None
    return model.objects.order_by("-id").only("id").first()


def _latest_load_target_post(*, actor_user_id: int | None):
    try:
        Post = apps.get_model("content", "Post")
    except LookupError:
        return None
    queryset = Post.objects.order_by("-id").only("id", "user_id")
    if actor_user_id:
        queryset = queryset.exclude(user_id=int(actor_user_id))
        try:
            PostLike = apps.get_model("likes", "PostLike")
        except LookupError:
            PostLike = None
        if PostLike is not None:
            liked_post_ids = PostLike.objects.filter(user_id=int(actor_user_id)).values("post_id")
            queryset = queryset.exclude(id__in=liked_post_ids)
    return queryset.first()


def _resolve_login_user_id(username: str) -> int | None:
    normalized = str(username or "").strip()
    if not normalized:
        return None
    UserModel = get_user_model()
    user = (
        UserModel.objects
        .filter(Q(username=normalized) | Q(email=normalized))
        .order_by("id")
        .only("id")
        .first()
    )
    return int(user.id) if user is not None else None


def _prepare_isolated_targets(*, profile: str, sequence: int, actor_user_id: int | None = None) -> dict[str, Any]:
    if profile not in {"forum-write", "forum-write-mixed", "forum-write-moderation"}:
        raise CommandError("--prepare-isolated-targets 仅支持写入 profile")

    UserModel = get_user_model()
    Discussion = _required_model("content", "Discussion")
    Post = _required_model("content", "Post")
    Tag = _optional_model("tags", "Tag")
    DiscussionTag = _optional_model("tags", "DiscussionTag")
    Notification = _optional_model("notifications", "Notification")

    if profile == "forum-write-mixed" and (Tag is None or DiscussionTag is None):
        raise CommandError("forum-write-mixed --prepare-isolated-targets 需要 tags.Tag 和 tags.DiscussionTag")
    if profile == "forum-write-moderation" and Notification is None:
        raise CommandError("forum-write-moderation --prepare-isolated-targets 需要 notifications.Notification")

    prefix = f"loadtest-isolated-{sequence}"
    transition_pool_size = _state_transition_pool_size()
    now = timezone.now()
    with transaction.atomic():
        user = _create_isolated_user(UserModel, prefix)
        actor = None
        if actor_user_id:
            actor = UserModel.objects.filter(id=int(actor_user_id)).first()
        discussion_user = actor or user
        discussion = Discussion.objects.create(
            title=f"Load isolated discussion {sequence}",
            slug=f"{prefix}-discussion",
            user=discussion_user,
            last_posted_user=user,
            last_posted_at=now,
            comment_count=0,
            participant_count=1,
            approval_status=getattr(Discussion, "APPROVAL_APPROVED", "approved"),
            approved_at=now,
        )
        tag = None
        if Tag is not None:
            tag = Tag.objects.create(
                name=f"Load Isolated Tag {sequence}",
                slug=f"{prefix}-tag",
                description="Load test isolated tag",
                position=sequence % 1000000,
                is_primary=True,
            )
            if DiscussionTag is not None:
                DiscussionTag.objects.create(discussion_id=discussion.id, tag_id=tag.id)

        first_post = Post.objects.create(
            discussion=discussion,
            number=1,
            user=user,
            type="comment",
            content=f"{prefix} first post",
            content_html=f"<p>{prefix} first post</p>",
            approval_status=getattr(Post, "APPROVAL_APPROVED", "approved"),
            approved_at=now,
        )
        next_post_number = 2
        reply = Post.objects.create(
            discussion=discussion,
            number=next_post_number,
            user=user,
            type="comment",
            content=f"{prefix} moderation target",
            content_html=f"<p>{prefix} moderation target</p>",
            approval_status=getattr(Post, "APPROVAL_APPROVED", "approved"),
            approved_at=now,
        )
        next_post_number += 1
        unlike_post = Post.objects.create(
            discussion=discussion,
            number=next_post_number,
            user=user,
            type="comment",
            content=f"{prefix} unlike target",
            content_html=f"<p>{prefix} unlike target</p>",
            approval_status=getattr(Post, "APPROVAL_APPROVED", "approved"),
            approved_at=now,
        )
        next_post_number += 1
        like_post_pool: list[int] = [int(reply.id)]
        unlike_post_pool: list[int] = [int(unlike_post.id)]
        edit_post_pool: list[int] = []
        report_post_pool: list[int] = []
        hide_post_pool: list[int] = []
        restore_post_pool: list[int] = []
        delete_post_pool: list[int] = []
        if actor is not None:
            try:
                PostLike = apps.get_model("likes", "PostLike")
            except LookupError:
                PostLike = None
            if PostLike is not None:
                PostLike.objects.get_or_create(post_id=unlike_post.id, user=actor)
            if profile == "forum-write-mixed":
                for pool_index in range(transition_pool_size):
                    like_target = Post.objects.create(
                        discussion=discussion,
                        number=next_post_number,
                        user=user,
                        type="comment",
                        content=f"{prefix} like target {pool_index}",
                        content_html=f"<p>{prefix} like target {pool_index}</p>",
                        approval_status=getattr(Post, "APPROVAL_APPROVED", "approved"),
                        approved_at=now,
                    )
                    next_post_number += 1
                    unlike_target = Post.objects.create(
                        discussion=discussion,
                        number=next_post_number,
                        user=user,
                        type="comment",
                        content=f"{prefix} unlike target {pool_index}",
                        content_html=f"<p>{prefix} unlike target {pool_index}</p>",
                        approval_status=getattr(Post, "APPROVAL_APPROVED", "approved"),
                        approved_at=now,
                    )
                    next_post_number += 1
                    PostLike.objects.get_or_create(post_id=unlike_target.id, user=actor)
                    like_post_pool.append(int(like_target.id))
                    unlike_post_pool.append(int(unlike_target.id))
            elif profile == "forum-write-moderation":
                for pool_index in range(transition_pool_size + 1):
                    edit_target = _create_isolated_post(
                        Post,
                        discussion=discussion,
                        user=user,
                        number=next_post_number,
                        content=f"{prefix} edit target {pool_index}",
                        approved_at=now,
                    )
                    next_post_number += 1
                    report_target = _create_isolated_post(
                        Post,
                        discussion=discussion,
                        user=user,
                        number=next_post_number,
                        content=f"{prefix} report target {pool_index}",
                        approved_at=now,
                    )
                    next_post_number += 1
                    hide_target = _create_isolated_post(
                        Post,
                        discussion=discussion,
                        user=user,
                        number=next_post_number,
                        content=f"{prefix} hide target {pool_index}",
                        approved_at=now,
                    )
                    next_post_number += 1
                    restore_target = _create_isolated_post(
                        Post,
                        discussion=discussion,
                        user=user,
                        number=next_post_number,
                        content=f"{prefix} restore target {pool_index}",
                        approved_at=now,
                    )
                    _mark_post_hidden(Post, restore_target, now=now)
                    next_post_number += 1
                    delete_target = _create_isolated_post(
                        Post,
                        discussion=discussion,
                        user=user,
                        number=next_post_number,
                        content=f"{prefix} delete target {pool_index}",
                        approved_at=now,
                    )
                    next_post_number += 1
                    edit_post_pool.append(int(edit_target.id))
                    report_post_pool.append(int(report_target.id))
                    hide_post_pool.append(int(hide_target.id))
                    restore_post_pool.append(int(restore_target.id))
                    delete_post_pool.append(int(delete_target.id))
        discussion.first_post_id = first_post.id
        discussion.last_post_id = (
            delete_post_pool[-1]
            if profile == "forum-write-moderation" and actor is not None
            else unlike_post_pool[-1]
        )
        discussion.last_post_number = next_post_number - 1
        discussion.comment_count = discussion.last_post_number
        discussion.save(update_fields=["first_post_id", "last_post_id", "last_post_number", "comment_count"])

        notification = None
        notification_user = user
        if actor_user_id:
            notification_user = UserModel.objects.filter(id=int(actor_user_id)).first() or user
        if Notification is not None:
            notification = Notification.objects.create(
                user=notification_user,
                from_user=user,
                type="loadTestSingleRead" if profile == "forum-write-moderation" else "postReply",
                subject_type="post",
                subject_id=reply.id,
                data={
                    "post_id": reply.id,
                    "discussion_id": discussion.id,
                    "discussion_title": discussion.title,
                },
                is_read=False,
                is_deleted=False,
            )
            notification_read_pool: list[int] = [int(notification.id)]
            if profile == "forum-write-moderation":
                for pool_index, subject_id in enumerate(report_post_pool[1:]):
                    pooled_notification = Notification.objects.create(
                        user=notification_user,
                        from_user=user,
                        type="loadTestSingleRead",
                        subject_type="post",
                        subject_id=subject_id,
                        data={
                            "post_id": subject_id,
                            "discussion_id": discussion.id,
                            "discussion_title": discussion.title,
                            "load_test_index": pool_index,
                        },
                        is_read=False,
                        is_deleted=False,
                    )
                    notification_read_pool.append(int(pooled_notification.id))
        else:
            notification_read_pool = []

    isolated = {
        "prefix": prefix,
        "user_id": user.id,
        "discussion_id": discussion.id,
        "post_id": reply.id,
        "like_post_id": reply.id,
        "unlike_post_id": unlike_post.id,
        "edit_post_id": edit_post_pool[0] if edit_post_pool else reply.id,
        "report_post_id": report_post_pool[0] if report_post_pool else reply.id,
        "hide_post_id": hide_post_pool[0] if hide_post_pool else reply.id,
        "restore_post_id": restore_post_pool[0] if restore_post_pool else reply.id,
        "delete_post_id": delete_post_pool[0] if delete_post_pool else reply.id,
        "first_post_id": first_post.id,
        "like_post_pool_size": len(like_post_pool),
        "unlike_post_pool_size": len(unlike_post_pool),
        "edit_post_pool_size": len(edit_post_pool),
        "report_post_pool_size": len(report_post_pool),
        "hide_post_pool_size": len(hide_post_pool),
        "restore_post_pool_size": len(restore_post_pool),
        "delete_post_pool_size": len(delete_post_pool),
    }
    values = {
        "discussion_id": int(discussion.id),
        "post_id": int(reply.id),
        "like_post_id": int(reply.id),
        "unlike_post_id": int(unlike_post.id),
        "edit_post_id": int(edit_post_pool[0]) if edit_post_pool else int(reply.id),
        "report_post_id": int(report_post_pool[0]) if report_post_pool else int(reply.id),
        "hide_post_id": int(hide_post_pool[0]) if hide_post_pool else int(reply.id),
        "restore_post_id": int(restore_post_pool[0]) if restore_post_pool else int(reply.id),
        "delete_post_id": int(delete_post_pool[0]) if delete_post_pool else int(reply.id),
        "isolated_targets": isolated,
    }
    if profile == "forum-write-mixed" and actor is not None:
        values["_sequence_pools"] = {
            "like_post_id": like_post_pool,
            "unlike_post_id": unlike_post_pool,
        }
    if profile == "forum-write-moderation" and actor is not None:
        values["_sequence_pools"] = {
            "edit_post_id": edit_post_pool,
            "report_post_id": report_post_pool,
            "hide_post_id": hide_post_pool,
            "restore_post_id": restore_post_pool,
            "delete_post_id": delete_post_pool,
        }
    if tag is not None:
        values["tag_id"] = int(tag.id)
        isolated["tag_id"] = tag.id
    if notification is not None:
        values["notification_id"] = int(notification.id)
        values["notification_read_id"] = int(notification.id)
        if profile == "forum-write-moderation" and actor is not None:
            values["_sequence_pools"]["notification_read_id"] = notification_read_pool
        isolated["notification_id"] = notification.id
        isolated["notification_read_id"] = notification.id
        isolated["notification_read_pool_size"] = len(notification_read_pool)
    return values


def _create_isolated_post(Post, *, discussion: Any, user: Any, number: int, content: str, approved_at) -> Any:
    return Post.objects.create(
        discussion=discussion,
        number=number,
        user=user,
        type="comment",
        content=content,
        content_html=f"<p>{content}</p>",
        approval_status=getattr(Post, "APPROVAL_APPROVED", "approved"),
        approved_at=approved_at,
    )


def _mark_post_hidden(Post, post: Any, *, now) -> None:
    update_fields = []
    if hasattr(post, "hidden_at"):
        post.hidden_at = now
        update_fields.append("hidden_at")
    if hasattr(post, "hidden_reason"):
        post.hidden_reason = "load-test-restore-target"
        update_fields.append("hidden_reason")
    if hasattr(post, "visibility"):
        post.visibility = "hidden"
        update_fields.append("visibility")
    if hasattr(Post, "APPROVAL_HIDDEN") and hasattr(post, "approval_status"):
        post.approval_status = getattr(Post, "APPROVAL_HIDDEN")
        update_fields.append("approval_status")
    if update_fields:
        post.save(update_fields=update_fields)


def _state_transition_pool_size() -> int:
    raw = str(os.environ.get(STATE_TRANSITION_POOL_SIZE_ENV) or "").strip()
    if not raw:
        return DEFAULT_STATE_TRANSITION_POOL_SIZE
    try:
        return max(1, int(raw))
    except ValueError as exc:
        raise CommandError(f"{STATE_TRANSITION_POOL_SIZE_ENV} 必须是正整数") from exc


def cleanup_isolated_targets_for_prefix(prefix: str) -> dict[str, Any]:
    prefix = str(prefix or "").strip()
    if not prefix.startswith("loadtest-isolated-"):
        raise CommandError("只允许清理 loadtest-isolated-* 前缀的隔离压测数据")

    UserModel = get_user_model()
    Discussion = _optional_model("content", "Discussion")
    Post = _optional_model("content", "Post")
    Tag = _optional_model("tags", "Tag")
    DiscussionTag = _optional_model("tags", "DiscussionTag")
    Notification = _optional_model("notifications", "Notification")

    deleted: dict[str, int] = {}
    details: dict[str, dict[str, int]] = {}
    with transaction.atomic():
        users = UserModel.objects.filter(Q(username=f"{prefix}-user") | Q(email=f"{prefix}@example.test"))
        user_ids = list(users.values_list("id", flat=True))

        discussion_ids: list[int] = []
        post_ids: list[int] = []
        tag_ids: list[int] = []
        if Discussion is not None:
            discussions = Discussion.objects.filter(Q(slug=f"{prefix}-discussion") | Q(title__startswith="Load isolated discussion "))
            discussions = discussions.filter(slug__startswith=prefix)
            discussion_ids = list(discussions.values_list("id", flat=True))
        if Post is not None:
            posts = Post.objects.filter(Q(content__startswith=prefix) | Q(content_html__contains=prefix))
            if discussion_ids:
                posts = posts | Post.objects.filter(discussion_id__in=discussion_ids)
            post_ids = list(posts.values_list("id", flat=True).distinct())
        if Tag is not None:
            tags = Tag.objects.filter(Q(slug=f"{prefix}-tag") | Q(slug__startswith=f"{prefix}-"))
            tag_ids = list(tags.values_list("id", flat=True))

        if Notification is not None:
            notifications = Notification.objects.none()
            if user_ids:
                notifications = notifications | Notification.objects.filter(Q(user_id__in=user_ids) | Q(from_user_id__in=user_ids))
            if post_ids:
                notifications = notifications | Notification.objects.filter(subject_type="post", subject_id__in=post_ids)
            if discussion_ids:
                notifications = notifications | Notification.objects.filter(subject_type="discussion", subject_id__in=discussion_ids)
            if discussion_ids:
                notifications = notifications | Notification.objects.filter(data__discussion_id__in=discussion_ids)
            _delete_queryset("notifications.Notification", notifications.distinct(), deleted, details)

        if DiscussionTag is not None:
            discussion_tags = DiscussionTag.objects.none()
            if discussion_ids:
                discussion_tags = discussion_tags | DiscussionTag.objects.filter(discussion_id__in=discussion_ids)
            if tag_ids:
                discussion_tags = discussion_tags | DiscussionTag.objects.filter(tag_id__in=tag_ids)
            _delete_queryset("tags.DiscussionTag", discussion_tags.distinct(), deleted, details)

        if Discussion is not None and discussion_ids:
            _delete_queryset("content.Discussion", Discussion.objects.filter(id__in=discussion_ids), deleted, details)
        if Tag is not None and tag_ids:
            _delete_queryset("tags.Tag", Tag.objects.filter(id__in=tag_ids), deleted, details)
        if user_ids:
            _delete_queryset("auth.User", UserModel.objects.filter(id__in=user_ids), deleted, details)

    return {
        "ok": True,
        "prefix": prefix,
        "deleted_total": sum(deleted.values()),
        "deleted": deleted,
        "details": details,
    }


def _delete_queryset(label: str, queryset, deleted: dict[str, int], details: dict[str, dict[str, int]]) -> None:
    total, model_details = queryset.delete()
    deleted[label] = int(total)
    details[label] = {str(key): int(value) for key, value in model_details.items()}


def _create_isolated_user(UserModel, prefix: str):
    fields = {field.name for field in UserModel._meta.fields}
    user = UserModel(
        username=f"{prefix}-user",
        email=f"{prefix}@example.test",
        password="!",
    )
    if "display_name" in fields:
        user.display_name = "Load Isolated User"
    if "is_email_confirmed" in fields:
        user.is_email_confirmed = True
    if "is_active" in fields:
        user.is_active = True
    if "preferences" in fields:
        user.preferences = dict(LOAD_TEST_NOTIFICATION_PREFERENCES)
    user.save()
    return user


def _required_model(app_label: str, model_name: str):
    try:
        return apps.get_model(app_label, model_name)
    except LookupError as exc:
        raise CommandError(f"缺少必需模型 {app_label}.{model_name}，请先启用 foundation 扩展并执行迁移。") from exc


def _optional_model(app_label: str, model_name: str):
    try:
        return apps.get_model(app_label, model_name)
    except LookupError:
        return None
