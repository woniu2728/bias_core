from __future__ import annotations

from typing import Any


def _build_setting_field_definition(data: dict[str, Any]):
    from bias_core.extensions.types import ExtensionManifestSettingFieldDefinition
    return ExtensionManifestSettingFieldDefinition(
        key=data.get("key", ""),
        label=data.get("label", ""),
        type=data.get("type", "text"),
        default=data.get("default", ""),
        help_text=data.get("help_text", ""),
        placeholder=data.get("placeholder", ""),
        required=data.get("required", False),
        multiline=data.get("multiline", False),
        order=data.get("order", 100),
    )


def _build_runtime_action_definition(data: dict[str, Any]):
    from bias_core.extensions.types import ExtensionManifestRuntimeActionDefinition
    return ExtensionManifestRuntimeActionDefinition(
        key=data.get("key", ""),
        label=data.get("label", ""),
        hook=data.get("hook", ""),
        tone=data.get("tone", "default"),
        confirm_title=data.get("confirm_title", ""),
        confirm_message=data.get("confirm_message", ""),
        confirm_text=data.get("confirm_text", ""),
        success_message=data.get("success_message", ""),
        requires_enabled=data.get("requires_enabled", False),
        requires_installed=data.get("requires_installed", False),
        description=data.get("description", ""),
        order=data.get("order", 100),
    )


def _build_admin_action_definition(data: dict[str, Any]):
    from bias_core.extensions.types import ExtensionAdminActionDefinition
    return ExtensionAdminActionDefinition(
        key=data.get("key", ""),
        label=data.get("label", ""),
        kind=data.get("kind", "route"),
        target=data.get("target", ""),
        icon=data.get("icon", ""),
        tone=data.get("tone", "default"),
        opens_in_new_tab=data.get("opens_in_new_tab", False),
        requires_enabled=data.get("requires_enabled", False),
        description=data.get("description", ""),
        order=data.get("order", 100),
    )
