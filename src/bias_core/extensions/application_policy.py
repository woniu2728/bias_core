from __future__ import annotations

from typing import TYPE_CHECKING

from bias_core.extensions.application_types import (
    ApplicationMiddlewareMount,
    ApplicationPolicyMount,
)
from bias_core.extensions.model_references import resolve_model_reference
from bias_core.extensions.types import ExtensionModelReference

if TYPE_CHECKING:
    from bias_core.extensions.application import ExtensionHost


class ApplicationMiddlewareService:
    def __init__(self, host: "ExtensionHost") -> None:
        self._host = host

    def mount(
        self,
        extension_id: str,
        target: str,
        middleware,
        *,
        order: int = 100,
    ) -> None:
        normalized_extension_id = str(extension_id or "").strip()
        if not normalized_extension_id or middleware is None:
            return

        view = self._host._get_or_create_runtime_view(normalized_extension_id)
        mount = ApplicationMiddlewareMount(
            target=str(target or "").strip() or "api",
            middleware=middleware,
            order=int(order),
        )
        view.middleware_mounts = _replace_by_key(
            view.middleware_mounts,
            mount,
            _middleware_mount_key,
        )

    def get_mounts(self, *, target: str | None = None) -> list[ApplicationMiddlewareMount]:
        mounts: list[ApplicationMiddlewareMount] = []
        for view in self._host.get_runtime_views():
            mounts.extend(view.middleware_mounts)
        if target is not None:
            mounts = [item for item in mounts if item.target == target]
        return sorted(mounts, key=lambda item: (item.target, item.order))


class ApplicationPolicyService:
    def __init__(self, host: "ExtensionHost") -> None:
        self._host = host

    def mount(self, extension_id: str, key: str, handler) -> None:
        self.mount_key(extension_id, key, handler)

    def mount_key(self, extension_id: str, key: str, handler) -> None:
        normalized_extension_id = str(extension_id or "").strip()
        normalized_key = str(key or "").strip()
        if not normalized_extension_id or not normalized_key or not callable(handler):
            return

        view = self._host._get_or_create_runtime_view(normalized_extension_id)
        mount = ApplicationPolicyMount(
            key=normalized_key,
            handler=handler,
        )
        view.policy_mounts = _replace_by_key(
            view.policy_mounts,
            mount,
            lambda item: _policy_mount_key(item, self._host),
        )

    def global_policy(self, extension_id: str, handler) -> None:
        normalized_extension_id = str(extension_id or "").strip()
        if not normalized_extension_id or not callable(handler):
            return
        view = self._host._get_or_create_runtime_view(normalized_extension_id)
        mount = ApplicationPolicyMount(
            key="",
            handler=handler,
            global_policy=True,
        )
        view.policy_mounts = _replace_by_key(
            view.policy_mounts,
            mount,
            lambda item: _policy_mount_key(item, self._host),
        )

    def model_policy(self, extension_id: str, model, handler) -> None:
        normalized_extension_id = str(extension_id or "").strip()
        if not normalized_extension_id or model is None or not callable(handler):
            return
        view = self._host._get_or_create_runtime_view(normalized_extension_id)
        mount = ApplicationPolicyMount(
            key="",
            handler=handler,
            model=model,
        )
        view.policy_mounts = _replace_by_key(
            view.policy_mounts,
            mount,
            lambda item: _policy_mount_key(item, self._host),
        )

    def query_model_policy(self, extension_id: str, model, handler) -> None:
        normalized_extension_id = str(extension_id or "").strip()
        if not normalized_extension_id or model is None or not callable(handler):
            return
        view = self._host._get_or_create_runtime_view(normalized_extension_id)
        mount = ApplicationPolicyMount(
            key="",
            handler=handler,
            model=model,
            query_policy=True,
        )
        view.policy_mounts = _replace_by_key(
            view.policy_mounts,
            mount,
            lambda item: _policy_mount_key(item, self._host),
        )

    def get_mounts(self) -> list[ApplicationPolicyMount]:
        mounts: list[ApplicationPolicyMount] = []
        for view in self._host.get_runtime_views():
            mounts.extend(view.policy_mounts)
        return mounts


def _replace_by_key(items, item, key):
    item_key = key(item)
    return tuple([
        *(current for current in items or () if key(current) != item_key),
        item,
    ])


def _middleware_mount_key(mount: ApplicationMiddlewareMount) -> tuple[str, str]:
    return (str(mount.target or "").strip() or "api", _handler_identity(mount.middleware))


def _policy_mount_key(mount: ApplicationPolicyMount, host: "ExtensionHost") -> tuple:
    if mount.global_policy:
        return ("global", _handler_identity(mount.handler))
    if mount.model is not None:
        return (
            "query_model" if mount.query_policy else "model",
            _model_identity_key(mount.model, host),
            _handler_identity(mount.handler),
        )
    return ("key", str(mount.key or "").strip(), _handler_identity(mount.handler))


def _model_identity_key(model, host: "ExtensionHost") -> tuple:
    if isinstance(model, ExtensionModelReference):
        return (
            "reference",
            str(model.service_key or "").strip(),
            str(model.attribute or "model").strip() or "model",
        )
    resolved_model = resolve_model_reference(model, host)
    target = resolved_model if resolved_model is not None else model
    if isinstance(target, type):
        return (
            "class",
            getattr(target, "__module__", ""),
            getattr(target, "__qualname__", getattr(target, "__name__", "")),
        )
    if isinstance(target, (str, int, float, bool, tuple)):
        return ("value", target)
    return ("object", id(target))


def _handler_identity(handler) -> str:
    label = str(getattr(handler, "__bias_callback_label__", "") or "").strip()
    if label:
        return label
    module = str(getattr(handler, "__module__", "") or "").strip()
    qualname = str(getattr(handler, "__qualname__", "") or getattr(handler, "__name__", "") or "").strip()
    if module or qualname:
        name = ".".join(item for item in (module, qualname) if item)
        if "<lambda>" not in qualname:
            return name
    code = getattr(handler, "__code__", None)
    if code is not None:
        location = ":".join((
            str(getattr(code, "co_filename", "") or "").strip(),
            str(getattr(code, "co_firstlineno", "") or "").strip(),
        )).strip(":")
        if location:
            return f"{name or '<callable>'}@{location}"
    return f"{type(handler).__module__}.{type(handler).__qualname__}:{id(handler)}"

