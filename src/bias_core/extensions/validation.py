from __future__ import annotations

from pathlib import Path
from typing import Any

from bias_core.extensions.types import ExtensionManifest
from bias_core.extensions.validation_rules import (
    EXTENSION_ID_PATTERN,
    MIGRATION_FILE_PATTERN,
    SEMVER_PATTERN,
)
from bias_core.extensions.validation_manifest import (
    validate_admin_actions,
    validate_admin_page_bindings,
    validate_django_app_config,
    validate_ecosystem_metadata,
    validate_runtime_actions,
    validate_settings_schema,
)
from bias_core.extensions.validation_source import (
    extension_root_path,
    validate_cross_extension_imports,
    validate_distribution_signature,
    validate_extension_source_contracts,
    validate_manifest_field_contracts,
)
from bias_core.extensions.validation_types import (
    ExtensionValidationCollector,
    ExtensionValidationIssue,
    ExtensionValidationResult,
)
from bias_core.extensions.validation_inspection import (
    build_required_frontend_admin_exports,
    expected_frontend_entry,
    inspect_backend_entry,
    inspect_frontend_admin_entry,
    inspect_frontend_forum_entry,
    resolve_admin_surface_implementation,
    resolve_surface_from_export_name,
)
from bias_core.extensions.paths import (
    extension_backend_dir,
    extension_django_migration_dir,
    extension_python_package,
    legacy_extension_python_package,
)
from bias_core.extensions.packaging import inspect_extension_package_resources
from bias_core.extensions.packaging import inspect_extension_package_metadata
from bias_core.extensions.version_compatibility import resolve_bias_version_compatibility


SUPPORTED_MANIFEST_SCHEMA_VERSION = 1


def validate_extension_manifests(manifests: list[ExtensionManifest], *, extensions_base_path: Path | None = None) -> ExtensionValidationResult:
    return validate_extension_manifests_with_available_ids(
        manifests,
        available_extension_ids=None,
        extensions_base_path=extensions_base_path,
        strict_runtime_hooks=False,
    )


def validate_extension_manifests_with_available_ids(
    manifests: list[ExtensionManifest],
    *,
    available_extension_ids: set[str] | None,
    extensions_base_path: Path | None = None,
    strict_runtime_hooks: bool = False,
    public_sdk_only: bool = False,
    frontend_routes_by_extension: dict[str, tuple[Any, ...]] | None = None,
    route_mounts_by_extension: dict[str, tuple[Any, ...]] | None = None,
    named_routes_by_extension: dict[str, tuple[Any, ...]] | None = None,
    websocket_routes_by_extension: dict[str, tuple[Any, ...]] | None = None,
    notification_types_by_extension: dict[str, tuple[Any, ...]] | None = None,
    permissions_by_extension: dict[str, tuple[Any, ...]] | None = None,
    admin_pages_by_extension: dict[str, tuple[Any, ...]] | None = None,
    user_preferences_by_extension: dict[str, tuple[Any, ...]] | None = None,
    language_packs_by_extension: dict[str, tuple[Any, ...]] | None = None,
    post_types_by_extension: dict[str, tuple[Any, ...]] | None = None,
    search_filters_by_extension: dict[str, tuple[Any, ...]] | None = None,
    discussion_list_queries_by_extension: dict[str, tuple[Any, ...]] | None = None,
    discussion_sorts_by_extension: dict[str, tuple[Any, ...]] | None = None,
    discussion_list_filters_by_extension: dict[str, tuple[Any, ...]] | None = None,
    resource_definitions_by_extension: dict[str, tuple[Any, ...]] | None = None,
    resource_fields_by_extension: dict[str, tuple[Any, ...]] | None = None,
    resource_relationships_by_extension: dict[str, tuple[Any, ...]] | None = None,
    resource_endpoints_by_extension: dict[str, tuple[Any, ...]] | None = None,
    resource_sorts_by_extension: dict[str, tuple[Any, ...]] | None = None,
    resource_filters_by_extension: dict[str, tuple[Any, ...]] | None = None,
    model_definitions_by_extension: dict[str, tuple[Any, ...]] | None = None,
    model_relations_by_extension: dict[str, tuple[Any, ...]] | None = None,
    model_casts_by_extension: dict[str, tuple[Any, ...]] | None = None,
    model_defaults_by_extension: dict[str, tuple[Any, ...]] | None = None,
    model_slug_drivers_by_extension: dict[str, tuple[Any, ...]] | None = None,
    search_drivers_by_extension: dict[str, tuple[Any, ...]] | None = None,
    search_indexes_by_extension: dict[str, tuple[Any, ...]] | None = None,
) -> ExtensionValidationResult:
    collector = ExtensionValidationCollector()
    collector.manifests.extend(manifests)

    manifest_ids = {manifest.id for manifest in manifests}
    provided_ids = {
        str(item or "").strip()
        for manifest in manifests
        for item in manifest.provides
        if str(item or "").strip()
    }
    known_extension_ids = set(available_extension_ids or set()) | manifest_ids | provided_ids
    seen_ids: set[str] = set()
    base_path = Path(extensions_base_path) if extensions_base_path else None

    for manifest in manifests:
        _validate_single_manifest(
            collector,
            manifest,
            seen_ids=seen_ids,
            base_path=base_path,
            strict_runtime_hooks=strict_runtime_hooks,
        )

    for manifest in manifests:
        for dependency in manifest.dependencies:
            if dependency not in known_extension_ids:
                collector.add_error(
                    "missing_dependency",
                    f"必需依赖不存在: {dependency}",
                    extension_id=manifest.id,
                    field="dependencies",
                )
        for conflict in manifest.conflicts:
            if conflict == manifest.id:
                collector.add_error(
                    "self_conflict",
                    "扩展不能把自己声明为冲突项",
                    extension_id=manifest.id,
                    field="conflicts",
                )
            elif conflict in manifest.dependencies:
                collector.add_error(
                    "dependency_conflict_overlap",
                    f"扩展不能同时依赖并冲突同一扩展: {conflict}",
                    extension_id=manifest.id,
                    field="conflicts",
                )
            elif conflict in manifest.optional_dependencies:
                collector.add_error(
                    "optional_dependency_conflict_overlap",
                    f"扩展不能同时可选依赖并冲突同一扩展: {conflict}",
                    extension_id=manifest.id,
                    field="conflicts",
                )

    _validate_dependency_graph(collector, manifests)
    _validate_frontend_route_contracts(collector, manifests, frontend_routes_by_extension or {})
    _validate_backend_route_contracts(
        collector,
        manifests,
        route_mounts_by_extension or {},
        named_routes_by_extension or {},
        websocket_routes_by_extension or {},
    )
    _validate_runtime_capability_contracts(
        collector,
        manifests,
        notification_types_by_extension or {},
        search_filters_by_extension or {},
        resource_definitions_by_extension or {},
        resource_fields_by_extension or {},
        resource_relationships_by_extension or {},
        resource_endpoints_by_extension or {},
        permissions_by_extension=permissions_by_extension or {},
        admin_pages_by_extension=admin_pages_by_extension or {},
        user_preferences_by_extension=user_preferences_by_extension or {},
        language_packs_by_extension=language_packs_by_extension or {},
        post_types_by_extension=post_types_by_extension or {},
        discussion_list_queries_by_extension=discussion_list_queries_by_extension or {},
        discussion_sorts_by_extension=discussion_sorts_by_extension or {},
        discussion_list_filters_by_extension=discussion_list_filters_by_extension or {},
        resource_sorts_by_extension=resource_sorts_by_extension or {},
        resource_filters_by_extension=resource_filters_by_extension or {},
        model_definitions_by_extension=model_definitions_by_extension or {},
        model_relations_by_extension=model_relations_by_extension or {},
        model_casts_by_extension=model_casts_by_extension or {},
        model_defaults_by_extension=model_defaults_by_extension or {},
        model_slug_drivers_by_extension=model_slug_drivers_by_extension or {},
        search_drivers_by_extension=search_drivers_by_extension or {},
        search_indexes_by_extension=search_indexes_by_extension or {},
    )

    if base_path is not None:
        for manifest in manifests:
            validate_cross_extension_imports(
                collector,
                manifest,
                base_path,
                known_extension_ids=known_extension_ids,
                public_sdk_only=public_sdk_only,
            )

    return collector.build()


