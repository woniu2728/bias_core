from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORT_MODULES = {
    "AccessTokenAuth": "bias_core.jwt_auth",
    "ACCESS_TOKEN_COOKIE_NAME": "bias_core.jwt_auth",
    "ACCESS_TOKEN_COOKIE_PATH": "bias_core.jwt_auth",
    "AuditLog": "bias_core.models",
    "AuthBearer": "bias_core.auth",
    "AuthorizationDecision": "bias_core.authorization",
    "AuthorizationPolicy": "bias_core.authorization",
    "BadJsonApiRequest": "bias_core.resource_errors",
    "DomainEvent": "bias_core.domain_events",
    "DomainEventBus": "bias_core.domain_events",
    "EmailService": "bias_core.email_service",
    "FileUploadService": "bias_core.file_service",
    "JsonApiConflict": "bias_core.resource_errors",
    "JsonApiError": "bias_core.resource_errors",
    "JsonApiErrorItem": "bias_core.resource_errors",
    "JsonApiForbidden": "bias_core.resource_errors",
    "JsonApiValidationError": "bias_core.resource_errors",
    "JSONAPI_CONTENT_TYPE": "bias_core.resource_api",
    "MarkdownService": "bias_core.markdown_service",
    "OnlineUserService": "bias_core.online_service",
    "PaginationService": "bias_core.services.pagination",
    "QueueService": "bias_core.queue_service",
    "REFRESH_TOKEN_COOKIE_NAME": "bias_core.jwt_auth",
    "REFRESH_TOKEN_COOKIE_PATH": "bias_core.jwt_auth",
    "ResourceQueryOptions": "bias_core.resource_api",
    "SearchIndexService": "bias_core.search_index_service",
    "UploadFileOutSchema": "bias_core.schemas",
    "access_token_max_age": "bias_core.jwt_auth",
    "allow": "bias_core.authorization",
    "api_error": "bias_core.api_errors",
    "apply_model_visibility_scope": "bias_core.visibility",
    "apply_related_model_visibility_subquery": "bias_core.visibility",
    "apply_resource_preloads": "bias_core.resource_api",
    "assert_can": "bias_core.authorization",
    "auth_cookie_secure": "bias_core.jwt_auth",
    "blacklist_jwt_token": "bias_core.jwt_auth",
    "broadcast_realtime_discussion_event": "bias_core.forum_runtime",
    "build_extension_settings_defaults": "bias_core.extension_settings_service",
    "can": "bias_core.authorization",
    "can_mail_driver_send": "bias_core.mail_drivers",
    "can_view_model_instance": "bias_core.visibility",
    "can_view_realtime_discussion": "bias_core.forum_runtime",
    "clear_access_token_cookie": "bias_core.jwt_auth",
    "clear_refresh_token_cookie": "bias_core.jwt_auth",
    "deny": "bias_core.authorization",
    "detect_database_label": "bias_core.runtime_diagnostics",
    "dispatch_forum_event_after_commit": "bias_core.domain_events",
    "evaluate_extension_policy": "bias_core.extensions.policy_runtime_service",
    "force_allow": "bias_core.authorization",
    "force_deny": "bias_core.authorization",
    "get_advanced_settings": "bias_core.settings_service",
    "get_advanced_settings_defaults": "bias_core.settings_service",
    "get_extension_settings": "bias_core.extension_settings_service",
    "get_forum_event_bus": "bias_core.domain_events",
    "get_forum_registry": "bias_core.forum_registry",
    "get_mail_settings_defaults": "bias_core.settings_service",
    "get_optional_user": "bias_core.auth",
    "get_registry_staff_managed_admin_permission_codes": "bias_core.forum_registry",
    "get_runtime_forum_event_bus": "bias_core.domain_events",
    "get_setting_group": "bias_core.settings_service",
    "get_storage_backend": "bias_core.storage_service",
    "has_forum_permission": "bias_core.forum_permissions",
    "is_jwt_blacklisted": "bias_core.jwt_auth",
    "iter_realtime_included_enrichers": "bias_core.forum_runtime",
    "jsonapi_error_response": "bias_core.resource_errors",
    "jsonapi_response": "bias_core.resource_api",
    "log_admin_action": "bias_core.audit",
    "merge_resource_includes": "bias_core.resource_api",
    "parse_csv_param": "bias_core.resource_api",
    "parse_resource_query_options": "bias_core.resource_api",
    "refresh_token_max_age": "bias_core.jwt_auth",
    "require_staff": "bias_core.admin_auth",
    "resolve_authenticated_user": "bias_core.jwt_auth",
    "resolve_extension_event_type": "bias_core.extensions.application_event_helpers",
    "resolve_realtime_visible_discussion_ids": "bias_core.forum_runtime",
    "resolve_user_from_refresh_token": "bias_core.websocket_auth",
    "save_extension_settings": "bias_core.extension_settings_service",
    "send_with_extension_mail_driver": "bias_core.mail_drivers",
    "serialize_resource_jsonapi_response": "bias_core.resource_api",
    "serialize_extension_settings_schema": "bias_core.extension_settings_service",
    "set_access_token_cookie": "bias_core.jwt_auth",
    "set_refresh_token_cookie": "bias_core.jwt_auth",
    "sqlite_write_retry": "bias_core.db",
    "wants_jsonapi_response": "bias_core.resource_api",
}

