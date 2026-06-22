from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Tuple

from bias_core.extensions.forum_registry_types import (
    AdminPageDefinition,
    DiscussionListFilterDefinition,
    DiscussionSortDefinition,
    LanguagePackDefinition,
    NotificationTypeDefinition,
    PermissionDefinition,
    PostTypeDefinition,
    SearchFilterDefinition,
    UserPreferenceDefinition,
)


@dataclass(frozen=True)
class ExtensionAdminActionDefinition:
    key: str
    label: str
    kind: str = "route"
    target: str = ""
    icon: str = ""
    tone: str = "default"
    opens_in_new_tab: bool = False
    requires_enabled: bool = False
    description: str = ""
    order: int = 100


@dataclass(frozen=True)
class ExtensionRuntimeActionDefinition:
    key: str
    label: str
    action: str
    tone: str = "default"
    confirm_title: str = ""
    confirm_message: str = ""
    confirm_text: str = ""
    success_message: str = ""
    requires_enabled: bool = False
    requires_installed: bool = False
    order: int = 100


@dataclass(frozen=True)
class ExtensionFrontendRouteDefinition:
    path: str
    name: str
    component: str
    frontend: str = "forum"
    module_id: str = ""
    title: str = ""
    description: str = ""
    preloads: Tuple[Any, ...] = ()
    document_attributes: Tuple[Any, ...] = ()
    head_tags: Tuple[Any, ...] = ()
    requires_auth: bool = False
    order: int = 100
    removed: bool = False


@dataclass(frozen=True)
class ExtensionManifestRuntimeActionDefinition:
    key: str
    label: str
    hook: str
    tone: str = "default"
    confirm_title: str = ""
    confirm_message: str = ""
    confirm_text: str = ""
    success_message: str = ""
    requires_enabled: bool = False
    requires_installed: bool = False
    description: str = ""
    order: int = 100


@dataclass(frozen=True)
class ExtensionManifestSettingOptionDefinition:
    value: str
    label: str


@dataclass(frozen=True)
class ExtensionManifestSettingFieldDefinition:
    key: str
    label: str
    type: str = "text"
    default: Any = ""
    help_text: str = ""
    placeholder: str = ""
    required: bool = False
    options: Tuple[ExtensionManifestSettingOptionDefinition, ...] = ()
    multiline: bool = False
    order: int = 100


ExtensionFormatterCallback = Callable[[str], str]


@dataclass(frozen=True)
class ExtensionFormatterDefinition:
    phase: str
    callback: Callable[..., Any]
    module_id: str = ""
    description: str = ""


@dataclass(frozen=True)
class ExtensionSettingDefaultDefinition:
    key: str
    value: Any
    module_id: str = ""


@dataclass(frozen=True)
class ExtensionSettingResetDefinition:
    key: str
    callback: Callable[[Any], bool]
    module_id: str = ""


@dataclass(frozen=True)
class ExtensionSettingThemeVariableDefinition:
    name: str
    key: str
    callback: Callable[[Any], Any] | None = None
    module_id: str = ""


@dataclass(frozen=True)
class ExtensionSettingForumSerializationDefinition:
    attribute: str
    key: str
    callback: Callable[[Any], Any] | None = None
    module_id: str = ""


ExtensionResourceBaseResolver = Callable[[Any, dict], dict]
ExtensionResourceFieldResolver = Callable[[Any, dict], Any]
ExtensionResourceRelationshipResolver = Callable[[Any, dict], Any]
ExtensionDomainEventHandler = Callable[[Any], None]


@dataclass(frozen=True)
class ExtensionValidatorDefinition:
    key: str
    target: str
    callback: Callable[[Any, dict], Any]
    module_id: str = ""
    description: str = ""


@dataclass(frozen=True)
class ExtensionMailDefinition:
    key: str
    callback: Callable[[Any, dict], Any]
    module_id: str = ""
    description: str = ""


