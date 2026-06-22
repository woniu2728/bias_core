from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    pass


class ExtenderInterface(Protocol):
    def extend(self, app, extension) -> None:
        ...


class LifecycleInterface(Protocol):
    def on_enable(self, extension) -> None:
        ...

    def on_disable(self, extension) -> None:
        ...


# ══════════════════════════════════════════════════════════════════════════════
# Extender 抽象基类
# ══════════════════════════════════════════════════════════════════════════════


class Extender:
    identifier: str = ""
    description: str = ""
    order: int = 100

    def extend(self, app, extension) -> None:
        raise NotImplementedError


# ————— 核心 Extender —————

@dataclass
class SettingsExtender(Extender):
    fields: list = None
    identifier: str = "settings"
    description: str = "Register extension settings"
    order: int = 100

    def __post_init__(self):
        self.fields = self.fields or []

    def extend(self, app, extension) -> None:
        pass  # Will be implemented in C4


@dataclass
class ApiRoutesExtender(Extender):
    routes: list = None
    identifier: str = "api_routes"
    description: str = "Register extension API routes"
    order: int = 80

    def __post_init__(self):
        self.routes = self.routes or []

    def extend(self, app, extension) -> None:
        pass


@dataclass
class FrontendExtender(Extender):
    forum_entry: str = ""
    admin_entry: str = ""
    identifier: str = "frontend"
    description: str = "Register extension frontend entries"
    order: int = 60

    def extend(self, app, extension) -> None:
        pass


@dataclass
class ForumPermissionExtender(Extender):
    permissions: list = None
    identifier: str = "forum_permissions"
    description: str = "Register forum permissions"
    order: int = 90

    def __post_init__(self):
        self.permissions = self.permissions or []

    def extend(self, app, extension) -> None:
        pass


@dataclass
class AdminNavigationExtender(Extender):
    items: list = None
    identifier: str = "admin_navigation"
    description: str = "Register admin navigation items"
    order: int = 90

    def __post_init__(self):
        self.items = self.items or []

    def extend(self, app, extension) -> None:
        pass


@dataclass
class AdminSurfaceExtender(Extender):
    identifier: str = "admin_surface"
    description: str = "Register admin surface items"
    order: int = 90

    def extend(self, app, extension) -> None:
        pass


@dataclass
class DiscussionLifecycleExtender(Extender):
    identifier: str = "discussion_lifecycle"
    description: str = "Register discussion lifecycle hooks"
    order: int = 70

    def extend(self, app, extension) -> None:
        pass


@dataclass
class ForumCapabilitiesExtender(Extender):
    identifier: str = "forum_capabilities"
    description: str = "Register forum capabilities"
    order: int = 90

    def extend(self, app, extension) -> None:
        pass


@dataclass
class NotificationsExtender(Extender):
    notifications: list = None
    identifier: str = "notifications"
    description: str = "Register notification types"
    order: int = 80

    def __post_init__(self):
        self.notifications = self.notifications or []

    def extend(self, app, extension) -> None:
        pass


@dataclass
class PostExtender(Extender):
    identifier: str = "posts"
    description: str = "Register post extensions"
    order: int = 70

    def extend(self, app, extension) -> None:
        pass


@dataclass
class PostLifecycleExtender(Extender):
    identifier: str = "post_lifecycle"
    description: str = "Register post lifecycle hooks"
    order: int = 70

    def extend(self, app, extension) -> None:
        pass


@dataclass
class RuntimeActionsExtender(Extender):
    actions: list = None
    identifier: str = "runtime_actions"
    description: str = "Register runtime actions"
    order: int = 90

    def __post_init__(self):
        self.actions = self.actions or []

    def extend(self, app, extension) -> None:
        pass


@dataclass
class UserExtender(Extender):
    identifier: str = "users"
    description: str = "Register user extensions"
    order: int = 70

    def extend(self, app, extension) -> None:
        pass


# ————— Model/Search Extender —————

@dataclass
class ModelExtender(Extender):
    models: list = None
    identifier: str = "models"
    description: str = "Register extension models"
    order: int = 100

    def __post_init__(self):
        self.models = self.models or []

    def extend(self, app, extension) -> None:
        pass


@dataclass
class ModelPrivateExtender(Extender):
    identifier: str = "model_private"
    description: str = "Register model private config"
    order: int = 90

    def extend(self, app, extension) -> None:
        pass


@dataclass
class ModelUrlExtender(Extender):
    identifier: str = "model_url"
    description: str = "Register model URL config"
    order: int = 90

    def extend(self, app, extension) -> None:
        pass


