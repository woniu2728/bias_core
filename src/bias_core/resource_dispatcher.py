from __future__ import annotations

from bias_core.resources import dispatcher as _dispatcher

ResourceEndpointContext = _dispatcher.ResourceEndpointContext
_default_get_runtime_resource_registry = _dispatcher.get_runtime_resource_registry
get_optional_user = _dispatcher.get_optional_user
has_forum_permission = _dispatcher.has_forum_permission


def __getattr__(name):
    return getattr(_dispatcher, name)


def dispatch_resource_endpoint(*args, **kwargs):
    originals = {
        "get_runtime_resource_registry": _dispatcher.get_runtime_resource_registry,
        "get_optional_user": _dispatcher.get_optional_user,
        "has_forum_permission": _dispatcher.has_forum_permission,
    }
    _dispatcher.get_runtime_resource_registry = get_runtime_resource_registry
    _dispatcher.get_optional_user = get_optional_user
    _dispatcher.has_forum_permission = has_forum_permission
    try:
        return _dispatcher.dispatch_resource_endpoint(*args, **kwargs)
    finally:
        for name, original in originals.items():
            setattr(_dispatcher, name, original)


def get_runtime_resource_registry():
    return _default_get_runtime_resource_registry()
