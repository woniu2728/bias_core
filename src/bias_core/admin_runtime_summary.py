from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.cache import cache

from bias_core import runtime_diagnostics
from bias_core.queue_service import QueueService
from bias_core.runtime_diagnostics import (
    build_runtime_dependency_checks,
    detect_queue_driver_label,
    probe_redis_ping,
)
from bias_core.settings_service import get_advanced_settings


def probe_cache_connection() -> dict[str, Any]:
    return runtime_diagnostics.probe_cache_connection(settings_obj=settings, cache_backend=cache)


def probe_realtime_connection() -> dict[str, Any]:
    return runtime_diagnostics.probe_realtime_connection(
        settings_obj=settings,
        redis_probe=lambda host, port, label, password="": probe_redis_ping(
            host,
            port,
            label=label,
            password=password,
        ),
    )


def probe_queue_broker_connection(queue_enabled: bool, queue_driver: str) -> dict[str, Any]:
    return runtime_diagnostics.probe_queue_broker_connection(
        settings_obj=settings,
        queue_enabled=queue_enabled,
        queue_driver=queue_driver,
        redis_probe=lambda host, port, label, password="": probe_redis_ping(
            host,
            port,
            label=label,
            password=password,
        ),
    )


def build_runtime_dependency_summary() -> dict[str, Any]:
    advanced_settings = get_advanced_settings()
    queue_driver = advanced_settings.get("queue_driver", "sync")
    queue_enabled = bool(advanced_settings.get("queue_enabled", False))
    queue_worker_status = QueueService.get_worker_status()
    cache_connection = probe_cache_connection()
    realtime_connection = probe_realtime_connection()
    queue_broker_connection = probe_queue_broker_connection(queue_enabled, queue_driver)
    checks = build_runtime_dependency_checks(
        cache_connection=cache_connection,
        realtime_connection=realtime_connection,
        queue_broker_connection=queue_broker_connection,
        queue_worker_status=queue_worker_status,
    )
    issues = [
        f"{item['label']}：{item['status_label']}"
        for item in checks
        if item.get("available") is False
    ]
    return {
        "status": "attention" if issues else "healthy",
        "label": "需关注" if issues else "健康",
        "issues": issues,
        "checks": checks,
        "queue_label": detect_queue_driver_label(queue_enabled, queue_driver),
    }
