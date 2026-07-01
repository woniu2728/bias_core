from __future__ import annotations

import time
import uuid
from typing import Any

from django.core.cache import cache
from django.utils import timezone


HTTP_METRICS_CACHE_KEY = "http.runtime.metrics"
HTTP_METRICS_TIMEOUT = 60 * 60 * 24 * 30
DEFAULT_HTTP_METRICS = {
    "request_count": 0,
    "error_count": 0,
    "total_duration_ms": 0.0,
    "last_duration_ms": 0.0,
    "max_duration_ms": 0.0,
    "average_duration_ms": 0.0,
    "error_rate": 0.0,
    "last_method": "",
    "last_path": "",
    "last_status_code": 0,
    "last_request_id": "",
    "last_error": "",
    "last_event_at": "",
    "status_code_counts": {},
    "method_counts": {},
}

_fallback_metrics: dict[str, Any] = DEFAULT_HTTP_METRICS.copy()


def start_request_timer(request) -> tuple[str, float]:
    request_id = str(request.headers.get("X-Request-ID") or "").strip() or uuid.uuid4().hex
    request.bias_request_id = request_id
    return request_id, time.perf_counter()


def record_http_request(
    *,
    method: str,
    path: str,
    status_code: int,
    request_id: str = "",
    duration_ms: float = 0.0,
    error: str = "",
) -> None:
    metrics = get_http_metrics()
    duration_ms = round(max(0.0, float(duration_ms or 0.0)), 3)
    status_key = str(int(status_code or 0))
    method_key = str(method or "").upper()

    metrics["request_count"] = int(metrics.get("request_count", 0) or 0) + 1
    if int(status_code or 0) >= 500 or error:
        metrics["error_count"] = int(metrics.get("error_count", 0) or 0) + 1

    metrics["last_duration_ms"] = duration_ms
    metrics["total_duration_ms"] = round(float(metrics.get("total_duration_ms", 0.0) or 0.0) + duration_ms, 3)
    metrics["max_duration_ms"] = round(max(float(metrics.get("max_duration_ms", 0.0) or 0.0), duration_ms), 3)
    metrics["last_method"] = method_key
    metrics["last_path"] = path
    metrics["last_status_code"] = int(status_code or 0)
    metrics["last_request_id"] = request_id
    metrics["last_error"] = error
    metrics["last_event_at"] = timezone.now().isoformat()

    status_counts = dict(metrics.get("status_code_counts") or {})
    status_counts[status_key] = int(status_counts.get(status_key, 0) or 0) + 1
    metrics["status_code_counts"] = status_counts

    method_counts = dict(metrics.get("method_counts") or {})
    method_counts[method_key] = int(method_counts.get(method_key, 0) or 0) + 1
    metrics["method_counts"] = method_counts
    _store_metrics(metrics)


def get_http_metrics() -> dict[str, Any]:
    try:
        metrics = cache.get(HTTP_METRICS_CACHE_KEY) or {}
    except Exception:
        metrics = _fallback_metrics

    normalized = _normalize_metrics(metrics)
    event_count = int(normalized.get("request_count", 0) or 0)
    error_count = int(normalized.get("error_count", 0) or 0)
    total_duration_ms = float(normalized.get("total_duration_ms", 0.0) or 0.0)
    normalized["average_duration_ms"] = round(total_duration_ms / event_count, 3) if event_count else 0.0
    normalized["error_rate"] = round(error_count / event_count, 4) if event_count else 0.0
    return normalized


def reset_http_metrics() -> dict[str, Any]:
    metrics = DEFAULT_HTTP_METRICS.copy()
    metrics["status_code_counts"] = {}
    metrics["method_counts"] = {}
    _store_metrics(metrics)
    return metrics


def _normalize_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        **DEFAULT_HTTP_METRICS,
        **{key: metrics.get(key) for key in DEFAULT_HTTP_METRICS.keys() if key in metrics},
    }
    normalized["status_code_counts"] = dict(normalized.get("status_code_counts") or {})
    normalized["method_counts"] = dict(normalized.get("method_counts") or {})
    return normalized


def _store_metrics(metrics: dict[str, Any]) -> None:
    global _fallback_metrics
    _fallback_metrics = _normalize_metrics(metrics)
    try:
        cache.set(HTTP_METRICS_CACHE_KEY, _fallback_metrics, HTTP_METRICS_TIMEOUT)
    except Exception:
        return None