@dataclass
class ModelVisibilityExtender(Extender):
    identifier: str = "model_visibility"
    description: str = "Register model visibility config"
    order: int = 90

    def extend(self, app, extension) -> None:
        pass


class RuntimeModel:
    pass


@dataclass
class SearchDriverExtender(Extender):
    drivers: list = None
    identifier: str = "search_drivers"
    description: str = "Register search drivers"
    order: int = 60

    def __post_init__(self):
        self.drivers = self.drivers or []

    def extend(self, app, extension) -> None:
        pass


@dataclass
class SearchIndexExtender(Extender):
    indexes: list = None
    identifier: str = "search_indexes"
    description: str = "Register search indexes"
    order: int = 70

    def __post_init__(self):
        self.indexes = self.indexes or []

    def extend(self, app, extension) -> None:
        pass


# ————— Runtime Extender —————

@dataclass
class EventListenersExtender(Extender):
    listeners: list = None
    identifier: str = "event_listeners"
    description: str = "Register extension event listeners"
    order: int = 90

    def __post_init__(self):
        self.listeners = self.listeners or []

    def extend(self, app, extension) -> None:
        pass


@dataclass
class MailExtender(Extender):
    identifier: str = "mail"
    description: str = "Register mail extensions"
    order: int = 80

    def extend(self, app, extension) -> None:
        pass


@dataclass
class RealtimeExtender(Extender):
    identifier: str = "realtime"
    description: str = "Register realtime extensions"
    order: int = 70

    def extend(self, app, extension) -> None:
        pass


@dataclass
class SignalExtender(Extender):
    signals: list = None
    identifier: str = "signals"
    description: str = "Register extension signals"
    order: int = 100

    def __post_init__(self):
        self.signals = self.signals or []

    def extend(self, app, extension) -> None:
        pass


@dataclass
class ValidatorExtender(Extender):
    identifier: str = "validators"
    description: str = "Register extension validators"
    order: int = 80

    def extend(self, app, extension) -> None:
        pass


@dataclass
class ViewExtender(Extender):
    views: list = None
    identifier: str = "views"
    description: str = "Register extension views"
    order: int = 80

    def __post_init__(self):
        self.views = self.views or []

    def extend(self, app, extension) -> None:
        pass


# ————— System Extender —————

@dataclass
class AuthExtender(Extender):
    identifier: str = "auth"
    description: str = "Register auth extensions"
    order: int = 100

    def extend(self, app, extension) -> None:
        pass


@dataclass
class ConsoleExtender(Extender):
    commands: list = None
    identifier: str = "console"
    description: str = "Register console commands"
    order: int = 90

    def __post_init__(self):
        self.commands = self.commands or []

    def extend(self, app, extension) -> None:
        pass


@dataclass
class CsrfExtender(Extender):
    identifier: str = "csrf"
    description: str = "Register CSRF extensions"
    order: int = 100

    def extend(self, app, extension) -> None:
        pass


@dataclass
class ErrorHandlingExtender(Extender):
    identifier: str = "error_handling"
    description: str = "Register error handlers"
    order: int = 100

    def extend(self, app, extension) -> None:
        pass


@dataclass
class FilesystemExtender(Extender):
    identifier: str = "filesystem"
    description: str = "Register filesystem extensions"
    order: int = 80

    def extend(self, app, extension) -> None:
        pass


@dataclass
class PostEventExtender(Extender):
    identifier: str = "post_events"
    description: str = "Register post events"
    order: int = 70

    def extend(self, app, extension) -> None:
        pass


@dataclass
class ServiceProviderExtender(Extender):
    identifier: str = "service_providers"
    description: str = "Register service providers"
    order: int = 100

    def extend(self, app, extension) -> None:
        pass


@dataclass
class SessionExtender(Extender):
    identifier: str = "session"
    description: str = "Register session extensions"
    order: int = 100

    def extend(self, app, extension) -> None:
        pass


@dataclass
class SystemHookExtender(Extender):
    hooks: list = None
    identifier: str = "system_hooks"
    description: str = "Register system hooks"
    order: int = 90

    def __post_init__(self):
        self.hooks = self.hooks or []

    def extend(self, app, extension) -> None:
        pass


@dataclass
class ThemeExtender(Extender):
    identifier: str = "theme"
    description: str = "Register theme extension"
    order: int = 50
    forum_css: str = ""
    admin_css: str = ""
    css_variables: dict = None
    entry: str = ""
    kind: str = "primary"

    def __post_init__(self):
        self.css_variables = self.css_variables or {}

    def extend(self, app, extension) -> None:
        pass


