from __future__ import annotations
import json
from pathlib import Path
from typing import Any


def discover_installed_extension_django_apps(base_dir=None):
    discovered = []
    discovered.extend(item["app_config"] for item in _discover_workspace_extension_django_app_records(base_dir))
    return list(dict.fromkeys(discovered))


def discover_extension_migration_modules(base_dir=None):
    modules = {}
    for item in _discover_workspace_extension_django_app_records(base_dir):
        migration_module = item.get("migration_module") or ""
        if migration_module:
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


def _iter_extension_manifest_paths(base_dir=None):
    roots = []
    base_path = Path(base_dir) if base_dir is not None else None
    if base_path is not None:
        roots.append(base_path / "extensions")
        roots.append(base_path)
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
