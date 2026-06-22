from __future__ import annotations

from bias_core.extensions.discovery import get_extension_host


def bootstrap_extension_host() -> None:
    """Initialize and discover all installed extensions."""
    host = get_extension_host()
    host.discover()
