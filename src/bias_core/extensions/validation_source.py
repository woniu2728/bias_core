from __future__ import annotations

import ast
from pathlib import Path

from bias_core.extensions.types import ExtensionManifest
from bias_core.extensions.validation_rules import (
    EXTENSION_SOURCE_SUFFIXES,
    FORBIDDEN_CROSS_EXTENSION_INTERNAL_IMPORT_RE,
    FORBIDDEN_EXTENSION_MANIFEST_FIELD_PATTERNS,
    FORBIDDEN_EXTENSION_SOURCE_PATTERNS,
    PUBLIC_EXTENSION_IMPORT_MODULES,
    PYTHON_EXTENSION_IMPORT_PATTERN,
    PYTHON_EXTENSION_INTERNAL_IMPORT_PATTERN,
    SKIPPED_SOURCE_DIRS,
)
from bias_core.extensions.validation_types import ExtensionValidationCollector


RUNTIME_FACADE_EXTENSION_DEPENDENCIES = {
    "apply_runtime_counted_discussion_filter": "discussions",
    "approve_runtime_discussion": "discussions",
    "clamp_runtime_discussion_read_states": "discussions",
    "count_runtime_discussion_pending_approvals": "discussions",
    "create_runtime_discussion": "discussions",
    "delete_runtime_discussion": "discussions",
    "follow_runtime_discussion": "discussions",
    "get_runtime_discussion_approval_approved": "discussions",
    "get_runtime_discussion_model": "discussions",
    "get_runtime_discussion_reply_notification_context": "discussions",
    "get_runtime_discussion_service": "discussions",
    "get_runtime_discussion_state_model": "discussions",
    "get_runtime_discussion_subscription_state": "discussions",
    "get_runtime_visible_discussion_ids": "discussions",
    "has_runtime_discussion_visibility": "discussions",
    "is_runtime_discussion_not_found": "discussions",
    "list_runtime_discussion_approval_queue_items": "discussions",
    "list_runtime_discussions": "discussions",
    "list_runtime_pending_discussion_first_post_ids": "discussions",
    "lock_runtime_discussion_for_post_number": "discussions",
    "mark_runtime_discussion_read": "discussions",
    "process_runtime_discussion_approval_item": "discussions",
    "refresh_runtime_discussion_approved_stats": "discussions",
    "reject_runtime_discussion": "discussions",
    "require_runtime_discussion_service": "discussions",
    "set_runtime_discussion_hidden_state": "discussions",
    "set_runtime_discussion_subscription_state": "discussions",
    "update_runtime_discussion": "discussions",
    "validate_runtime_replyable_discussion": "discussions",
    "approve_runtime_first_post": "content",
    "approve_runtime_post": "posts",
    "can_runtime_view_post": "posts",
    "count_runtime_post_pending_approvals": "posts",
    "create_runtime_first_post": "content",
    "create_runtime_post": "posts",
    "create_runtime_post_event": "posts",
    "delete_runtime_discussion_posts": "content",
    "delete_runtime_post": "posts",
    "get_runtime_content_posts_service": "content",
    "get_runtime_approved_discussion_post_stats": "content",
    "get_runtime_approved_reply_counts_by_author": "content",
    "get_runtime_discussion_post_number": "content",
    "get_runtime_discussion_posts_service": "content",
    "get_runtime_first_post": "content",
    "get_runtime_post_action_context": "posts",
    "get_runtime_post_approval_approved": "posts",
    "get_runtime_post_approval_pending": "posts",
    "get_runtime_post_approval_rejected": "posts",
    "get_runtime_post_by_id": "posts",
    "get_runtime_post_model": "posts",
    "get_runtime_post_model_or_none": "posts",
    "get_runtime_post_notification_context": "posts",
    "get_runtime_post_number": "posts",
    "get_runtime_post_reply_notification_context": "posts",
    "get_runtime_post_service": "posts",
    "get_runtime_visible_post_ids": "posts",
    "is_runtime_post_not_found": "posts",
    "list_runtime_post_approval_queue_items": "posts",
    "process_runtime_post_approval_item": "posts",
    "reject_runtime_first_post": "content",
    "reject_runtime_post": "posts",
    "require_runtime_post_service": "posts",
    "resubmit_runtime_first_post": "content",
    "resolve_runtime_discussion_post_content_html": "content",
    "resolve_runtime_post_content_html": "posts",
    "serialize_runtime_post": "posts",
    "serialize_runtime_post_by_id": "posts",
    "serialize_runtime_realtime_post_by_id": "realtime",
    "set_runtime_post_hidden_state": "posts",
    "update_runtime_first_post_content": "content",
    "update_runtime_post": "posts",
    "apply_runtime_user_comment_count_deltas": "users",
    "apply_runtime_user_group_processors": "users",
    "ensure_runtime_admin_user": "users",
    "ensure_runtime_forum_permission": "users",
    "ensure_runtime_user_email_confirmed": "users",
    "ensure_runtime_user_not_suspended": "users",
    "get_runtime_forum_permissions": "users",
    "get_runtime_group_model": "users",
    "get_runtime_permission_model": "users",
    "get_runtime_user_by_id": "users",
    "get_runtime_user_model": "users",
    "get_runtime_user_preference": "users",
    "get_runtime_user_service": "users",
    "get_runtime_username_id_map": "users",
    "has_runtime_forum_permission": "users",
    "increment_runtime_user_comment_count": "users",
    "increment_runtime_user_discussion_count": "users",
    "list_runtime_users_by_usernames": "users",
    "require_runtime_user_service": "users",
    "requires_runtime_content_approval": "users",
    "resolve_runtime_user_by_username": "users",
    "serialize_runtime_user": "users",
    "serialize_runtime_users_by_ids": "users",
    "verify_runtime_user_password": "users",
    "can_runtime_add_to_discussion": "tags",
    "can_runtime_reply_in_tag": "tags",
    "can_runtime_start_discussion_in_tag": "tags",
    "can_runtime_view_tag": "tags",
    "create_runtime_tag": "tags",
    "delete_runtime_tag": "tags",
    "dispatch_runtime_tag_stats_refresh": "tags",
    "ensure_can_change_runtime_discussion_tags": "tags",
    "ensure_can_start_discussion_in_runtime_tags": "tags",
    "filter_runtime_tags_for_user": "tags",
    "get_runtime_discussion_tag_model": "tags",
    "get_runtime_tag_model": "tags",
    "get_runtime_tag_scope_label": "tags",
    "get_runtime_tag_service": "tags",
    "get_runtime_tag_state_for_user": "tags",
    "get_runtime_tag_state_model": "tags",
    "get_runtime_tag_summaries_by_slugs": "tags",
    "mark_runtime_tag_read": "tags",
    "move_runtime_tag": "tags",
    "order_runtime_tags": "tags",
    "prefetch_runtime_tag_state_for_user": "tags",
    "refresh_runtime_discussion_tag_stats": "tags",
    "refresh_runtime_tag_stats": "tags",
    "require_runtime_tag_service": "tags",
    "runtime_tag_method": "tags",
    "update_runtime_tag": "tags",
    "validate_runtime_tag_parent_assignment": "tags",
    "validate_runtime_tag_scope_configuration": "tags",
    "create_runtime_notification": "notifications",
    "delete_runtime_notifications": "notifications",
    "delete_runtime_discussion_reply_notifications_for_post": "notifications",
    "get_runtime_notification_model": "notifications",
    "get_runtime_notification_service": "notifications",
    "notify_runtime_notification": "notifications",
    "require_runtime_notification_service": "notifications",
    "sync_runtime_notifications": "notifications",
    "apply_runtime_discussion_search": "search",
    "get_runtime_search_extension_service": "search",
    "get_runtime_search_service": "search",
    "can_runtime_like_post": "likes",
    "get_runtime_like_service": "likes",
    "get_runtime_post_like_model": "likes",
    "like_runtime_post": "likes",
    "require_runtime_like_service": "likes",
    "unlike_runtime_post": "likes",
    "delete_runtime_post_flags": "flags",
    "get_runtime_flag_service": "flags",
    "get_runtime_post_flag_model": "flags",
    "list_runtime_post_flags": "flags",
    "report_runtime_post_flag": "flags",
    "require_runtime_flag_service": "flags",
    "resolve_runtime_post_flag": "flags",
    "resolve_runtime_post_flags": "flags",
    "bulk_process_runtime_approval_items": "approval",
    "get_runtime_approval_service": "approval",
    "list_runtime_approval_queue_items": "approval",
    "process_runtime_approval_item": "approval",
    "require_runtime_approval_service": "approval",
    "broadcast_runtime_discussion_event": "realtime",
    "create_runtime_timeline_from_builder": "discussions",
    "get_runtime_discussion_lifecycle_service": "discussions",
    "get_runtime_timeline_service": "discussions",
}


