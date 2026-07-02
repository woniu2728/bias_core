from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.core.management.base import CommandParser
from django.db import OperationalError, ProgrammingError

from bias_core.extension_diagnostics import (
    classify_extension_diagnostics,
    summarize_extension_delivery,
    summarize_extension_diagnostics,
)
from bias_core.extension_serialization import (
    serialize_admin_extension,
    serialize_admin_extensions_payload,
)
from bias_core.extensions.module_extension_view import resolve_module_extension_definition
from bias_core.extensions.registry import get_extension_registry
from bias_core.extensions.exceptions import ExtensionNotFoundError
from bias_core.extensions.validation_rules import SEMVER_PATTERN, VERSION_RANGE_PATTERN
from bias_core.extensions.version_compatibility import matches_simple_version_range
from bias_core.forum_registry import get_forum_registry
from bias_core.version import APP_VERSION


class Command(BaseCommand):
    help = "导出扩展清单与诊断快照，供 CI、发布脚本和运维巡检消费。"
    requires_system_checks = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--extension-id",
            help="只导出指定扩展",
        )
        parser.add_argument(
            "--only-attention",
            action="store_true",
            help="仅输出存在风险、异常或待处理项的扩展",
        )
        parser.add_argument(
            "--only-blocking",
            action="store_true",
            help="仅输出会阻断发布或需要优先处理的扩展",
        )
        parser.add_argument(
            "--include-permissions",
            action="store_true",
            help="附带权限分组明细，默认仅输出权限摘要",
        )
        parser.add_argument(
            "--contract-baseline-only",
            action="store_true",
            help="仅输出扩展契约基线，供 prepare_release --contract-baseline 消费",
        )
        parser.add_argument(
            "--fail-on-runtime-service-fallback",
            action="store_true",
            help="存在 runtime service contract core fallback 时失败，用于 CI/发布阻断契约回退",
        )
        parser.add_argument(
            "--format",
            choices=("json",),
            default="json",
            help="输出格式，当前仅支持 json",
        )
        parser.add_argument(
            "--output",
            help="可选：把输出写入指定 JSON 文件，使用 UTF-8 编码",
        )

    def handle(self, *args, **options):
        extension_id = str(options.get("extension_id") or "").strip()
        only_attention = bool(options.get("only_attention"))
        only_blocking = bool(options.get("only_blocking"))
        include_permissions = bool(options.get("include_permissions"))
        contract_baseline_only = bool(options.get("contract_baseline_only"))
        fail_on_runtime_service_fallback = bool(options.get("fail_on_runtime_service_fallback"))
        output = str(options.get("output") or "").strip()

        try:
            registry = get_extension_registry()
            registry.load(force=True)
        except (OperationalError, ProgrammingError) as exc:
            self._write_json(json.dumps(
                _build_database_unavailable_payload(
                    error=exc,
                    extension_id=extension_id,
                    only_attention=only_attention,
                    only_blocking=only_blocking,
                    include_permissions=include_permissions,
                ),
                ensure_ascii=False,
                indent=2,
            ))
            return

        if extension_id:
            try:
                extensions = [registry.get_extension(extension_id)]
            except ExtensionNotFoundError as exc:
                module_extension = _resolve_core_module_extension(extension_id)
                if module_extension is None:
                    raise CommandError(str(exc)) from exc
                extensions = [module_extension]
        else:
            extensions = _resolve_inspection_extensions(registry.get_extensions())

        payload = serialize_admin_extensions_payload(extensions)
        serialized_extensions = payload["extensions"]

        if include_permissions or extension_id:
            serialized_extensions = [
                serialize_admin_extension(
                    extension,
                    include_permission_details=include_permissions or bool(extension_id),
                )
                for extension in extensions
            ]
            payload = {
                **payload,
                "extensions": serialized_extensions,
                "summary": {
                    **payload["summary"],
                    "extension_count": len(serialized_extensions),
                    "enabled_count": sum(1 for item in serialized_extensions if item["enabled"]),
                    "healthy_count": sum(1 for item in serialized_extensions if item["healthy"]),
                    "filesystem_count": sum(1 for item in serialized_extensions if item["source"] == "filesystem"),
                },
            }

        serialized_extensions = [
            {
                **item,
                "diagnostics": classify_extension_diagnostics(item),
            }
            for item in serialized_extensions
        ]

        if only_blocking:
            serialized_extensions = [
                item for item in serialized_extensions
                if item["diagnostics"]["blocking"]
            ]

        elif only_attention:
            serialized_extensions = [
                item for item in serialized_extensions
                if item["diagnostics"]["has_attention"]
            ]

        compatibility_matrix = _build_compatibility_matrix(serialized_extensions)
        diagnostics_summary = summarize_extension_diagnostics(serialized_extensions)
        delivery_summary = summarize_extension_delivery(serialized_extensions)
        payload = {
            **payload,
            "extensions": serialized_extensions,
            "compatibility_matrix": compatibility_matrix,
            "summary": {
                **payload["summary"],
                "extension_count": len(serialized_extensions),
                "enabled_count": sum(1 for item in serialized_extensions if item["enabled"]),
                "healthy_count": sum(1 for item in serialized_extensions if item["healthy"]),
                "filesystem_count": sum(1 for item in serialized_extensions if item["source"] == "filesystem"),
                **diagnostics_summary,
                **delivery_summary,
                "compatibility_blocking_count": compatibility_matrix["summary"]["blocking_count"],
                "compatibility_warning_count": compatibility_matrix["summary"]["warning_count"],
                "bias_version_incompatible_count": compatibility_matrix["summary"]["bias_version_incompatible_count"],
                "unstable_api_count": compatibility_matrix["summary"]["unstable_api_count"],
                "abandoned_distribution_count": compatibility_matrix["summary"]["abandoned_distribution_count"],
            },
        }

        payload["meta"] = {
            "base_dir": str(settings.BASE_DIR),
            "extension_id": extension_id,
            "only_attention": only_attention,
            "only_blocking": only_blocking,
            "include_permissions": include_permissions,
            "contract_baseline_only": contract_baseline_only,
            "fail_on_runtime_service_fallback": fail_on_runtime_service_fallback,
        }
        try:
            payload["package_lock"] = registry.inspect_extension_packages(force=True)
        except (OperationalError, ProgrammingError) as exc:
            payload["package_lock"] = {
                "status": "blocked",
                "code": "database_migrations_unapplied",
                "message": "Django 数据库迁移尚未应用，无法读取扩展安装状态。请先执行 python manage.py migrate。",
                "error": str(exc),
            }
        if fail_on_runtime_service_fallback:
            fallback_issues = _runtime_service_fallback_issues(payload)
            if fallback_issues:
                detail = ", ".join(f"{item['extension_id']}:{item['service_key']}" for item in fallback_issues[:10])
                suffix = " ..." if len(fallback_issues) > 10 else ""
                raise CommandError(f"runtime service contract 仍依赖 core fallback: {detail}{suffix}")
        if contract_baseline_only:
            payload = _build_contract_baseline_payload(payload)
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        if output:
            output_path = Path(output)
            if not output_path.is_absolute():
                output_path = settings.BASE_DIR / output_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(serialized + "\n", encoding="utf-8")
            self.stdout.write(str(output_path))
            return
        self._write_json(serialized)

    def _write_json(self, serialized: str) -> None:
        self.stdout.write(_encode_stdout_safe(serialized, _stdout_encoding(self.stdout)))


