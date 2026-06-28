from __future__ import annotations

from bias_core.domain_events import get_forum_event_bus
from bias_core.extension_settings_service import get_extension_settings, save_extension_settings
from bias_core.extensions.application import ExtensionApplication
from bias_core.extensions.bootstrap import (
    bootstrap_extension_application,
    bootstrap_extension_host,
    build_extension_application,
    reset_extension_application_bootstrap_state,
)
from bias_core.extensions.formatter_service import apply_extension_formatter_render, clear_extension_formatter_cache
from bias_core.extensions.lifecycle import rebuild_runtime_urlconf, reset_extension_runtime_state
from bias_core.extensions.registry import ExtensionRegistry
from bias_core.extensions.runtime_service import get_enabled_extension_runtime_entries
from bias_core.extensions.settings_runtime_service import (
    get_enabled_extension_settings_definitions,
    get_extension_settings_definition,
)
from bias_core.forum_registry import (
    get_forum_registry,
    get_registry_permission_codes_by_prefix,
    get_registry_staff_managed_admin_permission_codes,
)
from bias_core.models import AuditLog, ExtensionInstallation, Setting
from bias_core.online_service import OnlineUserService
from bias_core.queue_service import QueueService
from bias_core.search_index_service import get_search_index_definitions
from bias_core.services import PaginationService
from bias_core.settings_service import clear_runtime_setting_caches
from bias_core.visibility import can_view_model_instance
from bias_core.testing import (
    ExtensionRuntimeTestMixin,
    ResourceRegistry,
    build_extension_test_api,
    build_extension_test_host,
    build_extension_test_urlpatterns,
    bootstrap_enabled_extension_application,
    build_runtime_event,
    capture_realtime_discussion_events,
    capture_runtime_events,
    get_resource_registry,
    mark_extension_disabled,
)

__all__ = [
    "AuditLog",
    "ExtensionInstallation",
    "ExtensionApplication",
    "ExtensionRegistry",
    "ExtensionRuntimeTestMixin",
    "OnlineUserService",
    "PaginationService",
    "QueueService",
    "ResourceRegistry",
    "Setting",
    "apply_extension_formatter_render",
    "build_extension_test_api",
    "build_extension_test_host",
    "build_extension_test_urlpatterns",
    "bootstrap_extension_application",
    "bootstrap_extension_host",
    "bootstrap_enabled_extension_application",
    "build_runtime_event",
    "build_extension_application",
    "capture_realtime_discussion_events",
    "capture_runtime_events",
    "can_view_model_instance",
    "clear_runtime_setting_caches",
    "clear_extension_formatter_cache",
    "get_extension_settings",
    "get_enabled_extension_runtime_entries",
    "get_enabled_extension_settings_definitions",
    "get_forum_event_bus",
    "get_forum_registry",
    "get_extension_settings_definition",
    "get_registry_permission_codes_by_prefix",
    "get_registry_staff_managed_admin_permission_codes",
    "get_resource_registry",
    "get_search_index_definitions",
    "mark_extension_disabled",
    "rebuild_runtime_urlconf",
    "reset_extension_application_bootstrap_state",
    "reset_extension_runtime_state",
    "save_extension_settings",
]