def _validate_frontend_route_contracts(
    collector: ExtensionValidationCollector,
    manifests: list[ExtensionManifest],
    frontend_routes_by_extension: dict[str, tuple[Any, ...]],
) -> None:
    active_route_names: dict[tuple[str, str], tuple[str, Any]] = {}
    active_route_paths: dict[tuple[str, str], tuple[str, Any]] = {}
    allowed_frontends = {"forum", "admin", "common"}

    for manifest in manifests:
        for route in frontend_routes_by_extension.get(manifest.id, ()) or ():
            frontend = str(getattr(route, "frontend", "") or "forum").strip() or "forum"
            name = str(getattr(route, "name", "") or "").strip()
            path = str(getattr(route, "path", "") or "").strip()
            component = str(getattr(route, "component", "") or "").strip()
            module_id = str(getattr(route, "module_id", "") or "").strip()
            removed = bool(getattr(route, "removed", False))

            if frontend not in allowed_frontends:
                collector.add_error(
                    "invalid_frontend_route_target",
                    f"前端路由 {name or path or '<unnamed>'} 的 frontend 不支持: {frontend}",
                    extension_id=manifest.id,
                    field="frontend_routes",
                )
            if module_id and module_id != manifest.id:
                collector.add_error(
                    "foreign_frontend_route_owner",
                    f"前端路由 {name or path or '<unnamed>'} 不能声明为其他扩展归属: {module_id}",
                    extension_id=manifest.id,
                    field="frontend_routes",
                )
            if not name:
                collector.add_error(
                    "invalid_frontend_route",
                    "前端路由必须声明 name",
                    extension_id=manifest.id,
                    field="frontend_routes",
                )
                continue
            if removed:
                continue
            if not path.startswith("/"):
                collector.add_error(
                    "invalid_frontend_route_path",
                    f"前端路由 {name} 的 path 必须以 / 开头",
                    extension_id=manifest.id,
                    field="frontend_routes",
                )
            if not component:
                collector.add_error(
                    "invalid_frontend_route_component",
                    f"前端路由 {name} 必须声明 component",
                    extension_id=manifest.id,
                    field="frontend_routes",
                )

            name_key = (frontend, name)
            existing_name = active_route_names.get(name_key)
            if existing_name is not None:
                owner_id, _existing_route = existing_name
                collector.add_error(
                    "duplicate_frontend_route_name",
                    f"前端路由名称冲突: {frontend}:{name} 已由 {owner_id} 声明",
                    extension_id=manifest.id,
                    field="frontend_routes",
                )
            else:
                active_route_names[name_key] = (manifest.id, route)

            if path:
                path_key = (frontend, path)
                existing_path = active_route_paths.get(path_key)
                if existing_path is not None:
                    owner_id, _existing_route = existing_path
                    collector.add_error(
                        "duplicate_frontend_route_path",
                        f"前端路由路径冲突: {frontend}:{path} 已由 {owner_id} 声明",
                        extension_id=manifest.id,
                        field="frontend_routes",
                    )
                else:
                    active_route_paths[path_key] = (manifest.id, route)


