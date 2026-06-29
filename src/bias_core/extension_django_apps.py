from __future__ import annotations

from pathlib import Path

from bias_core.conf.extension_discovery import (
    discover_auth_user_model,
    discover_extension_migration_modules,
    discover_installed_extension_django_apps,
)


def discover_extension_django_apps(base_dir: str | Path) -> list[str]:
    return discover_installed_extension_django_apps(base_dir)


def discover_extension_django_migration_modules(base_dir: str | Path) -> dict[str, str]:
    return discover_extension_migration_modules(base_dir)


def discover_extension_auth_user_model(base_dir: str | Path, default: str = "auth.User") -> str:
    return discover_auth_user_model(base_dir, default=default)


def normalize_extension_django_app_label(extension_id: str, app_label: str | None = None) -> str:
    normalized = str(app_label or "").strip()
    if normalized:
        return normalized
    return str(extension_id or "").replace("-", "_").strip()

