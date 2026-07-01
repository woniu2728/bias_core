from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid

from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.core.management.base import CommandParser
from django.test import override_settings

from bias_core.models import Setting
from bias_core.queue_service import QueueService
from bias_core.settings_service import clear_runtime_setting_caches
from bias_core.tasks import queue_worker_probe


class Command(BaseCommand):
    help = "冒烟验证 Redis broker + Celery worker 能真实执行队列任务。"
    requires_system_checks = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--broker-url", default="", help="Celery broker URL，默认使用 settings.CELERY_BROKER_URL")
        parser.add_argument("--result-backend", default="", help="Celery result backend，默认使用 settings.CELERY_RESULT_BACKEND 或 broker URL")
        parser.add_argument("--timeout", type=int, default=30, help="等待 worker 和任务结果的超时时间，默认 30 秒")
        parser.add_argument("--worker-loglevel", default="WARNING", help="临时 worker 日志级别")
        parser.add_argument("--format", choices=("text", "json"), default="text", help="输出格式")

    def handle(self, *args, **options):
        broker_url = str(options.get("broker_url") or getattr(settings, "CELERY_BROKER_URL", "") or "").strip()
        result_backend = str(
            options.get("result_backend")
            or getattr(settings, "CELERY_RESULT_BACKEND", "")
            or broker_url
        ).strip()
        timeout = max(3, int(options.get("timeout") or 30))
        output_format = str(options.get("format") or "text")
        if not broker_url:
            raise CommandError("缺少 Celery broker URL，请配置 CELERY_BROKER_URL 或传入 --broker-url")
        if not result_backend:
            raise CommandError("缺少 Celery result backend，请配置 CELERY_RESULT_BACKEND 或传入 --result-backend")

        token = f"queue-smoke-{uuid.uuid4().hex}"
        payload = {
            "broker_url": self._redact_url(broker_url),
            "result_backend": self._redact_url(result_backend),
            "task_name": queue_worker_probe.name,
            "token": token,
            "worker_status": None,
            "task_result": None,
            "summary": {
                "ok": False,
                "error_count": 0,
            },
        }

        worker = None
        previous_settings = None
        with override_settings(CELERY_BROKER_URL=broker_url, CELERY_RESULT_BACKEND=result_backend):
            try:
                previous_settings = self._enable_redis_queue_runtime()
                env = self._build_worker_env(broker_url, result_backend)
                worker = self._start_worker(env, options)
                payload["worker_status"] = self._wait_for_worker(timeout)
                async_result = QueueService.dispatch_celery_task(queue_worker_probe, token)
                if async_result is None:
                    raise CommandError("队列已启用但任务未入队")
                result = async_result.get(timeout=timeout, propagate=True)
                payload["task_result"] = result
                if not isinstance(result, dict) or result.get("token") != token or result.get("ok") is not True:
                    raise CommandError("队列 probe 任务返回结果不匹配")
                payload["summary"]["ok"] = True
            except Exception as exc:
                payload["summary"]["error_count"] = 1
                payload["summary"]["error"] = str(exc)
                if output_format == "json":
                    self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
                raise
            finally:
                if previous_settings is not None:
                    self._restore_runtime_settings(previous_settings)
                if worker is not None:
                    self._stop_worker(worker)

        if output_format == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(self.style.SUCCESS("[OK] Redis queue worker 冒烟通过"))
            self.stdout.write(f"- task: {payload['task_name']}")
            self.stdout.write(f"- worker: {payload['worker_status']['label']}")

    def _build_worker_env(self, broker_url: str, result_backend: str) -> dict[str, str]:
        env = dict(os.environ)
        env.setdefault("DJANGO_SETTINGS_MODULE", os.getenv("DJANGO_SETTINGS_MODULE") or "config.settings")
        env["CELERY_BROKER_URL"] = broker_url
        env["CELERY_RESULT_BACKEND"] = result_backend
        env[QueueService.TEST_SKIP_LIVE_IO_ENV] = "1"
        return env

    def _start_worker(self, env: dict[str, str], options: dict) -> subprocess.Popen:
        app_path = str(getattr(settings, "BIAS_CELERY_APP", "config.celery:app") or "config.celery:app")
        command = [
            sys.executable,
            "-m",
            "celery",
            "-A",
            app_path,
            "worker",
            "--pool",
            "solo",
            "--concurrency",
            "1",
            "--loglevel",
            str(options.get("worker_loglevel") or "WARNING"),
            "--without-gossip",
            "--without-mingle",
            "--without-heartbeat",
        ]
        try:
            return subprocess.Popen(
                command,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            raise CommandError(f"无法启动 Celery worker: {exc}") from exc

    def _wait_for_worker(self, timeout: int) -> dict:
        deadline = time.monotonic() + timeout
        last_status = None
        while time.monotonic() < deadline:
            last_status = QueueService.get_worker_status()
            if last_status.get("available"):
                return last_status
            time.sleep(0.5)
        raise CommandError((last_status or {}).get("message") or "等待 Celery worker 超时")

    def _enable_redis_queue_runtime(self) -> dict[str, str | None]:
        keys = ["advanced.queue_enabled", "advanced.queue_driver"]
        previous = {
            key: Setting.objects.filter(key=key).values_list("value", flat=True).first()
            for key in keys
        }
        Setting.objects.update_or_create(
            key="advanced.queue_enabled",
            defaults={"value": json.dumps(True)},
        )
        Setting.objects.update_or_create(
            key="advanced.queue_driver",
            defaults={"value": json.dumps("redis")},
        )
        clear_runtime_setting_caches()
        QueueService.reset_metrics()
        return previous

    def _restore_runtime_settings(self, previous: dict[str, str | None]) -> None:
        for key, value in previous.items():
            if value is None:
                Setting.objects.filter(key=key).delete()
            else:
                Setting.objects.update_or_create(key=key, defaults={"value": value})
        clear_runtime_setting_caches()

    def _stop_worker(self, worker: subprocess.Popen) -> None:
        if worker.poll() is not None:
            return
        worker.terminate()
        try:
            worker.wait(timeout=5)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait(timeout=5)

    def _redact_url(self, value: str) -> str:
        if "@" not in value:
            return value
        scheme, rest = value.split("://", 1) if "://" in value else ("", value)
        credentials, host = rest.split("@", 1)
        if ":" not in credentials:
            redacted = "***"
        else:
            user, _password = credentials.split(":", 1)
            redacted = f"{user}:***"
        return f"{scheme}://{redacted}@{host}" if scheme else f"{redacted}@{host}"
