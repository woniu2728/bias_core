from __future__ import annotations

from dataclasses import dataclass

from bias_core.domain_events import DomainEvent


@dataclass
class ExtensionLifecycleEvent(DomainEvent):
    extension_id: str = ""
    reason: str = ""


@dataclass
class ExtensionInstalledEvent(ExtensionLifecycleEvent):
    reason: str = "extension_installed"


@dataclass
class ExtensionEnablingEvent(ExtensionLifecycleEvent):
    reason: str = "extension_enabling"


@dataclass
class ExtensionEnabledEvent(ExtensionLifecycleEvent):
    reason: str = "extension_enabled"


@dataclass
class ExtensionDisablingEvent(ExtensionLifecycleEvent):
    reason: str = "extension_disabling"


@dataclass
class ExtensionDisabledEvent(ExtensionLifecycleEvent):
    reason: str = "extension_disabled"


@dataclass
class ExtensionUninstalledEvent(ExtensionLifecycleEvent):
    reason: str = "extension_uninstalled"


@dataclass
class ExtensionPackagesSyncedEvent(DomainEvent):
    created: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    pruned: tuple[str, ...] = ()
    reason: str = "extension_packages_synced"


@dataclass
class RuntimeCacheClearedEvent(DomainEvent):
    reason: str = "runtime_cache_cleared"



