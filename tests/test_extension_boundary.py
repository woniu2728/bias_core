from tests.common import *

class ExtensionPublicApiBoundaryTests(TestCase):
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
            "set_access_token_cookie",
            "set_refresh_token_cookie",
        )

        for name in expected:
            self.assertIn(name, platform.__all__)
            self.assertTrue(callable(getattr(platform, name)))

    def test_builtin_extension_admin_code_uses_platform_staff_guard(self):
        extensions_root = Path(settings.BASE_DIR) / "extensions"
        violations = []
        forbidden = (
            "def _require_staff",
            "not request.auth or not request.auth.is_staff",
            "request.auth.is_staff",
        )

        for path in extensions_root.glob("*/backend/**/*.py"):
            if path.name == "tests.py" or "django_migrations" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            for marker in forbidden:
                if marker in text:
                    violations.append(f"{path.relative_to(settings.BASE_DIR)}: {marker}")

        self.assertEqual(violations, [])

    def test_sdk_exports_contracts_without_direct_internal_definition_imports(self):
        from bias_core.extensions import contracts

        self.assertEqual(contracts.PermissionDefinition.__name__, "PermissionDefinition")
        self.assertEqual(contracts.ExtensionModelVisibilityDefinition.__name__, "ExtensionModelVisibilityDefinition")
        self.assertEqual(contracts.ResourceEndpointDefinition.__name__, "ResourceEndpointDefinition")

        sdk_path = Path(settings.BASE_DIR) / "apps" / "core" / "extensions" / "sdk.py"
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
        extensions_root = Path(settings.BASE_DIR) / "extensions"
        violations = []
        for path in extensions_root.glob("*/backend/**/*.py"):
            if path.name == "tests.py" or "django_migrations" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            for marker in forbidden:
                if marker in text:
                    violations.append(f"{path.relative_to(settings.BASE_DIR)}: {marker}")

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
        extensions_root = Path(settings.BASE_DIR) / "extensions"
        violations = []
        for path in extensions_root.glob("*/backend/**/*.py"):
            if path.name == "tests.py" or "django_migrations" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            for marker in forbidden:
                if marker in text:
                    violations.append(f"{path.relative_to(settings.BASE_DIR)}: {marker}")

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
        extensions_root = Path(settings.BASE_DIR) / "extensions"
        violations = []
        for path in extensions_root.glob("*/backend/**/*.py"):
            if path.name == "tests.py" or "django_migrations" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            for marker in forbidden:
                if marker in text:
                    violations.append(f"{path.relative_to(settings.BASE_DIR)}: {marker}")

        self.assertEqual(violations, [])

    def test_builtin_extension_backend_code_does_not_import_other_extension_backends(self):
        extensions_root = Path(settings.BASE_DIR) / "extensions"
        violations = []
        for source_extension in extensions_root.iterdir():
            backend_root = source_extension / "backend"
            if not backend_root.is_dir():
                continue
            for path in backend_root.glob("**/*.py"):
                if path.name == "tests.py" or "django_migrations" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8")
                for target_extension in extensions_root.iterdir():
                    if target_extension == source_extension:
                        continue
                    target_name = target_extension.name.replace("-", "_")
                    markers = (
                        f"from extensions.{target_name}.backend",
                        f"import extensions.{target_name}.backend",
                    )
                    if any(marker in text for marker in markers):
                        violations.append(f"{path.relative_to(settings.BASE_DIR)}: {target_name}")

        self.assertEqual(violations, [], "extension backend code must depend on public contracts, not other extension backends")

    def test_core_runtime_code_uses_runtime_facade_instead_of_runtime_access_imports(self):
        forbidden = "from bias_core.extensions.runtime_access"
        allowed_files = {
            Path(settings.BASE_DIR) / "apps" / "core" / "extensions" / "runtime_access.py",
            Path(settings.BASE_DIR) / "apps" / "core" / "tests.py",
        }
        allowed_dirs = {
            Path(settings.BASE_DIR) / "apps" / "core" / "tests",
        }
        core_root = Path(settings.BASE_DIR) / "apps" / "core"
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

    def test_extension_serialization_does_not_import_admin_private_serializers(self):
        source = (Path(settings.BASE_DIR) / "apps" / "core" / "extension_serialization.py").read_text(encoding="utf-8")

        self.assertNotIn("import _serialize_admin_extension", source)
        self.assertNotIn("import _serialize_admin_extensions_payload", source)

