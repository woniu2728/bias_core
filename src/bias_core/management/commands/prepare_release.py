from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.core.management import call_command
from django.core.management.base import CommandParser

from bias_core.release import (
    ensure_release_versions_aligned,
    run_git_command,
    update_frontend_versions,
    validate_release_tag,
    validate_semver,
    version_from_tag,
)

DEFAULT_EXTENSION_CONTRACT_BASELINE = "extension-contract-baseline.json"


class Command(BaseCommand):
    help = "准备发布版本：统一 VERSION/前端版本，并强制校验 Git tag 与工作区状态。"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--set-version", help="要发布的语义化版本号，例如 1.2.3")
        parser.add_argument("--tag", help="要发布的 Git tag，例如 v1.2.3")
        parser.add_argument("--allow-dirty", action="store_true", help="允许 Git 工作区存在未提交改动")
        parser.add_argument("--dry-run", action="store_true", help="只输出检查结果，不写入任何文件")
        parser.add_argument("--extension-report", help="可选：把扩展诊断快照写入指定 JSON 文件")
        parser.add_argument(
            "--contract-baseline",
            help=f"可选：读取扩展契约基线 JSON，并阻断破坏性契约变化；默认自动使用 {DEFAULT_EXTENSION_CONTRACT_BASELINE}",
        )
        parser.add_argument(
            "--skip-frontend-platform-check",
            action="store_true",
            help="跳过站点前端 SDK/扩展边界检查；默认在前端 package 提供 check:platform 时执行",
        )
        parser.add_argument(
            "--allow-extension-attention",
            action="store_true",
            help="允许存在扩展关注项继续发布；默认存在关注项就阻止发布",
        )

    def handle(self, *args, **options):
        version = (options.get("set_version") or "").strip()
        tag = (options.get("tag") or "").strip()
        dry_run = bool(options.get("dry_run"))
        allow_dirty = bool(options.get("allow_dirty"))
        extension_report = (options.get("extension_report") or "").strip()
        contract_baseline_option = (options.get("contract_baseline") or "").strip()
        allow_extension_attention = bool(options.get("allow_extension_attention"))
        skip_frontend_platform_check = bool(options.get("skip_frontend_platform_check"))

        if not version and not tag:
            raise CommandError("必须至少提供 --set-version 或 --tag")

        if version:
            validate_semver(version)
        if tag:
            validate_release_tag(tag)

        resolved_version = version_from_tag(tag) if tag else version
        if version and tag and resolved_version != version:
            raise CommandError("--set-version 与 --tag 不一致")

        base_dir = settings.BASE_DIR
        version_file = base_dir / "VERSION"
        contract_baseline = contract_baseline_option or self._default_contract_baseline_path(base_dir)

        if not allow_dirty:
            self._ensure_clean_git_state()

        extensions_path = self._release_extensions_path(base_dir)
        call_command(
            "sync_extension_package_metadata",
            "--extensions-path",
            str(extensions_path),
        )
        call_command(
            "inspect_extension_imports",
            "--require-extensions",
            "--fail-on-warnings",
            "--extensions-path",
            str(extensions_path),
        )
        call_command(
            "inspect_extension_imports",
            "--require-extensions",
            "--fail-on-warnings",
            "--include-tests",
            "--extensions-path",
            str(extensions_path),
        )
        call_command(
            "inspect_extension_packages",
            "--require-extensions",
            "--build",
            "--install-smoke",
            "--install-set-smoke",
            "--migration-smoke",
            "--extensions-path",
            str(extensions_path),
        )
        call_command(
            "validate_extensions",
            "--strict",
            "--internal",
            "--require-extensions",
            "--extensions-path",
            str(extensions_path),
        )
        inspection_payload = self._inspect_extensions()
        self._validate_extension_contract_snapshots(inspection_payload)
        if contract_baseline:
            self._validate_extension_contract_baseline(inspection_payload, contract_baseline)
        pending_migration_summary = self._build_pending_extension_migration_summary(inspection_payload)
        summary = inspection_payload.get("summary") or {}
        blocking_count = int(summary.get("blocking_count") or 0)
        warning_count = int(summary.get("warning_count") or 0)
        attention_count = int(summary.get("attention_count") or 0)
        asset_count = int(summary.get("asset_count") or 0)
        frontend_bundle_count = int(summary.get("frontend_bundle_count") or 0)
        migration_bundle_count = int(summary.get("migration_bundle_count") or 0)
        locale_bundle_count = int(summary.get("locale_bundle_count") or 0)
        signed_extension_count = int(summary.get("signed_extension_count") or 0)
        if blocking_count and not allow_extension_attention:
            raise CommandError(
                f"扩展诊断存在 {blocking_count} 个阻断项，请先处理；如需继续请传 --allow-extension-attention"
            )
        if pending_migration_summary and not allow_extension_attention:
            raise CommandError(
                "扩展迁移摘要未同步: "
                f"{pending_migration_summary}；请先执行 python manage.py migrate_extensions --all，"
                "如需继续请传 --allow-extension-attention"
            )
        if extension_report:
            self._write_extension_report(extension_report, inspection_payload)
        if not skip_frontend_platform_check:
            self._run_frontend_platform_check(base_dir)

        current_version = version_file.read_text(encoding="utf-8").strip()
        validate_semver(current_version, field_name="VERSION")

        if not dry_run:
            version_file.write_text(f"{resolved_version}\n", encoding="utf-8")
            update_frontend_versions(base_dir, resolved_version)

        try:
            state = self._resolve_release_version_state(base_dir, resolved_version, dry_run=dry_run)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        if tag and state.version != version_from_tag(tag):
            raise CommandError("VERSION 与 Git tag 不一致")

        self.stdout.write(self.style.SUCCESS("[OK] 版本文件一致性检查通过"))
        self.stdout.write(f"- VERSION: {state.version}")
        self.stdout.write(f"- frontend/package.json: {state.frontend_version}")
        self.stdout.write(f"- 扩展阻断项: {blocking_count}")
        self.stdout.write(f"- 扩展告警项: {warning_count}")
        self.stdout.write(f"- 扩展关注项: {attention_count}")
        self.stdout.write(f"- 扩展交付资源: {asset_count}")
        self.stdout.write(f"- 含前端交付扩展: {frontend_bundle_count}")
        self.stdout.write(f"- 含迁移交付扩展: {migration_bundle_count}")
        self.stdout.write(f"- 含语言资源扩展: {locale_bundle_count}")
        self.stdout.write(f"- 已签名扩展: {signed_extension_count}")
        if extension_report:
            self.stdout.write(f"- 扩展报告: {extension_report}")
        if contract_baseline:
            self.stdout.write(f"- 扩展契约基线: {contract_baseline}")
        if tag:
            self.stdout.write(f"- Git tag: {tag}")
        if dry_run:
            self.stdout.write(self.style.SUCCESS("[DRY-RUN] 未写入文件"))
        else:
            self.stdout.write(self.style.SUCCESS("[OK] 已同步 VERSION 与前端版本号"))

    def _ensure_clean_git_state(self) -> None:
        result = run_git_command(settings.BASE_DIR, "status", "--short")
        output = result.stdout.strip()
        if output:
            raise CommandError("Git 工作区不干净，请先提交或 stash 改动；如需跳过请传 --allow-dirty")

    def _inspect_extensions(self) -> dict:
        from io import StringIO

        stdout = StringIO()
        call_command(
            "inspect_extensions",
            "--format",
            "json",
            "--fail-on-runtime-service-fallback",
            stdout=stdout,
        )
        return json.loads(stdout.getvalue())

    def _release_extensions_path(self, base_dir: Path) -> Path:
        workspace_root = str(getattr(settings, "BIAS_EXTENSION_WORKSPACE_ROOT", "") or "").strip()
        if workspace_root:
            return Path(workspace_root) / "extensions"
        return base_dir / "extensions"

    def _resolve_release_version_state(self, base_dir: Path, resolved_version: str, *, dry_run: bool):
        if not dry_run:
            return ensure_release_versions_aligned(base_dir)
        from bias_core.release import load_release_version_state

        state = load_release_version_state(base_dir)
        validate_semver(resolved_version, field_name="目标版本")
        return type(state)(version=resolved_version, frontend_version=resolved_version)

    def _run_frontend_platform_check(self, base_dir: Path) -> None:
        from bias_core.release import get_frontend_package_json_path

        package_json_path = get_frontend_package_json_path(base_dir)
        if not package_json_path.exists():
            return
        package = json.loads(package_json_path.read_text(encoding="utf-8"))
        scripts = package.get("scripts") if isinstance(package, dict) else {}
        if not isinstance(scripts, dict) or "check:platform" not in scripts:
            return
        npm_executable = shutil.which("npm") or shutil.which("npm.cmd")
        if not npm_executable:
            raise CommandError("无法执行前端平台检查：未找到 npm")
        try:
            subprocess.run(
                [npm_executable, "run", "check:platform"],
                cwd=str(package_json_path.parent),
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise CommandError("前端平台检查失败：npm run check:platform") from exc

    def _write_extension_report(self, output_path: str, payload: dict) -> None:
        report_path = Path(output_path)
        if not report_path.is_absolute():
            report_path = settings.BASE_DIR / report_path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _default_contract_baseline_path(self, base_dir: Path) -> str:
        path = base_dir / DEFAULT_EXTENSION_CONTRACT_BASELINE
        return str(path) if path.exists() else ""

    def _validate_extension_contract_snapshots(self, payload: dict) -> None:
        extensions = payload.get("extensions")
        if not isinstance(extensions, list) or not extensions:
            raise CommandError("扩展诊断快照缺少扩展契约数据")

        required_sections = {
            "admin",
            "backend",
            "events",
            "forum",
            "frontend",
            "lifecycle",
            "models",
            "presentation",
            "resources",
            "runtime",
            "search",
            "settings",
            "summary",
        }
        missing = []
        for extension in extensions:
            extension_id = str(extension.get("id") or "").strip() or "<unknown>"
            snapshot = extension.get("contract_snapshot")
            if not isinstance(snapshot, dict):
                missing.append(f"{extension_id}: contract_snapshot")
                continue
            if int(snapshot.get("schema_version") or 0) < 1:
                missing.append(f"{extension_id}: contract_snapshot.schema_version")
            if str(snapshot.get("extension_id") or "").strip() != extension_id:
                missing.append(f"{extension_id}: contract_snapshot.extension_id")
            for section in sorted(required_sections):
                if section not in snapshot:
                    missing.append(f"{extension_id}: contract_snapshot.{section}")

        if missing:
            detail = "；".join(missing[:10])
            suffix = f" 等 {len(missing)} 项" if len(missing) > 10 else ""
            raise CommandError(f"扩展契约快照不完整: {detail}{suffix}")

    def _build_pending_extension_migration_summary(self, payload: dict) -> str:
        pending = []
        for extension in payload.get("extensions") or ():
            if not isinstance(extension, dict):
                continue
            extension_id = str(extension.get("id") or "").strip()
            migration_plan = extension.get("migration_plan") or {}
            if not isinstance(migration_plan, dict):
                continue
            pending_files = [
                str(item or "").strip()
                for item in migration_plan.get("pending_files") or ()
                if str(item or "").strip()
            ]
            if not extension_id or not pending_files:
                continue
            pending.append(f"{extension_id}({len(pending_files)})")
        return ", ".join(pending[:10]) + (f" 等 {len(pending)} 个扩展" if len(pending) > 10 else "")

    def _validate_extension_contract_baseline(self, payload: dict, baseline_path: str) -> None:
        baseline = self._read_contract_baseline(baseline_path)
        baseline_snapshots = _extract_contract_snapshots(baseline)
        current_snapshots = _extract_contract_snapshots(payload)
        if not baseline_snapshots:
            raise CommandError("扩展契约基线缺少 contract_snapshot 数据")

        issues = []
        for extension_id, baseline_snapshot in sorted(baseline_snapshots.items()):
            current_snapshot = current_snapshots.get(extension_id)
            if current_snapshot is None:
                issues.append(f"{extension_id}: 扩展已从当前快照中移除")
                continue
            issues.extend(_compare_contract_snapshot(extension_id, baseline_snapshot, current_snapshot))

        if issues:
            detail = "；".join(issues[:10])
            suffix = f" 等 {len(issues)} 项" if len(issues) > 10 else ""
            raise CommandError(f"扩展契约发生破坏性变化: {detail}{suffix}")

    def _read_contract_baseline(self, baseline_path: str) -> dict:
        path = Path(baseline_path)
        if not path.is_absolute():
            path = settings.BASE_DIR / path
        if not path.exists():
            raise CommandError(f"扩展契约基线不存在: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"扩展契约基线不是有效 JSON: {path}") from exc
        if not isinstance(payload, dict):
            raise CommandError("扩展契约基线格式无效")
        return payload


def _extract_contract_snapshots(payload: dict) -> dict[str, dict]:
    snapshots = payload.get("contract_snapshots")
    if isinstance(snapshots, dict):
        return {
            str(extension_id): snapshot
            for extension_id, snapshot in snapshots.items()
            if isinstance(snapshot, dict)
        }

    output = {}
    for extension in payload.get("extensions") or ():
        if not isinstance(extension, dict):
            continue
        extension_id = str(extension.get("id") or "").strip()
        snapshot = extension.get("contract_snapshot")
        if extension_id and isinstance(snapshot, dict):
            output[extension_id] = snapshot
    return output


def _compare_contract_snapshot(extension_id: str, baseline: dict, current: dict) -> list[str]:
    issues = []
    if int(current.get("schema_version") or 0) < int(baseline.get("schema_version") or 0):
        issues.append(f"{extension_id}: schema_version 降级")

    for path in _CONTRACT_SCALAR_PATHS:
        baseline_value = _get_path(baseline, path)
        if baseline_value in (None, ""):
            continue
        current_value = _get_path(current, path)
        if current_value != baseline_value:
            issues.append(f"{extension_id}: contract_snapshot.{'.'.join(path)} 从 {baseline_value!r} 变为 {current_value!r}")

    for path, key_fields, value_fields in _CONTRACT_OBJECT_LIST_PATHS:
        baseline_items = _index_contract_items(_get_path(baseline, path), key_fields)
        current_items = _index_contract_items(_get_path(current, path), key_fields)
        for key, baseline_item in sorted(baseline_items.items()):
            current_item = current_items.get(key)
            if current_item is None:
                issues.append(f"{extension_id}: contract_snapshot.{'.'.join(path)} 移除 {key}")
                continue
            for field in value_fields:
                baseline_value = baseline_item.get(field)
                if baseline_value in (None, ""):
                    continue
                current_value = current_item.get(field)
                if current_value != baseline_value:
                    issues.append(f"{extension_id}: contract_snapshot.{'.'.join(path)}[{key}].{field} 从 {baseline_value!r} 变为 {current_value!r}")

    for path in _CONTRACT_STRING_LIST_PATHS:
        baseline_values = _contract_string_set(_get_path(baseline, path))
        current_values = _contract_string_set(_get_path(current, path))
        for value in sorted(baseline_values - current_values):
            issues.append(f"{extension_id}: contract_snapshot.{'.'.join(path)} 移除 {value}")

    return issues


def _get_path(payload: dict, path: tuple[str, ...]):
    value = payload
    for part in path:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _index_contract_items(items, key_fields: tuple[str, ...]) -> dict[str, dict]:
    output = {}
    for item in items or ():
        if not isinstance(item, dict):
            continue
        key = "|".join(str(item.get(field) or "").strip() for field in key_fields)
        if key.strip("|"):
            output[key] = item
    return output


def _contract_string_set(items) -> set[str]:
    return {str(item or "").strip() for item in items or () if str(item or "").strip()}


_CONTRACT_SCALAR_PATHS = (
    ("backend", "entry"),
    ("backend", "django_app_config"),
    ("backend", "django_app_label"),
    ("frontend", "admin_entry"),
    ("frontend", "forum_entry"),
)

_CONTRACT_STRING_LIST_PATHS = (
    ("dependencies",),
    ("conflicts",),
    ("provides",),
    ("frontend", "settings_pages"),
    ("frontend", "permissions_pages"),
    ("frontend", "operations_pages"),
    ("settings", "frontend_cache_keys"),
    ("settings", "forum_settings_keys"),
    ("runtime", "service_providers"),
    ("presentation", "frontend_assets", "css"),
    ("presentation", "frontend_assets", "js_directories"),
    ("presentation", "formatter_pipeline"),
)

_CONTRACT_OBJECT_LIST_PATHS = (
    (("frontend", "routes"), ("frontend", "name"), ("path", "component")),
    (("settings", "fields"), ("key",), ("type", "required")),
    (("settings", "defaults"), ("key",), ()),
    (("settings", "reset_rules"), ("key",), ()),
    (("settings", "theme_variables"), ("name", "key"), ()),
    (("settings", "forum_serializations"), ("forum_key", "setting_key"), ()),
    (("admin", "pages"), ("path",), ("module_id",)),
    (("admin", "permission_modules"), ("module_id",), ()),
    (("forum", "permissions"), ("code",), ("module_id",)),
    (("forum", "notification_types"), ("code",), ("module_id",)),
    (("forum", "user_preferences"), ("key",), ("module_id",)),
    (("forum", "language_packs"), ("code",), ("module_id",)),
    (("forum", "post_types"), ("code",), ("module_id",)),
    (("forum", "search_filters"), ("target", "code"), ("syntax", "module_id")),
    (("forum", "discussion_sorts"), ("code",), ("module_id",)),
    (("forum", "discussion_list_filters"), ("code",), ("route_path", "module_id")),
    (("resources", "definitions"), ("resource",), ("module_id",)),
    (("resources", "fields"), ("resource", "field"), ("module_id",)),
    (("resources", "relationships"), ("resource", "relationship"), ("module_id", "resource_type")),
    (("resources", "endpoints"), ("resource", "endpoint"), ("path", "module_id")),
    (("resources", "sorts"), ("resource", "sort"), ("module_id",)),
    (("resources", "filters"), ("resource", "filter"), ("module_id",)),
    (("models", "definitions"), ("model", "kind", "key"), ()),
    (("models", "owned"), ("module_id", "model"), ("app_label", "target_app_label")),
    (("models", "relations"), ("model", "name"), ("relation_type", "related_model")),
    (("models", "visibility"), ("model", "ability"), ()),
    (("search", "drivers"), ("target",), ("driver",)),
    (("events", "listeners"), ("event", "listener"), ("module_id",)),
    (("events", "realtime_broadcasts"), ("event_name", "event_type"), ()),
    (("events", "post_lifecycle"), ("key",), ("module_id",)),
    (("runtime", "validators"), ("target", "key"), ("module_id",)),
    (("runtime", "mailers"), ("key",), ("module_id",)),
    (("runtime", "error_handlers"), ("key",), ("module_id",)),
    (("runtime", "auth_handlers"), ("key",), ("module_id",)),
    (("runtime", "csrf_handlers"), ("key",), ("module_id",)),
    (("runtime", "filesystem_drivers"), ("key",), ("module_id",)),
    (("runtime", "console_commands"), ("key",), ("module_id",)),
    (("runtime", "session_handlers"), ("key",), ("module_id",)),
    (("runtime", "theme_handlers"), ("key",), ("module_id",)),
    (("runtime", "throttle_api_handlers"), ("key",), ("module_id",)),
    (("runtime", "user_handlers"), ("key",), ("module_id",)),
    (("runtime", "signal_handlers"), ("dispatch_uid",), ("module_id",)),
    (("runtime", "websocket_routes"), ("name",), ("path", "module_id")),
    (("runtime", "middleware_mounts"), ("target",), ()),
    (("runtime", "policy_mounts"), ("key", "model"), ()),
    (("runtime", "route_mounts"), ("prefix",), ("module_id",)),
    (("runtime", "facades"), ("name",), ("domain", "provider_extension", "stability", "missing_service")),
    (
        ("runtime", "service_contracts"),
        ("service_key",),
        ("provider_extension", "required_methods", "required_values", "optional_methods", "callable_service", "source"),
    ),
    (("presentation", "view_namespaces"), ("namespace",), ("hints", "module_id", "prepend")),
    (("presentation", "formatter_callbacks"), ("phase", "callback", "module_id"), ()),
)