def _validate_backend_route_contracts(
    collector: ExtensionValidationCollector,
    manifests: list[ExtensionManifest],
    route_mounts_by_extension: dict[str, tuple[Any, ...]],
    named_routes_by_extension: dict[str, tuple[Any, ...]],
    websocket_routes_by_extension: dict[str, tuple[Any, ...]],
) -> None:
    active_named_routes: dict[tuple[str, str], str] = {}
    active_named_route_paths: dict[tuple[str, str, str], str] = {}
    active_websocket_names: dict[str, str] = {}
    active_websocket_paths: dict[str, str] = {}

    for manifest in manifests:
        for mount in route_mounts_by_extension.get(manifest.id, ()) or ():
            for route in _iter_route_mount_operations(mount):
                _validate_api_route_contract(
                    collector,
                    manifest,
                    route,
                    active_named_routes,
                    active_named_route_paths,
                    field="route_mounts",
                )

        for route in named_routes_by_extension.get(manifest.id, ()) or ():
            _validate_api_route_contract(
                collector,
                manifest,
                route,
                active_named_routes,
                active_named_route_paths,
                field="named_routes",
            )

        for route in websocket_routes_by_extension.get(manifest.id, ()) or ():
            path = str(getattr(route, "path", "") or "").strip()
            name = str(getattr(route, "name", "") or "").strip()
            module_id = str(getattr(route, "module_id", "") or "").strip()

            if module_id and module_id != manifest.id:
                collector.add_error(
                    "foreign_websocket_route_owner",
                    f"WebSocket route {name or path or '<unnamed>'} 不能声明为其他扩展归属: {module_id}",
                    extension_id=manifest.id,
                    field="websocket_routes",
                )
            if not name:
                collector.add_error(
                    "invalid_websocket_route",
                    "WebSocket route 必须声明 name",
                    extension_id=manifest.id,
                    field="websocket_routes",
                )
                continue
            if not path:
                collector.add_error(
                    "invalid_websocket_route_path",
                    f"WebSocket route {name} 必须声明 path",
                    extension_id=manifest.id,
                    field="websocket_routes",
                )
                continue

            existing_owner = active_websocket_names.get(name)
            if existing_owner is not None:
                collector.add_error(
                    "duplicate_websocket_route_name",
                    f"WebSocket route 名称冲突: {name} 已由 {existing_owner} 声明",
                    extension_id=manifest.id,
                    field="websocket_routes",
                )
            else:
                active_websocket_names[name] = manifest.id

            normalized_path = path.strip("^$")
            existing_path_owner = active_websocket_paths.get(normalized_path)
            if existing_path_owner is not None:
                collector.add_error(
                    "duplicate_websocket_route_path",
                    f"WebSocket route 路径冲突: {path} 已由 {existing_path_owner} 声明",
                    extension_id=manifest.id,
                    field="websocket_routes",
                )
            else:
                active_websocket_paths[normalized_path] = manifest.id


def _validate_api_route_contract(
    collector: ExtensionValidationCollector,
    manifest: ExtensionManifest,
    route: Any,
    active_named_routes: dict[tuple[str, str], str],
    active_named_route_paths: dict[tuple[str, str, str], str],
    *,
    field: str,
) -> None:
    app_name = str(getattr(route, "app_name", "") or "api").strip() or "api"
    method = str(getattr(route, "method", "") or "GET").strip().upper() or "GET"
    path = "/" + str(getattr(route, "path", "") or "").strip().strip("/")
    name = str(getattr(route, "name", "") or "").strip()
    module_id = str(getattr(route, "module_id", "") or "").strip()

    if module_id and module_id != manifest.id:
        collector.add_error(
            "foreign_api_route_owner",
            f"API route {name or path or '<unnamed>'} 不能声明为其他扩展归属: {module_id}",
            extension_id=manifest.id,
            field=field,
        )
    if not name:
        collector.add_error(
            "invalid_api_route",
            "API route 必须声明 name",
            extension_id=manifest.id,
            field=field,
        )
        return
    if path == "/":
        collector.add_error(
            "invalid_api_route_path",
            f"API route {name} 不能挂载到根路径",
            extension_id=manifest.id,
            field=field,
        )

    name_key = (app_name, name)
    existing_owner = active_named_routes.get(name_key)
    if existing_owner is not None:
        collector.add_error(
            "duplicate_api_route_name",
            f"API route 名称冲突: {app_name}:{name} 已由 {existing_owner} 声明",
            extension_id=manifest.id,
            field=field,
        )
    else:
        active_named_routes[name_key] = manifest.id

    path_key = (app_name, method, path)
    existing_path_owner = active_named_route_paths.get(path_key)
    if existing_path_owner is not None:
        collector.add_error(
            "duplicate_api_route_path",
            f"API route 路径冲突: {method} {path} 已由 {existing_path_owner} 声明",
            extension_id=manifest.id,
            field=field,
        )
    else:
        active_named_route_paths[path_key] = manifest.id


def _iter_route_mount_operations(mount: Any) -> tuple[Any, ...]:
    prefix = "/" + str(getattr(mount, "prefix", "") or "").strip().strip("/")
    if prefix == "/":
        prefix = ""
    router = getattr(mount, "router", None)
    path_operations = getattr(router, "path_operations", None)
    if not isinstance(path_operations, dict):
        return ()

    routes = []
    for operation_path, path_view in path_operations.items():
        normalized_operation_path = "/" + str(operation_path or "").strip().strip("/")
        full_path = "/" + "/".join(
            item.strip("/")
            for item in (prefix, normalized_operation_path)
            if str(item or "").strip("/")
        )
        for operation in getattr(path_view, "operations", ()) or ():
            for method in getattr(operation, "methods", ()) or ("GET",):
                routes.append(type("_MountedApiRoute", (), {
                    "app_name": "api",
                    "method": method,
                    "path": full_path,
                    "name": _mounted_api_route_name(operation, full_path, method),
                    "module_id": "",
                })())
    return tuple(routes)


def _mounted_api_route_name(operation: Any, path: str, method: str) -> str:
    operation_id = str(getattr(operation, "operation_id", "") or "").strip()
    if operation_id:
        return operation_id
    view_func = getattr(operation, "view_func", None)
    function_name = str(getattr(view_func, "__name__", "") or "").strip()
    if function_name:
        return function_name
    return f"{str(method or 'GET').strip().upper()} {path}"