@dataclass(frozen=True)
class ExtensionViewNamespaceDefinition:
    namespace: str
    hints: Tuple[str, ...]
    module_id: str = ""
    description: str = ""
    order: int = 100
    prepend: bool = False


@dataclass(frozen=True)
class ExtensionSystemHookDefinition:
    key: str
    callback: Callable[[Any, dict], Any] | Any
    module_id: str = ""
    description: str = ""
    order: int = 100


@dataclass(frozen=True)
class ExtensionSignalDefinition:
    signal: Any
    receiver: Callable[..., Any]
    sender: Any = None
    dispatch_uid: str = ""
    weak: bool = False
    module_id: str = ""
    description: str = ""
    order: int = 100


@dataclass(frozen=True)
class ExtensionResourceDefinition:
    resource: str
    module_id: str
    resolver: ExtensionResourceBaseResolver
    description: str = ""


@dataclass(frozen=True)
class ExtensionResourceObjectDefinition:
    resource: Any
    module_id: str = ""
    description: str = ""


@dataclass(frozen=True)
class ExtensionResourceFieldDefinition:
    resource: str
    field: str
    module_id: str
    resolver: ExtensionResourceFieldResolver
    description: str = ""
    select_related: Tuple[str, ...] = ()
    prefetch_related: Tuple[Any, ...] = ()
    preload_resolver: Callable[[dict], tuple[tuple[str, ...], tuple[Any, ...]]] | None = None
    annotate_resolver: Callable[[dict], dict[str, Any]] | None = None
    visible: Callable[[Any, dict], bool] | bool = True
    writable: Callable[[Any, dict], bool] | bool = False
    required_on_create: bool = False
    required_on_update: bool = False
    nullable: bool = False
    value_type: str = ""
    validation_rules: Tuple[Any, ...] = ()
    setter: Callable[[Any, Any, dict], None] | None = None
    validator: Callable[[Any, dict], None] | None = None


@dataclass(frozen=True)
class ExtensionResourceRelationshipDefinition:
    resource: str
    relationship: str
    module_id: str
    resolver: ExtensionResourceRelationshipResolver
    description: str = ""
    select_related: Tuple[str, ...] = ()
    prefetch_related: Tuple[Any, ...] = ()
    preload_resolver: Callable[[dict], tuple[tuple[str, ...], tuple[Any, ...]]] | None = None
    visible: Callable[[Any, dict], bool] | bool = True
    includable: Callable[[dict], bool] | bool = True
    resource_type: str = ""
    many: bool = False
    inverse: str = ""
    setter: Callable[[Any, Any, dict], None] | None = None
    writable: Callable[[Any, dict], bool] | bool = False
    linkage: Callable[[Any, dict], Any] | bool = True
    required_on_create: bool = False
    required_on_update: bool = False
    nullable: bool = False
    value_type: str = ""
    validation_rules: Tuple[Any, ...] = ()
    validator: Callable[[Any, dict], None] | None = None


@dataclass(frozen=True)
class ExtensionResourceEndpointDefinition:
    resource: str
    endpoint: str
    module_id: str
    mutator: Callable[[Any], Any] | None = None
    description: str = ""
    operation: str = "mutate"
    anchor: str = ""
    condition: Callable[[dict], bool] | None = None
    handler: Callable[[dict], Any] | None = None
    methods: Tuple[str, ...] = ("GET",)
    path: str = ""
    absolute_path: bool = False
    auth_required: bool = False
    ability: Any = None
    forum_permission: str = ""
    pagination_default_limit: int = 20
    pagination_max_limit: int = 50


@dataclass(frozen=True)
class ExtensionResourceFieldMutatorDefinition:
    resource: str
    field: str
    module_id: str
    mutator: Callable[[Any], Any]
    description: str = ""
    operation: str = "mutate"
    anchor: str = ""
    condition: Callable[[dict], bool] | None = None
    kind: str = ""


