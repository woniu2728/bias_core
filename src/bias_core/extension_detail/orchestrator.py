from __future__ import annotations

import json

from bias_core.extension_detail.debug import _build_extension_debug_info
from bias_core.extension_detail.forum_domain import _build_extension_delivery_assets
from bias_core.extension_detail.forum_domain import _build_extension_discussion_list_filters
from bias_core.extension_detail.forum_domain import _build_extension_discussion_sorts
from bias_core.extension_detail.forum_domain import _build_extension_event_listeners
from bias_core.extension_detail.forum_domain import _build_extension_language_packs
from bias_core.extension_detail.forum_domain import _build_extension_notification_types
from bias_core.extension_detail.forum_domain import _build_extension_post_lifecycle
from bias_core.extension_detail.forum_domain import _build_extension_post_types
from bias_core.extension_detail.forum_domain import _build_extension_realtime_broadcasts
from bias_core.extension_detail.forum_domain import _build_extension_user_preferences
from bias_core.extension_detail.frontend import _build_extension_frontend_routes
from bias_core.extension_detail.frontend import _resolve_extension_frontend_admin_entry
from bias_core.extension_detail.frontend import _resolve_extension_frontend_forum_entry
from bias_core.extension_detail.frontend import _resolve_extension_frontend_outputs
from bias_core.extension_detail.frontend import _resolve_extension_operations_pages
from bias_core.extension_detail.frontend import _resolve_extension_permissions_pages
from bias_core.extension_detail.frontend import _resolve_extension_settings_pages
from bias_core.extension_detail.frontend import _serialize_extension_frontend_asset_state_for_extension
from bias_core.extension_detail.frontend import _serialize_extension_runtime_rebuild_state
from bias_core.extension_detail.models import _build_extension_model_definitions
from bias_core.extension_detail.models import _build_extension_model_ownership_audit
from bias_core.extension_detail.models import _build_extension_model_relations
from bias_core.extension_detail.models import _build_extension_model_visibility
from bias_core.extension_detail.models import _build_extension_owned_models
from bias_core.extension_detail.models import _serialize_extension_migration_execution
from bias_core.extension_detail.models import _serialize_extension_migration_plan
from bias_core.extension_detail.permissions import _build_extension_admin_page_details
from bias_core.extension_detail.permissions import _build_extension_permission_modules
from bias_core.extension_detail.permissions import _build_extension_permission_sections
from bias_core.extension_detail.permissions import _build_extension_permission_summary
from bias_core.extension_detail.permissions import _flatten_extension_permissions
from bias_core.extension_detail.resources import _build_extension_resource_definitions
from bias_core.extension_detail.resources import _build_extension_resource_endpoints
from bias_core.extension_detail.resources import _build_extension_resource_fields
from bias_core.extension_detail.resources import _build_extension_resource_filters
from bias_core.extension_detail.resources import _build_extension_resource_relationships
from bias_core.extension_detail.resources import _build_extension_resource_sorts
from bias_core.extension_detail.resources import _build_extension_search_drivers
from bias_core.extension_detail.resources import _build_extension_search_filters
from bias_core.extension_diagnostics import (
    classify_extension_diagnostics,
    summarize_extension_delivery,
    summarize_extension_diagnostics,
)
from bias_core.extension_django_apps import normalize_extension_django_app_label
from bias_core.extension_service import ExtensionService
from bias_core.extension_settings_service import (
    get_extension_settings,
    save_extension_settings,
    serialize_extension_settings_schema,
)
from bias_core.extensions.admin_actions import (
    build_default_extension_admin_actions,
    serialize_extension_admin_actions,
)
from bias_core.extensions.admin_manifest import (
    build_extension_author_names as _build_extension_author_names,
    build_extension_links as _build_extension_links,
    build_extension_readme as _build_extension_readme,
    manifest_attr as _manifest_attr,
    manifest_nested_attr as _manifest_nested_attr,
    manifest_nested_value as _manifest_nested_value,
    manifest_sequence as _manifest_sequence,
)
from bias_core.extensions.bootstrap import get_extension_host
from bias_core.extensions.exceptions import ExtensionNotFoundError
from bias_core.extensions.frontend_compiler import inspect_extension_frontend_output_manifest
from bias_core.extensions.frontend_serialization import serialize_frontend_values
from bias_core.extensions.manager_dependencies import build_optional_dependency_status_payload
from bias_core.extensions.module_extension_view import build_core_module_lifecycle_plan
from bias_core.extensions.product import (
    get_extension_protected_reason,
    is_extension_protected,
    is_product_visible_extension,
)
from bias_core.extensions.recovery import (
    get_extension_bisect_state,
    get_extension_safe_mode_extension_ids,
    is_extension_safe_mode_enabled,
    serialize_extension_recovery_state,
)

