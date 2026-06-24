from __future__ import annotations
from pathlib import Path
from typing import Any


def discover_installed_extension_django_apps(base_dir=None):
    import importlib.metadata
    discovered = []
    try:
        for ep in importlib.metadata.entry_points(group="bias.extensions"):
            cn = ep.name[0].upper() + ep.name[1:] + "ExtensionConfig"
            discovered.append("bias_ext_" + ep.name + ".backend.apps." + cn)
    except Exception:
        pass
    return discovered


def discover_extension_migration_modules(base_dir=None):
    import importlib.metadata
    modules = {}
    try:
        for ep in importlib.metadata.entry_points(group="bias.extensions"):
            modules[ep.name] = "bias_ext_" + ep.name + ".backend.django_migrations"
    except Exception:
        pass
    return modules