@dataclass(frozen=True)
class ExtensionResourceSortDefinition:
    resource: str
    sort: str
    module_id: str
    handler: Any = None
    description: str = ""


@dataclass(frozen=True)
class ExtensionResourceFilterDefinition:
    resource: str
    filter: str
    module_id: str
    handler: Any = None
    description: str = ""


@dataclass(frozen=True)
class ExtensionEventListenerDefinition:
    event_type: str
    handler: Callable[..., Any]
    description: str = ""
    module_id: str = ""
    order: int = 100


@dataclass(frozen=True)
class ExtensionSearchDriverDefinition:
    key: str
    module_id: str
    description: str = ""
    search: Callable | None = None
    search_ids: Callable | None = None
    indexing: Callable | None = None
    configure: Callable | None = None


@dataclass(frozen=True)
class ExtensionSearchIndexDefinition:
    resource: str
    module_id: str
    callback: Callable[..., Any] | None = None
    fields: Tuple[str, ...] = ()


# ————— Model-related definitions —————

@dataclass(frozen=True)
class ExtensionModelDefinition:
    key: str
    model: Any
    module_id: str = ""
    description: str = ""
    order: int = 100


@dataclass(frozen=True)
class ExtensionModelRelationDefinition:
    model: str
    relation: str
    related_model: str
    module_id: str
    resolver: Callable | None = None
    description: str = ""


@dataclass(frozen=True)
class ExtensionModelDefaultDefinition:
    model: str
    field: str
    module_id: str
    value: Any
    description: str = ""


@dataclass(frozen=True)
class ExtensionModelVisibilityDefinition:
    model: str
    module_id: str
    callback: Callable | None = None
    description: str = ""


@dataclass(frozen=True)
class ExtensionModelPrivateDefinition:
    model: str
    module_id: str
    callback: Callable | None = None
    description: str = ""


@dataclass(frozen=True)
class ExtensionModelCastDefinition:
    model: str
    field: str
    module_id: str
    callback: Callable | None = None
    description: str = ""


@dataclass(frozen=True)
class ExtensionModelSlugDriverDefinition:
    model: str
    module_id: str
    callback: Callable | None = None
    description: str = ""


# ————— Resource definitions —————


class DatabaseResource:
    """Placeholder for resource types module."""
    pass


class ResourceEndpoint:
    """Placeholder for resource endpoints."""
    pass


class ResourceField:
    """Placeholder for resource fields."""
    pass


class ResourceFilter:
    """Placeholder for resource filters."""
    pass


class ResourceRelationship:
    """Placeholder for resource relationships."""
    pass


class ResourceSort:
    """Placeholder for resource sorts."""
    pass


@dataclass(frozen=True)
class ResourceDefinition:
    type: str
    model: str
    module_id: str
    fields: Tuple[Any, ...] = ()
    relationships: Tuple[Any, ...] = ()
    filters: Tuple[Any, ...] = ()
    sorts: Tuple[Any, ...] = ()
    endpoints: Tuple[Any, ...] = ()


@dataclass(frozen=True)
class ResourceEndpointDefinition:
    type: str
    name: str
    method: str = "GET"
    path: str = ""
    handler: Callable | None = None


@dataclass(frozen=True)
class ResourceFieldDefinition:
    name: str
    type: str = "string"
    resolver: Callable | None = None
    visible: bool = True
    writable: bool = False


@dataclass(frozen=True)
class ResourceFieldMutatorDefinition:
    resource: str
    field: str
    mutator: Callable[[Any], Any]
    operation: str = "mutate"


@dataclass(frozen=True)
class ResourceFilterDefinition:
    name: str
    type: str = "string"
    handler: Callable | None = None


@dataclass(frozen=True)
class ResourceRelationshipDefinition:
    name: str
    type: str = "has_one"
    resource_type: str = ""
    resolver: Callable | None = None


@dataclass(frozen=True)
class ResourceSortDefinition:
    name: str
    handler: Callable | None = None