def _extension_import_match_parts(match) -> tuple[str, str]:
    groups = match.groups()
    if len(groups) >= 6:
        imported_module = groups[0] or groups[1] or groups[3] or groups[4] or ""
        imported_tail = groups[2] or groups[5] or ""
        return str(imported_module or "").strip(), str(imported_tail or "").strip()
    imported_module = str(match.group(1) or match.group(3) or "").strip()
    imported_tail = str(match.group(2) or match.group(4) or "").strip()
    return imported_module, imported_tail


def validate_distribution_signature(
    collector: ExtensionValidationCollector,
    manifest: ExtensionManifest,
    base_path: Path,
) -> None:
    signature_url = str(manifest.distribution.signature_url or "").strip()
    if not signature_url or is_remote_url(signature_url):
        return

    signature_path = resolve_extension_local_path(signature_url, manifest=manifest, base_path=base_path)
    if not signature_path.exists() or not signature_path.is_file():
        collector.add_warning(
            "missing_distribution_signature_file",
            f"distribution.signature_url 指向的本地签名文件不存在: {signature_url}",
            extension_id=manifest.id,
            field="distribution.signature_url",
        )


def validate_manifest_field_contracts(
    collector: ExtensionValidationCollector,
    manifest: ExtensionManifest,
    base_path: Path,
) -> None:
    manifest_path = extension_root_path(manifest, base_path) / "extension.json"
    if not manifest_path.exists():
        return
    try:
        source = manifest_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return

    relative_path = manifest_path.relative_to(base_path.parent).as_posix()
    for code, pattern, message in FORBIDDEN_EXTENSION_MANIFEST_FIELD_PATTERNS:
        if pattern.search(source):
            collector.add_error(
                code,
                f"{message} 文件: {relative_path}",
                extension_id=manifest.id,
                field=relative_path,
            )