def _validate_runtime_capability_contracts(
    collector: ExtensionValidationCollector,
    manifests: list[ExtensionManifest],
    notification_types_by_extension: dict[str, tuple[Any, ...]],
    search_filters_by_extension: dict[str, tuple[Any, ...]],
    resource_definitions_by_extension: dict[str, tuple[Any, ...]],
    resource_fields_by_extension: dict[str, tuple[Any, ...]],
    resource_relationships_by_extension: dict[str, tuple[Any, ...]],
    resource_endpoints_by_extension: dict[str, tuple[Any, ...]],
    *,
    permissions_by_extension: dict[str, tuple[Any, ...]],
    admin_pages_by_extension: dict[str, tuple[Any, ...]],
    user_preferences_by_extension: dict[str, tuple[Any, ...]],
    language_packs_by_extension: dict[str, tuple[Any, ...]],
    post_types_by_extension: dict[str, tuple[Any, ...]],
    discussion_list_queries_by_extension: dict[str, tuple[Any, ...]],
    discussion_sorts_by_extension: dict[str, tuple[Any, ...]],
    discussion_list_filters_by_extension: dict[str, tuple[Any, ...]],
    resource_sorts_by_extension: dict[str, tuple[Any, ...]],
    resource_filters_by_extension: dict[str, tuple[Any, ...]],
    model_definitions_by_extension: dict[str, tuple[Any, ...]],
    model_relations_by_extension: dict[str, tuple[Any, ...]],
    model_casts_by_extension: dict[str, tuple[Any, ...]],
    model_defaults_by_extension: dict[str, tuple[Any, ...]],
    model_slug_drivers_by_extension: dict[str, tuple[Any, ...]],
    search_drivers_by_extension: dict[str, tuple[Any, ...]],
    search_indexes_by_extension: dict[str, tuple[Any, ...]],
) -> None:
    active_notification_types: dict[str, str] = {}
    active_permissions: dict[str, str] = {}
    active_admin_pages: dict[str, str] = {}
    active_user_preferences: dict[str, str] = {}
    active_language_packs: dict[str, str] = {}
    active_post_types: dict[str, str] = {}
    active_search_filters: dict[tuple[str, str], str] = {}
    active_discussion_list_queries: dict[str, str] = {}
    active_discussion_sorts: dict[str, str] = {}
    active_discussion_list_filters: dict[str, str] = {}
    active_resources: dict[str, str] = {}
    active_resource_fields: dict[tuple[str, str], str] = {}
    active_resource_relationships: dict[tuple[str, str], str] = {}
    active_resource_endpoints: dict[tuple[str, str, str, tuple[str, ...]], str] = {}
    active_resource_sorts: dict[tuple[str, str], str] = {}
    active_resource_filters: dict[tuple[str, str], str] = {}
    active_model_definitions: dict[tuple[str, str, str], str] = {}
    active_model_relations: dict[tuple[str, str], str] = {}
    active_model_casts: dict[tuple[str, str], str] = {}
    active_model_defaults: dict[tuple[str, str], str] = {}
    active_model_slug_drivers: dict[tuple[str, str], str] = {}
    active_search_drivers: dict[str, str] = {}
    active_search_indexes: dict[str, str] = {}

    for manifest in manifests:
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            permissions_by_extension.get(manifest.id, ()) or (),
            active_permissions,
            field="permissions",
            code="duplicate_permission",
            label="权限",
            key=lambda item: str(getattr(item, "code", "") or "").strip(),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            admin_pages_by_extension.get(manifest.id, ()) or (),
            active_admin_pages,
            field="admin_pages",
            code="duplicate_admin_page",
            label="后台页面",
            key=lambda item: str(getattr(item, "path", "") or "").strip(),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            notification_types_by_extension.get(manifest.id, ()) or (),
            active_notification_types,
            field="notification_types",
            code="duplicate_notification_type",
            label="通知类型",
            key=lambda item: str(getattr(item, "code", "") or "").strip(),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            user_preferences_by_extension.get(manifest.id, ()) or (),
            active_user_preferences,
            field="user_preferences",
            code="duplicate_user_preference",
            label="用户偏好",
            key=lambda item: str(getattr(item, "key", "") or "").strip(),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            language_packs_by_extension.get(manifest.id, ()) or (),
            active_language_packs,
            field="language_packs",
            code="duplicate_language_pack",
            label="语言包",
            key=lambda item: str(getattr(item, "code", "") or "").strip(),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            post_types_by_extension.get(manifest.id, ()) or (),
            active_post_types,
            field="post_types",
            code="duplicate_post_type",
            label="帖子类型",
            key=lambda item: str(getattr(item, "code", "") or "").strip(),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            search_filters_by_extension.get(manifest.id, ()) or (),
            active_search_filters,
            field="search_filters",
            code="duplicate_search_filter",
            label="搜索过滤器",
            key=lambda item: (
                str(getattr(item, "target", "") or "").strip(),
                str(getattr(item, "code", "") or "").strip(),
            ),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            discussion_list_queries_by_extension.get(manifest.id, ()) or (),
            active_discussion_list_queries,
            field="discussion_list_queries",
            code="duplicate_discussion_list_query",
            label="讨论列表查询",
            key=lambda item: str(getattr(item, "key", "") or "").strip(),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            discussion_sorts_by_extension.get(manifest.id, ()) or (),
            active_discussion_sorts,
            field="discussion_sorts",
            code="duplicate_discussion_sort",
            label="讨论排序",
            key=lambda item: str(getattr(item, "code", "") or "").strip(),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            discussion_list_filters_by_extension.get(manifest.id, ()) or (),
            active_discussion_list_filters,
            field="discussion_list_filters",
            code="duplicate_discussion_list_filter",
            label="讨论列表过滤器",
            key=lambda item: str(getattr(item, "code", "") or "").strip(),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            resource_definitions_by_extension.get(manifest.id, ()) or (),
            active_resources,
            field="resource_definitions",
            code="duplicate_resource_definition",
            label="资源定义",
            key=lambda item: str(getattr(item, "resource", "") or "").strip(),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            resource_fields_by_extension.get(manifest.id, ()) or (),
            active_resource_fields,
            field="resource_fields",
            code="duplicate_resource_field",
            label="资源字段",
            key=lambda item: (
                str(getattr(item, "resource", "") or "").strip(),
                str(getattr(item, "field", "") or "").strip(),
            ),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            resource_relationships_by_extension.get(manifest.id, ()) or (),
            active_resource_relationships,
            field="resource_relationships",
            code="duplicate_resource_relationship",
            label="资源关系",
            key=lambda item: (
                str(getattr(item, "resource", "") or "").strip(),
                str(getattr(item, "relationship", "") or "").strip(),
            ),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            _add_resource_endpoint_definitions(resource_endpoints_by_extension.get(manifest.id, ()) or ()),
            active_resource_endpoints,
            field="resource_endpoints",
            code="duplicate_resource_endpoint",
            label="资源端点",
            key=lambda item: (
                str(getattr(item, "resource", "") or "").strip(),
                _normalize_resource_endpoint_path(item),
                _resource_endpoint_operation(item),
                _normalize_resource_endpoint_methods(getattr(item, "methods", ()) or ()),
            ),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            _add_operation_definitions(resource_sorts_by_extension.get(manifest.id, ()) or ()),
            active_resource_sorts,
            field="resource_sorts",
            code="duplicate_resource_sort",
            label="资源排序",
            key=lambda item: (
                str(getattr(item, "resource", "") or "").strip(),
                str(getattr(item, "sort", "") or "").strip(),
            ),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            _add_operation_definitions(resource_filters_by_extension.get(manifest.id, ()) or ()),
            active_resource_filters,
            field="resource_filters",
            code="duplicate_resource_filter",
            label="资源过滤器",
            key=lambda item: (
                str(getattr(item, "resource", "") or "").strip(),
                str(getattr(item, "filter", "") or "").strip(),
            ),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            model_definitions_by_extension.get(manifest.id, ()) or (),
            active_model_definitions,
            field="model_definitions",
            code="duplicate_model_definition",
            label="模型定义",
            key=lambda item: (
                _model_capability_key(getattr(item, "model", None)),
                str(getattr(item, "kind", "") or "").strip(),
                str(getattr(item, "key", "") or "").strip(),
            ),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            model_relations_by_extension.get(manifest.id, ()) or (),
            active_model_relations,
            field="model_relations",
            code="duplicate_model_relation",
            label="模型关系",
            key=lambda item: (
                _model_capability_key(getattr(item, "model", None)),
                str(getattr(item, "name", "") or "").strip(),
            ),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            model_casts_by_extension.get(manifest.id, ()) or (),
            active_model_casts,
            field="model_casts",
            code="duplicate_model_cast",
            label="模型类型转换",
            key=lambda item: (
                _model_capability_key(getattr(item, "model", None)),
                str(getattr(item, "attribute", "") or "").strip(),
            ),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            model_defaults_by_extension.get(manifest.id, ()) or (),
            active_model_defaults,
            field="model_defaults",
            code="duplicate_model_default",
            label="模型默认值",
            key=lambda item: (
                _model_capability_key(getattr(item, "model", None)),
                str(getattr(item, "attribute", "") or "").strip(),
            ),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            model_slug_drivers_by_extension.get(manifest.id, ()) or (),
            active_model_slug_drivers,
            field="model_slug_drivers",
            code="duplicate_model_slug_driver",
            label="模型 slug 驱动",
            key=lambda item: (
                _model_capability_key(getattr(item, "model", None)),
                str(getattr(item, "identifier", "") or "default").strip() or "default",
            ),
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            _iter_search_driver_slots(search_drivers_by_extension.get(manifest.id, ()) or ()),
            active_search_drivers,
            field="search_drivers",
            code="duplicate_search_driver",
            label="搜索驱动",
            key=lambda item: item,
        )
        _validate_unique_runtime_capabilities(
            collector,
            manifest,
            search_indexes_by_extension.get(manifest.id, ()) or (),
            active_search_indexes,
            field="search_indexes",
            code="duplicate_search_index",
            label="搜索索引",
            key=lambda item: str(getattr(item, "name", "") or "").strip(),
        )