def _serialize_admin_extension(
    extension,
    include_permission_details: bool = False,
    *,
    frontend_output_manifest: dict | None = None,
):
    runtime_view = _resolve_extension_runtime_record(extension)
    detail_page = f"/admin/extensions/{extension.id}"
    settings_pages = _resolve_extension_settings_pages(extension, runtime_view)
    permissions_pages = _resolve_extension_permissions_pages(extension, runtime_view)
    operations_pages = _resolve_extension_operations_pages(extension, runtime_view)
    frontend_admin_entry = _resolve_extension_frontend_admin_entry(extension, runtime_view)
    frontend_forum_entry = _resolve_extension_frontend_forum_entry(extension, runtime_view)
    frontend_boot = _build_extension_frontend_boot_payload(extension)
    frontend_outputs = _resolve_extension_frontend_outputs(extension.id, frontend_output_manifest=frontend_output_manifest)
    frontend_routes = _build_extension_frontend_routes(runtime_view)
    settings_page = next(iter(settings_pages), "")
    permissions_page = next(iter(permissions_pages), "")
    operations_page = next(iter(operations_pages), "")
    admin_actions = _serialize_extension_admin_actions(extension, runtime_record=runtime_view)
    permission_sections = _build_extension_permission_sections(extension, runtime_view) if include_permission_details else []
    permissions = _flatten_extension_permissions(permission_sections)
    permission_summary = _build_extension_permission_summary(permission_sections)
    permission_modules = _build_extension_permission_modules(permission_sections)
    admin_page_details = _build_extension_admin_page_details(extension)
    notification_types = _build_extension_notification_types(extension)
    user_preferences = _build_extension_user_preferences(extension)
    event_listeners = _build_extension_event_listeners(extension, runtime_view)
    realtime_broadcasts = _build_extension_realtime_broadcasts(runtime_view)
    post_lifecycle = _build_extension_post_lifecycle(extension, runtime_view)
    post_types = _build_extension_post_types(extension)
    search_filters = _build_extension_search_filters(extension)
    discussion_sorts = _build_extension_discussion_sorts(extension)
    discussion_list_filters = _build_extension_discussion_list_filters(extension)
    resource_definitions = _build_extension_resource_definitions(extension)
    resource_relationships = _build_extension_resource_relationships(extension)
    resource_fields = _build_extension_resource_fields(extension)
    resource_endpoints = _build_extension_resource_endpoints(extension)
    resource_sorts = _build_extension_resource_sorts(extension)
    resource_filters = _build_extension_resource_filters(extension)
    model_definitions = _build_extension_model_definitions(runtime_view)
    owned_models = _build_extension_owned_models(runtime_view, extension=extension)
    model_ownership_audit = _build_extension_model_ownership_audit(runtime_view, extension=extension)
    model_relations = _build_extension_model_relations(runtime_view)
    model_visibility = _build_extension_model_visibility(runtime_view)
    search_drivers = _build_extension_search_drivers(runtime_view)
    language_packs = _build_extension_language_packs(extension)
    delivery_assets = _build_extension_delivery_assets(extension)
    capability_summary = _build_extension_capability_summary(
        notification_types=notification_types,
        user_preferences=user_preferences,
        event_listeners=event_listeners,
        realtime_broadcasts=realtime_broadcasts,
        post_lifecycle=post_lifecycle,
        post_types=post_types,
        search_filters=search_filters,
        discussion_sorts=discussion_sorts,
        discussion_list_filters=discussion_list_filters,
        resource_definitions=resource_definitions,
        resource_relationships=resource_relationships,
        resource_fields=resource_fields,
        resource_endpoints=resource_endpoints,
        resource_sorts=resource_sorts,
        resource_filters=resource_filters,
        owned_models=owned_models,
        model_ownership_audit=model_ownership_audit,
        model_relations=model_relations,
        language_packs=language_packs,
    )
    settings_schema = serialize_extension_settings_schema(extension.id)
    all_extensions = ExtensionService().list_extensions()
    optional_dependency_status = build_optional_dependency_status_payload(extension, all_extensions)
    contract_snapshot = _build_extension_contract_snapshot(
        extension=extension,
        runtime_view=runtime_view,
        optional_dependency_status=optional_dependency_status,
        frontend_admin_entry=frontend_admin_entry,
        frontend_forum_entry=frontend_forum_entry,
        frontend_routes=frontend_routes,
        settings_pages=settings_pages,
        permissions_pages=permissions_pages,
        operations_pages=operations_pages,
        admin_page_details=admin_page_details,
        permission_modules=permission_modules,
        permissions=permissions,
        notification_types=notification_types,
        user_preferences=user_preferences,
        event_listeners=event_listeners,
        realtime_broadcasts=realtime_broadcasts,
        post_lifecycle=post_lifecycle,
        post_types=post_types,
        search_filters=search_filters,
        discussion_sorts=discussion_sorts,
        discussion_list_filters=discussion_list_filters,
        resource_definitions=resource_definitions,
        resource_relationships=resource_relationships,
        resource_fields=resource_fields,
        resource_endpoints=resource_endpoints,
        resource_sorts=resource_sorts,
        resource_filters=resource_filters,
        model_definitions=model_definitions,
        owned_models=owned_models,
        model_relations=model_relations,
        model_visibility=model_visibility,
        search_drivers=search_drivers,
        language_packs=language_packs,
        capability_summary=capability_summary,
    )

    payload = {
        "id": extension.id,
        "name": extension.name,
        "version": extension.version,
        "description": extension.description,
        "icon": _manifest_attr(extension, "icon", "fas fa-puzzle-piece"),
        "category": _manifest_attr(extension, "category", "feature"),
        "authors": _build_extension_author_names(extension),
        "homepage": _manifest_attr(extension, "homepage"),
        "documentation_url": _manifest_attr(extension, "documentation_url"),
        "links": _build_extension_links(extension),
        "readme": _build_extension_readme(extension),
        "dependencies": _manifest_sequence(extension, "dependencies"),
        "optional_dependencies": _manifest_sequence(extension, "optional_dependencies"),
        "optional_dependency_status": optional_dependency_status,
        "conflicts": _manifest_sequence(extension, "conflicts"),
        "provides": _manifest_sequence(extension, "provides"),
        "backend_entry": _manifest_attr(extension, "backend_entry"),
        "django_app_config": _manifest_attr(extension, "django_app_config"),
        "django_app_label": _manifest_attr(extension, "django_app_label") or normalize_extension_django_app_label(extension.id),
        "frontend_admin_entry": frontend_admin_entry,
        "frontend_forum_entry": frontend_forum_entry,
        "frontend_boot": frontend_boot,
        "frontend_outputs": frontend_outputs,
        "frontend_routes": frontend_routes,
        "settings_pages": list(settings_pages),
        "permissions_pages": list(permissions_pages),
        "operations_pages": list(operations_pages),
        "operations_profile": dict(getattr(extension.manifest, "operations_profile", {}) or {}),
        "settings_schema": settings_schema,
        "settings_values": get_extension_settings(extension.id) if settings_schema else {},
        "compatibility": {
            "bias_version": _manifest_nested_attr(extension, "compatibility", "bias_version"),
            "api_version": _manifest_nested_attr(extension, "compatibility", "api_version", "1.0"),
            "api_stability": _manifest_nested_attr(extension, "compatibility", "api_stability", "experimental"),
            "api_stability_label": _resolve_api_stability_label(extension),
            "breaking_change_policy": _manifest_nested_attr(extension, "compatibility", "breaking_change_policy"),
        },
        "security": {
            "policy_url": _manifest_nested_attr(extension, "security", "policy_url"),
            "support_email": _manifest_nested_attr(extension, "security", "support_email"),
            "capabilities_notice": _manifest_nested_attr(extension, "security", "capabilities_notice"),
        },
        "distribution": {
            "channel": _manifest_nested_attr(extension, "distribution", "channel", "private"),
            "channel_label": _resolve_distribution_channel_label(extension),
            "signing_key_id": _manifest_nested_attr(extension, "distribution", "signing_key_id"),
            "signature_url": _manifest_nested_attr(extension, "distribution", "signature_url"),
            "abandoned": bool(_manifest_nested_value(extension, "distribution", "abandoned", False)),
            "replacement": _manifest_nested_attr(extension, "distribution", "replacement"),
        },
        "installed": extension.runtime.installed,
        "enabled": extension.runtime.enabled,
        "booted": extension.runtime.booted,
        "healthy": extension.runtime.healthy,
        "runtime_status": {
            "key": extension.runtime.status_key,
            "label": extension.runtime.status_label,
        },
        "recovery_status": _serialize_extension_recovery_status(extension),
        "migration_state": extension.runtime.migration_state,
        "migration_label": extension.runtime.migration_label,
        "migration_execution": _serialize_extension_migration_execution(extension),
        "migration_plan": _serialize_extension_migration_plan(extension),
        "dependency_state": extension.runtime.dependency_state,
        "dependency_state_label": extension.runtime.dependency_state_label,
        "lifecycle_plan": _build_lifecycle_plan_for_extension_view(extension),
        "runtime_issues": list(extension.runtime.runtime_issues),
        "delivery_checks": [
            {
                "key": check.key,
                "label": check.label,
                "status": check.status,
                "status_label": check.status_label,
                "message": check.message,
                "path": check.path,
                "optional": check.optional,
            }
            for check in extension.runtime.delivery_checks
        ],
        "uninstall_warnings": list(extension.runtime.uninstall_warnings),
        "runtime_actions": [
            {
                "key": action.key,
                "label": action.label,
                "action": action.action,
                "payload": dict(action.payload or {}),
                "tone": action.tone,
                "confirm_title": action.confirm_title,
                "confirm_message": action.confirm_message,
                "confirm_text": action.confirm_text,
                "success_message": action.success_message,
                "requires_enabled": action.requires_enabled,
                "requires_installed": action.requires_installed,
                "order": action.order,
            }
            for action in extension.runtime.runtime_actions
        ],
        "backend_hooks": _serialize_extension_backend_hooks(extension),
        "source": extension.source,
        "product_visible": is_product_visible_extension(extension),
        "protected": is_extension_protected(extension),
        "protected_reason": get_extension_protected_reason(extension),
        "module_ids": list(extension.module_ids),
        "admin_pages": list(extension.admin_pages),
        "admin_page_details": admin_page_details,
        "settings_groups": list(extension.settings_groups),
        "admin_actions": admin_actions,
        "permission_summary": permission_summary,
        "permission_modules": permission_modules,
        "permissions": permissions,
        "permission_sections": permission_sections,
        "notification_types": notification_types,
        "user_preferences": user_preferences,
        "event_listeners": event_listeners,
        "realtime_broadcasts": realtime_broadcasts,
        "post_lifecycle": post_lifecycle,
        "post_types": post_types,
        "search_filters": search_filters,
        "discussion_sorts": discussion_sorts,
        "discussion_list_filters": discussion_list_filters,
        "resource_definitions": resource_definitions,
        "resource_relationships": resource_relationships,
        "resource_fields": resource_fields,
        "resource_endpoints": resource_endpoints,
        "resource_sorts": resource_sorts,
        "resource_filters": resource_filters,
        "model_definitions": model_definitions,
        "owned_models": owned_models,
        "model_ownership_audit": model_ownership_audit,
        "model_relations": model_relations,
        "model_visibility": model_visibility,
        "search_drivers": search_drivers,
        "language_packs": language_packs,
        "delivery_assets": delivery_assets,
        "frontend_asset_state": _serialize_extension_frontend_asset_state_for_extension(extension),
        "capability_summary": capability_summary,
        "contract_snapshot": contract_snapshot,
        "action_links": {
            "detail_page": detail_page,
            "settings_page": settings_page,
            "permissions_page": permissions_page,
            "operations_page": operations_page,
            "documentation_url": _manifest_attr(extension, "documentation_url"),
        },
        "lifecycle": {
            "registration_mode": extension.lifecycle.registration_mode,
            "registration_mode_label": extension.lifecycle.registration_mode_label,
            "readiness_probe": extension.lifecycle.readiness_probe,
            "supports_disable": extension.lifecycle.supports_disable,
            "supports_teardown": extension.lifecycle.supports_teardown,
            "runtime_phases": list(getattr(runtime_view, "lifecycle_phase_keys", ()) or ()),
            "runtime_extenders": list(getattr(runtime_view, "extender_keys", ()) or ()),
            "runtime_lifecycle_extenders": list(getattr(runtime_view, "lifecycle_extender_keys", ()) or ()),
            "runtime_lifecycle_hooks": list(getattr(runtime_view, "lifecycle_hook_keys", ()) or ()),
            "runtime_rebuild": _serialize_extension_runtime_rebuild_state(),
            "phases": [
                {
                    "key": phase.key,
                    "label": phase.label,
                    "description": phase.description,
                    "optional": phase.optional,
                }
                for phase in extension.lifecycle.phases
            ],
        },
        "debug_info": _build_extension_debug_info(extension),
    }
    payload["diagnostics"] = classify_extension_diagnostics(payload)
    return payload

