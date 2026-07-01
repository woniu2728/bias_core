from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.core.management.base import CommandParser

from bias_core.extensions.exceptions import ExtensionManifestError
from bias_core.extensions.manifest import ExtensionManifestLoader
from bias_core.extensions.validation import validate_extension_manifests_with_available_ids
from bias_core.forum_registry import get_core_module_ids


SITE_HOST_DIRECTORY_NAMES = {"bias", "bias_site", "site"}


def resolve_available_extension_ids(manifests) -> set[str]:
    return set(get_core_module_ids()) | {manifest.id for manifest in manifests}


def resolve_command_workspace_root(extensions_path: Path) -> Path | None:
    if extensions_path.name != "extensions":
        return None
    if extensions_path.parent.name in SITE_HOST_DIRECTORY_NAMES:
        return extensions_path.parent.parent
    return extensions_path.parent


class Command(BaseCommand):
    help = "校验扩展 manifest、依赖关系与后台入口约束。"
    requires_system_checks = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--extensions-path",
            help="扩展目录路径，默认使用 BASE_DIR/extensions",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="将 warning 也视为失败",
        )
        parser.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
            help="输出格式，默认 text，可选 json 便于 CI 消费",
        )
        parser.add_argument(
            "--internal",
            action="store_true",
            help="以内置扩展模式校验，允许 Bias 内部扩展使用非公开运行时辅助模块",
        )
        parser.add_argument(
            "--require-extensions",
            action="store_true",
            help="要求至少发现一个扩展；CI/发布校验可用它避免空目录误报通过",
        )

    def handle(self, *args, **options):
        extensions_path = Path(options.get("extensions_path") or (Path(settings.BASE_DIR) / "extensions"))
        strict = bool(options.get("strict"))
        internal = bool(options.get("internal"))
        require_extensions = bool(options.get("require_extensions"))
        output_format = str(options.get("format") or "text").strip() or "text"

        include_workspace = extensions_path.name == "extensions"
        loader = ExtensionManifestLoader(
            extensions_path,
            include_workspace=include_workspace,
            workspace_root=resolve_command_workspace_root(extensions_path),
        )
        try:
            manifests = loader.discover_manifests()
        except ExtensionManifestError as exc:
            raise CommandError(str(exc)) from exc

        available_extension_ids = resolve_available_extension_ids(manifests)
        result = validate_extension_manifests_with_available_ids(
            manifests,
            available_extension_ids=available_extension_ids,
            extensions_base_path=extensions_path,
            strict_runtime_hooks=strict,
            public_sdk_only=not internal,
        )
        if result.error_count == 0:
            try:
                discovery_results = loader.discover()
            except ExtensionManifestError as exc:
                raise CommandError(str(exc)) from exc
            manifests = [item.manifest for item in discovery_results]
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids=available_extension_ids,
                extensions_base_path=extensions_path,
                strict_runtime_hooks=strict,
                public_sdk_only=not internal,
                frontend_routes_by_extension={
                    item.manifest.id: tuple(item.frontend_routes or ())
                    for item in discovery_results
                },
                route_mounts_by_extension={
                    item.manifest.id: tuple(item.route_mounts or ())
                    for item in discovery_results
                },
                named_routes_by_extension={
                    item.manifest.id: tuple(item.named_routes or ())
                    for item in discovery_results
                },
                websocket_routes_by_extension={
                    item.manifest.id: tuple(item.websocket_routes or ())
                    for item in discovery_results
                },
                notification_types_by_extension={
                    item.manifest.id: tuple(item.notification_types or ())
                    for item in discovery_results
                },
                permissions_by_extension={
                    item.manifest.id: tuple(item.permissions or ())
                    for item in discovery_results
                },
                admin_pages_by_extension={
                    item.manifest.id: tuple(item.admin_pages or ())
                    for item in discovery_results
                },
                user_preferences_by_extension={
                    item.manifest.id: tuple(item.user_preferences or ())
                    for item in discovery_results
                },
                language_packs_by_extension={
                    item.manifest.id: tuple(item.language_packs or ())
                    for item in discovery_results
                },
                post_types_by_extension={
                    item.manifest.id: tuple(item.post_types or ())
                    for item in discovery_results
                },
                search_filters_by_extension={
                    item.manifest.id: tuple(item.search_filters or ())
                    for item in discovery_results
                },
                discussion_list_queries_by_extension={
                    item.manifest.id: tuple(item.discussion_list_queries or ())
                    for item in discovery_results
                },
                discussion_sorts_by_extension={
                    item.manifest.id: tuple(item.discussion_sorts or ())
                    for item in discovery_results
                },
                discussion_list_filters_by_extension={
                    item.manifest.id: tuple(item.discussion_list_filters or ())
                    for item in discovery_results
                },
                resource_definitions_by_extension={
                    item.manifest.id: tuple(item.resource_definitions or ())
                    for item in discovery_results
                },
                resource_fields_by_extension={
                    item.manifest.id: tuple(item.resource_fields or ())
                    for item in discovery_results
                },
                resource_relationships_by_extension={
                    item.manifest.id: tuple(item.resource_relationships or ())
                    for item in discovery_results
                },
                resource_endpoints_by_extension={
                    item.manifest.id: tuple(item.resource_endpoints or ())
                    for item in discovery_results
                },
                resource_sorts_by_extension={
                    item.manifest.id: tuple(item.resource_sorts or ())
                    for item in discovery_results
                },
                resource_filters_by_extension={
                    item.manifest.id: tuple(item.resource_filters or ())
                    for item in discovery_results
                },
                model_definitions_by_extension={
                    item.manifest.id: tuple(item.model_definitions or ())
                    for item in discovery_results
                },
                model_relations_by_extension={
                    item.manifest.id: tuple(item.model_relations or ())
                    for item in discovery_results
                },
                model_casts_by_extension={
                    item.manifest.id: tuple(item.model_casts or ())
                    for item in discovery_results
                },
                model_defaults_by_extension={
                    item.manifest.id: tuple(item.model_defaults or ())
                    for item in discovery_results
                },
                model_slug_drivers_by_extension={
                    item.manifest.id: tuple(item.model_slug_drivers or ())
                    for item in discovery_results
                },
                search_drivers_by_extension={
                    item.manifest.id: tuple(item.search_drivers or ())
                    for item in discovery_results
                },
                search_indexes_by_extension={
                    item.manifest.id: tuple(item.search_indexes or ())
                    for item in discovery_results
                },
            )

        payload = {
            "extensions_path": str(extensions_path),
            "strict": strict,
            "internal": internal,
            "summary": {
                "manifest_count": len(result.manifests),
                "error_count": result.error_count,
                "warning_count": result.warning_count,
                "ok": (
                    result.ok
                    and not (strict and _has_blocking_warnings(result.issues))
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

        if output_format == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            if require_extensions and not result.manifests:
                raise CommandError("扩展校验未发现任何扩展")
            if result.error_count:
                raise CommandError(f"扩展校验失败，共 {result.error_count} 个错误")
            if strict and _has_blocking_warnings(result.issues):
                raise CommandError("扩展严格校验失败，存在阻断性警告")
            return

        self.stdout.write(f"已扫描扩展: {len(result.manifests)}")
        for issue in result.issues:
            prefix = "[ERROR]" if issue.level == "error" else "[WARN]"
            target = f"{issue.extension_id}" if issue.extension_id else "-"
            field = f" ({issue.field})" if issue.field else ""
            self.stdout.write(f"{prefix} {issue.code} {target}{field} {issue.message}")

        if require_extensions and not result.manifests:
            raise CommandError("扩展校验未发现任何扩展")
        if result.error_count:
            raise CommandError(f"扩展校验失败，共 {result.error_count} 个错误")
        if strict and _has_blocking_warnings(result.issues):
            raise CommandError("扩展严格校验失败，存在阻断性警告")

        self.stdout.write(self.style.SUCCESS(
            f"[OK] 扩展校验通过，错误 {result.error_count}，警告 {result.warning_count}"
        ))


def _has_blocking_warnings(issues) -> bool:
    return any(
        item.level == "warning"
        for item in issues
    )