def _resolve_inspection_extensions(filesystem_extensions):
    extensions = list(filesystem_extensions)
    existing_ids = {extension.id for extension in extensions}
    core_module_extensions = [
        resolve_module_extension_definition(module)
        for module in get_forum_registry().get_modules()
        if module.module_id not in existing_ids
    ]
    return sorted(
        [*extensions, *core_module_extensions],
        key=lambda item: (
            0 if item.id == "core" else 1,
            0 if item.source == "core-module" else 1,
            item.id,
        ),
    )


def _encode_stdout_safe(value: str, encoding: str | None) -> str:
    if not encoding:
        return value
    try:
        value.encode(encoding)
    except UnicodeEncodeError:
        return value.encode(encoding, errors="backslashreplace").decode(encoding)
    return value


def _stdout_encoding(stdout) -> str | None:
    encoding = getattr(stdout, "encoding", None)
    if encoding:
        return encoding
    wrapped = getattr(stdout, "_out", None)
    return getattr(wrapped, "encoding", None)


def _resolve_core_module_extension(extension_id: str):
    normalized = str(extension_id or "").strip()
    if not normalized:
        return None
    module = next(
        (item for item in get_forum_registry().get_modules() if item.module_id == normalized),
        None,
    )
    if module is None:
        return None
    return resolve_module_extension_definition(module)


