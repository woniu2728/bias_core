from __future__ import annotations

from django.db import OperationalError, ProgrammingError

from bias_core.models import ExtensionInstallation

_NOT_CACHED = object()
_EXTENSION_STATE_OVERRIDES: dict[str, bool] | object = _NOT_CACHED


def get_extension_state_overrides() -> dict[str, bool] | None:
    global _EXTENSION_STATE_OVERRIDES
    if _EXTENSION_STATE_OVERRIDES is not _NOT_CACHED:
        return dict(_EXTENSION_STATE_OVERRIDES)
    try:
        overrides = {
            str(item["extension_id"]): bool(item["enabled"])
            for item in ExtensionInstallation.objects.filter(source="filesystem").values("extension_id", "enabled")
        }
    except (OperationalError, ProgrammingError, RuntimeError):
        return None
    _EXTENSION_STATE_OVERRIDES = overrides
    return dict(overrides)


def clear_extension_state_cache() -> None:
    global _EXTENSION_STATE_OVERRIDES
    _EXTENSION_STATE_OVERRIDES = _NOT_CACHED