def _build_lifecycle_plan_for_extension_view(extension) -> dict:
    if getattr(extension, "source", "") == "core-module":
        return build_core_module_lifecycle_plan(extension.id)
    try:
        return ExtensionService.build_extension_lifecycle_plan(extension.id)
    except ExtensionNotFoundError:
        return _build_readonly_lifecycle_plan_for_extension_view(extension)

def _build_readonly_lifecycle_plan_for_extension_view(extension) -> dict:
    installed = bool(getattr(getattr(extension, "runtime", None), "installed", False))
    enabled = bool(getattr(getattr(extension, "runtime", None), "enabled", False))
    protected = is_extension_protected(extension)
    protected_reason = get_extension_protected_reason(extension) if protected else "扩展不在当前扩展管理器中，不能执行生命周期操作。"
    blocked_action = {
        "can_execute": False,
        "blockers": ["unmanaged_runtime_extension"],
    }
    blocked_transaction = {
        "can_execute": False,
        "available": False,
        "order": [],
        "blockers": ["unmanaged_runtime_extension"],
    }
    return {
        "schema": 1,
        "extension_id": extension.id,
        "install": {
            "action": "install",
            "already_active": installed,
            "not_installed": not installed,
            "required_dependencies": [],
            "enabled_dependencies": [],
            "disabled_dependencies": [],
            "missing_dependencies": [],
            "active_conflicts": [],
            "dependency_transaction": dict(blocked_transaction),
            **blocked_action,
        },
        "enable": {
            "action": "enable",
            "already_active": enabled,
            "not_installed": not installed,
            "required_dependencies": [],
            "enabled_dependencies": [],
            "disabled_dependencies": [],
            "missing_dependencies": [],
            "active_conflicts": [],
            "dependency_transaction": dict(blocked_transaction),
            **blocked_action,
        },
        "disable": {
            "action": "disable",
            "protected": protected,
            "protected_reason": protected_reason,
            "core_extension": False,
            "blocking_dependents": [],
            "dependent_transaction": dict(blocked_transaction),
            **blocked_action,
        },
        "uninstall": {
            "action": "uninstall",
            "protected": protected,
            "protected_reason": protected_reason,
            "core_extension": False,
            "blocking_dependents": [],
            "dependent_transaction": dict(blocked_transaction),
            **blocked_action,
        },
    }