def _validate_unique_runtime_capabilities(
    collector: ExtensionValidationCollector,
    manifest: ExtensionManifest,
    items: tuple[Any, ...],
    active: dict[Any, str],
    *,
    field: str,
    code: str,
    label: str,
    key,
) -> None:
    for item in items:
        item_key = key(item)
        if _is_empty_capability_key(item_key):
            continue
        module_id = str(getattr(item, "module_id", "") or "").strip()
        if module_id and module_id != manifest.id:
            collector.add_error(
                f"foreign_{field.rstrip('s')}_owner",
                f"{label} {_format_capability_key(item_key)} 不能声明为其他扩展归属: {module_id}",
                extension_id=manifest.id,
                field=field,
            )
        owner = active.get(item_key)
        if owner is not None and owner != manifest.id:
            collector.add_error(
                code,
                f"{label} 冲突: {_format_capability_key(item_key)} 已由 {owner} 声明",
                extension_id=manifest.id,
                field=field,
            )
        else:
            active[item_key] = manifest.id


def _add_resource_endpoint_definitions(items: tuple[Any, ...]) -> tuple[Any, ...]:
    return tuple(
        item
        for item in items
        if _resource_endpoint_operation(item) == "add"
    )


def _resource_endpoint_operation(item: Any) -> str:
    operation = str(getattr(item, "operation", "") or "mutate").strip().lower()
    if operation == "mutate" and getattr(item, "handler", None) is not None and getattr(item, "mutator", None) is None:
        return "add"
    return operation


def _add_operation_definitions(items: tuple[Any, ...]) -> tuple[Any, ...]:
    return tuple(
        item
        for item in items
        if str(getattr(item, "operation", "") or "add").strip().lower() == "add"
    )


def _model_capability_key(model: Any) -> str:
    if model is None:
        return ""
    service_key = str(getattr(model, "service_key", "") or "").strip()
    if service_key:
        attribute = str(getattr(model, "attribute", "") or "model").strip() or "model"
        return f"reference:{service_key}:{attribute}"
    if isinstance(model, type):
        name = getattr(model, "__qualname__", getattr(model, "__name__", ""))
        return f"class:{getattr(model, '__module__', '')}.{name}"
    if isinstance(model, (str, int, float, bool)):
        return f"value:{model}"
    return f"object:{id(model)}"


