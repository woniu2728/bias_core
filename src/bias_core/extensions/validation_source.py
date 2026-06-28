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