@dataclass
class ThrottleApiExtender(Extender):
    identifier: str = "throttle_api"
    description: str = "Register API throttling"
    order: int = 100

    def extend(self, app, extension) -> None:
        pass


# ————— Routes/Policy Extender —————

@dataclass
class ConditionalExtender(Extender):
    identifier: str = "conditional"
    description: str = "Register conditional extension config"
    order: int = 100

    def extend(self, app, extension) -> None:
        pass


@dataclass
class MiddlewareExtender(Extender):
    middleware: list = None
    identifier: str = "middleware"
    description: str = "Register middleware"
    order: int = 100

    def __post_init__(self):
        self.middleware = self.middleware or []

    def extend(self, app, extension) -> None:
        pass


@dataclass
class PolicyExtender(Extender):
    policies: list = None
    identifier: str = "policies"
    description: str = "Register policies"
    order: int = 90

    def __post_init__(self):
        self.policies = self.policies or []

    def extend(self, app, extension) -> None:
        pass


@dataclass
class RoutesExtender(Extender):
    routes: list = None
    identifier: str = "routes"
    description: str = "Register extension routes"
    order: int = 90

    def __post_init__(self):
        self.routes = self.routes or []

    def extend(self, app, extension) -> None:
        pass


@dataclass
class WebSocketRoutesExtender(Extender):
    routes: list = None
    identifier: str = "websocket_routes"
    description: str = "Register WebSocket routes"
    order: int = 90

    def __post_init__(self):
        self.routes = self.routes or []

    def extend(self, app, extension) -> None:
        pass


# ————— Resources Extender —————
@dataclass
class ApiResourceExtender(Extender):
    resources: list = None
    identifier: str = "api_resources"
    description: str = "Register API resources"
    order: int = 70

    def __post_init__(self):
        self.resources = self.resources or []

    def extend(self, app, extension) -> None:
        pass


@dataclass
class ResourceExtender(Extender):
    resources: list = None
    identifier: str = "resources"
    description: str = "Register resources"
    order: int = 70

    def __post_init__(self):
        self.resources = self.resources or []

    def extend(self, app, extension) -> None:
        pass


# ————— Frontend Extenders —————

@dataclass
class FormatterExtender(Extender):
    identifier: str = "formatter"
    description: str = "Register content formatters"
    order: int = 80

    def extend(self, app, extension) -> None:
        pass


@dataclass
class LanguagePackExtender(Extender):
    packs: list = None
    identifier: str = "language_packs"
    description: str = "Register language packs"
    order: int = 90

    def __post_init__(self):
        self.packs = self.packs or []

    def extend(self, app, extension) -> None:
        pass


@dataclass
class LinkExtender(Extender):
    identifier: str = "links"
    description: str = "Register link extensions"
    order: int = 80

    def extend(self, app, extension) -> None:
        pass


@dataclass
class LocalesExtender(Extender):
    locales: list = None
    identifier: str = "locales"
    description: str = "Register locales"
    order: int = 90

    def __post_init__(self):
        self.locales = self.locales or []

    def extend(self, app, extension) -> None:
        pass


__all__ = [
    "AdminNavigationExtender",
    "AdminSurfaceExtender",
    "ApiResourceExtender",
    "ApiRoutesExtender",
    "AuthExtender",
    "ConditionalExtender",
    "ConsoleExtender",
    "CsrfExtender",
    "DiscussionLifecycleExtender",
    "ErrorHandlingExtender",
    "EventListenersExtender",
    "Extender",
    "ExtenderInterface",
    "FilesystemExtender",
    "FormatterExtender",
    "ForumCapabilitiesExtender",
    "ForumPermissionExtender",
    "FrontendExtender",
    "LanguagePackExtender",
    "LifecycleInterface",
    "LinkExtender",
    "LocalesExtender",
    "MailExtender",
    "MiddlewareExtender",
    "ModelExtender",
    "ModelPrivateExtender",
    "ModelUrlExtender",
    "ModelVisibilityExtender",
    "NotificationsExtender",
    "PolicyExtender",
    "PostEventExtender",
    "PostExtender",
    "PostLifecycleExtender",
    "RealtimeExtender",
    "ResourceExtender",
    "RoutesExtender",
    "RuntimeActionsExtender",
    "RuntimeModel",
    "SearchDriverExtender",
    "SearchIndexExtender",
    "ServiceProviderExtender",
    "SessionExtender",
    "SettingsExtender",
    "SignalExtender",
    "SystemHookExtender",
    "ThemeExtender",
    "ThrottleApiExtender",
    "UserExtender",
    "ValidatorExtender",
    "ViewExtender",
    "WebSocketRoutesExtender",
]
