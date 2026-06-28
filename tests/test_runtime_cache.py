from tests.common import *

class RuntimeStatusCacheTests(TestCase):
    def tearDown(self):
        from bias_core.runtime_state import clear_runtime_status_cache

        clear_runtime_status_cache()
        super().tearDown()

    def test_runtime_status_uses_short_process_cache(self):
        from bias_core.runtime_state import clear_runtime_status_cache, get_runtime_status

        clear_runtime_status_cache()
        Setting.objects.update_or_create(
            key="system.version",
            defaults={"value": json.dumps("1.0.0")},
        )
        bootstrap = SiteBootstrapConfig(installed=True, source="file", database_mode="sqlite")

        with self.assertNumQueries(1):
            first = get_runtime_status(bootstrap)
            second = get_runtime_status(bootstrap)

        self.assertEqual(first.state, "ready")
        self.assertEqual(second.state, "ready")

    def test_clear_runtime_setting_caches_clears_runtime_status_cache(self):
        from bias_core.runtime_state import clear_runtime_status_cache, get_runtime_status

        clear_runtime_status_cache()
        Setting.objects.update_or_create(
            key="system.version",
            defaults={"value": json.dumps("1.0.0")},
        )
        bootstrap = SiteBootstrapConfig(installed=True, source="file", database_mode="sqlite")
        get_runtime_status(bootstrap)

        clear_runtime_setting_caches()

        with self.assertNumQueries(1):
            status = get_runtime_status(bootstrap)

        self.assertEqual(status.state, "ready")


class ExtensionStateCacheTests(TestCase):
    def tearDown(self):
        from bias_core.extension_state_cache import clear_extension_state_cache

        clear_extension_state_cache()
        super().tearDown()

    def test_forum_registry_reuses_extension_state_overrides(self):
        from bias_core.extensions.forum_registry_types import ForumModuleDefinition, PermissionDefinition
        from bias_core.extension_state_cache import clear_extension_state_cache
        from bias_core.forum_registry import ForumRegistry

        ExtensionInstallation.objects.create(
            extension_id="alpha",
            version="0.1.0",
            source="filesystem",
            enabled=True,
            installed=True,
            booted=True,
        )
        registry = ForumRegistry()
        registry.register_module(ForumModuleDefinition(
            module_id="alpha",
            name="Alpha",
            description="Alpha module",
            version="0.1.0",
            enabled=True,
        ))
        registry.register_permission(PermissionDefinition(
            code="alpha.view",
            label="Alpha View",
            section="alpha",
            section_label="Alpha",
            module_id="alpha",
        ))

        clear_extension_state_cache()
        with self.assertNumQueries(1):
            self.assertEqual(registry.get_all_permissions()[0].code, "alpha.view")
            self.assertEqual(registry.get_all_permissions()[0].code, "alpha.view")