def _iter_search_driver_slots(items: tuple[Any, ...]) -> tuple[tuple[str, str, str], ...]:
    slots: list[tuple[str, str, str]] = []
    for item in items:
        driver = str(getattr(item, "driver", "") or "database").strip() or "database"
        model = getattr(item, "model", None)
        searcher = getattr(item, "searcher", None)
        if model is not None and searcher is not None:
            slots.append(("searcher", driver, _model_capability_key(model)))
        elif searcher is not None:
            slots.append(("searcher", driver, _search_component_key(searcher)))
        if getattr(item, "fulltext", None) is not None:
            searcher_key = searcher if searcher is not None else model
            slots.append(("fulltext", driver, _search_component_key(searcher_key)))
        for searcher_item in getattr(item, "searchers", ()) or ():
            searcher_model = getattr(searcher_item, "model", None)
            slots.append(("searcher", driver, _model_capability_key(searcher_model) or _search_component_key(searcher_item)))
    return tuple(slots)


def _search_component_key(value: Any) -> str:
    if value is None:
        return ""
    return _model_capability_key(value)


def _normalize_resource_endpoint_path(item: Any) -> str:
    value = str(getattr(item, "path", "") or getattr(item, "endpoint", "") or "").strip()
    return "/" + value.strip("/")


def _normalize_resource_endpoint_methods(methods: Any) -> tuple[str, ...]:
    if isinstance(methods, str):
        iterable = (methods,)
    else:
        iterable = tuple(methods or ())
    normalized = tuple(sorted({
        str(method or "").strip().upper()
        for method in iterable
        if str(method or "").strip()
    }))
    return normalized or ("GET",)


def _is_empty_capability_key(item_key: Any) -> bool:
    if isinstance(item_key, tuple):
        return any(not str(item or "").strip() for item in item_key)
    return not str(item_key or "").strip()


def _format_capability_key(item_key: Any) -> str:
    if isinstance(item_key, tuple):
        return ":".join(str(item or "").strip() for item in item_key)
    return str(item_key or "").strip()


def _validate_dependency_graph(
    collector: ExtensionValidationCollector,
    manifests: list[ExtensionManifest],
) -> None:
    manifest_ids = {manifest.id for manifest in manifests}
    providers_by_capability = _build_manifest_capability_provider_map(manifests)
    graph: dict[str, set[str]] = {manifest.id: set() for manifest in manifests}

    for manifest in manifests:
        required = set(manifest.dependencies)
        optional = set(manifest.optional_dependencies)

        if manifest.id in required:
            collector.add_error(
                "self_dependency",
                "扩展不能依赖自己",
                extension_id=manifest.id,
                field="dependencies",
            )
        if manifest.id in optional:
            collector.add_error(
                "self_optional_dependency",
                "扩展不能把自己声明为可选依赖",
                extension_id=manifest.id,
                field="optional_dependencies",
            )

        overlap = sorted(required & optional)
        for dependency_id in overlap:
            collector.add_error(
                "dependency_optional_overlap",
                f"扩展不能同时把同一扩展声明为必需依赖和可选依赖: {dependency_id}",
                extension_id=manifest.id,
                field="optional_dependencies",
            )

        for dependency_id in sorted(required | optional):
            provider_id = _resolve_manifest_dependency_provider_id(
                dependency_id,
                manifest_ids=manifest_ids,
                providers_by_capability=providers_by_capability,
            )
            if provider_id:
                graph[manifest.id].add(provider_id)

    for cycle in _find_dependency_cycles(graph):
        cycle_text = " -> ".join((*cycle, cycle[0]))
        for extension_id in cycle:
            collector.add_error(
                "dependency_cycle",
                f"扩展依赖图存在循环: {cycle_text}",
                extension_id=extension_id,
                field="dependencies",
            )


def _build_manifest_capability_provider_map(manifests: list[ExtensionManifest]) -> dict[str, str]:
    providers: dict[str, str] = {}
    for manifest in sorted(manifests, key=lambda item: item.id):
        for capability in manifest.provides:
            normalized = str(capability or "").strip()
            if normalized and normalized not in providers:
                providers[normalized] = manifest.id
    return providers


def _resolve_manifest_dependency_provider_id(
    dependency_id: str,
    *,
    manifest_ids: set[str],
    providers_by_capability: dict[str, str],
) -> str:
    normalized = str(dependency_id or "").strip()
    if normalized in manifest_ids:
        return normalized
    provider_id = providers_by_capability.get(normalized, "")
    return provider_id if provider_id in manifest_ids else ""


def _find_dependency_cycles(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    visited: set[str] = set()
    active: set[str] = set()
    stack: list[str] = []
    cycles: list[tuple[str, ...]] = []
    seen_cycles: set[tuple[str, ...]] = set()

    def visit(node: str) -> None:
        if node in active:
            try:
                cycle = tuple(stack[stack.index(node):])
            except ValueError:
                return
            normalized = _normalize_cycle(cycle)
            if normalized not in seen_cycles:
                seen_cycles.add(normalized)
                cycles.append(normalized)
            return
        if node in visited:
            return

        active.add(node)
        stack.append(node)
        for dependency_id in sorted(graph.get(node, ())):
            visit(dependency_id)
        stack.pop()
        active.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node)
    return cycles


def _normalize_cycle(cycle: tuple[str, ...]) -> tuple[str, ...]:
    if not cycle:
        return cycle
    rotations = [
        cycle[index:] + cycle[:index]
        for index in range(len(cycle))
    ]
    return min(rotations)

