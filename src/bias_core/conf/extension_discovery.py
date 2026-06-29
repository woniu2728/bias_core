from __future__ import annotations
import json
import sys
from importlib import metadata
from pathlib import Path
from typing import Any


def discover_extension_django_configuration(base_dir=None) -> dict[str, Any]:
    records = discover_extension_django_app_records(base_dir)
    migration_modules = {
        item["app_label"]: item["migration_module"]
        for item in records
        if item.get("migration_module")
    }
    return {
        "installed_apps": list(dict.fromkeys(item["app_config"] for item in records)),
        "migration_modules": migration_modules,
        "auth_user_model": _select_auth_user_model(records),
    }


def discover_extension_django_app_records(base_dir=None) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    records.extend(_discover_workspace_extension_django_app_records(base_dir))
    records.extend(_discover_distribution_extension_django_app_records())
    return _dedupe_django_app_records(records)


def discover_installed_extension_django_apps(base_dir=None):
    return discover_extension_django_configuration(base_dir)["installed_apps"]


def discover_extension_migration_modules(base_dir=None):
    return discover_extension_django_configuration(base_dir)["migration_modules"]


def discover_auth_user_model(base_dir=None, default: str = "auth.User") -> str:
    return _select_auth_user_model(discover_extension_django_app_records(base_dir), default=default)


def _discover_workspace_extension_django_app_records(base_dir=None) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for manifest_path in _iter_extension_manifest_paths(base_dir):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        _ensure_workspace_package_import_path(manifest_path.parent)
        record = _build_extension_django_app_record(payload, manifest_path)
        if record is not None:
            records.append(record)
    return records


def _ensure_workspace_package_import_path(package_root: Path) -> None:
    try:
        resolved = str(package_root.resolve())
    except OSError:
        resolved = str(package_root)
    if resolved and resolved not in sys.path:
        sys.path.insert(0, resolved)


def _discover_distribution_extension_django_app_records() -> list[dict[str, str]]:
    try:
        from django.conf import settings

        include_distributions = bool(getattr(settings, "BIAS_EXTENSION_PACKAGE_DISCOVERY", True))
    except Exception:
        include_distributions = True
    if not include_distributions:
        return []

    records: list[dict[str, str]] = []
    for distribution in sorted(metadata.distributions(), key=lambda item: (item.metadata.get("Name") or "").lower()):
        extension_files = [
            file
            for file in (distribution.files or ())
            if _is_distribution_manifest_file(str(file).replace("\\", "/"))
        ]
        for file in extension_files:
            manifest_path = Path(str(distribution.locate_file(file)))
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            record = _build_extension_django_app_record(payload, manifest_path)
            if record is not None:
                records.append(record)
    return records


def _build_extension_django_app_record(payload: dict[str, Any], manifest_path: Path) -> dict[str, str] | None:
    extension_id = str(payload.get("id") or manifest_path.parent.name).strip()
    django_payload = payload.get("django") if isinstance(payload.get("django"), dict) else {}
    app_config = str(payload.get("django_app_config") or django_payload.get("app_config") or "").strip()
    if not app_config:
        return None
    app_label = str(
        payload.get("django_app_label")
        or django_payload.get("app_label")
        or extension_id.replace("-", "_")
    ).strip()
    migration_module = str(
        payload.get("django_migration_module")
        or django_payload.get("migration_module")
        or ""
    ).strip()
    if not migration_module:
        module_prefix = app_config.rsplit(".apps.", 1)[0]
        if module_prefix != app_config:
            migration_module = f"{module_prefix}.django_migrations"
    auth_user_model = str(
        payload.get("auth_user_model")
        or django_payload.get("auth_user_model")
        or ""
    ).strip()
    if not auth_user_model and app_label == "users" and app_config.endswith(".UsersExtensionConfig"):
        auth_user_model = "users.User"
    record = {
        "app_config": app_config,
        "app_label": app_label,
        "migration_module": migration_module,
    }
    if auth_user_model:
        record["auth_user_model"] = auth_user_model
    return record


def _dedupe_django_app_records(records: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen_app_configs: set[str] = set()
    for record in records:
        app_config = record.get("app_config") or ""
        if not app_config or app_config in seen_app_configs:
            continue
        seen_app_configs.add(app_config)
        deduped.append(record)
    return deduped


def _select_auth_user_model(records: list[dict[str, str]], default: str = "auth.User") -> str:
    candidates = list(dict.fromkeys(
        str(item.get("auth_user_model") or "").strip()
        for item in records
        if str(item.get("auth_user_model") or "").strip()
    ))
    if len(candidates) > 1:
        raise RuntimeError(f"多个扩展声明了不同的 AUTH_USER_MODEL: {', '.join(candidates)}")
    return candidates[0] if candidates else default


def _iter_extension_manifest_paths(base_dir=None):
    roots = []
    base_path = Path(base_dir) if base_dir is not None else None
    if base_path is not None:
        roots.append(base_path / "extensions")
        roots.append(base_path)
        try:
            from django.conf import settings

            configured = str(getattr(settings, "BIAS_EXTENSION_WORKSPACE_ROOT", "") or "").strip()
            if configured:
                configured_path = Path(configured).resolve()
                try:
                    resolved_base = base_path.resolve()
                except OSError:
                    resolved_base = base_path
                if resolved_base == configured_path or resolved_base.parent == configured_path:
                    roots.append(configured_path)
        except Exception:
            pass
    else:
        try:
            from django.conf import settings

            configured = str(getattr(settings, "BIAS_EXTENSION_WORKSPACE_ROOT", "") or "").strip()
            if configured:
                roots.append(Path(configured))
            else:
                site_base = Path(getattr(settings, "BASE_DIR", ""))
                if site_base:
                    roots.append(site_base / "extensions")
                    roots.append(site_base)
        except Exception:
            pass

    seen = set()
    for root in roots:
        if root is None or not root.exists():
            continue
        patterns = ("bias-ext-*/extension.json", "*/extension.json")
        for pattern in patterns:
            for manifest_path in sorted(root.glob(pattern)):
                key = str(manifest_path.resolve())
                if key in seen:
                    continue
                seen.add(key)
                yield manifest_path


def _is_distribution_manifest_file(filename: str) -> bool:
    return (
        filename == "bias_extension.json"
        or filename.endswith("/bias_extension.json")
        or filename == "bias_extension/extension.json"
        or filename.endswith("/bias_extension/extension.json")
        or (
            "/bias_extensions/" in f"/{filename}"
            and filename.endswith("/extension.json")
        )
    )
