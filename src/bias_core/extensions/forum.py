from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORT_MODULES = {
    "AuditLog": "bias_core.models",
    "OnlineUserService": "bias_core.online_service",
    "SearchIndexService": "bias_core.search_index_service",
    "UploadFileOutSchema": "bias_core.schemas",
    "broadcast_realtime_discussion_event": "bias_core.forum_runtime",
    "can_view_realtime_discussion": "bias_core.forum_runtime",
    "detect_database_label": "bias_core.runtime_diagnostics",
    "get_forum_registry": "bias_core.forum_registry",
    "get_registry_staff_managed_admin_permission_codes": "bias_core.forum_registry",
    "iter_realtime_included_enrichers": "bias_core.forum_runtime",
    "resolve_realtime_visible_discussion_ids": "bias_core.forum_runtime",
    "sqlite_write_retry": "bias_core.db",
}

_LAZY_CALLABLE_EXPORTS = {
    "broadcast_realtime_discussion_event",
    "can_view_realtime_discussion",
    "detect_database_label",
    "get_forum_registry",
    "get_registry_staff_managed_admin_permission_codes",
    "iter_realtime_included_enrichers",
    "resolve_realtime_visible_discussion_ids",
    "sqlite_write_retry",
}

__all__ = sorted(_EXPORT_MODULES)


class _LazyForumCallable:
    def __init__(self, name: str, module_name: str) -> None:
        self.__name__ = name
        self.__qualname__ = name
        self.__module__ = __name__
        self._name = name
        self._module_name = module_name

    def __call__(self, *args, **kwargs):
        return self._resolve()(*args, **kwargs)

    def __getattr__(self, attr: str):
        return getattr(self._resolve(), attr)

    def __repr__(self) -> str:
        return f"<lazy forum callable {self._module_name}.{self._name}>"

    def _resolve(self):
        value = getattr(import_module(self._module_name), self._name)
        globals()[self._name] = value
        return value


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if name in _LAZY_CALLABLE_EXPORTS:
        value = _LazyForumCallable(name, module_name)
        globals()[name] = value
        return value
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