def _validate_single_manifest(
    collector: ExtensionValidationCollector,
    manifest: ExtensionManifest,
    *,
    seen_ids: set[str],
    base_path: Path | None,
    strict_runtime_hooks: bool,
) -> None:
    if manifest.id in seen_ids:
        collector.add_error(
            "duplicate_extension_id",
            f"扩展 ID 重复: {manifest.id}",
            extension_id=manifest.id,
            field="id",
        )
    else:
        seen_ids.add(manifest.id)

    if not EXTENSION_ID_PATTERN.match(manifest.id):
        collector.add_error(
            "invalid_extension_id",
            "扩展 ID 只能包含小写字母、数字和中划线，且不能以中划线开头或结尾",
            extension_id=manifest.id,
            field="id",
        )

    if not SEMVER_PATTERN.match(manifest.version):
        collector.add_error(
            "invalid_extension_version",
            "扩展版本号必须是 X.Y.Z 形式的语义化版本",
            extension_id=manifest.id,
            field="version",
        )

    schema_version = int(getattr(manifest, "schema_version", 1) or 0)
    if schema_version < 1:
        collector.add_error(
            "invalid_manifest_schema_version",
            "schema_version 必须是正整数，目前支持 1。",
            extension_id=manifest.id,
            field="schema_version",
        )
    elif schema_version > SUPPORTED_MANIFEST_SCHEMA_VERSION:
        collector.add_error(
            "unsupported_manifest_schema_version",
            f"schema_version={schema_version} 高于当前支持版本 {SUPPORTED_MANIFEST_SCHEMA_VERSION}。",
            extension_id=manifest.id,
            field="schema_version",
        )

    _validate_unique_strings(collector, manifest, "dependencies", manifest.dependencies)
    _validate_unique_strings(collector, manifest, "optional_dependencies", manifest.optional_dependencies)
    _validate_unique_strings(collector, manifest, "conflicts", manifest.conflicts)
    _validate_unique_strings(collector, manifest, "provides", manifest.provides)
    _validate_unique_strings(collector, manifest, "settings_pages", manifest.settings_pages)
    _validate_unique_strings(collector, manifest, "permissions_pages", manifest.permissions_pages)
    _validate_unique_strings(collector, manifest, "operations_pages", manifest.operations_pages)
    validate_admin_actions(collector, manifest)
    validate_admin_page_bindings(collector, manifest)
    validate_ecosystem_metadata(collector, manifest)
    validate_runtime_actions(collector, manifest)
    validate_settings_schema(collector, manifest)
    validate_django_app_config(collector, manifest)

    for field_name, pages in (
        ("settings_pages", manifest.settings_pages),
        ("permissions_pages", manifest.permissions_pages),
        ("operations_pages", manifest.operations_pages),
    ):
        for page in pages:
            if not page.startswith("/admin/extensions/"):
                collector.add_warning(
                    "non_extension_admin_page",
                    f"{field_name} 建议使用 /admin/extensions/... 作为扩展后台入口",
                    extension_id=manifest.id,
                    field=field_name,
                )

    if base_path is not None:
        validate_manifest_field_contracts(collector, manifest, base_path)
        validate_extension_source_contracts(collector, manifest, base_path)
        validate_distribution_signature(collector, manifest, base_path)
        _validate_package_resources(collector, manifest, base_path)
        _validate_frontend_admin_entry(collector, manifest, base_path)
        _validate_frontend_forum_entry(collector, manifest, base_path)
        _validate_backend_entry(
            collector,
            manifest,
            base_path,
            strict_runtime_hooks=strict_runtime_hooks,
        )
        _validate_migration_files(
            collector,
            manifest,
            base_path,
        )


def _validate_package_resources(
    collector: ExtensionValidationCollector,
    manifest: ExtensionManifest,
    base_path: Path,
) -> None:
    extension_root = extension_root_path(manifest, base_path)
    metadata = inspect_extension_package_metadata(
        extension_root,
        extension_id=manifest.id,
        extension_version=manifest.version,
        manifest_dependencies=manifest.dependencies,
        backend_entry=manifest.backend_entry,
    )
    if metadata is not None:
        for message in metadata.errors:
            collector.add_error(
                "extension_package_metadata_invalid",
                message,
                extension_id=manifest.id,
                field="pyproject.toml",
            )

    inspection = inspect_extension_package_resources(extension_root)
    if inspection is None or not inspection.missing_files:
        return

    preview = ", ".join(inspection.missing_files[:5])
    if len(inspection.missing_files) > 5:
        preview = f"{preview}, ..."
    collector.add_warning(
        "extension_package_resource_missing",
        f"pyproject.toml 未声明 {len(inspection.missing_files)} 个扩展资源文件，发布 wheel 后可能丢失: {preview}",
        extension_id=manifest.id,
        field="pyproject.toml",
    )

def _validate_backend_entry(
    collector: ExtensionValidationCollector,
    manifest: ExtensionManifest,
    base_path: Path,
    *,
    strict_runtime_hooks: bool,
) -> None:
    debug_payload = inspect_backend_entry(manifest, extensions_base_path=base_path)
    entry = str(debug_payload["entry"] or "").strip()
    requires_backend = bool(entry or manifest.runtime_actions)

    if requires_backend and not entry:
        collector.add_error(
            "missing_backend_entry_declaration",
            "声明 runtime_actions 时必须同时提供 backend_entry",
            extension_id=manifest.id,
            field="backend_entry",
        )
        return

    if not entry:
        return
    if debug_payload["entry_type"] == "external":
        collector.add_warning(
            "backend_entry_outside_extensions",
            "backend_entry 建议使用 bias_ext_<extension_id>.backend.ext 形式的扩展入口",
            extension_id=manifest.id,
            field="backend_entry",
        )
        return
    expected_backend_prefix = f"{extension_python_package(manifest.id)}.backend."
    legacy_backend_prefix = f"{legacy_extension_python_package(manifest.id)}.backend."
    if not entry.startswith(expected_backend_prefix) and not entry.startswith(legacy_backend_prefix):
        collector.add_error(
            "invalid_backend_entry_namespace",
            f"backend_entry 必须归属当前扩展命名空间，建议使用 {expected_backend_prefix}...",
            extension_id=manifest.id,
            field="backend_entry",
        )
        return
    if not debug_payload["exists"]:
        collector.add_error(
            "missing_backend_entry",
            f"找不到 backend_entry 对应文件: {entry}",
            extension_id=manifest.id,
            field="backend_entry",
        )
        return

    if not strict_runtime_hooks:
        return

    available_hooks = set(debug_payload["available_hooks"])
    for action in manifest.runtime_actions:
        if action.hook and action.hook not in available_hooks:
            collector.add_error(
                "missing_backend_hook",
                f"runtime_actions 声明的后端钩子不存在: {action.hook}",
                extension_id=manifest.id,
                field="runtime_actions",
            )


def _validate_unique_strings(
    collector: ExtensionValidationCollector,
    manifest: ExtensionManifest,
    field_name: str,
    values: tuple[str, ...],
) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            collector.add_error(
                "duplicate_manifest_value",
                f"{field_name} 中存在重复值: {value}",
                extension_id=manifest.id,
                field=field_name,
            )
        else:
            seen.add(value)


