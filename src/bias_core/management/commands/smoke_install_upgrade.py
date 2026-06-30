from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.core.management.base import CommandParser

from bias_core.management.command_utils import build_manage_env, run_manage_py


class Command(BaseCommand):
    help = "在临时站点中冒烟验证 install_forum / upgrade_forum 安装升级链路。"
    requires_system_checks = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--workdir", help="临时站点目录；未提供时自动创建并在结束后删除")
        parser.add_argument("--keep-workdir", action="store_true", help="保留自动创建的临时站点目录")
        parser.add_argument("--admin-username", default="smoke-admin", help="冒烟管理员用户名")
        parser.add_argument("--admin-email", default="smoke-admin@example.com", help="冒烟管理员邮箱")
        parser.add_argument("--admin-password", default="smoke-admin-password", help="冒烟管理员密码")
        parser.add_argument("--skip-collectstatic", action="store_true", help="传递给 install_forum / upgrade_forum，跳过 collectstatic")
        parser.add_argument("--skip-extension-frontend", action="store_true", help="传递给 install_forum / upgrade_forum，跳过扩展前端清单生成")
        parser.add_argument("--format", choices=("text", "json"), default="text", help="输出格式")

    def handle(self, *args, **options):
        explicit_workdir = str(options.get("workdir") or "").strip()
        keep_workdir = bool(options.get("keep_workdir"))
        output_format = str(options.get("format") or "text")
        workdir = Path(explicit_workdir) if explicit_workdir else Path(tempfile.mkdtemp(prefix="bias-install-upgrade-"))
        created_workdir = not explicit_workdir
        config_path = workdir / "instance" / "site.json"

        install_args = [
            "install_forum",
            "--database",
            "sqlite",
            "--config",
            str(config_path),
            "--overwrite",
            "--non-interactive",
            "--admin-username",
            str(options["admin_username"]),
            "--admin-email",
            str(options["admin_email"]),
            "--admin-password",
            str(options["admin_password"]),
            "--sqlite-name",
            str(workdir / "db.sqlite3"),
        ]
        upgrade_args = [
            "upgrade_forum",
            "--config",
            str(config_path),
            "--non-interactive",
        ]
        if options["skip_collectstatic"]:
            install_args.append("--skip-collectstatic")
            upgrade_args.append("--skip-collectstatic")
        if options["skip_extension_frontend"]:
            install_args.append("--skip-extension-frontend")
            upgrade_args.append("--skip-extension-frontend")

        payload = {
            "workdir": str(workdir),
            "config_path": str(config_path),
            "install": None,
            "upgrade": None,
            "summary": {
                "ok": False,
                "error_count": 0,
            },
        }

        try:
            workdir.mkdir(parents=True, exist_ok=True)
            env = build_manage_env(config_path=config_path)
            self._run_step("install", install_args, env, payload)
            payload["install"] = self._inspect_site_state(env)
            self._run_step("upgrade", upgrade_args, env, payload)
            payload["upgrade"] = self._inspect_site_state(env)
            self._validate_payload(payload)
            payload["summary"]["ok"] = True
        except Exception as exc:
            payload["summary"]["error_count"] = 1
            payload["summary"]["error"] = str(exc)
            if output_format == "json":
                self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            raise
        finally:
            if created_workdir and not keep_workdir:
                shutil.rmtree(workdir, ignore_errors=True)

        if output_format == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(self.style.SUCCESS("[OK] install_forum / upgrade_forum 冒烟通过"))
            self.stdout.write(f"- 临时站点: {workdir}")
            self.stdout.write(f"- 已启用扩展: {len(payload['upgrade']['enabled_extensions'])}")
            self.stdout.write(f"- 管理员: {payload['upgrade']['admin_username']}")

    def _run_step(self, key: str, args: list[str], env: dict[str, str], payload: dict) -> None:
        try:
            result = run_manage_py(args, env)
        except Exception as exc:
            payload[key] = {
                "args": args,
                "stdout": getattr(exc, "stdout", ""),
                "stderr": getattr(exc, "stderr", ""),
                "returncode": getattr(exc, "returncode", None),
            }
            raise CommandError(f"{key} 阶段失败") from exc
        payload[f"{key}_command"] = {
            "args": args,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    def _inspect_site_state(self, env: dict[str, str]) -> dict:
        script = r"""
import json
from django.contrib.auth import get_user_model
from bias_core.models import ExtensionInstallation, Setting

User = get_user_model()
admin = User.objects.filter(is_superuser=True).order_by("id").first()
enabled = list(
    ExtensionInstallation.objects
    .filter(installed=True, enabled=True)
    .order_by("extension_id")
    .values_list("extension_id", flat=True)
)
installed = list(
    ExtensionInstallation.objects
    .filter(installed=True)
    .order_by("extension_id")
    .values_list("extension_id", flat=True)
)
settings = {
    key: value
    for key, value in Setting.objects
    .filter(key__in=["system.version", "advanced.queue_enabled", "advanced.queue_driver"])
    .values_list("key", "value")
}
print(json.dumps({
    "admin_exists": admin is not None,
    "admin_username": getattr(admin, "username", ""),
    "admin_email": getattr(admin, "email", ""),
    "installed_extensions": installed,
    "enabled_extensions": enabled,
    "settings": settings,
}, ensure_ascii=False))
"""
        try:
            result = run_manage_py(["shell", "-c", script], env)
        except Exception as exc:
            raise CommandError("安装态状态检查失败") from exc
        try:
            return json.loads(result.stdout.strip() or "{}")
        except json.JSONDecodeError as exc:
            raise CommandError("安装态状态检查输出不是有效 JSON") from exc

    def _validate_payload(self, payload: dict) -> None:
        install_state = dict(payload.get("install") or {})
        upgrade_state = dict(payload.get("upgrade") or {})
        for label, state in (("install", install_state), ("upgrade", upgrade_state)):
            if not state.get("admin_exists"):
                raise CommandError(f"{label} 后未发现管理员账号")
            if not state.get("installed_extensions"):
                raise CommandError(f"{label} 后未发现已安装扩展")
            if not state.get("enabled_extensions"):
                raise CommandError(f"{label} 后未发现已启用扩展")
            if "system.version" not in dict(state.get("settings") or {}):
                raise CommandError(f"{label} 后未写入 system.version")

        if install_state.get("enabled_extensions") != upgrade_state.get("enabled_extensions"):
            raise CommandError("upgrade 后已启用扩展状态未保持")

        if install_state.get("admin_username") != upgrade_state.get("admin_username"):
            raise CommandError("upgrade 后管理员账号未保持")
