from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from django.conf import settings
from django.urls import path

from bias_core.api.runtime import build_api_application
from bias_core.extensions.bootstrap import (
    bootstrap_extension_application,
    reset_extension_application_bootstrap_state,
    set_bootstrapped_extension_host,
)
from bias_core.extensions.application import ExtensionApplication
from bias_core.extensions.extension_runtime import Extension
from bias_core.extensions.lifecycle import reset_extension_runtime_state
from bias_core.extensions.manifest import ExtensionManifestLoader
from bias_core.extensions.registry import get_extension_registry
from bias_core.models import ExtensionInstallation
from bias_core.resource_registry import ResourceRegistry, get_resource_registry


__all__ = [
    "ExtensionRuntimeTestMixin",
    "ResourceRegistry",
    "build_extension_test_api",
    "build_extension_test_host",
    "build_extension_test_urlpatterns",
    "bootstrap_enabled_extension_application",
    "get_resource_registry",
    "mark_extension_disabled",
]


class ExtensionRuntimeTestMixin:
    def _pre_setup(self):
        super()._pre_setup()
        reset_extension_runtime_state()
        reset_extension_application_bootstrap_state()
        bootstrap_extension_application(force=True)

    def _post_teardown(self):
        super()._post_teardown()
        reset_extension_runtime_state()
        reset_extension_application_bootstrap_state()

    def bootstrap_extensions(self, *extension_ids: str):
        return bootstrap_enabled_extension_application(*extension_ids)

    def disable_extension_for_test(self, extension_id: str, *, version: str = "0.1.0") -> None:
        mark_extension_disabled(extension_id, version=version)


def bootstrap_enabled_extension_application(*extension_ids: str):
    reset_extension_runtime_state()
    reset_extension_application_bootstrap_state()
    enabled_ids = _resolve_required_extension_ids(extension_ids)
    for extension_id in enabled_ids:
        ExtensionInstallation.objects.update_or_create(
            extension_id=extension_id,
            defaults={
                "version": "0.1.0",
                "source": "filesystem",
                "enabled": True,
                "installed": True,
                "booted": True,
            },
        )
    return bootstrap_extension_application(force=True)


def mark_extension_disabled(extension_id: str, *, version: str = "0.1.0") -> None:
    reset_extension_runtime_state()
    reset_extension_application_bootstrap_state()
    disabled_ids = _resolve_required_dependent_extension_ids(extension_id)
    for disabled_id in disabled_ids:
        ExtensionInstallation.objects.update_or_create(
            extension_id=disabled_id,
            defaults={
                "version": _resolve_extension_version(disabled_id, fallback=version),
                "source": "filesystem",
                "enabled": False,
                "installed": True,
                "booted": False,
            },
        )
    reset_extension_runtime_state()
    reset_extension_application_bootstrap_state()
    bootstrap_extension_application(force=True)


def build_extension_test_host(*extension_ids: str):
    """Build a test host without reading ExtensionInstallation state."""
    reset_extension_runtime_state()
    reset_extension_application_bootstrap_state()
    extensions = _load_workspace_extensions_for_test()
    enabled_ids = _resolve_required_extension_ids_from_map(extension_ids, extensions)
    extensions_to_boot = tuple(
        _as_enabled_test_extension(extensions[extension_id])
        for extension_id in enabled_ids
        if extension_id in extensions
    )
    host = ExtensionApplication(
        extensions_to_boot=extensions_to_boot,
        extensions_to_catalog=tuple(extensions.values()),
        resource_registry=get_resource_registry(),
    ).boot()
    set_bootstrapped_extension_host(host)
    return host


def build_extension_test_api(*extension_ids: str, urls_namespace: str | None = None):
    return build_api_application(
        extension_host=build_extension_test_host(*extension_ids),
        urls_namespace=urls_namespace,
    )


def build_extension_test_urlpatterns(*extension_ids: str, api_prefix: str = "api/"):
    api = build_extension_test_api(*extension_ids)
    return [
        path(api_prefix, api.urls),
    ]


def _resolve_required_extension_ids(extension_ids: tuple[str, ...]) -> tuple[str, ...]:
    registry = get_extension_registry()
    registry.load(force=True)
    by_id = {
        extension.id: extension
        for extension in registry.get_extensions()
    }
    resolved: list[str] = []

    def visit(extension_id: str) -> None:
        if extension_id == "core" or extension_id in resolved:
            return
        extension = by_id.get(extension_id)
        if extension is None:
            return
        for dependency_id in extension.manifest.dependencies:
            visit(dependency_id)
        resolved.append(extension_id)

    for extension_id in extension_ids:
        visit(extension_id)
    return tuple(resolved)


def _load_workspace_extensions_for_test() -> dict[str, Extension]:
    base_path = Path(getattr(settings, "BASE_DIR", Path.cwd())) / "extensions"
    loader = ExtensionManifestLoader(base_path, include_workspace=True)
    extensions: dict[str, Extension] = {}
    for manifest in loader.discover_manifests():
        extension = Extension.from_manifest(manifest)
        extensions[extension.id] = extension
    return extensions


def _resolve_required_extension_ids_from_map(
    extension_ids: tuple[str, ...],
    extensions: dict[str, Extension],
) -> tuple[str, ...]:
    resolved: list[str] = []

    def visit(extension_id: str) -> None:
        if extension_id == "core" or extension_id in resolved:
            return
        extension = extensions.get(extension_id)
        if extension is None:
            return
        for dependency_id in extension.manifest.dependencies:
            visit(dependency_id)
        resolved.append(extension_id)

    for extension_id in extension_ids:
        visit(extension_id)
    return tuple(resolved)


def _as_enabled_test_extension(extension: Extension) -> Extension:
    return replace(
        extension,
        runtime=replace(
            extension.runtime,
            installed=True,
            enabled=True,
            booted=True,
        ),
    )


def _resolve_required_dependent_extension_ids(extension_id: str) -> tuple[str, ...]:
    normalized = str(extension_id or "").strip()
    if not normalized:
        return ()
    registry = get_extension_registry()
    registry.load(force=True)
    extensions = registry.get_extensions()
    by_id = {extension.id: extension for extension in extensions}
    disabled: list[str] = []

    def visit(target_id: str) -> None:
        if target_id in disabled:
            return
        disabled.append(target_id)
        for extension in extensions:
            if target_id in tuple(extension.manifest.dependencies or ()):
                visit(extension.id)

    if normalized in by_id:
        visit(normalized)
    else:
        disabled.append(normalized)
    return tuple(disabled)


def _resolve_extension_version(extension_id: str, *, fallback: str) -> str:
    registry = get_extension_registry()
    registry.load(force=True)
    try:
        return registry.get_extension(extension_id).version or fallback
    except Exception:
        return fallback
