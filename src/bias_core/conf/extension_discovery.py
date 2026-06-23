from __future__ import annotations

from pathlib import Path
from typing import Any


def _get_discovered_extensions() -> dict[str, Any]:
    """Scan entry points for installed extensions. Inlined here to avoid
    triggering bias_core.extensions package import during settings loading."""
    import importlib.metadata
    exts = {}
    try:
        for ep in importlib.metadata.entry_points(group="bias.extensions"):
            exts[ep.name] = {"entry_point": ep}
    except Exception:
        pass
    return exts


def discover_installed_extension_django_apps(base_dir: str | Path | None = None) -> list[str]:
    """Discover installed extensions' Django app configs via entry points.

    Each extension can declare its Django app config in one of two ways:
    1. A 'django_app_config' attribute on the loaded entry point function.
    2. A standard module path convention: bias_ext_{name}.backend.apps.{name.title()}ExtensionConfig
    """
    discovered = []
    try:
        ext_entry_points = list(importlib.metadata.entry_points(group="bias.extensions"))
        for ep in ext_entry_points:
            try:
                fn = ep.load()
                # Check if the function has a django_app_config attribute
                django_config = getattr(fn, "django_app_config", None)
                if django_config:
                    discovered.append(django_config)
                    continue
            except Exception:
                pass
            # Fallback: convention-based path
            ext_name = ep.name
            discovered.append(f"bias_ext_{ext_name}.backend.apps.{ext_name.title()}ExtensionConfig")
    except Exception:
        pass
    return discovered


def discover_extension_migration_modules(base_dir: str | Path | None = None) -> dict[str, str]:
    """Discover installed extensions' Django migration modules."""
    modules = {}
    try:
        ext_entry_points = list(importlib.metadata.entry_points(group="bias.extensions"))
        for ep in ext_entry_points:
            ext_name = ep.name
            modules[ext_name] = f"bias_ext_{ext_name}.backend.django_migrations"
    except Exception:
        pass
    return modules