def validate_extension_source_contracts(
    collector: ExtensionValidationCollector,
    manifest: ExtensionManifest,
    base_path: Path,
) -> None:
    extension_dir = extension_root_path(manifest, base_path)
    if not extension_dir.exists():
        return

    for file_path in iter_extension_source_files(extension_dir):
        try:
            source = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        relative_path = file_path.relative_to(base_path.parent).as_posix()
        for code, pattern, message in FORBIDDEN_EXTENSION_SOURCE_PATTERNS:
            if pattern.search(source):
                collector.add_error(
                    code,
                    f"{message} 文件: {relative_path}",
                    extension_id=manifest.id,
                    field=relative_path,
                )


def validate_cross_extension_imports(
    collector: ExtensionValidationCollector,
    manifest: ExtensionManifest,
    base_path: Path,
    *,
    known_extension_ids: set[str],
    public_sdk_only: bool = False,
    include_tests: bool = False,
    check_runtime_facade_dependencies: bool = False,
    capability_providers: dict[str, str] | None = None,
) -> None:
    extension_dir = extension_root_path(manifest, base_path)
    if not extension_dir.exists():
        return

    required_dependencies = set(manifest.dependencies)
    optional_dependencies = set(manifest.optional_dependencies)
    for file_path in iter_extension_runtime_python_files(extension_dir, include_tests=include_tests):
        try:
            source = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        relative_path = file_path.relative_to(base_path.parent).as_posix()
        validate_conditional_extension_dependencies(
            collector,
            manifest,
            source,
            relative_path,
            known_extension_ids=known_extension_ids,
        )
        validate_public_contract_extension_dependencies(
            collector,
            manifest,
            source,
            relative_path,
            known_extension_ids=known_extension_ids,
        )
        if check_runtime_facade_dependencies:
            validate_runtime_facade_extension_dependencies(
                collector,
                manifest,
                source,
                relative_path,
                known_extension_ids=known_extension_ids,
                capability_providers=capability_providers,
            )
        validate_event_contract_paths(
            collector,
            manifest,
            source,
            relative_path,
        )
        internal_import_spans: set[tuple[int, int]] = set()
        for match in PYTHON_EXTENSION_INTERNAL_IMPORT_PATTERN.finditer(source):
            imported_module, imported_tail = _extension_import_match_parts(match)
            imported_extension_id = imported_module.replace("_", "-")
            if (
                not imported_extension_id
                or imported_extension_id == manifest.id
                or imported_extension_id not in known_extension_ids
                or not FORBIDDEN_CROSS_EXTENSION_INTERNAL_IMPORT_RE.match(imported_tail)
            ):
                continue
            internal_import_spans.add(match.span())
            collector.add_error(
                "forbidden_cross_extension_internal_import",
                f"扩展源码导入了 {imported_extension_id} 的内部 {imported_tail.lstrip('.')} 模块。"
                "跨扩展业务协作必须通过宿主 runtime service、事件或公开 extender capability，不能直接依赖其它扩展的内部 backend 模块。",
                extension_id=manifest.id,
                field=relative_path,
            )

        for match in PYTHON_EXTENSION_IMPORT_PATTERN.finditer(source):
            if match.span() in internal_import_spans:
                continue
            imported_module, _imported_tail = _extension_import_match_parts(match)
            imported_extension_id = imported_module.replace("_", "-")
            if (
                not imported_extension_id
                or imported_extension_id == manifest.id
                or imported_extension_id not in known_extension_ids
            ):
                continue
            if imported_extension_id in optional_dependencies:
                collector.add_error(
                    "optional_dependency_top_level_import",
                    f"扩展源码在模块顶层导入了可选依赖 {imported_extension_id}。"
                    "可选依赖必须通过 ConditionalExtender 与函数内延迟导入表达，避免未启用扩展被硬加载。",
                    extension_id=manifest.id,
                    field=relative_path,
                )
                continue
            if imported_extension_id in required_dependencies:
                continue
            collector.add_error(
                "undeclared_cross_extension_import",
                f"扩展源码导入了 {imported_extension_id}，但未在 dependencies 或 optional_dependencies 中声明。"
                "请通过扩展依赖显式表达跨扩展耦合。",
                extension_id=manifest.id,
                field=relative_path,
            )

        if public_sdk_only:
            validate_public_sdk_imports(collector, manifest, source, relative_path)


