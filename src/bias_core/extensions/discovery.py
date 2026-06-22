from __future__ import annotations

import importlib.metadata
from typing import Any

_extension_host = None


class ExtensionHost:
    """Minimal extension host for discovery via entry points."""

    def __init__(self):
        self.extensions: dict[str, Any] = {}
        self._discovered = False

    def discover(self) -> None:
        if self._discovered:
            return
        try:
            for ep in importlib.metadata.entry_points(group="bias.extensions"):
                try:
                    ext_fn = ep.load()
                    self.extensions[ep.name] = {"entry": ext_fn, "module": ext_fn.__module__}
                except Exception:
                    continue
        except Exception:
            pass
        self._discovered = True


_host_instance: ExtensionHost | None = None


def get_extension_host() -> ExtensionHost:
    global _host_instance
    if _host_instance is None:
        _host_instance = ExtensionHost()
        _host_instance.discover()
    return _host_instance
