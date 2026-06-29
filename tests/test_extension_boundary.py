from tests.common import *
import ast
import importlib
import os
import subprocess
import sys


def core_source_root() -> Path:
    return Path(settings.BASE_DIR) / "src" / "bias_core"


def extension_backend_roots() -> list[tuple[str, Path]]:
    site_extensions_root = Path(settings.BASE_DIR) / "extensions"
    roots: list[tuple[str, Path]] = []

    if site_extensions_root.exists():
        for extension_dir in site_extensions_root.iterdir():
            backend_root = extension_dir / "backend"
            if backend_root.is_dir():
                roots.append((extension_dir.name, backend_root))
        return roots

    workspace_root = Path(settings.BASE_DIR).parent
    for extension_dir in sorted(workspace_root.glob("bias-ext-*")):
        package_name = extension_dir.name.replace("-", "_")
        backend_root = extension_dir / package_name / "backend"
        if backend_root.is_dir():
            roots.append((extension_dir.name.removeprefix("bias-ext-"), backend_root))

    return roots


def iter_extension_backend_files():
    for extension_id, backend_root in extension_backend_roots():
        for path in backend_root.glob("**/*.py"):
            if path.name == "tests.py" or "django_migrations" in path.parts:
                continue
            yield extension_id, path


def extension_source_backend_root(extension_id: str) -> Path | None:
    workspace_root = Path(settings.BASE_DIR).parent
    extension_dir = workspace_root / f"bias-ext-{extension_id}"
    package_root = extension_dir / f"bias_ext_{extension_id.replace('-', '_')}" / "backend"
    if package_root.is_dir():
        return package_root
    return None


def relative_to_known_root(path: Path) -> str:
    try:
        return str(path.relative_to(settings.BASE_DIR))
    except ValueError:
        return str(path)


def iter_python_imports(path: Path):
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.lineno, node.module

