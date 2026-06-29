from __future__ import annotations

from typing import Any

from bias_core.extensions.container import import_string
from bias_core.extensions.forum_registry_types import EventListenerDefinition


_EVENT_TYPE_ALIASES: dict[str, type] = {}


def register_event_type_alias(alias: str, event_type: Any) -> None:
    normalized = str(alias or "").strip()
    if not normalized or not isinstance(event_type, type):
        return
    _EVENT_TYPE_ALIASES[normalized] = event_type


def register_event_type_aliases(aliases: dict[str, Any] | None) -> None:
    for alias, event_type in dict(aliases or {}).items():
        register_event_type_alias(alias, event_type)


def clear_event_type_aliases() -> None:
    _EVENT_TYPE_ALIASES.clear()


def resolve_event_type(event_type: Any):
    if isinstance(event_type, str):
        alias = _EVENT_TYPE_ALIASES.get(str(event_type or "").strip())
        if alias is not None:
            return alias
        try:
            resolved = import_string(event_type)
        except Exception:
            resolved = _resolve_legacy_extension_event_type(event_type)
            if resolved is None:
                return None
        return resolved if isinstance(resolved, type) else None
    return event_type if isinstance(event_type, type) else None


def resolve_extension_event_type(event_type: Any):
    return resolve_event_type(event_type)


def _resolve_legacy_extension_event_type(event_type: str):
    raw = str(event_type or "").strip()
    prefix = "extensions."
    marker = ".backend."
    if not raw.startswith(prefix) or marker not in raw:
        return None
    extension_id, suffix = raw[len(prefix):].split(marker, 1)
    module_path = f"bias_ext_{extension_id.replace('-', '_')}.backend.{suffix}"
    try:
        return import_string(module_path)
    except Exception:
        return None


def build_forum_event_listener_definition(extension_id: str, definition) -> EventListenerDefinition:
    event_type = getattr(definition, "event_type", None)
    handler = getattr(definition, "handler", None)
    event_name = str(getattr(event_type, "__name__", "") or event_type or "").strip()
    handler_name = str(getattr(handler, "__name__", "") or handler or "").strip()
    return EventListenerDefinition(
        event=event_name,
        listener=handler_name,
        module_id=extension_id,
        description=str(getattr(definition, "description", "") or "").strip(),
    )


def build_event_bus_listener_key(extension_id: str, definition) -> tuple[str, str, str]:
    event_type = getattr(definition, "event_type", None)
    handler = getattr(definition, "handler", None)
    event_key = ":".join(
        item
        for item in (
            str(getattr(event_type, "__module__", "") or "").strip(),
            str(getattr(event_type, "__qualname__", "") or "").strip(),
        )
        if item
    ) or str(event_type)
    handler_key = ":".join(
        item
        for item in (
            str(getattr(handler, "__module__", "") or "").strip(),
            str(getattr(handler, "__qualname__", "") or "").strip(),
        )
        if item
    ) or str(handler)
    return extension_id, event_key, handler_key


def event_type_key(event_type: Any) -> str:
    return ":".join(
        item
        for item in (
            str(getattr(event_type, "__module__", "") or "").strip(),
            str(getattr(event_type, "__qualname__", "") or "").strip(),
        )
        if item
    ) or str(event_type)


def event_value_key(value: Any) -> str:
    if callable(value):
        return ":".join(
            item
            for item in (
                str(getattr(value, "__module__", "") or "").strip(),
                str(getattr(value, "__qualname__", "") or "").strip(),
            )
            if item
        ) or str(value)
    return str(value or "").strip()


def resolve_event_value(source: Any, event: Any, *, default: Any = None) -> Any:
    if source is None:
        return default
    if callable(source):
        try:
            return source(event)
        except TypeError:
            return source()
    if isinstance(source, str):
        return getattr(event, source, default)
    return source


def resolve_event_name(source: Any, event: Any) -> Any:
    if callable(source):
        try:
            return source(event)
        except TypeError:
            return source()
    return source


