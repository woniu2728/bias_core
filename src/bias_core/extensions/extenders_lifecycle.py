from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from bias_core.extensions.application import ExtensionHost, ExtensionRuntimeView
    from bias_core.extensions.backend import ExtensionBackendContext


class ExtenderInterface(Protocol):
    def extend(self, app: "ExtensionHost", extension: "ExtensionRuntimeView") -> None:
        ...


class LifecycleInterface(Protocol):
    def on_install(self, context: "ExtensionBackendContext") -> Any:
        ...

    def on_enable(self, context: "ExtensionBackendContext") -> Any:
        ...

    def on_disable(self, context: "ExtensionBackendContext") -> Any:
        ...

    def on_uninstall(self, context: "ExtensionBackendContext") -> Any:
        ...


@dataclass(frozen=True)
class LifecycleExtender:
    install: Callable[["ExtensionBackendContext"], Any] | None = None
    enable: Callable[["ExtensionBackendContext"], Any] | None = None
    disable: Callable[["ExtensionBackendContext"], Any] | None = None
    uninstall: Callable[["ExtensionBackendContext"], Any] | None = None

    @property
    def lifecycle_hook_keys(self) -> tuple[str, ...]:
        hooks = []
        if self.install is not None:
            hooks.append("install")
        if self.enable is not None:
            hooks.append("enable")
        if self.disable is not None:
            hooks.append("disable")
        if self.uninstall is not None:
            hooks.append("uninstall")
        return tuple(hooks)

    def extend(self, app: "ExtensionHost", extension: "ExtensionRuntimeView") -> None:
        app.register_lifecycle_extender(extension.extension_id, self)

    def on_install(self, context: "ExtensionBackendContext") -> Any:
        if self.install is None:
            return None
        return self.install(context)

    def on_enable(self, context: "ExtensionBackendContext") -> Any:
        if self.enable is None:
            return None
        return self.enable(context)

    def on_disable(self, context: "ExtensionBackendContext") -> Any:
        if self.disable is None:
            return None
        return self.disable(context)

    def on_uninstall(self, context: "ExtensionBackendContext") -> Any:
        if self.uninstall is None:
            return None
        return self.uninstall(context)