def _serialize_admin_extension_summary(extension, *, frontend_output_manifest: dict | None = None):
    runtime_view = _resolve_extension_runtime_record(extension)
    settings_pages = _resolve_extension_settings_pages(extension, runtime_view)
    permissions_pages = _resolve_extension_permissions_pages(extension, runtime_view)
    operations_pages = _resolve_extension_operations_pages(extension, runtime_view)
    frontend_admin_entry = _resolve_extension_frontend_admin_entry(extension, runtime_view)
    frontend_boot = _build_extension_frontend_boot_payload(extension)
    frontend_outputs = _resolve_extension_frontend_outputs(extension.id, frontend_output_manifest=frontend_output_manifest)
    frontend_routes = _build_extension_frontend_routes(runtime_view)

    return {
        "id": extension.id,
        "name": extension.name,
        "version": extension.version,
        "description": extension.description,
        "icon": _manifest_attr(extension, "icon", "fas fa-puzzle-piece"),
        "category": _manifest_attr(extension, "category", "feature"),
        "frontend_admin_entry": frontend_admin_entry,
        "frontend_boot": frontend_boot,
        "frontend_outputs": frontend_outputs,
        "frontend_routes": frontend_routes,
        "installed": extension.runtime.installed,
        "enabled": extension.runtime.enabled,
        "booted": extension.runtime.booted,
        "healthy": extension.runtime.healthy,
        "runtime_status": {
            "key": extension.runtime.status_key,
            "label": extension.runtime.status_label,
        },
        "source": extension.source,
        "product_visible": is_product_visible_extension(extension),
        "protected": is_extension_protected(extension),
        "module_ids": list(extension.module_ids),
        "admin_pages": list(extension.admin_pages),
        "settings_pages": list(settings_pages),
        "permissions_pages": list(permissions_pages),
        "operations_pages": list(operations_pages),
        "action_links": {
            "detail_page": f"/admin/extensions/{extension.id}",
            "settings_page": next(iter(settings_pages), ""),
            "permissions_page": next(iter(permissions_pages), ""),
            "operations_page": next(iter(operations_pages), ""),
            "documentation_url": _manifest_attr(extension, "documentation_url"),
        },
        "diagnostics": [],
        "delivery_checks": [],
        "delivery_assets": [],
        "runtime_issues": list(extension.runtime.runtime_issues),
        "lifecycle_plan": _build_lifecycle_plan_for_extension_view(extension),
    }

def _serialize_admin_extensions_payload(extensions, *, summary: bool = False):
    frontend_output_manifest = inspect_extension_frontend_output_manifest()
    payload = [
        _serialize_admin_extension_summary(
            extension,
            frontend_output_manifest=frontend_output_manifest,
        ) if summary else _serialize_admin_extension(
            extension,
            frontend_output_manifest=frontend_output_manifest,
        )
        for extension in extensions
    ]
    diagnostics_summary = summarize_extension_diagnostics(payload)
    delivery_summary = summarize_extension_delivery(payload)

    return {
        "summary": {
            "extension_count": len(payload),
            "enabled_count": sum(1 for item in payload if item["enabled"]),
            "healthy_count": sum(1 for item in payload if item["healthy"]),
            "filesystem_count": sum(1 for item in payload if item["source"] == "filesystem"),
            "blocking_count": diagnostics_summary["blocking_count"],
            "warning_count": diagnostics_summary["warning_count"],
            "attention_count": diagnostics_summary["attention_count"],
            "asset_count": delivery_summary["asset_count"],
            "frontend_bundle_count": delivery_summary["frontend_bundle_count"],
            "migration_bundle_count": delivery_summary["migration_bundle_count"],
            "locale_bundle_count": delivery_summary["locale_bundle_count"],
            "signed_extension_count": delivery_summary["signed_extension_count"],
            "product_visible_count": sum(1 for item in payload if item["product_visible"]),
        },
        "runtime": {
            **_serialize_extension_runtime_rebuild_state(),
            "recovery": serialize_extension_recovery_state(),
            "package_lock": ExtensionService.inspect_extension_packages(),
        },
        "extensions": payload,
    }

def _build_extension_frontend_boot_payload(extension) -> dict[str, bool]:
    extra = dict(getattr(getattr(extension, "manifest", None), "extra", {}) or {})
    payload = extra.get("frontend_boot")
    if not isinstance(payload, dict):
        payload = {}
    return {
        "admin": bool(payload.get("admin", False)),
        "forum": bool(payload.get("forum", False)),
    }

def _serialize_admin_extension_action_payload(extension):
    frontend_output_manifest = inspect_extension_frontend_output_manifest()
    return {
        "runtime": {
            **_serialize_extension_runtime_rebuild_state(),
            "recovery": serialize_extension_recovery_state(),
        },
        "extension": _serialize_admin_extension(
            extension,
            include_permission_details=True,
            frontend_output_manifest=frontend_output_manifest,
        ),
    }

def _build_default_extension_admin_actions(extension, *, runtime_record=None):
    return build_default_extension_admin_actions(
        extension,
        runtime_record=runtime_record,
        resolve_settings_pages=_resolve_extension_settings_pages,
        resolve_permissions_pages=_resolve_extension_permissions_pages,
        resolve_operations_pages=_resolve_extension_operations_pages,
        resolve_documentation_url=lambda item: _manifest_attr(item, "documentation_url"),
    )

def _serialize_extension_admin_actions(extension, *, runtime_record=None):
    return serialize_extension_admin_actions(
        extension,
        runtime_record=runtime_record,
        resolve_settings_pages=_resolve_extension_settings_pages,
        resolve_permissions_pages=_resolve_extension_permissions_pages,
        resolve_operations_pages=_resolve_extension_operations_pages,
        resolve_documentation_url=lambda item: _manifest_attr(item, "documentation_url"),
    )

