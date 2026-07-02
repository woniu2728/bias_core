from __future__ import annotations

import json
from pathlib import Path
import sys

import django
from django.conf import settings
from ninja import Router

from bias_core import admin_runtime_summary
from bias_core import runtime_diagnostics
from bias_core.admin_auth import require_staff
from bias_core.jwt_auth import AccessTokenAuth
from bias_core.queue_service import QueueService
from bias_core.runtime_diagnostics import (
    build_runtime_dependency_checks,
    detect_cache_driver,
    detect_database_label,
    detect_queue_driver_label,
    detect_realtime_driver,
    is_redis_enabled,
)
from bias_core.health import collect_health_status
from bias_core.services.http_metrics import get_http_metrics
from bias_core.storage_service import get_storage_metrics


router = Router()


CAPACITY_SMOKE_PROFILES = {
    "forum-main": "P0 anonymous read",
    "forum-main-auth": "P1 authenticated read",
    "forum-write": "P1 write reply",
    "forum-write-mixed": "P1 mixed write",
    "forum-upload": "P1 upload",
    "forum-write-moderation": "P1 moderation",
}


def _build_auth_secret_risks() -> list[dict]:
    secret_key = runtime_diagnostics.normalize_secret_value(settings.SECRET_KEY)
    jwt_algorithm = str(settings.NINJA_JWT.get("ALGORITHM") or "").strip().upper()
    jwt_signing_key = runtime_diagnostics.normalize_secret_value(
        settings.NINJA_JWT.get("SIGNING_KEY") or settings.SECRET_KEY
    )
    return runtime_diagnostics.build_auth_secret_risks(
        secret_key=secret_key,
        jwt_algorithm=jwt_algorithm,
        jwt_signing_key=jwt_signing_key,
    ) or []


