from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
import tomllib

from django.conf import settings
from django.core.management import BaseCommand, CommandError, call_command
from django.core.management.base import CommandParser

from bias_core.extensions.exceptions import ExtensionManifestError
from bias_core.extensions.manifest import ExtensionManifestLoader
from bias_core.extensions.runtime_service_contracts import (
    inspect_runtime_service_contract_sources,
    inspect_runtime_service_contracts,
    snapshot_runtime_service_contracts,
)
from bias_core.testing import build_extension_test_host


EXPECTED_TEST_SETTINGS = "bias_core.extension_test_settings"
SITE_HOST_DIRECTORY_NAMES = {"bias", "bias_site", "site"}


def resolve_command_workspace_root(extensions_path: Path) -> Path | None:
    if extensions_path.name != "extensions":
        return None
    if extensions_path.parent.name in SITE_HOST_DIRECTORY_NAMES:
        return extensions_path.parent.parent
    return extensions_path.parent


class Command(BaseCommand):
    help = "运行扩展 workspace 解耦门禁，覆盖 import 边界、runtime service 契约和测试配置。"
    requires_system_checks = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--extensions-path",
            help="扩展目录路径，默认使用 BASE_DIR/extensions；拆分仓库会自动扫描同级 bias-ext-* 目录",
        )
        parser.add_argument(
            "--internal",
            action="store_true",
            help="以内置扩展维护模式审计 import 边界，允许扩展测试/后端导入 bias_core 内部模块。",
        )
        parser.add_argument(
            "--include-tests",
            action="store_true",
            help="同时审计扩展测试代码 import 边界。",
        )
        parser.add_argument(
            "--skip-inspect-extensions",
            action="store_true",
            help="跳过依赖数据库/运行时引导的 inspect_extensions 检查，只做静态门禁。",
        )
        parser.add_argument(
            "--format",
            choices=("text", "json"),
            default="text",
            help="输出格式，默认 text，可选 json 便于 CI 消费。",
        )

    def handle(self, *args, **options):
        extensions_path = Path(options.get("extensions_path") or (Path(settings.BASE_DIR) / "extensions"))
        internal = bool(options.get("internal"))
        include_tests = bool(options.get("include_tests"))
        skip_inspect_extensions = bool(options.get("skip_inspect_extensions"))
        output_format = str(options.get("format") or "text").strip() or "text"

        payload = {
            "extensions_path": str(extensions_path),
            "internal": internal,
            "include_tests": include_tests,
            "checks": {},
            "issues": [],
            "summary": {
                "ok": True,
                "manifest_count": 0,
                "error_count": 0,
                "warning_count": 0,
            },
        }

        manifests = self._discover_manifests(extensions_path)
        payload["summary"]["manifest_count"] = len(manifests)
        payload["checks"]["pyproject_test_settings"] = self._check_pyproject_test_settings(manifests)
        payload["checks"]["import_boundaries"] = self._run_import_boundary_check(
            extensions_path,
            internal=internal,
            include_tests=include_tests,
        )
        if not skip_inspect_extensions:
            payload["checks"]["runtime_service_contracts"] = self._run_runtime_service_contract_check(manifests)
            payload["checks"]["foundation_boundaries"] = self._run_foundation_boundary_check(manifests)
        else:
            payload["checks"]["runtime_service_contracts"] = {
                "ok": True,
                "skipped": True,
                "issues": [],
            }
            payload["checks"]["foundation_boundaries"] = {
                "ok": True,
                "skipped": True,
                "issues": [],
            }

        issues = []
        if not manifests:
            issues.append({
                "level": "error",
                "code": "no_extensions_discovered",
                "message": "扩展 workspace 门禁未发现任何扩展。",
            })
        for check_name, check_payload in payload["checks"].items():
            for issue in check_payload.get("issues") or ():
                issues.append({
                    "check": check_name,
                    **issue,
                })

        payload["issues"] = issues
        payload["summary"]["error_count"] = sum(1 for issue in issues if issue.get("level") == "error")
        payload["summary"]["warning_count"] = sum(1 for issue in issues if issue.get("level") == "warning")
        payload["summary"]["ok"] = payload["summary"]["error_count"] == 0

        if output_format == "json":
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(f"已检查扩展 workspace: {extensions_path}")
            for check_name, check_payload in payload["checks"].items():
                status = "SKIP" if check_payload.get("skipped") else ("OK" if check_payload.get("ok") else "FAIL")
                self.stdout.write(f"- {check_name}: {status}")
            for issue in issues:
                prefix = "[ERROR]" if issue.get("level") == "error" else "[WARN]"
                self.stdout.write(f"{prefix} {issue.get('check', '-')} {issue.get('code')}: {issue.get('message')}")
            if payload["summary"]["ok"]:
                self.stdout.write(self.style.SUCCESS("[OK] 扩展 workspace 门禁通过"))

        if not payload["summary"]["ok"]:
            raise CommandError(f"扩展 workspace 门禁失败，共 {payload['summary']['error_count']} 个错误")

    def _discover_manifests(self, extensions_path: Path):
        include_workspace = extensions_path.name == "extensions"
        loader = ExtensionManifestLoader(
            extensions_path,
            include_workspace=include_workspace,
            workspace_root=resolve_command_workspace_root(extensions_path),
            include_distributions=False,
        )
        try:
            return loader.discover_manifests()
        except ExtensionManifestError as exc:
            raise CommandError(str(exc)) from exc

    def _check_pyproject_test_settings(self, manifests) -> dict:
        issues = []
        checked = []
        for manifest in manifests:
            manifest_path = Path(manifest.path or "")
            pyproject_path = manifest_path / "pyproject.toml"
            checked.append({
                "extension_id": manifest.id,
                "pyproject": str(pyproject_path),
            })
            if not pyproject_path.exists():
                issues.append(_issue(
                    "missing_pyproject",
                    f"{manifest.id} 缺少 pyproject.toml，无法声明共享扩展测试配置。",
                    extension_id=manifest.id,
                ))
                continue
            try:
                pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError) as exc:
                issues.append(_issue(
                    "invalid_pyproject",
                    f"{manifest.id} 的 pyproject.toml 无法解析: {exc}",
                    extension_id=manifest.id,
                ))
                continue
            configured = (
                pyproject.get("tool", {})
                .get("pytest", {})
                .get("ini_options", {})
                .get("DJANGO_SETTINGS_MODULE")
            )
            if configured != EXPECTED_TEST_SETTINGS:
                issues.append(_issue(
                    "missing_shared_test_settings",
                    (
                        f"{manifest.id} 必须在 pyproject.toml 配置 "
                        f'DJANGO_SETTINGS_MODULE = "{EXPECTED_TEST_SETTINGS}"'
                    ),
                    extension_id=manifest.id,
                ))
        return {
            "ok": not issues,
            "expected_settings_module": EXPECTED_TEST_SETTINGS,
            "checked_count": len(checked),
            "checked": checked,
            "issues": issues,
        }

    def _run_import_boundary_check(self, extensions_path: Path, *, internal: bool, include_tests: bool) -> dict:
        stdout = StringIO()
        args = [
            "inspect_extension_imports",
            "--extensions-path",
            str(extensions_path),
            "--require-extensions",
            "--fail-on-warnings",
            "--check-runtime-facades",
            "--format",
            "json",
        ]
        if internal:
            args.append("--internal")
        if include_tests:
            args.append("--include-tests")
        try:
            call_command(*args, stdout=stdout)
        except CommandError as exc:
            payload = _load_json_stdout(stdout)
            return {
                "ok": False,
                "error": str(exc),
                "issues": _issues_from_import_payload(payload),
                "payload": payload,
            }
        payload = _load_json_stdout(stdout)
        ok = bool((payload.get("summary") or {}).get("ok"))
        return {
            "ok": ok,
            "issues": [] if ok else _issues_from_import_payload(payload),
            "payload": payload,
        }

    def _run_runtime_service_contract_check(self, manifests) -> dict:
        try:
            extension_ids = tuple(sorted(str(manifest.id or "").strip() for manifest in manifests if manifest.id))
            host = build_extension_test_host(*extension_ids)
            contract_issues = inspect_runtime_service_contracts(host)
            source_warnings = inspect_runtime_service_contract_sources(host)
            snapshot = snapshot_runtime_service_contracts(host=host)
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "issues": [_issue("runtime_service_contract_failed", str(exc))],
            }
        issues = [
            {
                "level": "error",
                "code": item.get("code") or "runtime_service_contract_issue",
                "extension_id": item.get("provider_extension") or "",
                "message": json.dumps(item, ensure_ascii=False, sort_keys=True),
            }
            for item in contract_issues
        ]
        issues.extend(
            {
                "level": "error" if item.get("code") == "runtime_service_contract_uses_core_fallback" else "warning",
                "code": item.get("code") or "runtime_service_contract_warning",
                "extension_id": item.get("provider_extension") or "",
                "message": json.dumps(item, ensure_ascii=False, sort_keys=True),
            }
            for item in source_warnings
        )
        return {
            "ok": not any(issue.get("level") == "error" for issue in issues),
            "contract_count": len(snapshot),
            "checked_extension_count": len(extension_ids),
            "issues": issues,
            "contracts": snapshot,
        }

    def _run_foundation_boundary_check(self, manifests) -> dict:
        by_id = {str(manifest.id or "").strip(): manifest for manifest in manifests}
        issues = []
        for extension_id in ("content", "users"):
            manifest = by_id.get(extension_id)
            if manifest is None:
                issues.append(_issue(
                    "missing_foundation_extension",
                    f"{extension_id} foundation 扩展必须存在。",
                    extension_id=extension_id,
                ))
                continue
            extra = dict(getattr(manifest, "extra", {}) or {})
            for field in ("auto_install", "auto_enable", "protected"):
                if extra.get(field) is not True:
                    issues.append(_issue(
                        "foundation_not_protected",
                        f"{extension_id} foundation 扩展 extra.{field} 必须为 true。",
                        extension_id=extension_id,
                    ))

        required_ids = tuple(
            extension_id
            for extension_id in ("content", "users", "discussions", "posts")
            if extension_id in by_id
        )
        owned_by_extension: dict[str, list[str]] = {}
        content_owned_labels: set[str] = set()
        try:
            host = build_extension_test_host(*required_ids)
            for extension_id in required_ids:
                owned = host.models.get_owned_models(extension_id=extension_id)
                owned_labels = sorted(_model_label(definition.model) for definition in owned)
                owned_by_extension[extension_id] = owned_labels
                if extension_id == "content":
                    content_owned_labels.update(owned_labels)
        except Exception as exc:
            issues.append(_issue("foundation_model_ownership_failed", str(exc), extension_id="content"))
            owned_by_extension = {}

        required_content_labels = {"content.Discussion", "content.DiscussionUser", "content.Post"}
        missing_labels = sorted(required_content_labels - content_owned_labels)
        if missing_labels:
            issues.append(_issue(
                "content_missing_foundation_model_owner",
                f"content 必须拥有基础内容模型: {', '.join(missing_labels)}。",
                extension_id="content",
            ))
        for extension_id in ("discussions", "posts"):
            leaked = sorted(required_content_labels & set(owned_by_extension.get(extension_id, ())))
            if leaked:
                issues.append(_issue(
                    "feature_extension_owns_foundation_model",
                    f"{extension_id} 只能作为 UI/API wrapper，不能拥有 foundation 模型: {', '.join(leaked)}。",
                    extension_id=extension_id,
                ))

        return {
            "ok": not any(issue.get("level") == "error" for issue in issues),
            "required_foundations": ["content", "users"],
            "foundation_model_labels": sorted(required_content_labels),
            "owned_by_extension": owned_by_extension,
            "issues": issues,
        }


def _load_json_stdout(stdout: StringIO) -> dict:
    value = stdout.getvalue().strip()
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {
            "raw": value,
        }


def _issues_from_import_payload(payload: dict) -> list[dict]:
    issues = []
    for issue in payload.get("issues") or ():
        if not isinstance(issue, dict):
            continue
        issues.append({
            "level": issue.get("level") or "error",
            "code": issue.get("code") or "import_boundary_issue",
            "extension_id": issue.get("extension_id") or "",
            "message": issue.get("message") or "",
        })
    if not issues and payload:
        issues.append(_issue("import_boundary_failed", "扩展 import 边界检查失败。"))
    return issues


def _issue(code: str, message: str, *, extension_id: str = "", level: str = "error") -> dict:
    return {
        "level": level,
        "code": code,
        "extension_id": extension_id,
        "message": message,
    }


def _model_label(model) -> str:
    meta = getattr(model, "_meta", None)
    label = str(getattr(meta, "label", "") or getattr(meta, "label_lower", "") or "").strip()
    if label:
        return label
    module = str(getattr(model, "__module__", "") or "").strip()
    name = str(getattr(model, "__name__", "") or getattr(model, "__qualname__", "") or "").strip()
    return f"{module}.{name}" if module and name else (name or str(model))
