from __future__ import annotations

from bias_core.resources import dispatcher as _dispatcher

ResourceEndpointContext = _dispatcher.ResourceEndpointContext
_default_get_runtime_resource_registry = _dispatcher.get_runtime_resource_registry


def __getattr__(name):
    return getattr(_dispatcher, name)


def dispatch_resource_endpoint(*args, **kwargs):
    original = _dispatcher.get_runtime_resource_registry
    _dispatcher.get_runtime_resource_registry = get_runtime_resource_registry
    try:
        return _dispatcher.dispatch_resource_endpoint(*args, **kwargs)
    finally:
        _dispatcher.get_runtime_resource_registry = original


def get_runtime_resource_registry():
    return _default_get_runtime_resource_registry()
