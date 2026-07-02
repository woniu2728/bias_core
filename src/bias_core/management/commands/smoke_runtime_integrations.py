from __future__ import annotations

import json
import smtplib
import time
import uuid
from typing import Any

from django.conf import settings
from django.core.mail import get_connection
from django.core.management import BaseCommand, CommandError
from django.core.management.base import CommandParser

from bias_core.mail_drivers import validate_mail_settings
from bias_core.settings_service import get_mail_settings
from bias_core.storage_service import get_runtime_storage_settings, get_storage_backend


class Command(BaseCommand):
    help = "Run machine-readable smoke checks for runtime SMTP and storage integrations."
    requires_system_checks = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--skip-email", action="store_true", help="跳过邮件配置检查")
        parser.add_argument("--smtp-connect", action="store_true", help="实际连接 SMTP；默认只做配置 dry-run")
        parser.add_argument("--require-smtp-connect", action="store_true", help="要求本次 smoke 实际连接 SMTP")
        parser.add_argument("--skip-storage", action="store_true", help="跳过 storage 检查")
        parser.add_argument(
            "--storage-write",
            action="store_true",
            help="对 storage 执行临时对象写入和删除；默认只初始化 backend",
        )
        parser.add_argument("--require-storage-write", action="store_true", help="要求本次 smoke 执行 storage 写入删除")
        parser.add_argument("--require-object-storage", action="store_true", help="要求 storage driver 不是 local")
        parser.add_argument("--fail-on-warning", action="store_true", help="warning 也视为失败，适合目标环境 gate")
        parser.add_argument("--storage-prefix", default="smoke/runtime-integrations", help="临时 storage key 前缀")
        parser.add_argument("--timeout", type=float, default=10.0, help="SMTP 连接超时秒数")
        parser.add_argument("--format", choices=("text", "json"), default="text")

    def handle(self, *args, **options):
        checks: list[dict[str, Any]] = []
        if not options["skip_email"]:
            checks.append(self._check_email(smtp_connect=bool(options["smtp_connect"]), timeout=float(options["timeout"])))
        if not options["skip_storage"]:
            checks.append(self._check_storage(
                storage_write=bool(options["storage_write"]),
                storage_prefix=str(options["storage_prefix"] or ""),
            ))

        if not checks:
            raise CommandError("至少需要启用 email 或 storage 其中一个 smoke 检查")

        payload = self._build_payload(
            checks,
            require_smtp_connect=bool(options["require_smtp_connect"]),
            require_storage_write=bool(options["require_storage_write"]),
            require_object_storage=bool(options["require_object_storage"]),
            fail_on_warning=bool(options["fail_on_warning"]),
        )
        if options["format"] == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self._write_text(payload)

        if not payload["summary"]["ok"]:
            failed = ", ".join(check["key"] for check in checks if not check["ok"])
            raise CommandError(f"Runtime integration smoke failed: {failed}")

    def _check_email(self, *, smtp_connect: bool, timeout: float) -> dict[str, Any]:
        mail_settings = get_mail_settings()
        validation_errors = validate_mail_settings(mail_settings)
        backend = str(getattr(settings, "EMAIL_BACKEND", "") or "")
        check: dict[str, Any] = {
            "key": "email",
            "label": "SMTP/email runtime",
            "ok": not validation_errors,
            "mode": "smtp_connect" if smtp_connect else "config_dry_run",
            "backend": backend,
            "driver": mail_settings.get("mail_driver"),
            "host": mail_settings.get("mail_host"),
            "port": mail_settings.get("mail_port"),
            "encryption": mail_settings.get("mail_encryption"),
            "from_email": mail_settings.get("mail_from"),
            "validation_errors": validation_errors,
            "duration_ms": 0.0,
        }
        if validation_errors or not smtp_connect:
            return check

        started_at = time.perf_counter()
        try:
            connection = get_connection(timeout=timeout)
            opened = connection.open()
            if opened:
                connection.close()
            check["ok"] = True
            check["connected"] = True
        except (OSError, smtplib.SMTPException, TimeoutError) as exc:
            check["ok"] = False
            check["connected"] = False
            check["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            check["duration_ms"] = round((time.perf_counter() - started_at) * 1000, 3)
        return check

    def _check_storage(self, *, storage_write: bool, storage_prefix: str) -> dict[str, Any]:
        config = get_runtime_storage_settings()
        driver = str(config.get("storage_driver") or "local").strip().lower()
        check: dict[str, Any] = {
            "key": "storage",
            "label": "File storage runtime",
            "ok": False,
            "mode": "write_read_delete" if storage_write else "backend_init",
            "driver": driver,
            "duration_ms": 0.0,
        }
        started_at = time.perf_counter()
        try:
            backend = get_storage_backend(config)
            backend_name = getattr(getattr(backend, "backend", None), "__class__", backend.__class__).__name__
            check["backend"] = backend_name
            if not storage_write:
                check["ok"] = True
                return check

            key = self._storage_smoke_key(storage_prefix)
            content = f"bias runtime integration smoke {uuid.uuid4().hex}\n".encode("utf-8")
            file_url = backend.save_bytes(key, content, content_type="text/plain")
            extracted_key = backend.extract_key(file_url)
            delete_key = extracted_key or key
            deleted = backend.delete_key(delete_key)
            check.update({
                "ok": bool(file_url and deleted),
                "key_written": key,
                "file_url": file_url,
                "delete_key": delete_key,
                "deleted": deleted,
                "byte_count": len(content),
            })
            if not check["ok"]:
                check["error"] = "storage smoke object was not deleted"
        except Exception as exc:
            check["ok"] = False
            check["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            check["duration_ms"] = round((time.perf_counter() - started_at) * 1000, 3)
        return check

    def _storage_smoke_key(self, prefix: str) -> str:
        normalized = "/".join(part.strip("/") for part in str(prefix or "").split("/") if part.strip("/"))
        base = normalized or "smoke/runtime-integrations"
        return f"{base}/probe-{uuid.uuid4().hex}.txt"

    def _build_payload(
        self,
        checks: list[dict[str, Any]],
        *,
        require_smtp_connect: bool,
        require_storage_write: bool,
        require_object_storage: bool,
        fail_on_warning: bool,
    ) -> dict[str, Any]:
        errors = [
            {
                "key": check["key"],
                "error": check.get("error") or check.get("validation_errors") or "check failed",
            }
            for check in checks
            if not check["ok"]
        ]
        warnings = [
            {
                "key": check["key"],
                "warning": "SMTP connection was not attempted; pass --smtp-connect for target-environment proof.",
            }
            for check in checks
            if check["key"] == "email" and check["ok"] and check["mode"] == "config_dry_run"
        ]
        warnings.extend(
            {
                "key": check["key"],
                "warning": "Storage write/read/delete was not attempted; pass --storage-write for target-environment proof.",
            }
            for check in checks
            if check["key"] == "storage" and check["ok"] and check["mode"] == "backend_init"
        )
        checks_by_key = {check["key"]: check for check in checks}
        email_check = checks_by_key.get("email")
        storage_check = checks_by_key.get("storage")
        if require_smtp_connect:
            if email_check is None:
                errors.append({"key": "email", "error": "email smoke was skipped but SMTP connect is required"})
            elif email_check.get("mode") != "smtp_connect":
                errors.append({"key": "email", "error": "SMTP connect was required but not attempted"})
        if require_storage_write:
            if storage_check is None:
                errors.append({"key": "storage", "error": "storage smoke was skipped but storage write is required"})
            elif storage_check.get("mode") != "write_read_delete":
                errors.append({"key": "storage", "error": "storage write/delete was required but not attempted"})
        if require_object_storage:
            if storage_check is None:
                errors.append({"key": "storage", "error": "storage smoke was skipped but object storage is required"})
            elif storage_check.get("driver") == "local":
                errors.append({"key": "storage", "error": "object storage is required but driver is local"})
        if fail_on_warning:
            errors.extend({"key": warning["key"], "error": warning["warning"]} for warning in warnings)
        return {
            "checks": checks,
            "errors": errors,
            "warnings": warnings,
            "summary": {
                "ok": not errors,
                "check_count": len(checks),
                "error_count": len(errors),
                "warning_count": len(warnings),
                "fail_on_warning": fail_on_warning,
                "require_smtp_connect": require_smtp_connect,
                "require_storage_write": require_storage_write,
                "require_object_storage": require_object_storage,
            },
        }

    def _write_text(self, payload: dict[str, Any]) -> None:
        marker = "OK" if payload["summary"]["ok"] else "FAILED"
        self.stdout.write(f"Runtime integrations smoke: {marker}")
        for check in payload["checks"]:
            status = "ok" if check["ok"] else "failed"
            self.stdout.write(f"- {check['label']}: {status} ({check['mode']})")
