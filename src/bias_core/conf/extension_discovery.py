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
    """Discover installed extensions' Django app configs via entry points."""
    try:
        exts = _get_discovered_extensions()
        return []
    except Exception:
        return []


def discover_extension_migration_modules(base_dir: str | Path | None = None) -> dict[str, str]:
    """Discover installed extensions' Django migration modules."""
    try:
        _ = _get_discovered_extensions()
        return {}
    except Exception:
        return {}
