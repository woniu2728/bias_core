from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.core.management.base import CommandParser

from bias_core.extensions.exceptions import ExtensionManifestError
from bias_core.extensions.manifest import ExtensionManifestLoader
from bias_core.extensions.validation_source import (
    build_capability_provider_map,
    snapshot_runtime_facade_dependency_graph,
    validate_cross_extension_imports,
    validate_runtime_facade_dependency_graph,
)
from bias_core.extensions.validation_types import ExtensionValidationCollector
from bias_core.forum_registry import get_core_module_ids


SITE_HOST_DIRECTORY_NAMES = {"bias", "bias_site", "site"}


def resolve_command_workspace_root(extensions_path: Path) -> Path | None:
    if extensions_path.name != "extensions":
        return None
    if extensions_path.parent.name in SITE_HOST_DIRECTORY_NAMES:
        return extensions_path.parent.parent
    return extensions_path.parent


class Command(BaseCommand):
    help = "审计扩展后端 import 边界，确保扩展只依赖公开 SDK 与声明过的扩展契约。"
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
            "--internal",
            action="store_true",
            help="以内置扩展维护模式审计，允许导入 bias_core 内部模块，但仍检查跨扩展依赖声明。",
        )
        parser.add_argument(
            "--include-tests",
            action="store_true",
            help="同时审计扩展测试代码；测试只能依赖 bias_core.extensions.testing 等公开 facade。",
        )
        parser.add_argument(
            "--check-runtime-facades",
            action="store_true",
            help="审计 bias_core.extensions.runtime facade 访问是否已在 manifest 依赖中显式声明。",
        )
        parser.add_argument(
            "--require-extensions",
            action="store_true",
            help="要求至少发现一个扩展；CI/发布校验可用它避免空目录误报通过",
        )
        parser.add_argument(
            "--fail-on-warnings",
            action="store_true",
            help="将警告也视为失败；CI/发布校验可用它阻断软性边界规则回归",
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
        internal = bool(options.get("internal"))
        include_tests = bool(options.get("include_tests"))
        check_runtime_facades = bool(options.get("check_runtime_facades"))
        require_extensions = bool(options.get("require_extensions"))
        fail_on_warnings = bool(options.get("fail_on_warnings"))
        output_format = str(options.get("format") or "text").strip() or "text"

        include_workspace = extensions_path.name == "extensions"
        loader = ExtensionManifestLoader(
            extensions_path,
            include_workspace=include_workspace,
            workspace_root=resolve_command_workspace_root(extensions_path),
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

        collector = ExtensionValidationCollector()
        collector.manifests.extend(manifests)
        capability_providers = build_capability_provider_map(manifests)
        known_extension_ids = set(get_core_module_ids()) | {manifest.id for manifest in manifests} | set(capability_providers)
        for manifest in manifests:
            validate_cross_extension_imports(
                collector,
                manifest,
                extensions_path,
                known_extension_ids=known_extension_ids,
                public_sdk_only=not internal,
                include_tests=include_tests,
                check_runtime_facade_dependencies=check_runtime_facades,
                capability_providers=capability_providers,
            )
        runtime_facade_dependency_graph = None
        if check_runtime_facades:
            validate_runtime_facade_dependency_graph(
                collector,
                manifests,
                extensions_path,
                known_extension_ids=known_extension_ids,
                include_tests=include_tests,
                capability_providers=capability_providers,
            )
            runtime_facade_dependency_graph = snapshot_runtime_facade_dependency_graph(
                manifests,
                extensions_path,
                known_extension_ids=known_extension_ids,
                include_tests=include_tests,
                capability_providers=capability_providers,
            )
        result = collector.build()

        payload = {
            "extensions_path": str(extensions_path),
            "internal": internal,
            "include_tests": include_tests,
            "check_runtime_facades": check_runtime_facades,
            "summary": {
                "manifest_count": len(result.manifests),
                "error_count": result.error_count,
                "warning_count": result.warning_count,
                "ok": (
                    result.ok
                    and not (fail_on_warnings and result.warning_count)
                    and not (require_extensions and not result.manifests)
                ),
            },
            "manifests": [
                {
                    "id": manifest.id,
                    "name": manifest.name,
                    "version": manifest.version,
                    "source": manifest.source,
                    "path": manifest.path,
                }
                for manifest in result.manifests
            ],
            "issues": [
                {
                    "level": issue.level,
                    "code": issue.code,
                    "field": issue.field,
                    "message": issue.message,
                    "extension_id": issue.extension_id,
                }
                for issue in result.issues
            ],
        }
        if runtime_facade_dependency_graph is not None:
            payload["runtime_facade_dependency_graph"] = runtime_facade_dependency_graph

        if output_format == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(f"已审计扩展 import 边界: {len(result.manifests)}")
            for issue in result.issues:
                prefix = "[ERROR]" if issue.level == "error" else "[WARN]"
                target = issue.extension_id or "-"
                field = f" ({issue.field})" if issue.field else ""
                self.stdout.write(f"{prefix} {issue.code} {target}{field} {issue.message}")
            if payload["summary"]["ok"]:
                self.stdout.write(self.style.SUCCESS(
                    f"[OK] 扩展 import 边界通过，错误 {result.error_count}，警告 {result.warning_count}"
                ))

        if require_extensions and not result.manifests:
            raise CommandError("扩展 import 边界审计未发现任何扩展")
        if result.error_count:
            raise CommandError(f"扩展 import 边界审计失败，共 {result.error_count} 个错误")
        if fail_on_warnings and result.warning_count:
            raise CommandError(f"扩展 import 边界审计失败，共 {result.warning_count} 个警告")
