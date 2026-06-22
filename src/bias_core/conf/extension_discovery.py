from __future__ import annotations

from pathlib import Path
from typing import Any


def discover_installed_extension_django_apps(base_dir: str | Path | None = None) -> list[str]:
    try:
        from bias_core.extensions.discovery import get_extension_host

        host = get_extension_host()
        if host is None:
            return []

        discovered = []
        for ext_id, ext in host.extensions.items():
            django_config = ext.get("django", {}).get("app_config")
            if django_config:
                discovered.append(django_config)

        return discovered
    except (ImportError, AttributeError):
        return []


def discover_extension_migration_modules(base_dir: str | Path | None = None) -> dict[str, str]:
    try:
        from bias_core.extensions.discovery import get_extension_host

        host = get_extension_host()
        if host is None:
            return {}

        modules = {}
        for ext_id, ext in host.extensions.items():
            migration_module = ext.get("django", {}).get("migration_module")
            app_label = ext.get("django", {}).get("app_label")
            if migration_module and app_label:
                modules[app_label] = migration_module

        return modules
    except (ImportError, AttributeError):
        return {}
