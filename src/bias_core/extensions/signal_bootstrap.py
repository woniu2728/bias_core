from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from django.conf import settings

from bias_core.extensions.application import ExtensionHost
from bias_core.extensions.container import wrap_callback
from bias_core.extensions.exceptions import ExtensionBootError, ExtensionManifestError
from bias_core.extensions.extension_runtime import Extension
from bias_core.extensions.extenders import SignalExtender
from bias_core.extensions.manifest import ExtensionManifestLoader
from bias_core.extensions.product import is_extension_auto_enabled
from bias_core.extensions.signal_runtime import connect_runtime_signal_proxy
from bias_core.extensions.signal_runtime import disconnect_runtime_signal_receivers


_signal_proxy_bootstrapped = False


def reset_extension_signal_proxy_bootstrap() -> None:
    global _signal_proxy_bootstrapped
    disconnect_runtime_signal_receivers(include_proxies=True, proxy_only=True)
    _signal_proxy_bootstrapped = False


def bootstrap_extension_signal_proxies(*, force: bool = False, host: Any = None) -> None:
    global _signal_proxy_bootstrapped
    if _signal_proxy_bootstrapped and not force:
        return
    if force:
        disconnect_runtime_signal_receivers(include_proxies=True, proxy_only=True)
        _signal_proxy_bootstrapped = False

    resolved_host = host or _resolve_bootstrapped_host()
    extensions = tuple(_iter_host_extensions(resolved_host))
    if extensions:
        for extension in extensions:
            try:
                _connect_signal_extenders(resolved_host, extension)
            except (ExtensionBootError, ExtensionManifestError, ImportError, RuntimeError):
                continue
    else:
        fallback_host = ExtensionHost()
        loader = ExtensionManifestLoader(Path(settings.BASE_DIR) / "extensions")
        for manifest in loader.discover_manifests():
            try:
                extension = Extension.from_manifest(manifest)
                _connect_signal_extenders(fallback_host, extension)
            except (ExtensionBootError, ExtensionManifestError, ImportError, RuntimeError):
                continue

    _signal_proxy_bootstrapped = True


def _resolve_bootstrapped_host():
    try:
        from bias_core.extensions.bootstrap_state import is_extension_host_bootstrapped

        if not is_extension_host_bootstrapped():
            return None
        from bias_core.extensions.bootstrap import get_extension_host

        return get_extension_host()
    except Exception:
        return None


def _iter_host_extensions(host: Any):
    if host is None:
        return ()
    extensions = getattr(host, "extensions_to_catalog", ()) or ()
    if extensions:
        return tuple(extensions)
    getter = getattr(host, "get_runtime_extensions", None)
    if callable(getter):
        return tuple(getter() or ())
    return ()


def _connect_signal_extenders(host: ExtensionHost, extension: Extension) -> None:
    enabled_by_default = is_extension_auto_enabled(extension)
    for extender in extension.get_extenders():
        if not isinstance(extender, SignalExtender):
            continue
        for definition in extender.definitions:
            receiver = definition.receiver
            if isinstance(receiver, str) or isinstance(receiver, type):
                receiver = wrap_callback(receiver, host)
                definition = replace(definition, receiver=receiver)
            connect_runtime_signal_proxy(
                extension.id,
                replace(definition, module_id=definition.module_id or extension.id),
                enabled_by_default=enabled_by_default,
            )