def _build_contract_baseline_payload(payload: dict) -> dict:
    snapshots = {}
    for extension in payload.get("extensions") or ():
        if not isinstance(extension, dict):
            continue
        extension_id = str(extension.get("id") or "").strip()
        snapshot = extension.get("contract_snapshot")
        if extension_id and isinstance(snapshot, dict):
            snapshots[extension_id] = snapshot
    return {
        "schema_version": 1,
        "contract_snapshots": dict(sorted(snapshots.items())),
        "meta": {
            "source": "inspect_extensions",
            "extension_count": len(snapshots),
            "base_dir": (payload.get("meta") or {}).get("base_dir", ""),
        },
    }


def _build_compatibility_matrix(extensions: list[dict]) -> dict:
    rows = []
    for extension in extensions:
        if not isinstance(extension, dict):
            continue
        compatibility = extension.get("compatibility") if isinstance(extension.get("compatibility"), dict) else {}
        distribution = extension.get("distribution") if isinstance(extension.get("distribution"), dict) else {}
        diagnostics = extension.get("diagnostics") if isinstance(extension.get("diagnostics"), dict) else {}
        bias_compatibility = _resolve_bias_version_matrix_status(compatibility)
        api_stability = str(compatibility.get("api_stability") or "").strip()
        abandoned = bool(distribution.get("abandoned"))
        blocking_reasons = list(diagnostics.get("blocking_reasons") or [])
        warning_reasons = list(diagnostics.get("warning_reasons") or [])
        diagnostic_blocking = bool(diagnostics.get("blocking"))
        diagnostic_warning = bool(diagnostics.get("warning"))
        if not bias_compatibility["compatible"]:
            blocking_reasons.append(str(bias_compatibility["message"] or "Bias 版本不满足扩展兼容范围。"))
        if api_stability in {"experimental", "beta"}:
            warning_reasons.append(f"API 稳定性为 {api_stability}，发布前需复核兼容契约。")
        if abandoned:
            replacement = str(distribution.get("replacement") or "").strip()
            warning_reasons.append(
                "分发已标记 abandoned"
                + (f"，替代项: {replacement}" if replacement else "。")
            )

        row = {
            "extension_id": str(extension.get("id") or "").strip(),
            "name": str(extension.get("name") or "").strip(),
            "version": str(extension.get("version") or "").strip(),
            "schema_version": int(extension.get("schema_version") or 1),
            "source": str(extension.get("source") or "").strip(),
            "enabled": bool(extension.get("enabled")),
            "healthy": bool(extension.get("healthy")),
            "compatibility": {
                "bias_version": str(compatibility.get("bias_version") or "").strip(),
                "api_version": str(compatibility.get("api_version") or "").strip(),
                "api_stability": api_stability,
                "breaking_change_policy": str(compatibility.get("breaking_change_policy") or "").strip(),
                "current_bias_version": bias_compatibility["current_version"],
                "bias_version_compatible": bias_compatibility["compatible"],
                "bias_version_message": bias_compatibility["message"],
            },
            "dependencies": list(extension.get("dependencies") or []),
            "optional_dependencies": list(extension.get("optional_dependencies") or []),
            "conflicts": list(extension.get("conflicts") or []),
            "provides": list(extension.get("provides") or []),
            "distribution": {
                "channel": str(distribution.get("channel") or "").strip(),
                "signing_key_id": str(distribution.get("signing_key_id") or "").strip(),
                "signature_url": str(distribution.get("signature_url") or "").strip(),
                "abandoned": abandoned,
                "replacement": str(distribution.get("replacement") or "").strip(),
            },
            "release_policy": {
                "contract_snapshot_required": True,
                "contract_baseline_gate": "prepare_release --contract-baseline",
                "runtime_service_fallback_gate": "inspect_extensions --fail-on-runtime-service-fallback",
                "package_install_plan_gate": "inspect_extension_packages --build --install-smoke --install-set-smoke --migration-smoke",
            },
            "status": {
                "blocking": diagnostic_blocking or bool(blocking_reasons),
                "warning": diagnostic_warning or bool(warning_reasons),
                "blocking_reasons": _dedupe_strings(blocking_reasons),
                "warning_reasons": _dedupe_strings(warning_reasons),
            },
        }
        rows.append(row)

    rows.sort(key=lambda item: item["extension_id"])
    blocking_count = sum(1 for row in rows if row["status"]["blocking"])
    warning_count = sum(1 for row in rows if row["status"]["warning"])
    incompatible_count = sum(1 for row in rows if not row["compatibility"]["bias_version_compatible"])
    unstable_count = sum(
        1
        for row in rows
        if row["compatibility"]["api_stability"] in {"experimental", "beta"}
    )
    abandoned_count = sum(1 for row in rows if row["distribution"]["abandoned"])
    return {
        "schema": 1,
        "current_bias_version": str(APP_VERSION or "").strip(),
        "rows": rows,
        "summary": {
            "extension_count": len(rows),
            "blocking_count": blocking_count,
            "warning_count": warning_count,
            "bias_version_incompatible_count": incompatible_count,
            "unstable_api_count": unstable_count,
            "abandoned_distribution_count": abandoned_count,
            "ok": blocking_count == 0 and incompatible_count == 0,
        },
    }


