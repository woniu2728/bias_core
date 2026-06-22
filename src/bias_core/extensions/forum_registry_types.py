from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Tuple


# ══════════════════════════════════════════════════════════════════════════════
# 通用框架类型：权限、管理页、通知、偏好、语言包、生命周期
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class PermissionDefinition:
    code: str
    label: str
    section: str
    section_label: str
    module_id: str
    icon: str = "fas fa-key"
    description: str = ""
    required_permissions: Tuple[str, ...] = ()


@dataclass(frozen=True)
class AdminPageDefinition:
    path: str
    label: str
    icon: str
    module_id: str
    nav_section: str = "feature"
    description: str = ""
    settings_group: str = ""


@dataclass(frozen=True)
class NotificationTypeDefinition:
    code: str
    label: str
    module_id: str
    description: str = ""
    icon: str = "fas fa-bell"
    navigation_scope: str = "notifications"
    preference_key: str = ""
    preference_label: str = ""
    preference_description: str = ""
    preference_default_enabled: bool = True


@dataclass(frozen=True)
class UserPreferenceDefinition:
    key: str
    label: str
    module_id: str
    description: str = ""
    category: str = "notification"
    default_value: bool = False


@dataclass(frozen=True)
class DiscussionListFilterDefinition:
    key: str
    label: str
    module_id: str
    query: str = ""
    icon: str = "fas fa-filter"
    type: str = "option"
    options: Tuple[Any, ...] = ()
    filter: Callable | None = None
    serializer: Callable | None = None
    active_callback: Callable | None = None


@dataclass(frozen=True)
class DiscussionListQueryDefinition:
    key: str
    label: str
    module_id: str
    slug: str = ""
    route: str = ""
    icon: str = "fas fa-comments"
    query_params: Tuple[Any, ...] = ()
    default_params: dict[str, Any] | None = None
    toggle: dict[str, Any] | None = None
    filter: Callable | None = None
    serializer: Callable | None = None


@dataclass(frozen=True)
class DiscussionSortDefinition:
    key: str
    label: str
    module_id: str
    sort: Callable | None = None


@dataclass(frozen=True)
class LanguagePackDefinition:
    locale: str
    module_id: str
    resources: dict[str, str] | None = None
    extends: str = ""


@dataclass(frozen=True)
class SearchFilterDefinition:
    key: str
    label: str
    module_id: str
    fulltext: str = ""
    placeholder: str = ""
    conditions: Tuple[Any, ...] = ()
    query: Callable | None = None
    query_conditions: Any = None


@dataclass(frozen=True)
class PostTypeDefinition:
    key: str
    label: str
    module_id: str
    icon: str = "fas fa-comment"


@dataclass(frozen=True)
class EventListenerDefinition:
    event: str
    class_name: str = ""
    method: str = ""
    handler: str = ""
    module_id: str = ""
    priority: int = 100
    description: str = ""


@dataclass(frozen=True)
class LifecycleDefinition:
    key: str
    module_id: str
    label: str = ""
    description: str = ""
    order: int = 100
    enabled_by_default: bool = True
    settings_preview: Any = None


@dataclass(frozen=True)
class LifecycleModeSettings:
    enabled: bool = True
    mode: str = "default"
    value: Any = None


__all__ = [
    "AdminPageDefinition",
    "DiscussionListFilterDefinition",
    "DiscussionListQueryDefinition",
    "DiscussionSortDefinition",
    "LanguagePackDefinition",
    "LifecycleDefinition",
    "LifecycleModeSettings",
    "NotificationTypeDefinition",
    "PermissionDefinition",
    "PostTypeDefinition",
    "SearchFilterDefinition",
    "UserPreferenceDefinition",
]