def _resolve_extension_runtime_record(extension):
    try:
        host = get_extension_host()
    except Exception:
        return None
    if host is None:
        return None
    return host.get_runtime_view(extension.id)

def _serialize_extension_recovery_status(extension):
    safe_mode = is_extension_safe_mode_enabled()
    safe_mode_extensions = get_extension_safe_mode_extension_ids()
    bisect = get_extension_bisect_state()
    extension_id = str(extension.id or "").strip()
    return {
        "safe_mode": safe_mode,
        "safe_mode_allowed": (not safe_mode)
        or extension_id in safe_mode_extensions,
        "bisect_active": bool(bisect.get("active")),
        "bisect_current": extension_id in set(bisect.get("current") or []),
        "bisect_candidate": extension_id in set(bisect.get("ids") or []),
        "bisect_culprit": extension_id == str(bisect.get("culprit") or "").strip(),
    }

def _resolve_api_stability_label(extension):
    label = _manifest_nested_attr(extension, "compatibility", "api_stability_label")
    if label:
        return label
    api_stability = _manifest_nested_attr(extension, "compatibility", "api_stability", "experimental")
    return {
        "experimental": "实验性",
        "beta": "测试中",
        "stable": "稳定",
        "deprecated": "废弃中",
        "internal": "内部",
    }.get(api_stability, api_stability or "未知")

def _resolve_distribution_channel_label(extension):
    label = _manifest_nested_attr(extension, "distribution", "channel_label")
    if label:
        return label
    channel = _manifest_nested_attr(extension, "distribution", "channel", "private")
    return {
        "private": "私有分发",
        "bundled": "随平台内置",
        "partner": "合作方分发",
        "public": "公开分发",
    }.get(channel, channel or "未知")

def _build_extension_capability_summary(
    *,
    notification_types,
    user_preferences,
    event_listeners,
    realtime_broadcasts,
    post_lifecycle,
    post_types,
    search_filters,
    discussion_sorts,
    discussion_list_filters,
    resource_definitions,
    resource_relationships,
    resource_fields,
    resource_endpoints,
    resource_sorts,
    resource_filters,
    owned_models,
    model_ownership_audit,
    model_relations,
    language_packs,
):
    return {
        "notification_type_count": len(notification_types),
        "user_preference_count": len(user_preferences),
        "event_listener_count": len(event_listeners),
        "realtime_broadcast_count": len(realtime_broadcasts),
        "post_lifecycle_count": len(post_lifecycle),
        "post_type_count": len(post_types),
        "search_filter_count": len(search_filters),
        "discussion_sort_count": len(discussion_sorts),
        "discussion_list_filter_count": len(discussion_list_filters),
        "resource_definition_count": len(resource_definitions),
        "resource_relationship_count": len(resource_relationships),
        "resource_field_count": len(resource_fields),
        "resource_endpoint_count": len(resource_endpoints),
        "resource_sort_count": len(resource_sorts),
        "resource_filter_count": len(resource_filters),
        "owned_model_count": len(owned_models),
        "model_package_migration_required_count": int(
            (model_ownership_audit or {}).get("package_migration_required_count") or 0
        ),
        "model_app_label_migration_required_count": int(
            (model_ownership_audit or {}).get("app_label_migration_required_count") or 0
        ),
        "model_relation_count": len(model_relations),
        "language_pack_count": len(language_packs),
    }