def _build_capacity_smoke_summary() -> dict:
    report_root = Path(settings.BASE_DIR) / "reports" / "capacity"
    profiles = {
        profile: {
            "profile": profile,
            "label": label,
            "status": "missing",
            "ok": False,
            "runId": "",
            "reportFile": "",
            "requestCount": 0,
            "errorCount": 0,
            "errorRate": None,
            "failedThresholdCount": 0,
            "durationSeconds": None,
            "concurrency": None,
        }
        for profile, label in CAPACITY_SMOKE_PROFILES.items()
    }
    if report_root.exists():
        for run_dir in sorted((path for path in report_root.iterdir() if path.is_dir()), reverse=True):
            for report_file in sorted(run_dir.glob("*.json")):
                try:
                    payload = json.loads(report_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                profile = str(payload.get("profile") or "").strip()
                if profile not in profiles or profiles[profile]["reportFile"]:
                    continue
                summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
                ok = bool(summary.get("ok"))
                profiles[profile].update({
                    "status": "passed" if ok else "failed",
                    "ok": ok,
                    "runId": run_dir.name,
                    "reportFile": str(report_file.relative_to(report_root.parent.parent)),
                    "requestCount": int(summary.get("request_count") or 0),
                    "errorCount": int(summary.get("error_count") or 0),
                    "errorRate": summary.get("error_rate"),
                    "failedThresholdCount": int(summary.get("failed_threshold_count") or 0),
                    "durationSeconds": payload.get("duration_seconds"),
                    "concurrency": payload.get("concurrency"),
                })

    profile_values = list(profiles.values())
    missing_count = sum(1 for profile in profile_values if profile["status"] == "missing")
    failed_count = sum(1 for profile in profile_values if profile["status"] == "failed")
    passed_count = sum(1 for profile in profile_values if profile["status"] == "passed")
    if failed_count:
        status = "failed"
    elif missing_count == len(profile_values):
        status = "missing"
    elif missing_count:
        status = "partial"
    else:
        status = "passed"
    return {
        "schema": 1,
        "status": status,
        "ok": status == "passed",
        "reportRoot": str(report_root),
        "profileCount": len(profile_values),
        "passedCount": passed_count,
        "failedCount": failed_count,
        "missingCount": missing_count,
        "profiles": profile_values,
    }


@router.get("/stats", auth=AccessTokenAuth(), tags=["Admin"])
def get_stats(request):
    denied = require_staff(request)
    if denied:
        return denied

    from bias_core import admin_stats_api as public_admin_stats_api

    advanced_settings = public_admin_stats_api.get_runtime_advanced_settings()
    queue_driver = advanced_settings.get("queue_driver", "sync")
    queue_enabled = bool(advanced_settings.get("queue_enabled", False))
    queue_worker_status = QueueService.get_worker_status()
    queue_metrics = QueueService.get_metrics()
    http_metrics = get_http_metrics()
    storage_metrics = get_storage_metrics()
    database_label = detect_database_label()
    cache_driver = detect_cache_driver()
    realtime_driver = detect_realtime_driver()
    redis_enabled = is_redis_enabled(queue_enabled=queue_enabled, queue_driver=queue_driver)
    cache_connection = admin_runtime_summary.probe_cache_connection()
    realtime_connection = admin_runtime_summary.probe_realtime_connection()
    queue_broker_connection = admin_runtime_summary.probe_queue_broker_connection(queue_enabled, queue_driver)
    runtime_dependency_checks = build_runtime_dependency_checks(
        cache_connection=cache_connection,
        realtime_connection=realtime_connection,
        queue_broker_connection=queue_broker_connection,
        queue_worker_status=queue_worker_status,
    )
    auth_secret_risks = _build_auth_secret_risks()
    auth_secret_status = runtime_diagnostics.build_auth_secret_status(risks=auth_secret_risks)
    runtime_risks = runtime_diagnostics.build_runtime_risks(
        debug_mode=settings.DEBUG,
        database_label=database_label,
        cache_driver=cache_driver,
        realtime_driver=realtime_driver,
        queue_enabled=queue_enabled,
        queue_driver=queue_driver,
        queue_worker_status=queue_worker_status,
        redis_enabled=redis_enabled,
        cache_connection=cache_connection,
        realtime_connection=realtime_connection,
        queue_broker_connection=queue_broker_connection,
        auth_secret_risks=auth_secret_risks,
        web_concurrency=getattr(settings, "WEB_CONCURRENCY", 1),
    )
    health = collect_health_status(
        advanced_settings=advanced_settings,
        cache_connection=cache_connection,
        realtime_connection=realtime_connection,
        queue_broker_connection=queue_broker_connection,
        queue_worker_status=queue_worker_status,
        storage_config=advanced_settings,
        queue_enabled=queue_enabled,
        queue_driver=queue_driver,
    )
    storage_health = health["checks"]["storage"]

    stats = {
        "runtimeName": "Python",
        "pythonVersion": sys.version.split()[0],
        "djangoVersion": django.get_version(),
        "databaseLabel": database_label,
        "cacheDriver": cache_driver,
        "queueDriver": queue_driver,
        "queueEnabled": queue_enabled,
        "queueLabel": detect_queue_driver_label(queue_enabled, queue_driver),
        "queueWorkerStatus": queue_worker_status["status"],
        "queueWorkerLabel": queue_worker_status["label"],
        "queueWorkerAvailable": queue_worker_status["available"],
        "queueWorkerCount": queue_worker_status["worker_count"],
        "queueWorkerMessage": queue_worker_status["message"],
        "queueMetrics": queue_metrics,
        "httpMetrics": http_metrics,
        "realtimeDriver": realtime_driver,
        "redisEnabled": redis_enabled,
        "cacheConnectionStatus": cache_connection["status"],
        "cacheConnectionLabel": cache_connection["label"],
        "cacheConnectionAvailable": cache_connection["available"],
        "cacheConnectionMessage": cache_connection["message"],
        "realtimeConnectionStatus": realtime_connection["status"],
        "realtimeConnectionLabel": realtime_connection["label"],
        "realtimeConnectionAvailable": realtime_connection["available"],
        "realtimeConnectionMessage": realtime_connection["message"],
        "queueBrokerStatus": queue_broker_connection["status"],
        "queueBrokerLabel": queue_broker_connection["label"],
        "queueBrokerAvailable": queue_broker_connection["available"],
        "queueBrokerMessage": queue_broker_connection["message"],
        "runtimeDependencyChecks": runtime_dependency_checks,
        "healthStatus": health["status"],
        "healthChecks": health["checks"],
        "storageStatus": storage_health["status"],
        "storageAvailable": storage_health["available"],
        "storageMessage": storage_health["message"],
        "storageDriver": storage_health.get("driver", ""),
        "storageBackend": storage_health.get("backend", ""),
        "storageMetrics": storage_metrics,
        "capacitySmokeSummary": _build_capacity_smoke_summary(),
        "runtimeRisks": runtime_risks,
        "authSecretStatus": auth_secret_status["status"],
        "authSecretLabel": auth_secret_status["label"],
        "authSecretMessage": auth_secret_status["message"],
        "debugMode": settings.DEBUG,
        "maintenanceMode": bool(advanced_settings.get("maintenance_mode", False)),
        "maintenanceModeKey": advanced_settings.get("maintenance_mode_key", "none"),
        "maintenanceModeLabel": advanced_settings.get("maintenance_mode_label", "未启用"),
    }
    return stats