def validate_runtime_facade_extension_dependencies(
    collector: ExtensionValidationCollector,
    manifest: ExtensionManifest,
    source: str,
    relative_path: str,
    *,
    known_extension_ids: set[str],
    capability_providers: dict[str, str] | None = None,
) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return

    declared_dependency_ids = set(manifest.dependencies) | set(manifest.optional_dependencies)
    for imported_name, required_extension_id in iter_runtime_facade_extension_references(tree):
        required_provider_id = resolve_capability_provider_id(
            required_extension_id,
            capability_providers=capability_providers,
        )
        if not _is_missing_extension_dependency(
            manifest,
            required_provider_id,
            known_extension_ids=known_extension_ids,
            declared_dependency_ids=declared_dependency_ids,
        ):
            continue
        collector.add_error(
            "undeclared_runtime_facade_dependency",
            f"扩展源码通过 runtime facade {imported_name} 访问了 {required_extension_id}，"
            "但未在 dependencies 或 optional_dependencies 中声明。"
            "运行时 facade 会影响启动顺序和可选扩展加载，必须显式表达依赖关系。",
            extension_id=manifest.id,
            field=relative_path,
        )


def validate_runtime_facade_dependency_graph(
    collector: ExtensionValidationCollector,
    manifests: list[ExtensionManifest],
    base_path: Path,
    *,
    known_extension_ids: set[str],
    include_tests: bool = False,
    capability_providers: dict[str, str] | None = None,
) -> None:
    manifest_ids = {manifest.id for manifest in manifests}
    graph: dict[str, set[str]] = {manifest.id: set() for manifest in manifests}
    runtime_edges: dict[tuple[str, str], list[tuple[str, str]]] = {}

    for manifest in manifests:
        for dependency_id in (*manifest.dependencies, *manifest.optional_dependencies):
            if dependency_id in manifest_ids:
                graph[manifest.id].add(dependency_id)

        extension_dir = extension_root_path(manifest, base_path)
        if not extension_dir.exists():
            continue
        for file_path in iter_extension_runtime_python_files(extension_dir, include_tests=include_tests):
            try:
                source = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            relative_path = file_path.relative_to(base_path.parent).as_posix()
            for imported_name, required_extension_id in iter_runtime_facade_extension_references(tree):
                required_provider_id = resolve_capability_provider_id(
                    required_extension_id,
                    capability_providers=capability_providers,
                )
                if (
                    not required_provider_id
                    or required_provider_id == manifest.id
                    or required_provider_id not in known_extension_ids
                    or required_provider_id not in manifest_ids
                ):
                    continue
                graph[manifest.id].add(required_provider_id)
                runtime_edges.setdefault((manifest.id, required_provider_id), []).append(
                    (relative_path, imported_name)
                )

    for cycle in _find_dependency_cycles(graph):
        cycle_edges = list(zip(cycle, (*cycle[1:], cycle[0])))
        inferred_edges = [
            (source_id, target_id, runtime_edges[(source_id, target_id)])
            for source_id, target_id in cycle_edges
            if (source_id, target_id) in runtime_edges
        ]
        if not inferred_edges:
            continue
        cycle_text = " -> ".join((*cycle, cycle[0]))
        for source_id, target_id, references in inferred_edges:
            fields = sorted({field for field, _name in references})
            names = sorted({name for _field, name in references})
            names_text = ", ".join(names[:8])
            if len(names) > 8:
                names_text = f"{names_text}, ..."
            fields_text = ", ".join(fields[:4])
            if len(fields) > 4:
                fields_text = f"{fields_text}, ..."
            collector.add_error(
                "runtime_facade_dependency_cycle",
                f"runtime facade 推断出 {source_id} -> {target_id} 依赖，"
                f"与现有依赖图形成循环: {cycle_text}。"
                f"涉及 facade: {names_text or '-'}。涉及文件: {fields_text or '-'}。"
                "这类问题不能靠补 manifest 依赖解决，需要合并领域边界或把共享生命周期契约下沉到更低层。",
                extension_id=source_id,
                field=fields[0] if fields else "dependencies",
            )


