from __future__ import annotations

from typing import Any

from django.db import connection

from bias_core import admin_runtime_summary
from bias_core.queue_service import QueueService
from bias_core.runtime_state import get_runtime_status
from bias_core.services.http_metrics import get_http_metrics
from bias_core.settings_service import get_advanced_settings
from bias_core.storage_service import get_runtime_storage_settings, get_storage_backend, get_storage_metrics


def collect_health_status(
    *,
    advanced_settings: dict[str, Any] | None = None,
    cache_connection: dict[str, Any] | None = None,
    realtime_connection: dict[str, Any] | None = None,
    queue_broker_connection: dict[str, Any] | None = None,
    queue_worker_status: dict[str, Any] | None = None,
    storage_config: dict[str, Any] | None = None,
    queue_enabled: bool | None = None,
    queue_driver: str | None = None,
) -> dict[str, Any]:
    runtime = get_runtime_status()
    advanced_settings = advanced_settings or get_advanced_settings()
    if queue_driver is None:
        queue_driver = str(advanced_settings.get("queue_driver") or "sync")
    if queue_enabled is None:
        queue_enabled = bool(advanced_settings.get("queue_enabled", False))

    app_check = {
        "status": "ok" if runtime.state in {"ready", "starting"} else "degraded",
        "available": runtime.state in {"ready", "starting"},
        "message": "Bias API runtime is available.",
        "state": runtime.state,
        "current_version": runtime.current_version,
        "installed_version": runtime.installed_version,
    }
    db_check = _probe_database()
    cache_connection = cache_connection or admin_runtime_summary.probe_cache_connection()
    realtime_connection = realtime_connection or admin_runtime_summary.probe_realtime_connection()
    queue_broker_connection = queue_broker_connection or admin_runtime_summary.probe_queue_broker_connection(
        bool(queue_enabled),
        str(queue_driver),
    )
    queue_worker_status = queue_worker_status or QueueService.get_worker_status()
    cache_check = _normalize_dependency_check(cache_connection)
    realtime_check = _normalize_dependency_check(realtime_connection)
    queue_broker_check = _normalize_dependency_check(
        queue_broker_connection
    )
    queue_worker_check = _normalize_worker_check(queue_worker_status)
    storage_check = _probe_storage(storage_config or advanced_settings)
    http_check = _probe_http_metrics()
    checks = {
        "app": app_check,
        "db": db_check,
        "http": http_check,
        "cache": cache_check,
        "queue": {
            "status": _combine_status(queue_broker_check, queue_worker_check, disabled_ok=True),
            "available": _combine_available(queue_broker_check, queue_worker_check),
            "broker": queue_broker_check,
            "worker": queue_worker_check,
        },
        "realtime": realtime_check,
        "storage": storage_check,
    }

    status = "ok"
    if any(check.get("status") in {"error", "unavailable", "misconfigured", "degraded"} for check in checks.values()):
        status = "degraded"

    return {
        "status": status,
        "checks": checks,
    }


def strict_health_failed(payload: dict[str, Any]) -> bool:
    if payload.get("status") != "ok":
        return True
    checks = payload.get("checks") or {}
    for check in checks.values():
        if isinstance(check, dict) and check.get("status") in {"error", "unavailable", "misconfigured", "degraded"}:
            return True
    return False


def health_status_code(payload: dict[str, Any], *, strict: bool = False) -> int:
    if strict and strict_health_failed(payload):
        return 503
    return 200


def _probe_database() -> dict[str, Any]:
    try:
        connection.ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:
        return {
            "status": "unavailable",
            "available": False,
            "message": str(exc) or "Database connection failed.",
        }

    return {
        "status": "available",
        "available": True,
        "message": "Database connection is available.",
        "vendor": connection.vendor,
    }


def _probe_storage(config: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        config = config or get_runtime_storage_settings()
        backend = get_storage_backend(config)
    except Exception as exc:
        return {
            "status": "misconfigured",
            "available": False,
            "message": str(exc) or "Storage backend could not be initialized.",
        }

    driver = str(config.get("storage_driver") or "local").strip().lower()
    backend_name = getattr(getattr(backend, "backend", None), "__class__", backend.__class__).__name__
    return {
        "status": "available",
        "available": True,
        "message": "Storage backend is configured.",
        "driver": driver,
        "backend": backend_name,
        "metrics": get_storage_metrics(),
    }


def _probe_http_metrics() -> dict[str, Any]:
    metrics = get_http_metrics()
    return {
        "status": "available",
        "available": True,
        "message": "HTTP request metrics are enabled.",
        "metrics": metrics,
    }


def _normalize_dependency_check(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": payload.get("status") or "unknown",
        "available": payload.get("available"),
        "enabled": bool(payload.get("enabled", False)),
        "label": payload.get("label") or "",
        "message": payload.get("message") or "",
    }


def _normalize_worker_check(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": payload.get("status") or "unknown",
        "available": payload.get("available"),
        "label": payload.get("label") or "",
        "message": payload.get("message") or "",
        "worker_count": int(payload.get("worker_count", 0) or 0),
    }


def _combine_available(*checks: dict[str, Any]) -> bool | None:
    enabled_checks = [check for check in checks if check.get("available") is not None]
    if not enabled_checks:
        return None
    return all(bool(check.get("available")) for check in enabled_checks)


def _combine_status(*checks: dict[str, Any], disabled_ok: bool = False) -> str:
    relevant = [check for check in checks if check.get("available") is not None]
    if not relevant:
        return "disabled" if disabled_ok else "unknown"
    if all(check.get("available") is True for check in relevant):
        return "available"
    for check in relevant:
        if check.get("available") is False:
            return str(check.get("status") or "unavailable")
    return "unknown"