def _build_extension_contract_snapshot(
    *,
    extension,
    runtime_view,
    optional_dependency_status,
    frontend_admin_entry,
    frontend_forum_entry,
    frontend_routes,
    settings_pages,
    permissions_pages,
    operations_pages,
    admin_page_details,
    permission_modules,
    permissions,
    notification_types,
    user_preferences,
    event_listeners,
    realtime_broadcasts,
    post_lifecycle,
    post_types,
    search_filters,
    discussion_sorts,
    discussion_list_filters,
    resource_definitions,
    resource_relationships,
    resource_fields,
    resource_endpoints,
    resource_sorts,
    resource_filters,
    model_definitions,
    owned_models,
    model_relations,
    model_visibility,
    search_drivers,
    language_packs,
    capability_summary,
):
    runtime_extenders = list(getattr(runtime_view, "extender_keys", ()) or ()) if runtime_view is not None else []
    lifecycle_extenders = list(getattr(runtime_view, "lifecycle_extender_keys", ()) or ()) if runtime_view is not None else []
    lifecycle_hooks = list(getattr(runtime_view, "lifecycle_hook_keys", ()) or ()) if runtime_view is not None else []
    lifecycle_phases = list(getattr(runtime_view, "lifecycle_phase_keys", ()) or ()) if runtime_view is not None else []
    settings = _snapshot_settings_contracts(runtime_view)
    presentation = _snapshot_presentation_contracts(runtime_view)
    forum = {
        "permissions": _snapshot_items(permissions, ("code", "label", "module_id")),
        "notification_types": _snapshot_items(notification_types, ("code", "label", "module_id")),
        "user_preferences": _snapshot_items(user_preferences, ("key", "label", "module_id")),
        "language_packs": _snapshot_items(language_packs, ("code", "label", "module_id")),
        "post_types": _snapshot_items(post_types, ("code", "label", "module_id")),
        "search_filters": _snapshot_items(search_filters, ("target", "code", "module_id", "syntax")),
        "discussion_sorts": _snapshot_items(discussion_sorts, ("code", "label", "module_id")),
        "discussion_list_filters": _snapshot_items(discussion_list_filters, ("code", "label", "module_id", "route_path")),
    }
    resources = {
        "definitions": _snapshot_resource_definitions(runtime_view, fallback=resource_definitions),
        "fields": _snapshot_resource_fields(runtime_view, fallback=resource_fields),
        "relationships": _snapshot_resource_relationships(runtime_view, fallback=resource_relationships),
        "endpoints": _snapshot_resource_endpoints(runtime_view, fallback=resource_endpoints),
        "sorts": _snapshot_resource_sorts(runtime_view, fallback=resource_sorts),
        "filters": _snapshot_resource_filters(runtime_view, fallback=resource_filters),
    }
    models = {
        "definitions": _snapshot_items(model_definitions, ("model", "kind", "key")),
        "owned": _snapshot_items(owned_models, ("module_id", "model", "app_label", "target_app_label")),
        "relations": _snapshot_items(model_relations, ("model", "name", "relation_type", "related_model")),
        "visibility": _snapshot_items(model_visibility, ("model", "ability")),
    }
    events = {
        "listeners": _snapshot_items(event_listeners, ("event", "listener", "module_id", "source")),
        "realtime_broadcasts": _snapshot_items(realtime_broadcasts, ("event_name", "event_type")),
        "post_lifecycle": _snapshot_items(post_lifecycle, ("key", "module_id")),
    }
    runtime = _snapshot_runtime_contracts(runtime_view)
    return {
        "schema_version": 1,
        "extension_id": extension.id,
        "source": extension.source,
        "module_ids": _sorted_strings(extension.module_ids),
        "dependencies": _sorted_strings(_manifest_sequence(extension, "dependencies")),
        "optional_dependencies": _sorted_strings(_manifest_sequence(extension, "optional_dependencies")),
        "optional_dependency_status": _snapshot_items(
            optional_dependency_status,
            ("id", "state", "installed", "enabled", "active", "contributes_to_boot_order"),
        ),
        "conflicts": _sorted_strings(_manifest_sequence(extension, "conflicts")),
        "provides": _sorted_strings(_manifest_sequence(extension, "provides")),
        "backend": {
            "entry": _manifest_attr(extension, "backend_entry"),
            "django_app_config": _manifest_attr(extension, "django_app_config"),
            "django_app_label": _manifest_attr(extension, "django_app_label") or normalize_extension_django_app_label(extension.id),
        },
        "frontend": {
            "admin_entry": frontend_admin_entry,
            "forum_entry": frontend_forum_entry,
            "routes": _snapshot_items(frontend_routes, ("frontend", "name", "path", "component")),
            "settings_pages": _sorted_strings(settings_pages),
            "permissions_pages": _sorted_strings(permissions_pages),
            "operations_pages": _sorted_strings(operations_pages),
        },
        "settings": settings,
        "presentation": presentation,
        "admin": {
            "pages": _snapshot_items(admin_page_details, ("path", "label", "module_id")),
            "permission_modules": _snapshot_items(permission_modules, ("module_id", "permission_count")),
        },
        "forum": forum,
        "resources": resources,
        "models": models,
        "search": {
            "drivers": _snapshot_items(search_drivers, ("target", "driver", "filter_count")),
        },
        "events": events,
        "runtime": runtime,
        "lifecycle": {
            "extenders": _sorted_strings(runtime_extenders),
            "lifecycle_extenders": _sorted_strings(lifecycle_extenders),
            "hooks": _sorted_strings(lifecycle_hooks),
            "phases": _sorted_strings(lifecycle_phases),
        },
        "summary": {
            **dict(capability_summary or {}),
            **_snapshot_forum_summary(forum),
            **_snapshot_resource_summary(resources),
            **_snapshot_model_summary(models),
            **_snapshot_event_summary(events),
            **_snapshot_settings_summary(settings),
            **_snapshot_presentation_summary(presentation),
            **_snapshot_runtime_summary(runtime),
        },
    }


def _snapshot_items(items, fields):
    output = []
    for item in items or ():
        if not isinstance(item, dict):
            continue
        output.append({
            field: _snapshot_value(item.get(field))
            for field in fields
            if field in item
        })
    return sorted(output, key=lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True))


def _snapshot_resource_definitions(runtime_view, *, fallback):
    items = _runtime_items(runtime_view, "resource_definitions")
    if not items:
        return _snapshot_items(fallback, ("resource", "module_id"))
    return _snapshot_objects(items, ("resource", "module_id", "description"))


def _snapshot_resource_fields(runtime_view, *, fallback):
    items = _runtime_items(runtime_view, "resource_fields")
    mutators = _runtime_items(runtime_view, "resource_field_mutators")
    if not items and not mutators:
        return _snapshot_items(fallback, ("resource", "field", "module_id", "operation", "anchor"))
    return _snapshot_objects(items, ("resource", "field", "module_id", "description")) + _snapshot_objects(
        mutators,
        ("resource", "field", "module_id", "operation", "anchor", "description"),
    )


def _snapshot_resource_relationships(runtime_view, *, fallback):
    items = _runtime_items(runtime_view, "resource_relationships")
    if not items:
        return _snapshot_items(fallback, ("resource", "relationship", "module_id"))
    return _snapshot_objects(items, ("resource", "relationship", "module_id", "resource_type", "description"))


def _snapshot_resource_endpoints(runtime_view, *, fallback):
    items = _runtime_items(runtime_view, "resource_endpoints")
    if not items:
        return _snapshot_items(fallback, ("resource", "endpoint", "module_id", "operation", "anchor"))
    return _snapshot_objects(items, ("resource", "endpoint", "path", "module_id", "operation", "anchor", "description"))


def _snapshot_resource_sorts(runtime_view, *, fallback):
    items = _runtime_items(runtime_view, "resource_sorts")
    if not items:
        return _snapshot_items(fallback, ("resource", "sort", "module_id", "operation", "anchor"))
    return _snapshot_objects(items, ("resource", "sort", "module_id", "operation", "anchor", "description"))


def _snapshot_resource_filters(runtime_view, *, fallback):
    items = _runtime_items(runtime_view, "resource_filters")
    if not items:
        return _snapshot_items(fallback, ("resource", "filter", "module_id", "operation", "anchor"))
    return _snapshot_objects(items, ("resource", "filter", "module_id", "operation", "anchor", "description"))


def _snapshot_objects(items, fields):
    output = []
    for item in items or ():
        output.append({
            field: _snapshot_value(getattr(item, field, ""))
            for field in fields
            if hasattr(item, field)
        })
    return sorted(output, key=lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True))


def _runtime_items(runtime_view, field):
    if runtime_view is None:
        return ()
    return tuple(getattr(runtime_view, field, ()) or ())


def _snapshot_settings_contracts(runtime_view):
    return {
        "fields": _snapshot_setting_fields(_runtime_items(runtime_view, "settings_schema")),
        "defaults": _snapshot_setting_defaults(_runtime_items(runtime_view, "settings_defaults")),
        "reset_rules": _snapshot_objects(_runtime_items(runtime_view, "settings_reset_rules"), ("key",)),
        "frontend_cache_keys": _sorted_strings(_runtime_items(runtime_view, "settings_frontend_cache_keys")),
        "theme_variables": _snapshot_objects(_runtime_items(runtime_view, "settings_theme_variables"), ("name", "key")),
        "forum_serializations": _snapshot_objects(_runtime_items(runtime_view, "settings_forum_serializations"), ("forum_key", "setting_key")),
        "forum_settings_keys": _sorted_strings(_runtime_items(runtime_view, "forum_settings_keys")),
    }


