from __future__ import annotations
import json
import sys
from importlib import metadata
from pathlib import Path
from typing import Any


def discover_installed_extension_django_apps(base_dir=None):
    discovered = []
    discovered.extend(item["app_config"] for item in _discover_workspace_extension_django_app_records(base_dir))
    discovered.extend(item["app_config"] for item in _discover_distribution_extension_django_app_records())
    return list(dict.fromkeys(discovered))


def discover_extension_migration_modules(base_dir=None):
    modules = {}
    for item in _discover_workspace_extension_django_app_records(base_dir):
        migration_module = item.get("migration_module") or ""
        if migration_module:
            modules[item["app_label"]] = migration_module
    for item in _discover_distribution_extension_django_app_records():
        migration_module = item.get("migration_module") or ""
        if migration_module and item["app_label"] not in modules:
            modules[item["app_label"]] = migration_module
    return modules


def _discover_workspace_extension_django_app_records(base_dir=None) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for manifest_path in _iter_extension_manifest_paths(base_dir):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        extension_id = str(payload.get("id") or manifest_path.parent.name).strip()
        django_payload = payload.get("django") if isinstance(payload.get("django"), dict) else {}
        app_config = str(payload.get("django_app_config") or django_payload.get("app_config") or "").strip()
        if not app_config:
            continue
        _ensure_workspace_package_import_path(manifest_path.parent)
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
        records.append({
            "app_config": app_config,
            "app_label": app_label,
            "migration_module": migration_module,
        })
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
    return {
        "app_config": app_config,
        "app_label": app_label,
        "migration_module": migration_module,
    }


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
