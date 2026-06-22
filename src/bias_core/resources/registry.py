from __future__ import annotations

from typing import Any

_registry: dict[str, Any] | None = None


def get_resource_registry() -> dict[str, Any]:
    global _registry
    if _registry is None:
        _registry = {}
    return _registry


def register_resource(resource_type: str, definition: Any) -> None:
    registry = get_resource_registry()
    registry[resource_type] = definition


def unregister_resource(resource_type: str) -> None:
    registry = get_resource_registry()
    registry.pop(resource_type, None)
