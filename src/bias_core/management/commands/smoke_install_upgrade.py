from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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
        parser.add_argument("--rebuild-extension-frontend", action="store_true", help="传递给 install_forum / upgrade_forum，执行真实前端构建")
        parser.add_argument("--publish-frontend-dist", action="store_true", help="传递给 install_forum / upgrade_forum，把 frontend/dist 发布到 static/frontend")
        parser.add_argument("--from-wheels", action="store_true", help="先构建并安装本地 wheel 到临时 target，再从该安装态运行安装升级冒烟")
        parser.add_argument("--wheel-source-root", help="拆分仓库根目录，默认使用 settings.BASE_DIR.parent")
        parser.add_argument("--wheel-build-timeout", type=int, default=120, help="单个 wheel 构建/安装超时时间，默认 120 秒")
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
        if options["rebuild_extension_frontend"] or options["publish_frontend_dist"]:
            install_args.append("--rebuild-extension-frontend")
            upgrade_args.append("--rebuild-extension-frontend")
        if options["publish_frontend_dist"]:
            install_args.append("--publish-frontend-dist")
            upgrade_args.append("--publish-frontend-dist")

        payload = {
            "workdir": str(workdir),
            "config_path": str(config_path),
            "static_root": str(workdir / "staticfiles"),
            "install": None,
            "upgrade": None,
            "static": None,
            "wheel_install": None,
            "summary": {
                "ok": False,
                "error_count": 0,
            },
        }

        try:
            workdir.mkdir(parents=True, exist_ok=True)
            env = build_manage_env(config_path=config_path)
            env["BIAS_STATIC_ROOT"] = str(workdir / "staticfiles")
            if options["from_wheels"]:
                wheel_payload = self._build_and_install_wheels(
                    workdir,
                    source_root=Path(options.get("wheel_source_root") or Path(settings.BASE_DIR).parent),
                    timeout=int(options.get("wheel_build_timeout") or 120),
                )
                payload["wheel_install"] = wheel_payload
                env = self._with_wheel_pythonpath(env, wheel_payload["target"])
            self._run_step("install", install_args, env, payload)
            payload["install"] = self._inspect_site_state(env)
            self._run_step("upgrade", upgrade_args, env, payload)
            payload["upgrade"] = self._inspect_site_state(env)
            payload["static"] = self._inspect_static_state(env)
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
            if payload.get("wheel_install"):
                self.stdout.write(f"- wheel target: {payload['wheel_install']['target']}")
            self.stdout.write(f"- 已启用扩展: {len(payload['upgrade']['enabled_extensions'])}")
            self.stdout.write(f"- 管理员: {payload['upgrade']['admin_username']}")

    def _build_and_install_wheels(self, workdir: Path, *, source_root: Path, timeout: int) -> dict:
        wheelhouse = workdir / "wheelhouse"
        target = workdir / "site-packages"
        wheelhouse.mkdir(parents=True, exist_ok=True)
        target.mkdir(parents=True, exist_ok=True)
        package_roots = self._resolve_package_roots(source_root)
        built_wheels: list[str] = []
        for package_root in package_roots:
            self._run_subprocess(
                [
                    sys.executable,
                    "-m",
                    "build",
                    "--wheel",
                    "--no-isolation",
                    "--outdir",
                    str(wheelhouse),
                ],
                cwd=package_root,
                timeout=timeout,
                label=f"构建 wheel: {package_root.name}",
            )
        built_wheels = [str(path) for path in sorted(wheelhouse.glob("*.whl"))]
        if not built_wheels:
            raise CommandError("未构建出任何 wheel")
        self._run_subprocess(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--disable-pip-version-check",
                "--target",
                str(target),
                *built_wheels,
            ],
            cwd=source_root,
            timeout=timeout,
            label="安装 wheel 到临时 target",
        )
        return {
            "source_root": str(source_root),
            "target": str(target),
            "wheelhouse": str(wheelhouse),
            "package_roots": [str(path) for path in package_roots],
            "wheels": built_wheels,
        }

    def _resolve_package_roots(self, source_root: Path) -> list[Path]:
        candidates = [
            source_root / "bias_core",
            source_root / "bias-content",
            *sorted(source_root.glob("bias-ext-*")),
        ]
        roots = []
        for candidate in candidates:
            if (candidate / "pyproject.toml").exists():
                roots.append(candidate)
        if not roots:
            raise CommandError(f"未在 {source_root} 找到可构建 package")
        return roots

    def _run_subprocess(self, args: list[str], *, cwd: Path, timeout: int, label: str) -> None:
        try:
            result = subprocess.run(
                args,
                cwd=str(cwd),
                text=True,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise CommandError(f"{label} 超时: {exc}") from exc
        if result.returncode != 0:
            detail = "\n".join(part.strip() for part in (result.stderr, result.stdout) if part.strip())
            if len(detail) > 2000:
                detail = detail[:2000] + "...[truncated]"
            raise CommandError(f"{label} 失败: {detail or result.returncode}")

    def _with_wheel_pythonpath(self, env: dict[str, str], target: str) -> dict[str, str]:
        updated = dict(env)
        existing = updated.get("PYTHONPATH", "")
        updated["PYTHONPATH"] = str(target) if not existing else str(target) + os.pathsep + existing
        updated["BIAS_SMOKE_WHEEL_TARGET"] = str(target)
        return updated

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
import os
from django.contrib.auth import get_user_model
from django.conf import settings
from bias_core.models import ExtensionInstallation, Setting
import bias_core

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
    "bias_core_file": getattr(bias_core, "__file__", ""),
    "wheel_target": os.environ.get("BIAS_SMOKE_WHEEL_TARGET", ""),
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

    def _inspect_static_state(self, env: dict[str, str]) -> dict:
        script = r"""
import json
from pathlib import Path
from django.conf import settings

static_root = Path(settings.STATIC_ROOT)
frontend_root = static_root / "frontend"
extension_root = static_root / "extensions"
build_manifest = extension_root / "frontend-build-manifest.json"
output_manifest = extension_root / "frontend-output-manifest.json"
print(json.dumps({
    "static_root": str(static_root),
    "static_root_exists": static_root.exists(),
    "frontend_root": str(frontend_root),
    "frontend_root_exists": frontend_root.exists(),
    "frontend_file_count": sum(1 for path in frontend_root.rglob("*") if path.is_file()) if frontend_root.exists() else 0,
    "extension_root": str(extension_root),
    "extension_root_exists": extension_root.exists(),
    "build_manifest": str(build_manifest),
    "build_manifest_exists": build_manifest.exists(),
    "output_manifest": str(output_manifest),
    "output_manifest_exists": output_manifest.exists(),
}, ensure_ascii=False))
"""
        try:
            result = run_manage_py(["shell", "-c", script], env)
        except Exception as exc:
            raise CommandError("静态资源状态检查失败") from exc
        try:
            return json.loads(result.stdout.strip() or "{}")
        except json.JSONDecodeError as exc:
            raise CommandError("静态资源状态检查输出不是有效 JSON") from exc

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

        install_args = list((payload.get("install_command") or {}).get("args") or [])
        collectstatic_enabled = "--skip-collectstatic" not in install_args
        extension_frontend_enabled = "--skip-extension-frontend" not in install_args
        publish_frontend_enabled = "--publish-frontend-dist" in install_args
        if collectstatic_enabled:
            static_state = dict(payload.get("static") or {})
            if not static_state.get("static_root_exists"):
                raise CommandError("collectstatic 后未发现 static root")
            if extension_frontend_enabled:
                if not static_state.get("build_manifest_exists"):
                    raise CommandError("collectstatic 后未发现扩展前端 build manifest")
                if not static_state.get("output_manifest_exists"):
                    raise CommandError("collectstatic 后未发现扩展前端 output manifest")
            if publish_frontend_enabled:
                if not static_state.get("frontend_root_exists"):
                    raise CommandError("collectstatic 后未发现已发布 frontend dist")
                if int(static_state.get("frontend_file_count") or 0) <= 0:
                    raise CommandError("已发布 frontend dist 为空")

        wheel_target = str((payload.get("wheel_install") or {}).get("target") or "")
        if wheel_target:
            for label, state in (("install", install_state), ("upgrade", upgrade_state)):
                core_file = str(state.get("bias_core_file") or "")
                if wheel_target not in core_file:
                    raise CommandError(f"{label} 未从 wheel target 导入 bias_core: {core_file}")
