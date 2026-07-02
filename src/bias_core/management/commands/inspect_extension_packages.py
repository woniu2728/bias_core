from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.core.management.base import CommandParser

from bias_core.extensions.exceptions import ExtensionManifestError
from bias_core.extensions.manifest import ExtensionManifestLoader
from bias_core.extensions.manager_dependencies import (
    get_core_satisfied_dependency_ids,
    resolve_extension_order,
)
from bias_core.extensions.packaging import (
    _temporary_directory,
    inspect_extension_package_install_set,
    inspect_extension_package_wheel,
)
from bias_core.extensions.version_compatibility import resolve_bias_version_compatibility


class Command(BaseCommand):
    help = "审计扩展 wheel 交付内容，确保安装态仍可发现 manifest、后端入口和前端资源。"
    requires_system_checks = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--extensions-path",
            help="扩展目录路径，默认使用 BASE_DIR/extensions；拆分仓库会自动扫描同级 bias-ext-* 目录",
        )
        parser.add_argument(
            "--extension-id",
            help="只审计指定扩展",
        )
        parser.add_argument(
            "--build",
            action="store_true",
            help="审计前临时构建 wheel；默认检查扩展 dist 目录中已有 wheel",
        )
        parser.add_argument(
            "--install-smoke",
            action="store_true",
            help="将 wheel 安装到临时目录，并验证安装态扩展发现与后端入口导入",
        )
        parser.add_argument(
            "--install-set-smoke",
            action="store_true",
            help="将本次审计的所有 wheel 安装到同一个临时目录，并验证整组扩展发现、后端入口导入和依赖顺序",
        )
        parser.add_argument(
            "--migration-smoke",
            action="store_true",
            help="配合 --install-set-smoke，在安装态临时数据库中执行 Django migrate 并验证扩展迁移已应用",
        )
        parser.add_argument(
            "--lifecycle-smoke",
            action="store_true",
            help="配合 --install-set-smoke，在安装态临时站点中验证扩展 install/disable/enable 生命周期",
        )
        parser.add_argument(
            "--wheel-dir",
            help="不构建时，从指定目录查找 wheel；默认使用每个扩展自己的 dist 目录",
        )
        parser.add_argument(
            "--build-timeout",
            type=int,
            default=120,
            help="单个扩展 wheel 构建超时时间，单位秒，默认 120",
        )
        parser.add_argument(
            "--require-extensions",
            action="store_true",
            help="要求至少发现一个扩展；CI/发布校验可用它避免空目录误报通过",
        )
        parser.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
            help="输出格式，默认 text，可选 json 便于 CI 消费",
        )

    def handle(self, *args, **options):
        extensions_path = Path(options.get("extensions_path") or (Path(settings.BASE_DIR) / "extensions"))
        extension_id = str(options.get("extension_id") or "").strip()
        build = bool(options.get("build"))
        install_smoke = bool(options.get("install_smoke"))
        install_set_smoke = bool(options.get("install_set_smoke"))
        migration_smoke = bool(options.get("migration_smoke"))
        lifecycle_smoke = bool(options.get("lifecycle_smoke"))
        wheel_dir_option = str(options.get("wheel_dir") or "").strip()
        wheel_dir = Path(wheel_dir_option) if wheel_dir_option else None
        build_timeout = int(options.get("build_timeout") or 120)
        require_extensions = bool(options.get("require_extensions"))
        output_format = str(options.get("format") or "text").strip() or "text"

        if migration_smoke and not install_set_smoke:
            raise CommandError("--migration-smoke 必须配合 --install-set-smoke 使用")
        if lifecycle_smoke and not install_set_smoke:
            raise CommandError("--lifecycle-smoke 必须配合 --install-set-smoke 使用")

        include_workspace = bool(
            extensions_path.name == "extensions"
            and any(extensions_path.parent.glob("bias-ext-*/extension.json"))
        )
        loader = ExtensionManifestLoader(
            extensions_path,
            include_workspace=include_workspace,
            workspace_root=extensions_path.parent if include_workspace else None,
            include_distributions=False,
        )
        try:
            manifests = loader.discover_manifests()
        except ExtensionManifestError as exc:
            raise CommandError(str(exc)) from exc

        if extension_id:
            manifests = [manifest for manifest in manifests if manifest.id == extension_id]
            if not manifests:
                raise CommandError(f"未找到扩展: {extension_id}")

        install_plan = self._build_install_plan(
            manifests,
            build=build,
            install_smoke=install_smoke,
            install_set_smoke=install_set_smoke,
            migration_smoke=migration_smoke,
            lifecycle_smoke=lifecycle_smoke,
            wheel_dir=wheel_dir,
        )
        upgrade_risk = self._build_upgrade_risk(manifests, install_plan=install_plan)

        with (
            _temporary_directory("bias-wheel-set-", extensions_path)
            if build and install_set_smoke
            else _null_temp_dir()
        ) as build_temp_dir:
            build_output_dir = Path(build_temp_dir) if build_temp_dir else None
            results = [
                inspect_extension_package_wheel(
                    Path(manifest.path),
                    extension_id=manifest.id,
                    extension_version=manifest.version,
                    backend_entry=manifest.backend_entry,
                    build=build,
                    install_smoke=False,
                    wheel_dir=wheel_dir,
                    build_output_dir=build_output_dir,
                    timeout=build_timeout,
                )
                for manifest in manifests
            ]
            if install_smoke:
                context_wheel_paths = tuple(
                    result.wheel_path
                    for result in results
                    if result.wheel_path is not None
                )
                results = [
                    (
                        result
                        if result.errors or result.wheel_path is None
                        else inspect_extension_package_wheel(
                            Path(manifest.path),
                            extension_id=manifest.id,
                            extension_version=manifest.version,
                            backend_entry=manifest.backend_entry,
                            build=False,
                            install_smoke=True,
                            install_context_wheel_paths=context_wheel_paths,
                            wheel_dir=result.wheel_path.parent,
                            timeout=build_timeout,
                        )
                    )
                    for manifest, result in zip(manifests, results, strict=True)
                ]
            error_count = sum(1 for result in results if result.errors)
            set_smoke_result = None
            if install_set_smoke and not error_count:
                set_smoke_result = inspect_extension_package_install_set(
                    [result.wheel_path for result in results if result.wheel_path is not None],
                    expected_extensions={
                        manifest.id: manifest.backend_entry
                        for manifest in manifests
                    },
                    migration_smoke=migration_smoke,
                    lifecycle_smoke=lifecycle_smoke,
                    timeout=build_timeout,
                )
                if set_smoke_result.errors:
                    error_count += 1
        payload = {
            "extensions_path": str(extensions_path),
            "build": build,
            "install_smoke": install_smoke,
            "install_set_smoke": install_set_smoke,
            "migration_smoke": migration_smoke,
            "lifecycle_smoke": lifecycle_smoke,
            "wheel_dir": str(wheel_dir) if wheel_dir is not None else "",
            "install_plan": install_plan,
            "upgrade_risk": upgrade_risk,
            "summary": {
                "manifest_count": len(manifests),
                "error_count": error_count,
                "risk_count": upgrade_risk["summary"]["risk_count"],
                "blocking_risk_count": upgrade_risk["summary"]["blocking_risk_count"],
                "ok": error_count == 0 and not (require_extensions and not manifests),
            },
            "results": [
                {
                    "extension_id": result.extension_id,
                    "extension_root": str(result.extension_root),
                    "pyproject_path": str(result.pyproject_path),
                    "wheel_path": str(result.wheel_path) if result.wheel_path is not None else "",
                    "built": result.built,
                    "install_smoke": result.install_smoke,
                    "source_file_count": len(result.source_files),
                    "packaged_file_count": len(result.packaged_files),
                    "discovered_extension_id": result.discovered_extension_id,
                    "discovered_source": result.discovered_source,
                    "errors": list(result.errors),
                }
                for result in results
            ],
            "install_set": (
                {
                    "extension_ids": list(set_smoke_result.extension_ids),
                    "wheel_count": len(set_smoke_result.wheel_paths),
                    "discovered_extension_ids": list(set_smoke_result.discovered_extension_ids),
                    "discovered_sources": dict(set_smoke_result.discovered_sources),
                    "discovered_migration_modules": dict(set_smoke_result.discovered_migration_modules),
                    "migration_smoke": set_smoke_result.migration_smoke,
                    "lifecycle_smoke": set_smoke_result.lifecycle_smoke,
                    "applied_migration_files": {
                        key: list(value)
                        for key, value in set_smoke_result.applied_migration_files.items()
                    },
                    "lifecycle_states": dict(set_smoke_result.lifecycle_states),
                    "lifecycle_backend_hooks": dict(set_smoke_result.lifecycle_backend_hooks),
                    "boot_order": list(set_smoke_result.boot_order),
                    "errors": list(set_smoke_result.errors),
                }
                if set_smoke_result is not None
                else None
            ),
        }

        if output_format == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            action = "已构建并审计" if build else "已审计"
            if install_smoke:
                action += "安装态"
            if install_set_smoke:
                action += "整组"
            self.stdout.write(f"{action}扩展 wheel: {len(results)}")
            for result in results:
                if result.errors:
                    self.stdout.write(f"[ERROR] {result.extension_id} {result.wheel_path or '-'}")
                    for error in result.errors:
                        self.stdout.write(f"  - {error}")
            if set_smoke_result is not None and set_smoke_result.errors:
                self.stdout.write("[ERROR] install-set")
                for error in set_smoke_result.errors:
                    self.stdout.write(f"  - {error}")
            if payload["summary"]["ok"]:
                self.stdout.write(self.style.SUCCESS("[OK] 扩展 wheel 交付内容已对齐"))

        if require_extensions and not manifests:
            raise CommandError("扩展 wheel 审计未发现任何扩展")
        if error_count:
            raise CommandError(f"扩展 wheel 审计失败，共 {error_count} 个问题")

    def _build_install_plan(
        self,
        manifests,
        *,
        build: bool,
        install_smoke: bool,
        install_set_smoke: bool,
        migration_smoke: bool,
        lifecycle_smoke: bool,
        wheel_dir: Path | None,
    ) -> dict:
        resolved = resolve_extension_order(
            [
                SimpleNamespace(
                    id=manifest.id,
                    manifest=manifest,
                )
                for manifest in manifests
            ],
            satisfied_dependency_ids=get_core_satisfied_dependency_ids(),
        )
        ordered_ids = list(resolved.get("order") or [])
        known_ids = {manifest.id for manifest in manifests}
        remaining_ids = sorted(known_ids - set(ordered_ids))
        install_order = [item for item in ordered_ids if item in known_ids] + remaining_ids
        step_count = 0
        steps = []
        manifest_by_id = {manifest.id: manifest for manifest in manifests}
        for extension_id in install_order:
            manifest = manifest_by_id[extension_id]
            actions = [
                "discover_manifest",
                "validate_pyproject",
                "build_wheel" if build else "select_existing_wheel",
                "inspect_wheel_archive",
            ]
            if install_smoke:
                actions.append("install_smoke")
            if install_set_smoke:
                actions.append("install_set_smoke")
            if migration_smoke:
                actions.append("migration_smoke")
            if lifecycle_smoke:
                actions.append("lifecycle_smoke")
            for action in actions:
                step_count += 1
                steps.append({
                    "step": step_count,
                    "extension_id": extension_id,
                    "action": action,
                    "executes_install": False,
                    "requires_wheel": action not in {"discover_manifest", "validate_pyproject", "build_wheel"},
                })

        return {
            "schema": 1,
            "executes_install": False,
            "extension_count": len(manifests),
            "extension_ids": [manifest.id for manifest in manifests],
            "install_order": install_order,
            "build_requested": build,
            "install_smoke_requested": install_smoke,
            "install_set_smoke_requested": install_set_smoke,
            "migration_smoke_requested": migration_smoke,
            "lifecycle_smoke_requested": lifecycle_smoke,
            "wheel_dir": str(wheel_dir) if wheel_dir is not None else "",
            "dependency_graph": dict(resolved.get("graph") or {}),
            "missing_dependencies": dict(resolved.get("missing_dependencies") or {}),
            "circular_dependencies": list(resolved.get("circular_dependencies") or []),
            "steps": steps,
        }

    def _build_upgrade_risk(self, manifests, *, install_plan: dict) -> dict:
        risks = []
        missing_dependencies = dict(install_plan.get("missing_dependencies") or {})
        for extension_id, dependencies in sorted(missing_dependencies.items()):
            if dependencies:
                risks.append(self._risk(
                    extension_id,
                    "blocking",
                    "missing_dependency",
                    f"缺少必需依赖: {', '.join(dependencies)}",
                ))
        for extension_id in install_plan.get("circular_dependencies") or ():
            risks.append(self._risk(
                str(extension_id),
                "blocking",
                "dependency_cycle",
                "扩展依赖图存在循环，无法确定安装顺序。",
            ))

        for manifest in manifests:
            compatibility = resolve_bias_version_compatibility(manifest)
            if not compatibility["compatible"]:
                risks.append(self._risk(
                    manifest.id,
                    "blocking",
                    "bias_version_incompatible",
                    str(compatibility["message"] or "Bias 版本不满足扩展兼容范围。"),
                    {
                        "current_bias_version": str(compatibility["current_version"] or ""),
                        "required_bias_version": str(compatibility["required_range"] or ""),
                    },
                ))
            stability = str(manifest.compatibility.api_stability or "").strip()
            if stability in {"experimental", "beta"}:
                risks.append(self._risk(
                    manifest.id,
                    "warning" if stability == "experimental" else "info",
                    "unstable_api",
                    f"扩展声明 API 稳定性为 {stability}，升级前需要复核兼容契约。",
                    {
                        "api_version": manifest.compatibility.api_version,
                        "api_stability": stability,
                        "breaking_change_policy": manifest.compatibility.breaking_change_policy,
                    },
                ))
            if manifest.distribution.abandoned:
                risks.append(self._risk(
                    manifest.id,
                    "warning",
                    "abandoned_distribution",
                    "扩展分发已标记 abandoned，升级前应确认替代扩展或迁移路径。",
                    {"replacement": manifest.distribution.replacement},
                ))

        severity_rank = {"blocking": 0, "warning": 1, "info": 2}
        risks.sort(key=lambda item: (severity_rank.get(item["severity"], 9), item["extension_id"], item["code"]))
        return {
            "schema": 1,
            "risk_count": len(risks),
            "risks": risks,
            "summary": {
                "risk_count": len(risks),
                "blocking_risk_count": sum(1 for risk in risks if risk["severity"] == "blocking"),
                "warning_risk_count": sum(1 for risk in risks if risk["severity"] == "warning"),
                "info_risk_count": sum(1 for risk in risks if risk["severity"] == "info"),
                "ok": not any(risk["severity"] == "blocking" for risk in risks),
            },
        }

    def _risk(self, extension_id: str, severity: str, code: str, message: str, extra: dict | None = None) -> dict:
        payload = {
            "extension_id": extension_id,
            "severity": severity,
            "code": code,
            "message": message,
        }
        if extra:
            payload.update(extra)
        return payload


class _null_temp_dir:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, traceback):
        return False