def _resolve_bias_version_matrix_status(compatibility: dict) -> dict:
    current_version = str(APP_VERSION or "").strip()
    version_range = str(compatibility.get("bias_version") or "").strip()
    if not version_range:
        return {
            "compatible": True,
            "current_version": current_version,
            "required_range": "",
            "message": "",
        }
    if not current_version or not SEMVER_PATTERN.match(current_version):
        return {
            "compatible": False,
            "current_version": current_version,
            "required_range": version_range,
            "message": f"当前 Bias 版本 {current_version or '未知'} 无法用于校验扩展兼容范围 {version_range}。",
        }
    if not VERSION_RANGE_PATTERN.match(version_range):
        return {
            "compatible": False,
            "current_version": current_version,
            "required_range": version_range,
            "message": f"扩展声明的 Bias 兼容范围非法：{version_range}。",
        }
    compatible = matches_simple_version_range(current_version, version_range)
    return {
        "compatible": compatible,
        "current_version": current_version,
        "required_range": version_range,
        "message": "" if compatible else f"当前 Bias 版本 {current_version} 不满足扩展声明的兼容范围 {version_range}。",
    }


def _dedupe_strings(values) -> list[str]:
    output = []
    seen = set()
    for value in values or ():
        normalized = str(value or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            output.append(normalized)
    return output


def _runtime_service_fallback_issues(payload: dict) -> list[dict]:
    issues: list[dict] = []
    for extension in payload.get("extensions") or ():
        if not isinstance(extension, dict):
            continue
        extension_id = str(extension.get("id") or "").strip()
        for warning in extension.get("runtime_service_contract_warnings") or ():
            if not isinstance(warning, dict):
                continue
            if warning.get("code") != "runtime_service_contract_uses_core_fallback":
                continue
            issues.append({
                "extension_id": extension_id,
                "service_key": str(warning.get("service_key") or "").strip(),
            })
        snapshot = extension.get("contract_snapshot") or {}
        runtime = snapshot.get("runtime") or {}
        for contract in runtime.get("service_contracts") or ():
            if not isinstance(contract, dict):
                continue
            if contract.get("source") != "core_fallback":
                continue
            service_key = str(contract.get("service_key") or "").strip()
            duplicate = any(
                item["extension_id"] == extension_id and item["service_key"] == service_key
                for item in issues
            )
            if not duplicate:
                issues.append({
                    "extension_id": extension_id,
                    "service_key": service_key,
                })
    return issues


def _build_database_unavailable_payload(
    *,
    error: Exception,
    extension_id: str,
    only_attention: bool,
    only_blocking: bool,
    include_permissions: bool,
) -> dict:
    diagnostic = {
        "code": "database_migrations_unapplied",
        "message": "Django 数据库迁移尚未应用，无法读取扩展安装状态。请先执行 python manage.py migrate。",
        "blocking": True,
        "has_attention": True,
        "severity": "error",
    }
    return {
        "extensions": [],
        "summary": {
            "extension_count": 0,
            "enabled_count": 0,
            "healthy_count": 0,
            "filesystem_count": 0,
            "attention_count": 1,
            "blocking_count": 1,
            "warning_count": 0,
            "frontend_bundle_count": 0,
            "migration_bundle_count": 0,
            "status": "blocked",
        },
        "diagnostics": [diagnostic],
        "meta": {
            "base_dir": str(settings.BASE_DIR),
            "extension_id": extension_id,
            "only_attention": only_attention,
            "only_blocking": only_blocking,
            "include_permissions": include_permissions,
            "database_ready": False,
            "error": str(error),
        },
        "package_lock": {
            "status": "blocked",
            "code": diagnostic["code"],
            "message": diagnostic["message"],
        },
    }