def validate_conditional_extension_dependencies(
    collector: ExtensionValidationCollector,
    manifest: ExtensionManifest,
    source: str,
    relative_path: str,
    *,
    known_extension_ids: set[str],
) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return

    declared_dependency_ids = set(manifest.dependencies) | set(manifest.optional_dependencies)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if not isinstance(function, ast.Attribute):
            continue
        if function.attr not in {"when_extension_enabled", "when_extension_disabled"}:
            continue
        if not node.args:
            continue
        extension_id_node = node.args[0]
        if not isinstance(extension_id_node, ast.Constant) or not isinstance(extension_id_node.value, str):
            continue
        extension_id = extension_id_node.value.strip()
        if not _is_missing_extension_dependency(
            manifest,
            extension_id,
            known_extension_ids=known_extension_ids,
            declared_dependency_ids=declared_dependency_ids,
        ):
            continue
        collector.add_error(
            "undeclared_conditional_extension_dependency",
            f"扩展源码条件接入了 {extension_id}，但未在 optional_dependencies 中声明。"
            "ConditionalExtender 的扩展 ID 会影响启动顺序，必须通过 optional_dependencies 显式表达。",
            extension_id=manifest.id,
            field=relative_path,
        )


def validate_public_contract_extension_dependencies(
    collector: ExtensionValidationCollector,
    manifest: ExtensionManifest,
    source: str,
    relative_path: str,
    *,
    known_extension_ids: set[str],
) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return

    declared_dependency_ids = set(manifest.dependencies) | set(manifest.optional_dependencies)
    for extension_id, kind, value in iter_public_contract_extension_references(tree):
        if not _is_missing_extension_dependency(
            manifest,
            extension_id,
            known_extension_ids=known_extension_ids,
            declared_dependency_ids=declared_dependency_ids,
        ):
            continue
        collector.add_error(
            "undeclared_public_contract_extension_dependency",
            f"扩展源码通过公开 {kind} 契约引用了 {extension_id}（{value}），"
            "但未在 dependencies 或 optional_dependencies 中声明。"
            "事件别名、RuntimeModel 与 runtime service 字符串同样会影响启动顺序，必须显式表达依赖关系。",
            extension_id=manifest.id,
            field=relative_path,
        )