def _snapshot_forum_summary(forum):
    return {
        "notification_type_count": len(forum["notification_types"]),
        "user_preference_count": len(forum["user_preferences"]),
        "post_type_count": len(forum["post_types"]),
        "search_filter_count": len(forum["search_filters"]),
        "discussion_sort_count": len(forum["discussion_sorts"]),
        "discussion_list_filter_count": len(forum["discussion_list_filters"]),
        "language_pack_count": len(forum["language_packs"]),
    }


def _snapshot_resource_summary(resources):
    return {
        "resource_definition_count": len(resources["definitions"]),
        "resource_relationship_count": len(resources["relationships"]),
        "resource_field_count": len(resources["fields"]),
        "resource_endpoint_count": len(resources["endpoints"]),
        "resource_sort_count": len(resources["sorts"]),
        "resource_filter_count": len(resources["filters"]),
    }


def _snapshot_model_summary(models):
    return {
        "owned_model_count": len(models["owned"]),
        "model_relation_count": len(models["relations"]),
    }


def _snapshot_event_summary(events):
    return {
        "event_listener_count": len(events["listeners"]),
        "realtime_broadcast_count": len(events["realtime_broadcasts"]),
        "post_lifecycle_count": len(events["post_lifecycle"]),
    }


def _snapshot_settings_summary(settings):
    return {
        "settings_field_count": len(settings["fields"]),
        "settings_default_count": len(settings["defaults"]),
        "settings_reset_rule_count": len(settings["reset_rules"]),
        "settings_frontend_cache_key_count": len(settings["frontend_cache_keys"]),
        "settings_theme_variable_count": len(settings["theme_variables"]),
        "settings_forum_serialization_count": len(settings["forum_serializations"]),
        "forum_settings_key_count": len(settings["forum_settings_keys"]),
    }


def _snapshot_setting_fields(items):
    output = []
    for item in items or ():
        output.append({
            "key": _snapshot_value(getattr(item, "key", "")),
            "label": _snapshot_value(getattr(item, "label", "")),
            "type": _snapshot_value(getattr(item, "type", "")),
            "default": _snapshot_value(getattr(item, "default", "")),
            "order": _snapshot_value(getattr(item, "order", "")),
        })
    return sorted(output, key=lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True))


def _snapshot_setting_defaults(items):
    output = []
    for item in items or ():
        output.append({
            "key": _snapshot_value(getattr(item, "key", "")),
            "value": _snapshot_value(getattr(item, "value", "")),
        })
    return sorted(output, key=lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True))


def _snapshot_presentation_contracts(runtime_view):
    frontend_assets = {
        "css": _sorted_strings(_runtime_items(runtime_view, "frontend_css")),
        "js_directories": _sorted_strings(_runtime_items(runtime_view, "frontend_js_directories")),
        "preloads": _snapshot_frontend_values(_runtime_items(runtime_view, "frontend_preloads")),
        "document_attributes": _snapshot_frontend_values(_runtime_items(runtime_view, "frontend_document_attributes")),
        "head_tags": _snapshot_frontend_values(_runtime_items(runtime_view, "frontend_head_tags")),
        "theme_variables": _snapshot_frontend_values(_runtime_items(runtime_view, "frontend_theme_variables")),
        "content_callbacks": _snapshot_frontend_content_callbacks(_runtime_items(runtime_view, "frontend_content_callbacks")),
        "title_driver": _snapshot_callable_identity(getattr(runtime_view, "frontend_title_driver", None)),
    }
    return {
        "frontend_assets": frontend_assets,
        "locale_paths": _sorted_strings(_runtime_items(runtime_view, "locale_paths")),
        "view_namespaces": _snapshot_objects(
            _runtime_items(runtime_view, "view_namespaces"),
            ("namespace", "hints", "module_id", "description", "prepend", "order"),
        ),
        "formatter_callbacks": _snapshot_formatter_callbacks(_runtime_items(runtime_view, "formatter_callbacks")),
        "formatter_pipeline": _snapshot_formatter_pipeline(_runtime_items(runtime_view, "formatter_pipeline")),
    }


def _snapshot_presentation_summary(presentation):
    frontend_assets = presentation["frontend_assets"]
    return {
        "frontend_css_count": len(frontend_assets["css"]),
        "frontend_js_directory_count": len(frontend_assets["js_directories"]),
        "frontend_preload_count": len(frontend_assets["preloads"]),
        "frontend_document_attribute_count": len(frontend_assets["document_attributes"]),
        "frontend_head_tag_count": len(frontend_assets["head_tags"]),
        "frontend_theme_variable_count": len(frontend_assets["theme_variables"]),
        "frontend_content_callback_count": len(frontend_assets["content_callbacks"]),
        "frontend_title_driver_count": 1 if frontend_assets["title_driver"] else 0,
        "locale_path_count": len(presentation["locale_paths"]),
        "view_namespace_count": len(presentation["view_namespaces"]),
        "formatter_callback_count": len(presentation["formatter_callbacks"]),
        "formatter_pipeline_count": len(presentation["formatter_pipeline"]),
    }


def _snapshot_frontend_values(items):
    output = serialize_frontend_values(items or ())
    return sorted(output, key=lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True))


def _snapshot_frontend_content_callbacks(items):
    output = []
    for item in items or ():
        if isinstance(item, dict):
            payload = {
                str(key): _snapshot_value(value)
                for key, value in item.items()
                if key != "callback"
            }
            payload["callback"] = _snapshot_callable_identity(item.get("callback"))
            output.append(payload)
            continue
        output.append({"callback": _snapshot_callable_identity(item)})
    return sorted(output, key=lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True))


def _snapshot_formatter_callbacks(items):
    output = []
    for item in items or ():
        output.append({
            "phase": _snapshot_value(getattr(item, "phase", "")),
            "callback": _snapshot_callable_identity(getattr(item, "callback", None)),
            "module_id": _snapshot_value(getattr(item, "module_id", "")),
            "description": _snapshot_value(getattr(item, "description", "")),
        })
    return sorted(output, key=lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True))


def _snapshot_formatter_pipeline(items):
    return _sorted_strings(_snapshot_callable_identity(item) for item in items or ())


