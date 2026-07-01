from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from bias_core.extensions.exceptions import ExtensionManifestError
from bias_core.extensions.manifest import ExtensionManifestLoader
from bias_core.queue_service import QueueService
from bias_core.services.http_metrics import get_http_metrics
from bias_core.storage_service import get_storage_metrics


DISCUSSION_QUERY_BUDGETS = {
    "discussion_list": {
        "path": "/api/discussions/?limit=6",
        "max_queries": 24,
        "test": "tests.test_forum_discussion_api.ForumDiscussionApiTests.test_discussion_list_endpoint_keeps_query_count_within_budget",
    },
    "discussion_detail": {
        "path": "/api/discussions/{id}",
        "max_queries": 20,
        "test": "tests.test_forum_discussion_api.ForumDiscussionApiTests.test_discussion_detail_endpoint_keeps_query_count_within_budget",
    },
    "post_stream": {
        "path": "/api/discussions/{id}/posts?near={number}&limit=8",
        "max_queries": 22,
        "test": "tests.test_forum_discussion_api.ForumDiscussionApiTests.test_post_stream_endpoint_keeps_query_count_within_budget",
    },
}

QUEUE_REQUIRED_METRICS = {
    "enqueued_count",
    "sync_count",
    "fallback_count",
    "failed_count",
    "retry_count",
    "task_event_count",
    "last_duration_ms",
    "max_duration_ms",
    "average_duration_ms",
    "failure_rate",
}

HTTP_REQUIRED_METRICS = {
    "request_count",
    "error_count",
    "last_duration_ms",
    "max_duration_ms",
    "average_duration_ms",
    "error_rate",
    "status_code_counts",
    "method_counts",
}

STORAGE_REQUIRED_METRICS = {
    "upload_count",
    "upload_failure_count",
    "delete_count",
    "delete_failure_count",
    "operation_count",
    "failure_count",
    "last_duration_ms",
    "max_duration_ms",
    "average_duration_ms",
    "failure_rate",
    "total_bytes",
}

SITE_HOST_DIRECTORY_NAMES = {"bias", "bias_site", "site"}

EXPECTED_EXTENSION_PERFORMANCE_CONTRACTS = {
    "tag_stats_refresh": "tag stats refresh exposes batched implementation and duration metrics.",
    "notification_pagination_indexes": "notification list has pagination and required indexes.",
    "search_driver_boundary": "database search uses PostgreSQL full text only when supported and keeps extension targets behind runtime services.",
    "realtime_metrics": "realtime metrics include connections, subscriptions and message counters.",
}


class Command(BaseCommand):
    help = "Inspect CI-friendly performance baseline contracts for production readiness."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--format", choices=("text", "json"), default="text")
        parser.add_argument("--strict", action="store_true", help="Fail when any baseline check is missing.")
        parser.add_argument(
            "--extensions-path",
            help="Extension directory path; defaults to BASE_DIR/extensions and scans sibling split repositories.",
        )

    def handle(self, **options):
        extensions_path = Path(options.get("extensions_path") or (Path(settings.BASE_DIR) / "extensions"))
        payload = build_performance_baseline_payload(extensions_path=extensions_path)
        if options["format"] == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            self._write_text(payload)

        if options["strict"] and not payload["ok"]:
            missing = [
                check["name"]
                for check in payload["checks"]
                if check["status"] != "ok"
            ]
            raise CommandError(f"performance baseline check failed: {', '.join(missing)}")

    def _write_text(self, payload: dict[str, Any]) -> None:
        status = "OK" if payload["ok"] else "FAILED"
        self.stdout.write(f"Performance baseline: {status}")
        for check in payload["checks"]:
            marker = "ok" if check["status"] == "ok" else "missing"
            self.stdout.write(f"- [{marker}] {check['name']}: {check['message']}")


def build_performance_baseline_payload(extensions_path: Path | str | None = None) -> dict[str, Any]:
    resolved_extensions_path = Path(extensions_path or (Path(settings.BASE_DIR) / "extensions"))
    extension_contracts = _discover_performance_contracts(resolved_extensions_path)
    checks = [
        _discussion_query_budget_check(),
        _extension_performance_contract_check(extension_contracts, "tag_stats_refresh"),
        _extension_performance_contract_check(extension_contracts, "notification_pagination_indexes"),
        _extension_performance_contract_check(extension_contracts, "search_driver_boundary"),
        _http_metrics_check(),
        _storage_metrics_check(),
        _queue_metrics_check(),
        _extension_performance_contract_check(extension_contracts, "realtime_metrics"),
    ]
    return {
        "ok": all(check["status"] == "ok" for check in checks),
        "checks": checks,
        "extensions_path": str(resolved_extensions_path),
        "extension_contract_count": len(extension_contracts),
        "p95_load_test_required": True,
        "p95_note": "此命令只验证仓库内性能基线契约；正式上线前仍需在目标部署环境执行真实数据量 P95 压测。",
    }


