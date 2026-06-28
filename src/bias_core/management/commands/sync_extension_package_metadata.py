from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.core.management.base import CommandParser

from bias_core.extensions.exceptions import ExtensionManifestError
from bias_core.extensions.manifest import ExtensionManifestLoader
from bias_core.extensions.packaging import sync_extension_package_metadata


class Command(BaseCommand):
    help = "同步扩展 pyproject.toml 中由 manifest 决定的包元数据。"
    requires_system_checks = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--extensions-path",
            help="扩展目录路径，默认使用 BASE_DIR/extensions；拆分仓库会自动扫描同级 bias-ext-* 目录",
        )
        parser.add_argument(
            "--extension-id",
            help="只同步指定扩展",
        )
        parser.add_argument(
            "--write",
            action="store_true",
            help="写回 pyproject.toml；默认只检查并报告漂移",
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
        write = bool(options.get("write"))
        output_format = str(options.get("format") or "text").strip() or "text"

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

        results = [
            {
                "extension_id": manifest.id,
                "pyproject_path": str(Path(manifest.path) / "pyproject.toml"),
                "changed": result.changed,
                "updates": list(result.updates),
                "errors": list(result.errors),
            }
            for manifest in manifests
            for result in (
                sync_extension_package_metadata(
                    Path(manifest.path),
                    extension_id=manifest.id,
                    extension_version=manifest.version,
                    manifest_dependencies=manifest.dependencies,
                    backend_entry=manifest.backend_entry,
                    write=write,
                ),
            )
        ]

        payload = {
            "extensions_path": str(extensions_path),
            "write": write,
            "summary": {
                "manifest_count": len(manifests),
                "changed_count": sum(1 for item in results if item["changed"]),
                "error_count": sum(1 for item in results if item["errors"]),
                "ok": not any(item["errors"] for item in results)
                and (write or not any(item["changed"] for item in results)),
            },
            "results": results,
        }

        if output_format == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            action = "已同步" if write else "已检查"
            self.stdout.write(f"{action}扩展包元数据: {len(manifests)}")
            for item in results:
                if item["errors"]:
                    self.stdout.write(f"[ERROR] {item['extension_id']} {', '.join(item['errors'])}")
                    continue
                if item["changed"]:
                    status = "updated" if write else "drift"
                    updates = ", ".join(item["updates"]) or "pyproject.toml"
                    self.stdout.write(f"[{status.upper()}] {item['extension_id']} {updates}")
            if payload["summary"]["ok"]:
                self.stdout.write(self.style.SUCCESS("[OK] 扩展包元数据已对齐"))

        if payload["summary"]["error_count"]:
            raise CommandError(f"扩展包元数据同步失败，共 {payload['summary']['error_count']} 个错误")
        if not write and payload["summary"]["changed_count"]:
            raise CommandError(f"扩展包元数据存在漂移，共 {payload['summary']['changed_count']} 个扩展需要同步")