def _snapshot_runtime_contracts(runtime_view):
    return {
        "validators": _snapshot_objects(_runtime_items(runtime_view, "validators"), ("target", "key", "module_id", "description")),
        "mailers": _snapshot_objects(_runtime_items(runtime_view, "mailers"), ("key", "module_id", "description")),
        "error_handlers": _snapshot_objects(_runtime_items(runtime_view, "error_handlers"), ("key", "module_id", "description", "order")),
        "auth_handlers": _snapshot_objects(_runtime_items(runtime_view, "auth_handlers"), ("key", "module_id", "description", "order")),
        "csrf_handlers": _snapshot_objects(_runtime_items(runtime_view, "csrf_handlers"), ("key", "module_id", "description", "order")),
        "filesystem_drivers": _snapshot_objects(_runtime_items(runtime_view, "filesystem_drivers"), ("key", "module_id", "description", "order")),
        "console_commands": _snapshot_objects(_runtime_items(runtime_view, "console_commands"), ("key", "module_id", "description", "order")),
        "session_handlers": _snapshot_objects(_runtime_items(runtime_view, "session_handlers"), ("key", "module_id", "description", "order")),
        "theme_handlers": _snapshot_objects(_runtime_items(runtime_view, "theme_handlers"), ("key", "module_id", "description", "order")),
        "throttle_api_handlers": _snapshot_objects(_runtime_items(runtime_view, "throttle_api_handlers"), ("key", "module_id", "description", "order")),
        "user_handlers": _snapshot_objects(_runtime_items(runtime_view, "user_handlers"), ("key", "module_id", "description", "order")),
        "signal_handlers": _snapshot_objects(_runtime_items(runtime_view, "signal_handlers"), ("module_id", "dispatch_uid", "description", "order")),
        "websocket_routes": _snapshot_objects(_runtime_items(runtime_view, "websocket_routes"), ("path", "name", "module_id")),
        "middleware_mounts": _snapshot_objects(_runtime_items(runtime_view, "middleware_mounts"), ("target", "order")),
        "policy_mounts": _snapshot_policy_mounts(runtime_view),
        "route_mounts": _snapshot_objects(_runtime_items(runtime_view, "route_mounts"), ("prefix", "module_id", "tags")),
        "service_providers": _sorted_strings(_runtime_items(runtime_view, "service_providers")),
    }


def _snapshot_runtime_summary(runtime):
    return {
        "validator_count": len(runtime["validators"]),
        "mailer_count": len(runtime["mailers"]),
        "error_handler_count": len(runtime["error_handlers"]),
        "auth_handler_count": len(runtime["auth_handlers"]),
        "csrf_handler_count": len(runtime["csrf_handlers"]),
        "filesystem_driver_count": len(runtime["filesystem_drivers"]),
        "console_command_count": len(runtime["console_commands"]),
        "session_handler_count": len(runtime["session_handlers"]),
        "theme_handler_count": len(runtime["theme_handlers"]),
        "throttle_api_handler_count": len(runtime["throttle_api_handlers"]),
        "user_handler_count": len(runtime["user_handlers"]),
        "signal_handler_count": len(runtime["signal_handlers"]),
        "websocket_route_count": len(runtime["websocket_routes"]),
        "middleware_mount_count": len(runtime["middleware_mounts"]),
        "policy_mount_count": len(runtime["policy_mounts"]),
        "route_mount_count": len(runtime["route_mounts"]),
        "service_provider_count": len(runtime["service_providers"]),
    }


def _snapshot_policy_mounts(runtime_view):
    output = []
    for item in _runtime_items(runtime_view, "policy_mounts"):
        output.append({
            "key": _snapshot_value(getattr(item, "key", "")),
            "model": _snapshot_model_reference(getattr(item, "model", None)),
            "global_policy": bool(getattr(item, "global_policy", False)),
            "query_policy": bool(getattr(item, "query_policy", False)),
        })
    return sorted(output, key=lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True))


def _snapshot_model_reference(model):
    if model is None:
        return ""
    if isinstance(model, str):
        return model
    module = str(getattr(model, "__module__", "") or "").strip()
    qualname = str(getattr(model, "__qualname__", "") or getattr(model, "__name__", "") or "").strip()
    if module or qualname:
        return ".".join(item for item in (module, qualname) if item)
    service_key = str(getattr(model, "service_key", "") or "").strip()
    attribute = str(getattr(model, "attribute", "") or "").strip()
    if service_key:
        return ".".join(item for item in (service_key, attribute) if item)
    return str(model)


def _snapshot_callable_identity(callback):
    if callback is None:
        return ""
    label = str(getattr(callback, "__bias_callback_label__", "") or "").strip()
    if label:
        return label
    if isinstance(callback, str):
        return callback.strip()
    module = str(getattr(callback, "__module__", "") or "").strip()
    qualname = str(getattr(callback, "__qualname__", "") or getattr(callback, "__name__", "") or "").strip()
    if module or qualname:
        return ".".join(item for item in (module, qualname) if item)
    service_key = str(getattr(callback, "service_key", "") or "").strip()
    attribute = str(getattr(callback, "attribute", "") or "").strip()
    if service_key:
        return ".".join(item for item in (service_key, attribute) if item)
    return type(callback).__module__ + "." + type(callback).__qualname__


def _snapshot_value(value):
    if isinstance(value, (list, tuple, set)):
        return _sorted_strings(value)
    if value is None:
        return ""
    return value


def _sorted_strings(items):
    return sorted(str(item or "").strip() for item in items or () if str(item or "").strip())


def _serialize_extension_backend_hooks(extension):
    hooks = []
    raw_hooks = dict(extension.runtime.backend_hooks or {})
    for hook_name in sorted(raw_hooks.keys()):
        payload = raw_hooks.get(hook_name)
        if not isinstance(payload, dict):
            continue
        hooks.append({
            "hook": str(payload.get("hook") or hook_name),
            "status": str(payload.get("status") or "ok"),
            "status_label": str(payload.get("status_label") or "已完成"),
            "message": str(payload.get("message") or ""),
            "executed_at": str(payload.get("executed_at") or ""),
            "details": dict(payload.get("details") or {}),
        })
    return hooks

def serialize_admin_extension(extension, *, include_permission_details: bool = False):
    return _serialize_admin_extension(
        extension,
        include_permission_details=include_permission_details,
    )

def serialize_admin_extensions_payload(extensions, *, summary: bool = False):
    return _serialize_admin_extensions_payload(extensions, summary=summary)