def _validate_frontend_admin_entry(
    collector: ExtensionValidationCollector,
    manifest: ExtensionManifest,
    base_path: Path,
) -> None:
    debug_payload = inspect_frontend_admin_entry(manifest, extensions_base_path=base_path)
    entry = str(debug_payload["entry"] or "").strip()
    if not entry:
        return
    if debug_payload["entry_type"] == "external":
        collector.add_warning(
            "frontend_admin_entry_outside_extensions",
            "frontend_admin_entry 建议使用相对当前扩展根目录的路径，例如 frontend/admin/index.js 或 frontend/dist/admin/index.js",
            extension_id=manifest.id,
            field="frontend_admin_entry",
        )
        return
    expected_entry = expected_frontend_entry(manifest, base_path, "admin")
    if entry != expected_entry and not bool(debug_payload["exists"]):
        collector.add_error(
            "invalid_frontend_admin_entry_path",
            f"frontend_admin_entry 必须指向当前扩展的标准后台入口: {expected_entry}",
            extension_id=manifest.id,
            field="frontend_admin_entry",
        )
        return

    if not debug_payload["exists"]:
        collector.add_error(
            "missing_frontend_admin_entry",
            f"找不到 frontend_admin_entry 对应文件: {entry}",
            extension_id=manifest.id,
            field="frontend_admin_entry",
        )
        return

    required_exports = list(debug_payload["required_exports"])
    available_exports = set(debug_payload["available_exports"])

    if not required_exports and "resolveDetailPage" not in available_exports:
        collector.add_warning(
            "missing_frontend_admin_detail_export",
            "frontend_admin_entry 未导出 resolveDetailPage，扩展详情页将回退到平台默认视图",
            extension_id=manifest.id,
            field="frontend_admin_entry",
        )

    for export_name in required_exports:
        surface = resolve_surface_from_export_name(export_name)
        if surface and resolve_admin_surface_implementation(manifest, surface, available_exports).get("mode") == "generated":
            continue
        if export_name not in available_exports:
            collector.add_error(
                "missing_frontend_admin_export",
                f"frontend_admin_entry 缺少导出函数: {export_name}",
                extension_id=manifest.id,
                field="frontend_admin_entry",
            )


def _validate_frontend_forum_entry(
    collector: ExtensionValidationCollector,
    manifest: ExtensionManifest,
    base_path: Path,
) -> None:
    debug_payload = inspect_frontend_forum_entry(manifest, extensions_base_path=base_path)
    entry = str(debug_payload["entry"] or "").strip()
    if not entry:
        return
    if debug_payload["entry_type"] == "external":
        collector.add_warning(
            "frontend_forum_entry_outside_extensions",
            "frontend_forum_entry 建议使用相对当前扩展根目录的路径，例如 frontend/forum/index.js 或 frontend/dist/forum/index.js",
            extension_id=manifest.id,
            field="frontend_forum_entry",
        )
        return
    expected_entry = expected_frontend_entry(manifest, base_path, "forum")
    if entry != expected_entry and not bool(debug_payload["exists"]):
        collector.add_error(
            "invalid_frontend_forum_entry_path",
            f"frontend_forum_entry 必须指向当前扩展的标准前台入口: {expected_entry}",
            extension_id=manifest.id,
            field="frontend_forum_entry",
        )
        return

    if not debug_payload["exists"]:
        collector.add_error(
            "missing_frontend_forum_entry",
            f"找不到 frontend_forum_entry 对应文件: {entry}",
            extension_id=manifest.id,
            field="frontend_forum_entry",
        )
        return

    required_exports = list(debug_payload["required_exports"])
    available_exports = set(debug_payload["available_exports"])
    for export_name in required_exports:
        if export_name not in available_exports:
            collector.add_error(
                "missing_frontend_forum_export",
                f"frontend_forum_entry 缺少导出: {export_name}",
                extension_id=manifest.id,
                field="frontend_forum_entry",
            )


def _validate_migration_files(
    collector: ExtensionValidationCollector,
    manifest: ExtensionManifest,
    base_path: Path,
) -> None:
    extension_root = extension_root_path(manifest, base_path)
    backend_dir = extension_backend_dir(extension_root, manifest.id)
    legacy_migration_dir = backend_dir / "migrations"
    if legacy_migration_dir.exists():
        collector.add_error(
            "legacy_extension_migration_dir",
            "扩展不能继续使用 legacy backend/migrations；请迁移到 backend/django_migrations 并通过 django_app_config 接入 Django。",
            extension_id=manifest.id,
            field="django_app_config",
        )

    django_app_config = str(manifest.django_app_config or "").strip()
    migration_dir = extension_django_migration_dir(extension_root, manifest.id)
    if not django_app_config:
        if migration_dir.exists():
            collector.add_error(
                "django_migrations_without_app_config",
                "扩展提供了 backend/django_migrations，但 manifest 未声明 django_app_config。",
                extension_id=manifest.id,
                field="django_app_config",
            )
        return

    if not migration_dir.exists():
        collector.add_error(
            "missing_extension_django_migration_dir",
            "manifest 已声明 django_app_config，但 backend/django_migrations 目录不存在",
            extension_id=manifest.id,
            field="django_app_config",
        )
        return

    init_file = migration_dir / "__init__.py"
    if not init_file.exists():
        collector.add_error(
            "missing_extension_django_migration_package",
            "backend/django_migrations 缺少 __init__.py",
            extension_id=manifest.id,
            field="django_app_config",
        )
        return

    migration_files = sorted(
        item for item in migration_dir.glob("*.py")
        if item.name != "__init__.py"
    )
    if not migration_files:
        return

    for file_path in migration_files:
        if not MIGRATION_FILE_PATTERN.match(file_path.name):
            collector.add_warning(
                "invalid_extension_migration_filename",
                f"迁移文件命名建议使用四位编号前缀，例如 0001_initial.py：{file_path.name}",
                extension_id=manifest.id,
                field="django_app_config",
            )