class ExtensionPublicApiBoundaryTests(TestCase):
    def test_extension_public_package_import_is_lightweight_without_django_settings(self):
        env = os.environ.copy()
        env.pop("DJANGO_SETTINGS_MODULE", None)
        env["PYTHONPATH"] = str(core_source_root().parent)
        code = (
            "import bias_core.extensions\n"
            "import importlib\n"
            "from bias_core.extensions.validation_rules import PUBLIC_EXTENSION_IMPORT_MODULES\n"
            "for module_name in sorted(PUBLIC_EXTENSION_IMPORT_MODULES):\n"
            "    importlib.import_module(module_name)\n"
            "from bias_core.extensions import (\n"
            "    ApiResourceExtender,\n"
            "    ConditionalExtender,\n"
            "    EventListenersExtender,\n"
            "    FrontendExtender,\n"
            "    LifecycleExtender,\n"
            "    ModelExtender,\n"
            "    RoutesExtender,\n"
            "    ServiceProviderExtender,\n"
            "    SettingsExtender,\n"
            "    sdk,\n"
            "    setting_field,\n"
            "    ExtensionManifestSettingFieldDefinition,\n"
            ")\n"
            "field = setting_field(key='alpha.enabled', label='Enabled')\n"
            "assert isinstance(field, ExtensionManifestSettingFieldDefinition)\n"
            "assert FrontendExtender().forum('forum.js').forum_entry == 'forum.js'\n"
            "assert SettingsExtender(fields=(field,)).fields == (field,)\n"
            "assert LifecycleExtender().lifecycle_hook_keys == ()\n"
            "assert ApiResourceExtender('discussions').resource_name == 'discussions'\n"
            "assert RoutesExtender().get('/alpha', 'alpha.index', lambda: None).routes\n"
            "assert ConditionalExtender().callbacks == ()\n"
            "assert ModelExtender(model='alpha').model == 'alpha'\n"
            "assert EventListenersExtender().listeners == ()\n"
            "assert ServiceProviderExtender('alpha', object()).key == 'alpha'\n"
            "from bias_core.extensions import platform\n"
            "from bias_core.extensions.platform import api_error, get_forum_registry, set_access_token_cookie\n"
            "assert 'set_access_token_cookie' in platform.__all__\n"
            "assert set_access_token_cookie.__name__ == 'set_access_token_cookie'\n"
            "assert api_error.__name__ == 'api_error'\n"
            "assert get_forum_registry.__name__ == 'get_forum_registry'\n"
        )

        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=settings.BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_public_sdk_import_whitelist_modules_are_importable(self):
        from bias_core.extensions.validation_rules import PUBLIC_EXTENSION_IMPORT_MODULES

        for module_name in sorted(PUBLIC_EXTENSION_IMPORT_MODULES):
            with self.subTest(module_name=module_name):
                importlib.import_module(module_name)

    def test_public_sdk_exports_common_extension_definitions_and_helpers(self):
        from bias_core.extensions import (
            ExtensionEventListenerDefinition,
            ExtensionManifestRuntimeActionDefinition,
            ExtensionManifestSettingFieldDefinition,
            PermissionDefinition,
            ResourceEndpointDefinition,
            ResourceFieldDefinition,
            ResourceFieldMutatorDefinition,
            admin_action,
            event_listener,
            runtime_action,
            setting_field,
        )

        def handler(event):
            return event

        setting = setting_field(key="alpha.enabled", label="Alpha", type="boolean", default=True)
        runtime = runtime_action(key="rebuild", label="Rebuild", hook="run_rebuild_cache")
        admin = admin_action(key="settings", label="Settings", target="/admin/extensions/alpha")
        listener = event_listener(event_type=AlphaStringEvent, handler=handler, description="Alpha listener")

        self.assertIsInstance(setting, ExtensionManifestSettingFieldDefinition)
        self.assertEqual(setting.key, "alpha.enabled")
        self.assertIsInstance(runtime, ExtensionManifestRuntimeActionDefinition)
        self.assertEqual(runtime.hook, "run_rebuild_cache")
        self.assertEqual(admin.target, "/admin/extensions/alpha")
        self.assertIsInstance(listener, ExtensionEventListenerDefinition)
        self.assertIs(listener.event_type, AlphaStringEvent)
        self.assertEqual(PermissionDefinition.__name__, "PermissionDefinition")
        self.assertEqual(ResourceEndpointDefinition.__name__, "ResourceEndpointDefinition")
        self.assertEqual(ResourceFieldDefinition.__name__, "ResourceFieldDefinition")
        self.assertEqual(ResourceFieldMutatorDefinition.__name__, "ResourceFieldMutatorDefinition")

    def test_runtime_facade_exports_extension_runtime_helpers(self):
        from bias_core.extensions import runtime

        self.assertTrue(callable(runtime.get_runtime_user_by_id))
        self.assertTrue(callable(runtime.get_runtime_resource_registry))
        self.assertTrue(callable(runtime.notify_runtime_notification))

    def test_platform_sdk_exports_auth_and_cookie_helpers(self):
        from bias_core.extensions import platform

        expected = (
            "auth_cookie_secure",
            "clear_access_token_cookie",
            "clear_refresh_token_cookie",
            "require_forum_permission",
            "require_staff",
            "resolve_authenticated_user",
            "resolve_user_from_refresh_token",
            "set_access_token_cookie",
            "set_refresh_token_cookie",
        )

        for name in expected:
            self.assertIn(name, platform.__all__)
            self.assertTrue(callable(getattr(platform, name)))

    def test_platform_sdk_exports_jsonapi_response_helpers(self):
        from bias_core.extensions import platform

        self.assertIn("JSONAPI_CONTENT_TYPE", platform.__all__)
        self.assertIn("jsonapi_response", platform.__all__)
        self.assertIn("serialize_resource_jsonapi_response", platform.__all__)
        self.assertIn("serialize_resource_plain", platform.__all__)
        self.assertIn("wants_jsonapi_response", platform.__all__)
        self.assertEqual(platform.JSONAPI_CONTENT_TYPE, "application/vnd.api+json")
        self.assertTrue(callable(platform.jsonapi_response))
        self.assertTrue(callable(platform.serialize_resource_jsonapi_response))
        self.assertTrue(callable(platform.serialize_resource_plain))
        self.assertTrue(callable(platform.wants_jsonapi_response))

    def test_builtin_extension_admin_code_uses_platform_staff_guard(self):
        violations = []
        forbidden = (
            "def _require_staff",
            "not request.auth or not request.auth.is_staff",
            "request.auth.is_staff",
        )

        for _, path in iter_extension_backend_files():
            text = path.read_text(encoding="utf-8")
            for marker in forbidden:
                if marker in text:
                    violations.append(f"{relative_to_known_root(path)}: {marker}")

        self.assertEqual(violations, [])

    def test_sdk_exports_contracts_without_direct_internal_definition_imports(self):
        from bias_core.extensions import contracts

        self.assertEqual(contracts.PermissionDefinition.__name__, "PermissionDefinition")
        self.assertEqual(contracts.ExtensionModelVisibilityDefinition.__name__, "ExtensionModelVisibilityDefinition")
        self.assertEqual(contracts.ResourceEndpointDefinition.__name__, "ResourceEndpointDefinition")

        sdk_path = core_source_root() / "extensions" / "sdk.py"
        sdk_source = sdk_path.read_text(encoding="utf-8")
        forbidden = (
            "from bias_core.extensions.types",
            "from bias_core.forum_registry_types",
            "from bias_core.resource_registry",
        )
        self.assertFalse(any(marker in sdk_source for marker in forbidden))

    def test_builtin_extension_runtime_code_uses_public_api_facades(self):
        forbidden = (
            "from bias_core.extensions.runtime_access",
            "from bias_core.extensions import runtime_access",
            "from bias_core.extensions.types",
            "from bias_core.forum_registry_types",
            "from bias_core.resource_registry",
        )
        violations = []
        for _, path in iter_extension_backend_files():
            text = path.read_text(encoding="utf-8")
            for marker in forbidden:
                if marker in text:
                    violations.append(f"{relative_to_known_root(path)}: {marker}")

        self.assertEqual(violations, [])

    def test_builtin_extension_runtime_code_does_not_import_private_core_modules(self):
        forbidden = (
            "from bias_core.api_errors",
            "from bias_core.audit",
            "from bias_core.auth",
            "from bias_core.authorization",
            "from bias_core.domain_events",
            "from bias_core.extension_settings_service",
            "from bias_core.extensions.backend",
            "from bias_core.extensions.extenders",
            "from bias_core.extensions.policy_runtime_service",
            "from bias_core.email_service",
            "from bias_core.file_service",
            "from bias_core.forum_registry",
            "from bias_core.forum_runtime",
            "from bias_core.forum_permissions",
            "from bias_core.jwt_auth",
            "from bias_core.mail_drivers",
            "from bias_core.markdown_service",
            "from bias_core.models",
            "from bias_core.online_service",
            "from bias_core.queue_service",
            "from bias_core.resource_api",
            "from bias_core.resource_errors",
            "from bias_core.resource_objects",
            "from bias_core.runtime_checks",
            "from bias_core.schemas",
            "from bias_core.search_index_service",
            "from bias_core.services",
            "from bias_core.settings_service",
            "from bias_core.storage_service",
            "from bias_core.visibility",
        )
        violations = []
        for _, path in iter_extension_backend_files():
            text = path.read_text(encoding="utf-8")
            for marker in forbidden:
                if marker in text:
                    violations.append(f"{relative_to_known_root(path)}: {marker}")

        self.assertEqual(violations, [])

    def test_builtin_extension_runtime_code_uses_platform_facade_for_common_core_helpers(self):
        forbidden = (
            "from bias_core.api_errors",
            "from bias_core.audit",
            "from bias_core.auth",
            "from bias_core.authorization",
            "from bias_core.domain_events",
            "from bias_core.extension_settings_service",
            "from bias_core.extensions.policy_runtime_service",
            "from bias_core.email_service",
            "from bias_core.file_service",
            "from bias_core.forum_registry",
            "from bias_core.forum_runtime",
            "from bias_core.forum_permissions",
            "from bias_core.jwt_auth",
            "from bias_core.mail_drivers",
            "from bias_core.markdown_service",
            "from bias_core.models",
            "from bias_core.online_service",
            "from bias_core.queue_service",
            "from bias_core.resource_api",
            "from bias_core.resource_errors",
            "from bias_core.resource_objects",
            "from bias_core.runtime_checks",
            "from bias_core.schemas",
            "from bias_core.search_index_service",
            "from bias_core.services",
            "from bias_core.settings_service",
            "from bias_core.storage_service",
            "from bias_core.visibility",
        )
        violations = []
        for _, path in iter_extension_backend_files():
            text = path.read_text(encoding="utf-8")
            for marker in forbidden:
                if marker in text:
                    violations.append(f"{relative_to_known_root(path)}: {marker}")

        self.assertEqual(violations, [])

    def test_builtin_extension_backend_code_does_not_import_other_extension_backends(self):
        violations = []
        backend_roots = extension_backend_roots()
        for source_extension, backend_root in backend_roots:
            for path in backend_root.glob("**/*.py"):
                if path.name == "tests.py" or "django_migrations" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8")
                for target_extension, _ in backend_roots:
                    if target_extension == source_extension:
                        continue
                    target_name = target_extension.replace("-", "_")
                    markers = (
                        f"from extensions.{target_name}.backend",
                        f"import extensions.{target_name}.backend",
                        f"from bias_ext_{target_name}.backend",
                        f"import bias_ext_{target_name}.backend",
                    )
                    if any(marker in text for marker in markers):
                        violations.append(f"{relative_to_known_root(path)}: {target_name}")

        self.assertEqual(violations, [], "extension backend code must depend on public contracts, not other extension backends")

    def test_refactored_builtin_extension_entries_stay_thin(self):
        violations = []
        checked = []
        for extension_id, _ in extension_backend_roots():
            backend_root = extension_source_backend_root(extension_id)
            if backend_root is None:
                continue
            checked.append(extension_id)
            entry_path = backend_root / "ext.py"
            extenders_path = backend_root / "extenders.py"
            if not entry_path.exists():
                violations.append(f"{extension_id}: missing backend/ext.py")
                continue
            if not extenders_path.exists():
                violations.append(f"{extension_id}: missing backend/extenders.py")
                continue
            source = entry_path.read_text(encoding="utf-8")
            line_count = len(source.splitlines())
            if line_count > 40:
                violations.append(f"{extension_id}: backend/ext.py has {line_count} lines")
            expected_import = f"from bias_ext_{extension_id.replace('-', '_')}.backend.extenders import"
            if expected_import not in source:
                violations.append(f"{extension_id}: backend/ext.py does not import backend.extenders")
            forbidden_markers = (
                "from bias_core.extensions import",
                "from bias_core.extensions.",
                "ApiResourceExtender(",
                "ForumCapabilitiesExtender(",
                "ModelExtender(",
                "RealtimeExtender(",
                "ServiceProviderExtender(",
            )
            for marker in forbidden_markers:
                if marker in source:
                    violations.append(f"{extension_id}: backend/ext.py contains {marker}")

        self.assertTrue(checked, "expected at least one source extension backend entry to be checked")
        self.assertEqual(violations, [])

    def test_core_runtime_code_uses_runtime_facade_instead_of_runtime_access_imports(self):
        forbidden = "from bias_core.extensions.runtime_access"
        allowed_files = {
            core_source_root() / "extensions" / "runtime_access.py",
        }
        allowed_dirs = {
            Path(settings.BASE_DIR) / "tests",
        }
        core_root = core_source_root()
        violations = []
        for path in core_root.glob("**/*.py"):
            if path in allowed_files:
                continue
            if any(parent in allowed_dirs for parent in path.parents):
                continue
            text = path.read_text(encoding="utf-8")
            if forbidden in text:
                violations.append(str(path.relative_to(settings.BASE_DIR)))

        self.assertEqual(violations, [])

    def test_core_source_does_not_import_extension_backend_implementations(self):
        violations = []
        core_root = core_source_root()

        for path in core_root.glob("**/*.py"):
            for line_number, module_name in iter_python_imports(path):
                if module_name.startswith("bias_ext_") or module_name.startswith("extensions."):
                    violations.append(f"{path.relative_to(settings.BASE_DIR)}:{line_number}: {module_name}")

        self.assertEqual(
            violations,
            [],
            "core must depend on extension runtime services and manifests, not extension backend implementations",
        )

    def test_extension_serialization_does_not_import_admin_private_serializers(self):
        source = (core_source_root() / "extension_serialization.py").read_text(encoding="utf-8")

        self.assertNotIn("import _serialize_admin_extension", source)
        self.assertNotIn("import _serialize_admin_extensions_payload", source)

