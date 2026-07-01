from __future__ import annotations

from typing import Any


_RUNTIME_SERVICE_PROXIES = []


class RuntimeServiceProxy:
    """统一运行时服务代理，减少逐方法转发样板。

    用法::

        _post = RuntimeServiceProxy("posts.service")
        result = _post.get_by_id(post_id, user=user)
        model = _post.value("model", required_message="未提供帖子模型")

    等价于手写::

        service = require_extension_host_service("posts.service")
        result = runtime_service_method(service, "get_by_id")(post_id, user=user)
        model = runtime_service_value(service, "model", required_message="...")
    """

    def __init__(self, service_key: str) -> None:
        self._service_key = service_key
        self._cached_service: Any = _NOT_FOUND
        _RUNTIME_SERVICE_PROXIES.append(self)

    def _get_service(self) -> Any:
        if self._cached_service is _NOT_FOUND:
            self._cached_service = require_extension_host_service(self._service_key)
        return self._cached_service

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return runtime_service_method(self._get_service(), name)

    def method(self, name: str):
        """显式获取方法，用于需要方法对象而非调用的场景。"""
        return runtime_service_method(self._get_service(), name)

    def value(self, name: str, default: Any = None, *, required_message: str = ""):
        """获取服务提供的值/属性。"""
        return runtime_service_value(
            self._get_service(), name, default, required_message=required_message
        )

    def invalidate(self) -> None:
        """清除缓存，下次访问时重新获取服务。"""
        self._cached_service = _NOT_FOUND

    @property
    def service_key(self) -> str:
        return self._service_key


_NOT_FOUND = object()


def invalidate_runtime_service_proxies(service_key: str = "") -> None:
    normalized = str(service_key or "").strip()
    for proxy in tuple(_RUNTIME_SERVICE_PROXIES):
        if not normalized or proxy.service_key == normalized:
            proxy.invalidate()


def get_extension_host_service(key: str, default: Any = None) -> Any:
    from bias_core.extensions.bootstrap import get_extension_host

    host = get_extension_host()
    if host is None:
        return default
    return host.make(key, default)


def require_extension_host_service(key: str) -> Any:
    service = get_extension_host_service(key)
    if service is None:
        raise RuntimeError(f"扩展运行时服务未注册: {key}")
    return service


def get_runtime_service(key: str, default: Any = None) -> Any:
    """Return a registered extension runtime service."""
    return get_extension_host_service(key, default)


def require_runtime_service(key: str) -> Any:
    """Return a registered extension runtime service or raise."""
    return require_extension_host_service(key)


def get_runtime_service_value(
    service_key: str,
    name: str,
    default: Any = None,
    *,
    required_message: str = "",
) -> Any:
    """Read a value exposed by a registered runtime service."""
    return runtime_service_value(
        require_runtime_service(service_key),
        name,
        default,
        required_message=required_message,
    )


def call_runtime_service(service_key: str, method_name: str, *args, **kwargs) -> Any:
    """Call a method exposed by a registered runtime service."""
    method = runtime_service_method(require_runtime_service(service_key), method_name)
    return method(*args, **kwargs)


def get_runtime_model(service_key: str, default: Any = None, *, required_message: str = "") -> Any:
    """Read the conventional ``model`` value exposed by a runtime service."""
    return get_runtime_service_value(
        service_key,
        "model",
        default,
        required_message=required_message,
    )


def runtime_service_method(service: Any, name: str):
    if isinstance(service, dict):
        method = service.get(name)
    else:
        method = getattr(service, name, None)
    if not callable(method):
        raise RuntimeError(f"扩展运行时服务缺少方法: {name}")
    return method


def runtime_service_value(service: Any, name: str, default: Any = None, *, required_message: str = ""):
    if isinstance(service, dict):
        value = service.get(name, default)
    else:
        value = getattr(service, name, default)
    if value is None and required_message:
        raise RuntimeError(required_message)
    return value


def get_runtime_resource_registry():
    from bias_core.resource_registry import get_resource_registry

    return get_extension_host_service("resource.registry", get_resource_registry())