_LAZY_CALLABLE_EXPORTS = {
    "access_token_max_age",
    "allow",
    "api_error",
    "apply_model_visibility_scope",
    "apply_related_model_visibility_subquery",
    "apply_resource_preloads",
    "assert_can",
    "auth_cookie_secure",
    "blacklist_jwt_token",
    "broadcast_realtime_discussion_event",
    "build_extension_settings_defaults",
    "can",
    "can_mail_driver_send",
    "can_view_model_instance",
    "can_view_realtime_discussion",
    "clear_access_token_cookie",
    "clear_refresh_token_cookie",
    "deny",
    "detect_database_label",
    "dispatch_forum_event_after_commit",
    "evaluate_extension_policy",
    "force_allow",
    "force_deny",
    "get_advanced_settings",
    "get_advanced_settings_defaults",
    "get_extension_settings",
    "get_forum_event_bus",
    "get_forum_registry",
    "get_mail_settings_defaults",
    "get_optional_user",
    "get_registry_staff_managed_admin_permission_codes",
    "get_runtime_forum_event_bus",
    "get_setting_group",
    "get_storage_backend",
    "has_forum_permission",
    "is_jwt_blacklisted",
    "iter_realtime_included_enrichers",
    "jsonapi_error_response",
    "jsonapi_response",
    "log_admin_action",
    "merge_resource_includes",
    "parse_csv_param",
    "parse_resource_query_options",
    "refresh_token_max_age",
    "require_staff",
    "resolve_authenticated_user",
    "resolve_extension_event_type",
    "resolve_realtime_visible_discussion_ids",
    "resolve_user_from_refresh_token",
    "save_extension_settings",
    "send_with_extension_mail_driver",
    "serialize_resource_jsonapi_response",
    "serialize_extension_settings_schema",
    "set_access_token_cookie",
    "set_refresh_token_cookie",
    "sqlite_write_retry",
    "wants_jsonapi_response",
}

__all__ = sorted(
    {
        *_EXPORT_MODULES,
        "get_enabled_theme",
        "get_frontend_url",
        "get_theme_settings",
        "is_debug_mode",
        "require_forum_permission",
    }
)


class _LazyPlatformCallable:
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
        return f"<lazy platform callable {self._module_name}.{self._name}>"

    def _resolve(self):
        value = getattr(import_module(self._module_name), self._name)
        globals()[self._name] = value
        return value


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if name in _LAZY_CALLABLE_EXPORTS:
        value = _LazyPlatformCallable(name, module_name)
        globals()[name] = value
        return value
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def is_debug_mode() -> bool:
    from django.conf import settings

    return bool(settings.DEBUG)


def get_frontend_url() -> str:
    from django.conf import settings

    return str(getattr(settings, "FRONTEND_URL", "") or "http://localhost:5173").rstrip("/")


def get_enabled_theme() -> dict:
    theme_settings = get_theme_settings()
    theme_id = str(theme_settings.get("theme_id") or "default").strip() or "default"
    return {
        "id": theme_id,
        "name": str(theme_settings.get("theme_name") or "Default").strip() or "Default",
        "className": str(theme_settings.get("theme_class") or f"bias-theme-{theme_id}").strip() or f"bias-theme-{theme_id}",
        "colorScheme": str(theme_settings.get("color_scheme") or "light").strip() or "light",
        "settings": theme_settings,
    }


def get_theme_settings() -> dict:
    from django.db import OperationalError, ProgrammingError
    from bias_core.models import Setting

    try:
        records = Setting.objects.filter(key__startswith="theme.").values("key", "value")
    except (OperationalError, ProgrammingError):
        return {}

    output = {}
    for record in records:
        key = str(record.get("key") or "").removeprefix("theme.").strip()
        if key:
            output[key] = record.get("value")
    return output


def require_forum_permission(request, permission_code, message: str):
    from bias_core.admin_auth import require_staff
    from bias_core.api_errors import api_error
    from bias_core.forum_permissions import has_forum_permission

    denied = require_staff(request)
    if denied:
        return denied
    if not has_forum_permission(request.auth, permission_code):
        return api_error(message, status=403, code="permission_denied")
    return None