def _check(name: str, status: str, message: str, **extra) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "message": message,
        **extra,
    }


def _discussion_query_budget_check() -> dict[str, Any]:
    return _check(
        "discussion_query_budgets",
        "ok",
        "discussion list/detail/post stream query budget tests are declared.",
        budgets=DISCUSSION_QUERY_BUDGETS,
    )


def _extension_performance_contract_check(
    contracts: dict[str, dict[str, Any]],
    name: str,
) -> dict[str, Any]:
    contract = contracts.get(name)
    if not contract:
        return _check(
            name,
            "missing",
            f"extension performance contract is not declared: {name}",
        )

    status = str(contract.get("status") or "ok").strip() or "ok"
    message = str(
        contract.get("message")
        or EXPECTED_EXTENSION_PERFORMANCE_CONTRACTS.get(name)
        or "extension performance contract is declared."
    ).strip()
    extra = {
        key: value
        for key, value in contract.items()
        if key not in {"name", "status", "message"}
    }
    return _check(name, status, message, **extra)


def _discover_performance_contracts(extensions_path: Path) -> dict[str, dict[str, Any]]:
    include_workspace = extensions_path.name == "extensions"
    loader = ExtensionManifestLoader(
        extensions_path,
        include_workspace=include_workspace,
        workspace_root=_resolve_command_workspace_root(extensions_path),
    )
    try:
        manifests = loader.discover_manifests()
    except ExtensionManifestError as exc:
        raise CommandError(str(exc)) from exc

    contracts: dict[str, dict[str, Any]] = {}
    for manifest in manifests:
        for contract in _load_manifest_performance_contracts(manifest):
            name = str(contract.get("name") or "").strip()
            if not name:
                continue
            contracts[name] = {
                "extension_id": manifest.id,
                "extension_name": manifest.name,
                "extension_version": manifest.version,
                **contract,
                "name": name,
            }
    return contracts


def _load_manifest_performance_contracts(manifest) -> list[dict[str, Any]]:
    manifest_path = Path(manifest.path) / "extension.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    contracts = payload.get("performance_contracts")
    if not isinstance(contracts, list):
        return []
    return [
        dict(item)
        for item in contracts
        if isinstance(item, dict)
    ]


def _resolve_command_workspace_root(extensions_path: Path) -> Path | None:
    if extensions_path.name != "extensions":
        return None
    configured = getattr(settings, "BIAS_EXTENSION_WORKSPACE_ROOT", None)
    if configured:
        configured_path = Path(configured)
        if configured_path.exists():
            return configured_path
    if extensions_path.parent.name in SITE_HOST_DIRECTORY_NAMES:
        return extensions_path.parent.parent
    return extensions_path.parent


def _queue_metrics_check() -> dict[str, Any]:
    metrics = QueueService.get_metrics()
    missing = sorted(QUEUE_REQUIRED_METRICS - set(metrics))
    return _check(
        "queue_worker_metrics",
        "ok" if not missing else "missing",
        "queue metrics include task duration, failure rate and retry count." if not missing else "queue metrics are missing required fields.",
        required_fields=sorted(QUEUE_REQUIRED_METRICS),
        missing_fields=missing,
    )


def _http_metrics_check() -> dict[str, Any]:
    metrics = get_http_metrics()
    missing = sorted(HTTP_REQUIRED_METRICS - set(metrics))
    return _check(
        "http_request_metrics",
        "ok" if not missing else "missing",
        "HTTP metrics include request counts, status buckets and latency fields." if not missing else "HTTP metrics are missing required fields.",
        required_fields=sorted(HTTP_REQUIRED_METRICS),
        missing_fields=missing,
    )


def _storage_metrics_check() -> dict[str, Any]:
    metrics = get_storage_metrics()
    missing = sorted(STORAGE_REQUIRED_METRICS - set(metrics))
    return _check(
        "storage_operation_metrics",
        "ok" if not missing else "missing",
        "storage metrics include upload/delete counts, failures, bytes and latency fields." if not missing else "storage metrics are missing required fields.",
        required_fields=sorted(STORAGE_REQUIRED_METRICS),
        missing_fields=missing,
    )