def validate_event_contract_paths(
    collector: ExtensionValidationCollector,
    manifest: ExtensionManifest,
    source: str,
    relative_path: str,
) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return

    for value in iter_event_contract_values(tree):
        if _is_legacy_extension_internal_event_path(value):
            collector.add_error(
                "forbidden_internal_event_contract_path",
                f"扩展事件契约使用了内部事件类路径 {value}。"
                "跨扩展事件必须通过提供方公开的事件别名引用，例如 posts.post.created。",
                extension_id=manifest.id,
                field=relative_path,
            )


def iter_public_contract_extension_references(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            function = node.func
            if (
                isinstance(function, ast.Name)
                and function.id == "RuntimeModel"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                value = node.args[0].value.strip()
                extension_id = _extension_id_from_runtime_service_key(value)
                if extension_id:
                    yield extension_id, "RuntimeModel", value
            event_alias = _event_alias_from_event_contract_call(node)
            if event_alias:
                extension_id = _extension_id_from_event_alias(event_alias)
                if extension_id:
                    yield extension_id, "event alias", event_alias


def iter_runtime_facade_extension_references(tree: ast.AST):
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if getattr(node, "level", 0):
            continue
        module = str(node.module or "").strip()
        if module != "bias_core.extensions.runtime":
            continue
        for alias in node.names:
            imported_name = str(alias.name or "").strip()
            required_extension_id = RUNTIME_FACADE_EXTENSION_DEPENDENCIES.get(imported_name)
            if required_extension_id:
                yield imported_name, required_extension_id


def iter_event_contract_values(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            value = _event_alias_from_event_contract_call(node)
            if value:
                yield value


def _is_legacy_extension_internal_event_path(value: str) -> bool:
    normalized = str(value or "").strip()
    return normalized.startswith("extensions.") and ".backend." in normalized


def _extension_id_from_runtime_service_key(value: str) -> str:
    normalized = str(value or "").strip()
    if "." not in normalized:
        return ""
    extension_id, suffix = normalized.split(".", 1)
    if suffix != "service" and not suffix.startswith("service."):
        return ""
    return extension_id.strip()


def _extension_id_from_event_alias(value: str) -> str:
    normalized = str(value or "").strip()
    parts = normalized.split(".")
    if len(parts) < 3:
        return ""
    extension_id = parts[0].strip()
    domain = parts[1].strip()
    event_name = ".".join(parts[2:]).strip()
    if not extension_id or not domain or not event_name:
        return ""
    return extension_id


def _event_alias_from_event_contract_call(node: ast.Call) -> str:
    function = node.func
    if isinstance(function, ast.Name) and function.id == "ExtensionEventListenerDefinition":
        for keyword in node.keywords:
            if keyword.arg == "event_type":
                return _string_constant_value(keyword.value)
        if node.args:
            return _string_constant_value(node.args[0])
        return ""
    if isinstance(function, ast.Attribute) and function.attr == "broadcast_discussion_event":
        if node.args:
            return _string_constant_value(node.args[0])
        for keyword in node.keywords:
            if keyword.arg == "event_type":
                return _string_constant_value(keyword.value)
    return ""


def _string_constant_value(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.strip()
    return ""


def _is_missing_extension_dependency(
    manifest: ExtensionManifest,
    extension_id: str,
    *,
    known_extension_ids: set[str],
    declared_dependency_ids: set[str],
) -> bool:
    normalized = str(extension_id or "").strip()
    return bool(
        normalized
        and normalized != manifest.id
        and normalized in known_extension_ids
        and normalized not in declared_dependency_ids
    )


def build_capability_provider_map(manifests: list[ExtensionManifest]) -> dict[str, str]:
    providers: dict[str, str] = {}
    manifest_ids = {manifest.id for manifest in manifests}
    for manifest_id in sorted(manifest_ids):
        providers[manifest_id] = manifest_id
    for manifest in sorted(manifests, key=lambda item: item.id):
        for capability in manifest.provides:
            normalized = str(capability or "").strip()
            if normalized and normalized not in providers:
                providers[normalized] = manifest.id
    return providers


def resolve_capability_provider_id(
    extension_id: str,
    *,
    capability_providers: dict[str, str] | None,
) -> str:
    normalized = str(extension_id or "").strip()
    if not normalized:
        return ""
    if not capability_providers:
        return normalized
    return str(capability_providers.get(normalized) or normalized).strip()


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


def validate_public_sdk_imports(
    collector: ExtensionValidationCollector,
    manifest: ExtensionManifest,
    source: str,
    relative_path: str,
) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return

    for imported_path in iter_core_import_paths(tree):
        if imported_path == "bias_core":
            collector.add_error(
                "forbidden_core_internal_import",
                "扩展源码不能直接导入 bias_core 内部模块；请只使用 bias_core.extensions 暴露的公共 SDK 接口。",
                extension_id=manifest.id,
                field=relative_path,
            )
            continue
        if is_public_extension_sdk_import(imported_path):
            continue
        collector.add_error(
            "forbidden_core_internal_import",
            "扩展源码不能直接导入 bias_core 内部模块；请只使用 bias_core.extensions 暴露的公共 SDK 接口。",
            extension_id=manifest.id,
            field=relative_path,
        )


def is_public_extension_sdk_import(imported_path: str) -> bool:
    normalized = str(imported_path or "").strip()
    return normalized in PUBLIC_EXTENSION_IMPORT_MODULES


def iter_core_import_paths(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = str(alias.name or "").strip()
                if name == "bias_core" or name.startswith("bias_core."):
                    yield normalize_core_public_import_path(name)
        elif isinstance(node, ast.ImportFrom):
            if getattr(node, "level", 0):
                continue
            module = str(node.module or "").strip()
            if module == "bias_core":
                yield "bias_core"
            elif module.startswith("bias_core."):
                yield normalize_core_public_import_path(module)


def normalize_core_public_import_path(module: str) -> str:
    parts = str(module or "").strip().split(".")
    if parts[:2] == ["bias_core", "extensions"]:
        if len(parts) <= 2:
            return ".".join(parts[:2])
        facade = ".".join(parts[:3])
        if facade in PUBLIC_EXTENSION_IMPORT_MODULES:
            return ".".join(parts)
        return ".".join(parts[:3])
    if len(parts) <= 2:
        return "bias_core"
    return ".".join(parts[:3])


def iter_extension_source_files(extension_dir: Path):
    for file_path in extension_dir.rglob("*"):
        if not file_path.is_file():
            continue
        if any(part in SKIPPED_SOURCE_DIRS for part in file_path.parts):
            continue
        if file_path.suffix.lower() not in EXTENSION_SOURCE_SUFFIXES:
            continue
        yield file_path


def iter_extension_runtime_python_files(extension_dir: Path, *, include_tests: bool = False):
    for file_path in extension_dir.rglob("*.py"):
        if not file_path.is_file():
            continue
        skipped_source_dirs = SKIPPED_SOURCE_DIRS - {"tests"} if include_tests else SKIPPED_SOURCE_DIRS
        if any(part in skipped_source_dirs for part in file_path.parts):
            continue
        if not include_tests and (
            file_path.name == "tests.py" or file_path.name.startswith("test_") or file_path.name.endswith("_test.py")
        ):
            continue
        yield file_path


def is_remote_url(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized.startswith(("http://", "https://"))


def resolve_extension_local_path(value: str, *, manifest: ExtensionManifest, base_path: Path) -> Path:
    normalized = str(value or "").strip()
    if normalized.startswith("file://"):
        normalized = normalized[7:]
    path = Path(normalized)
    if path.is_absolute():
        return path
    root_path = extension_root_path(manifest, base_path)
    return root_path / path


def extension_root_path(manifest: ExtensionManifest, base_path: Path) -> Path:
    manifest_path = str(getattr(manifest, "path", "") or "").strip()
    return Path(manifest_path) if manifest_path else Path(base_path) / manifest.id




