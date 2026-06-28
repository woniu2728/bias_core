from tests.common import *

@override_settings(BIAS_EXTENSION_PACKAGE_DISCOVERY=False)
class ExtensionManifestLoaderTests(TestCase):
    def test_discovers_declared_extension_django_apps_and_infers_migration_modules(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "django_app_config": "extensions.alpha_tools.backend.apps.AlphaToolsConfig",
            }, ensure_ascii=False), encoding="utf-8")

            self.assertEqual(
                discover_extension_django_apps(temp_dir),
                ["extensions.alpha_tools.backend.apps.AlphaToolsConfig"],
            )
            self.assertEqual(
                discover_extension_django_migration_modules(temp_dir),
                {"alpha_tools": "extensions.alpha_tools.backend.django_migrations"},
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_discovers_explicit_extension_django_app_label(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "django_app_config": "extensions.alpha_tools.backend.apps.AlphaToolsConfig",
                "django_app_label": "alpha",
            }, ensure_ascii=False), encoding="utf-8")

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifest = loader.discover_manifests()[0]

            self.assertEqual(manifest.django_app_label, "alpha")
            self.assertEqual(
                discover_extension_django_migration_modules(temp_dir),
                {"alpha": "extensions.alpha_tools.backend.django_migrations"},
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_loader_applies_default_compatibility_and_distribution_metadata(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
            }, ensure_ascii=False), encoding="utf-8")

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifest = loader.discover_manifests()[0]

            self.assertEqual(manifest.compatibility.bias_version, ">=0.1.0 <0.2.0")
            self.assertEqual(manifest.compatibility.api_version, "1.0")
            self.assertEqual(manifest.compatibility.api_stability, "experimental")
            self.assertEqual(manifest.compatibility.api_stability_label, "实验性")
            self.assertEqual(
                manifest.compatibility.breaking_change_policy,
                "扩展协议调整会随 Bias 主版本升级同步说明。",
            )
            self.assertEqual(manifest.distribution.channel, "private")
            self.assertEqual(manifest.distribution.channel_label, "私有分发")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_loader_reads_extension_manifest_from_extensions_directory(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            manifest_dir = base_dir / "extensions" / "sample-extension"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "sample-extension",
                "name": "Sample Extension",
                "version": "1.0.0",
                "description": "A sample extension.",
                "dependencies": ["core"],
                "settings_pages": ["/admin/extensions/sample"],
                "permissions_pages": ["/admin/extensions/sample/permissions"],
                "operations_pages": ["/admin/extensions/sample/operations"],
                "operations_profile": {
                    "kicker": "Alpha Runtime",
                    "title": "Sample Operations",
                    "highlights": ["示例能力"],
                    "focus_panels": [
                        {
                            "key": "notification_types",
                            "title": "示例通知",
                        }
                    ],
                    "recommended_action_keys": ["details"],
                    "next_steps": ["继续补齐示例操作页。"],
                },
                "admin_actions": [
                    {
                        "key": "details",
                        "label": "查看详情",
                        "kind": "route",
                        "target": "/admin/extensions/sample-extension",
                    }
                ],
                "runtime_actions": [
                    {
                        "key": "rebuild-cache",
                        "label": "刷新缓存",
                        "hook": "run_rebuild_cache",
                        "requires_enabled": True,
                    }
                ],
                "settings_schema": [
                    {
                        "key": "theme",
                        "label": "主题",
                        "type": "select",
                        "default": "light",
                        "options": [
                            {"value": "light", "label": "浅色"},
                            {"value": "dark", "label": "深色"}
                        ]
                    }
                ],
            }, ensure_ascii=False), encoding="utf-8")

            loader = ExtensionManifestLoader(base_dir / "extensions")
            results = loader.discover()

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].manifest.id, "sample-extension")
            self.assertEqual(results[0].manifest.name, "Sample Extension")
            self.assertEqual(results[0].manifest.dependencies, ("core",))
            self.assertEqual(results[0].manifest.settings_pages, ("/admin/extensions/sample",))
            self.assertEqual(results[0].manifest.permissions_pages, ("/admin/extensions/sample/permissions",))
            self.assertEqual(results[0].manifest.operations_pages, ("/admin/extensions/sample/operations",))
            self.assertEqual(results[0].manifest.operations_profile["kicker"], "Alpha Runtime")
            self.assertEqual(results[0].manifest.operations_profile["focus_panels"][0]["key"], "notification_types")
            self.assertEqual(results[0].manifest.admin_actions[0].key, "details")
            self.assertEqual(results[0].manifest.runtime_actions[0].hook, "run_rebuild_cache")
            self.assertEqual(results[0].manifest.settings_schema[0].key, "theme")
            self.assertFalse(hasattr(results[0].manifest, "migration_namespace"))
            self.assertEqual(results[0].manifest.django_app_config, "")
            self.assertEqual(results[0].manifest.compatibility.api_version, "1.0")
            self.assertEqual(results[0].manifest.compatibility.api_stability, "experimental")
            self.assertEqual(results[0].manifest.distribution.channel, "private")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_loader_reads_split_package_manifest_sections(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "split-users"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "split-users",
                "name": "Split Users",
                "version": "1.0.0",
                "backend": {
                    "entry": "bias_ext_users.backend.ext:extend",
                },
                "frontend": {
                    "admin_entry": "frontend/dist/admin/index.js",
                    "forum_entry": "frontend/dist/forum/index.js",
                },
                "django": {
                    "app_config": "bias_ext_users.backend.apps.UsersExtensionConfig",
                    "app_label": "users",
                    "migration_module": "bias_ext_users.backend.django_migrations",
                },
            }, ensure_ascii=False), encoding="utf-8")

            manifest = ExtensionManifestLoader(Path(temp_dir) / "extensions").discover_manifests()[0]

            self.assertEqual(manifest.backend_entry, "bias_ext_users.backend.ext:extend")
            self.assertEqual(manifest.frontend_admin_entry, "frontend/dist/admin/index.js")
            self.assertEqual(manifest.frontend_forum_entry, "frontend/dist/forum/index.js")
            self.assertEqual(manifest.django_app_config, "bias_ext_users.backend.apps.UsersExtensionConfig")
            self.assertEqual(manifest.django_app_label, "users")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_loader_discovers_split_workspace_extension_packages(self):
        temp_dir = make_workspace_temp_dir()
        try:
            workspace_root = Path(temp_dir)
            extensions_dir = workspace_root / "site" / "extensions"
            extensions_dir.mkdir(parents=True, exist_ok=False)
            manifest_dir = workspace_root / "bias-ext-alpha"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha",
                "name": "Alpha",
                "version": "1.0.0",
                "backend": {"entry": "bias_ext_alpha.backend.ext:extend"},
            }, ensure_ascii=False), encoding="utf-8")

            with override_settings(BIAS_EXTENSION_WORKSPACE_ROOT=workspace_root):
                loader = ExtensionManifestLoader(extensions_dir, include_workspace=True)
                manifests = loader.discover_manifests()

            self.assertEqual([manifest.id for manifest in manifests], ["alpha"])
            self.assertEqual(manifests[0].path, str(manifest_dir))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_loader_discovers_split_workspace_extension_packages_from_bias_site_host(self):
        temp_dir = make_workspace_temp_dir()
        try:
            workspace_root = Path(temp_dir)
            extensions_dir = workspace_root / "bias" / "extensions"
            extensions_dir.mkdir(parents=True, exist_ok=False)
            manifest_dir = workspace_root / "bias-ext-alpha"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha",
                "name": "Alpha",
                "version": "1.0.0",
                "backend": {"entry": "bias_ext_alpha.backend.ext:extend"},
            }, ensure_ascii=False), encoding="utf-8")

            with override_settings(BASE_DIR=workspace_root / "bias", BIAS_EXTENSION_WORKSPACE_ROOT=workspace_root):
                loader = ExtensionManifestLoader(extensions_dir, include_workspace=True)
                manifests = loader.discover_manifests()

            self.assertEqual([manifest.id for manifest in manifests], ["alpha"])
            self.assertEqual(manifests[0].path, str(manifest_dir))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_loader_discovers_workspace_from_base_path_when_base_dir_points_elsewhere(self):
        temp_dir = make_workspace_temp_dir()
        try:
            workspace_root = Path(temp_dir) / "workspace"
            unrelated_site = Path(temp_dir) / "unrelated-site"
            extensions_dir = workspace_root / "extensions"
            manifest_dir = workspace_root / "bias-ext-alpha"
            extensions_dir.mkdir(parents=True, exist_ok=False)
            unrelated_site.mkdir(parents=True, exist_ok=False)
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha",
                "name": "Alpha",
                "version": "1.0.0",
                "backend": {"entry": "bias_ext_alpha.backend.ext:extend"},
            }, ensure_ascii=False), encoding="utf-8")

            with override_settings(BASE_DIR=unrelated_site, BIAS_EXTENSION_WORKSPACE_ROOT=""):
                loader = ExtensionManifestLoader(extensions_dir, include_workspace=True)
                manifests = loader.discover_manifests()

            self.assertEqual([manifest.id for manifest in manifests], ["alpha"])
            self.assertEqual(manifests[0].path, str(manifest_dir))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


    def test_loader_merges_forum_setting_exposure_from_extenders(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import SettingsExtender, setting_field\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        SettingsExtender(\n"
                "            fields=(\n"
                "                setting_field({'key': 'cdn_url', 'label': 'CDN', 'type': 'text', 'default': ''}),\n"
                "            ),\n"
                "            expose_to_forum=('cdn_url',),\n"
                "        ),\n"
                "    ]\n",
                encoding="utf-8",
            )

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            result = loader.discover()[0]

            self.assertEqual(result.forum_settings_keys, ("cdn_url",))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_loader_merges_forum_capabilities_from_extenders(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import ForumCapabilitiesExtender, NotificationsExtender\n"
                "from bias_core.extensions import SearchFilterDefinition\n"
                "\n"
                "def _parse_author(token):\n"
                "    if token.startswith('author:'):\n"
                "        return token.split(':', 1)[1]\n"
                "    return None\n"
                "\n"
                "def _apply(queryset, value, context):\n"
                "    return queryset\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        NotificationsExtender().type(\n"
                "            'alphaPing',\n"
                "            label='Alpha Ping',\n"
                "            description='Notify alpha pings.',\n"
                "            preference_key='notify_alpha_ping',\n"
                "            preference_label='Alpha Ping',\n"
                "            preference_description='Notify alpha pings.',\n"
                "        ),\n"
                "        ForumCapabilitiesExtender(\n"
                "            search_filters=(\n"
                "                SearchFilterDefinition(code='author', label='作者', module_id='alpha-tools', target='discussion', parser=_parse_author, applier=_apply, syntax='author:<username>'),\n"
                "            ),\n"
                "        ),\n"
                "    ]\n",
                encoding="utf-8",
            )

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            result = loader.discover()[0]

            self.assertEqual(result.notification_types[0].code, "alphaPing")
            self.assertEqual(result.notification_types[0].module_id, "alpha-tools")
            self.assertEqual(result.notification_types[0].preference_key, "notify_alpha_ping")
            self.assertEqual(result.user_preferences[0].key, "notify_alpha_ping")
            self.assertEqual(result.user_preferences[0].module_id, "alpha-tools")
            self.assertTrue(result.user_preferences[0].default_value)
            self.assertEqual(result.search_filters[0].syntax, "author:<username>")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_loader_merges_language_pack_extender_into_contract(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-lang"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-lang",
                "name": "Alpha Language",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_lang.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import LanguagePackExtender\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        LanguagePackExtender(\n"
                "            code='en-US',\n"
                "            label='English',\n"
                "            native_label='English',\n"
                "            path='extensions/alpha-lang/locale',\n"
                "        ),\n"
                "    ]\n",
                encoding="utf-8",
            )

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            result = loader.discover()[0]

            self.assertEqual(result.language_packs[0].code, "en-US")
            self.assertEqual(result.language_packs[0].module_id, "alpha-lang")
            self.assertEqual(result.locale_paths, ("extensions/alpha-lang/locale",))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_loader_merges_admin_surface_extender_into_contract(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import AdminSurfaceExtender\n"
                "from bias_core.extensions import PermissionDefinition, AdminPageDefinition\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        AdminSurfaceExtender(\n"
                "            permissions=(\n"
                "                PermissionDefinition(code='alpha.manage', label='管理 Alpha', section='admin', section_label='后台', module_id='alpha-tools'),\n"
                "            ),\n"
                "            admin_pages=(\n"
                "                AdminPageDefinition(path='/admin/alpha-tools', label='Alpha Tools', icon='fas fa-toolbox', module_id='alpha-tools'),\n"
                "            ),\n"
                "        ),\n"
                "    ]\n",
                encoding="utf-8",
            )

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            result = loader.discover()[0]

            self.assertEqual(result.permissions[0].code, "alpha.manage")
            self.assertEqual(result.admin_pages[0].path, "/admin/alpha-tools")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_loader_merges_extenders_into_manifest(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import SettingsExtender, RuntimeActionsExtender, runtime_action, setting_field\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        SettingsExtender(fields=(\n"
                "            setting_field({'key': 'cdn_url', 'label': 'CDN', 'type': 'text', 'default': ''}),\n"
                "        )),\n"
                "        RuntimeActionsExtender(actions=(\n"
                "            runtime_action({'key': 'rebuild', 'label': '刷新', 'hook': 'run_rebuild_cache'}),\n"
                "        )),\n"
                "    ]\n",
                encoding="utf-8",
            )

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            results = loader.discover()

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].manifest.settings_schema[0].key, "cdn_url")
            self.assertEqual(results[0].manifest.runtime_actions[0].hook, "run_rebuild_cache")
            self.assertEqual(results[0].manifest.settings_pages, ("/admin/extensions/alpha-tools/settings",))
            self.assertEqual(results[0].settings_pages, ("/admin/extensions/alpha-tools/settings",))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_loader_merges_frontend_extender_into_contract(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import FrontendExtender\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        (FrontendExtender()\n"
                "            .admin('extensions/alpha-tools/frontend/admin/index.js')\n"
                "            .forum('extensions/alpha-tools/frontend/forum/index.js')),\n"
                "    ]\n",
                encoding="utf-8",
            )

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            result = loader.discover()[0]

            self.assertEqual(result.frontend_admin_entry, "extensions/alpha-tools/frontend/admin/index.js")
            self.assertEqual(result.frontend_forum_entry, "extensions/alpha-tools/frontend/forum/index.js")
            self.assertEqual(result.manifest.frontend_admin_entry, "extensions/alpha-tools/frontend/admin/index.js")
            self.assertEqual(result.manifest.frontend_forum_entry, "extensions/alpha-tools/frontend/forum/index.js")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_application_bootstrap_collects_extension_api_route_mounts(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from ninja import Router\n"
                "from bias_core.extensions import ApiRoutesExtender\n"
                "\n"
                "router = Router()\n"
                "\n"
                "@router.get('/ping')\n"
                "def ping(request):\n"
                "    return {'ok': True}\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        ApiRoutesExtender(mounts=(('/ext/alpha-tools', router),), tags=('Alpha',)),\n"
                "    ]\n",
                encoding="utf-8",
            )

            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            registry = ExtensionRegistry(extensions_path=extensions_dir)
            application = build_extension_application(manager=registry, force=True)
            mounts = application.get_route_mounts()

            self.assertEqual(len(mounts), 1)
            self.assertEqual(mounts[0].prefix, "/ext/alpha-tools")
            self.assertEqual(tuple(mounts[0].tags), ("Alpha",))
            runtime_view = application.get_runtime_view("alpha-tools")
            self.assertEqual(runtime_view.lifecycle_phase_keys, ("register", "boot", "ready"))
            self.assertEqual(runtime_view.extender_keys, ("ApiRoutesExtender",))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_route_mount_service_replaces_same_runtime_mount_key(self):
        from ninja import Router

        app = ExtensionApplication()
        router = Router()

        app.routes.mount("alpha-tools", "/ext/alpha", router, tags=("Old",))
        app.routes.mount("alpha-tools", "/ext/alpha", router, tags=("New",))

        runtime_view = app.get_runtime_view("alpha-tools")
        mounts = app.get_route_mounts()

        self.assertEqual(len(runtime_view.route_mounts), 1)
        self.assertEqual(len(mounts), 1)
        self.assertEqual(mounts[0].prefix, "/ext/alpha")
        self.assertEqual(mounts[0].tags, ("New",))

    def test_application_bootstrap_collects_extension_websocket_routes(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from channels.generic.websocket import AsyncWebsocketConsumer\n"
                "from bias_core.extensions import WebSocketRoutesExtender\n"
                "\n"
                "class AlphaConsumer(AsyncWebsocketConsumer):\n"
                "    pass\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        WebSocketRoutesExtender().route(r'ws/alpha/$', 'alpha.websocket', AlphaConsumer),\n"
                "    ]\n",
                encoding="utf-8",
            )

            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            registry = ExtensionRegistry(extensions_path=extensions_dir)
            application = build_extension_application(manager=registry, force=True)
            routes = application.get_websocket_routes()
            runtime_view = application.get_runtime_view("alpha-tools")

            self.assertEqual(len(routes), 1)
            self.assertEqual(routes[0].path, "ws/alpha/$")
            self.assertEqual(routes[0].name, "alpha.websocket")
            self.assertEqual(routes[0].module_id, "alpha-tools")
            self.assertEqual(runtime_view.websocket_routes[0].name, "alpha.websocket")
            self.assertEqual(runtime_view.extender_keys, ("WebSocketRoutesExtender",))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_realtime_routing_builds_extension_websocket_urlpatterns(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from channels.generic.websocket import AsyncWebsocketConsumer\n"
                "from bias_core.extensions import WebSocketRoutesExtender\n"
                "\n"
                "class AlphaConsumer(AsyncWebsocketConsumer):\n"
                "    pass\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        WebSocketRoutesExtender().route(r'ws/alpha/$', 'alpha.websocket', AlphaConsumer),\n"
                "    ]\n",
                encoding="utf-8",
            )

            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            registry = ExtensionRegistry(extensions_path=extensions_dir)
            application = build_extension_application(manager=registry, force=True)

            from bias_core.realtime.routing import build_websocket_urlpatterns

            with patch("bias_core.realtime.routing.get_extension_host", return_value=application):
                patterns = build_websocket_urlpatterns()

            self.assertEqual(len(patterns), 1)
            self.assertEqual(str(patterns[0].pattern), "ws/alpha/$")
            self.assertEqual(patterns[0].name, "alpha.websocket")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_frontend_extender_aliases_match_runtime_registration(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import FrontendExtender\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        (FrontendExtender()\n"
                "            .js('forum.js')\n"
                "            .js('admin.js', frontend='admin')\n"
                "            .common('common.js')\n"
                "            .css('forum.css')\n"
                "            .jsDirectory('chunks')\n"
                "            .preload([\n"
                "                {'href': '/x.js', 'as': 'script'},\n"
                "                {'href': '/x.css', 'as': 'style'},\n"
                "            ])\n"
                "            .extraDocumentAttributes({'data-alpha': '1'})\n"
                "            .extraDocumentClasses('alpha-page')\n"
                "            .route('/alpha', 'alpha', 'AlphaPage')\n"
                "            .removeRoute('old-alpha')),\n"
                "    ]\n",
                encoding="utf-8",
            )
            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            application = build_extension_application(manager=ExtensionRegistry(extensions_path=extensions_dir), force=True)
            runtime_view = application.get_runtime_view("alpha-tools")

            self.assertEqual(runtime_view.frontend_forum_entry, "forum.js")
            self.assertEqual(runtime_view.frontend_admin_entry, "admin.js")
            self.assertEqual(runtime_view.frontend_common_entry, "common.js")
            self.assertEqual(runtime_view.frontend_css, ("forum.css",))
            self.assertEqual(runtime_view.frontend_js_directories, ("chunks",))
            self.assertEqual(runtime_view.frontend_preloads[0]["as"], "script")
            self.assertEqual(runtime_view.frontend_preloads[1]["as"], "style")
            self.assertEqual(runtime_view.frontend_document_attributes[0]["data-alpha"], "1")
            self.assertIn({"class": "alpha-page"}, runtime_view.frontend_document_attributes)
            self.assertEqual(runtime_view.frontend_routes[0].path, "/alpha")
            self.assertEqual(runtime_view.frontend_routes[1].name, "old-alpha")
            self.assertTrue(runtime_view.frontend_routes[1].removed)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extension_extenders_are_flattened_from_nested_extend_files(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import FrontendExtender\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        FrontendExtender(admin_entry='extensions/alpha/admin.js'),\n"
                "        [None, FrontendExtender(forum_entry='extensions/alpha/forum.js')],\n"
                "    ]\n",
                encoding="utf-8",
            )

            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            registry = ExtensionRegistry(extensions_path=extensions_dir)
            application = build_extension_application(manager=registry, force=True)
            runtime_view = application.get_runtime_view("alpha-tools")

            self.assertEqual(runtime_view.frontend_admin_entry, "extensions/alpha/admin.js")
            self.assertEqual(runtime_view.frontend_forum_entry, "extensions/alpha/forum.js")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_frontend_service_replaces_same_runtime_document_keys(self):
        app = ExtensionApplication()
        extension_id = "alpha-tools"

        def content_callback(payload):
            return payload

        def replacement_content_callback(payload):
            return payload

        replacement_content_callback.__module__ = content_callback.__module__
        replacement_content_callback.__qualname__ = content_callback.__qualname__
        replacement_content_callback.__name__ = content_callback.__name__

        app.frontend.register_entries(
            extension_id,
            preloads=({"href": "/alpha.css", "as": "style", "media": "screen"},),
            content_callbacks=({"callback": content_callback, "priority": 10},),
            document_attributes=({"data-alpha": "old", "data-beta": "keep"},),
            head_tags=({"tag": "meta", "attributes": {"name": "alpha"}, "text": "old"},),
            theme_variables=({"--alpha-color": "red", "--alpha-gap": "4px"},),
        )
        app.frontend.register_entries(
            extension_id,
            preloads=({"href": "/alpha.css", "as": "style", "media": "print"},),
            content_callbacks=({"callback": replacement_content_callback, "priority": 90},),
            document_attributes=({"data-alpha": "new", "data-beta": "keep"},),
            head_tags=({"tag": "meta", "attributes": {"name": "alpha"}, "text": "new"},),
            theme_variables=({"--alpha-color": "blue", "--alpha-gap": "8px"},),
        )
        app.frontend.register_entries(
            extension_id,
            preloads=({"href": "/beta.js", "as": "script"},),
            content_callbacks=("beta.content",),
            document_attributes=({"data-gamma": "1"},),
            head_tags=({"tag": "link", "attributes": {"rel": "preload", "href": "/beta.js"}},),
            theme_variables=({"--beta-color": "green"},),
        )

        runtime_view = app.get_runtime_view(extension_id)

        self.assertEqual(len(runtime_view.frontend_preloads), 2)
        self.assertEqual(runtime_view.frontend_preloads[0]["media"], "print")
        self.assertEqual(runtime_view.frontend_preloads[1]["href"], "/beta.js")
        self.assertEqual(len(runtime_view.frontend_content_callbacks), 2)
        self.assertEqual(runtime_view.frontend_content_callbacks[0]["priority"], 90)
        self.assertIs(runtime_view.frontend_content_callbacks[0]["callback"], replacement_content_callback)
        self.assertEqual(runtime_view.frontend_content_callbacks[1], "beta.content")
        self.assertEqual(len(runtime_view.frontend_document_attributes), 2)
        self.assertEqual(runtime_view.frontend_document_attributes[0]["data-alpha"], "new")
        self.assertEqual(runtime_view.frontend_document_attributes[1]["data-gamma"], "1")
        self.assertEqual(len(runtime_view.frontend_head_tags), 2)
        self.assertEqual(runtime_view.frontend_head_tags[0]["text"], "new")
        self.assertEqual(runtime_view.frontend_head_tags[1]["attributes"]["href"], "/beta.js")
        self.assertEqual(len(runtime_view.frontend_theme_variables), 2)
        self.assertEqual(runtime_view.frontend_theme_variables[0]["--alpha-color"], "blue")
        self.assertEqual(runtime_view.frontend_theme_variables[1]["--beta-color"], "green")

    def test_application_bootstrap_collects_named_api_routes(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import RoutesExtender\n"
                "\n"
                "def ping(request):\n"
                "    return {'ok': True}\n"
                "\n"
                "def replacement(request):\n"
                "    return {'ok': 'replacement'}\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        RoutesExtender('api', tags=('Alpha',)).get('/ext/alpha-tools/ping', 'alpha.ping', ping),\n"
                "        RoutesExtender('api').remove('alpha.old').get('/ext/alpha-tools/replacement', 'alpha.old', replacement),\n"
                "    ]\n",
                encoding="utf-8",
            )

            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            registry = ExtensionRegistry(extensions_path=extensions_dir)
            application = build_extension_application(manager=registry, force=True)
            named_routes = application.get_named_routes(app_name="api")

            self.assertEqual([route.name for route in named_routes], ["alpha.ping", "alpha.old"])
            self.assertEqual(named_routes[0].method, "GET")
            self.assertEqual(named_routes[0].tags, ("Alpha",))
            self.assertEqual(application.get_runtime_view("alpha-tools").named_routes[0].name, "alpha.ping")

            api = application.make("api.application")
            paths = {item[0] for item in api._routers}
            self.assertIn("/ext/alpha-tools/ping", paths)
            self.assertIn("/ext/alpha-tools/replacement", paths)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_forum_settings_exposes_extension_document_runtime(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import FrontendExtender\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        FrontendExtender(forum_entry='forum.js')\n"
                "            .preload({'href': '/static/alpha.css', 'as': 'style'})\n"
                "            .extra_document_attributes({'data-alpha': '1'})\n"
                "            .title('AlphaTitle')\n"
                "            .content('alpha.content', priority=120)\n"
                "            .content('alpha.late_content', priority=20),\n"
                "    ]\n",
                encoding="utf-8",
            )

            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            registry = ExtensionRegistry(extensions_path=extensions_dir)
            application = build_extension_application(manager=registry, force=True)
            with patch("bias_core.extensions.frontend_runtime_service.get_extension_host", return_value=application):
                clear_runtime_setting_caches()
                payload = get_public_forum_settings()

            document = payload["extension_document"]
            self.assertEqual(document["preloads"], [{"href": "/static/alpha.css", "as": "style"}])
            self.assertEqual(document["document_attributes"], {"data-alpha": "1"})
            self.assertEqual(document["title_drivers"], [{"extension_id": "alpha-tools", "driver": "AlphaTitle"}])
            self.assertEqual(document["content_callbacks"], [
                {"extension_id": "alpha-tools", "callback": "alpha.content", "priority": 120},
                {"extension_id": "alpha-tools", "callback": "alpha.late_content", "priority": 20},
            ])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            clear_runtime_setting_caches()

    def test_extension_sources_do_not_import_replaced_private_runtime_helpers(self):
        forbidden_helpers = (
            "_broadcast_discussion_event",
            "_build_realtime_included_payload",
            "_create_timeline_from_builder",
            "_make_timeline_context",
        )
        extension_root = Path.cwd() / "extensions"
        offenders = []
        for path in extension_root.rglob("*.py"):
            content = path.read_text(encoding="utf-8")
            for helper in forbidden_helpers:
                if helper in content:
                    offenders.append(f"{path.relative_to(Path.cwd())}: {helper}")

        self.assertEqual(offenders, [])

    def test_backend_entry_namespace_controls_loaded_file(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            alternate_dir = manifest_dir / "alternate"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            alternate_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.alternate.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import FrontendExtender\n"
                "\n"
                "def extend():\n"
                "    return [FrontendExtender(forum_entry='extensions/alpha-tools/frontend/forum/wrong.js')]\n",
                encoding="utf-8",
            )
            (alternate_dir / "ext.py").write_text(
                "from bias_core.extensions import FrontendExtender\n"
                "\n"
                "def extend():\n"
                "    return [FrontendExtender(forum_entry='extensions/alpha-tools/frontend/forum/right.js')]\n",
                encoding="utf-8",
            )

            loader = ExtensionManifestLoader(extensions_dir)
            result = loader.discover()[0]

            self.assertEqual(result.frontend_forum_entry, "extensions/alpha-tools/frontend/forum/right.js")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @patch("bias_core.extensions.manifest.metadata.distributions")
    def test_manifest_loader_discovers_python_distribution_extensions(self, distributions_mock):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BIAS_EXTENSION_PACKAGE_DISCOVERY=True):
                from bias_core.extensions import manifest as manifest_module

                manifest_module._distribution_manifest_cache = None
                package_dir = Path(temp_dir) / "site-packages" / "alpha_tools" / "bias_extension"
                package_dir.mkdir(parents=True, exist_ok=False)
                manifest_path = package_dir / "extension.json"
                manifest_path.write_text(json.dumps({
                    "id": "alpha-tools",
                    "name": "Alpha Tools",
                    "version": "1.2.3",
                    "backend_entry": "alpha_tools.ext",
                }, ensure_ascii=False), encoding="utf-8")

                class DemoDistribution:
                    version = "1.2.3"
                    files = ("alpha_tools/bias_extension/extension.json",)
                    metadata = {"Name": "alpha-tools"}

                    def locate_file(self, file):
                        return Path(temp_dir) / "site-packages" / str(file)

                distributions_mock.return_value = [DemoDistribution()]
                loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
                manifests = loader.discover_manifests()

            self.assertEqual(len(manifests), 1)
            self.assertEqual(manifests[0].id, "alpha-tools")
            self.assertEqual(manifests[0].source, "python-package")
            self.assertEqual(manifests[0].extra["python_distribution"]["name"], "alpha-tools")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_application_bootstrap_runs_extension_service_provider(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import ServiceProviderExtender\n"
                "\n"
                "def provide(app):\n"
                "    return {'has_app': app.has('app'), 'ready': True}\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        ServiceProviderExtender(key='alpha.provider', provider=provide),\n"
                "    ]\n",
                encoding="utf-8",
            )

            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            registry = ExtensionRegistry(extensions_path=extensions_dir)
            application = build_extension_application(manager=registry, force=True)

            self.assertEqual(application.get_service("alpha.provider"), {
                "has_app": True,
                "ready": True,
            })
            runtime_view = application.get_runtime_view("alpha-tools")
            self.assertIsNotNone(runtime_view)
            self.assertIn("alpha.provider", runtime_view.service_providers)
            compatibility_record = next(item for item in application.get_records() if item.extension_id == "alpha-tools")
            self.assertIn("alpha.provider", compatibility_record.service_providers)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_application_bootstrap_runs_host_service_provider_class(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import ServiceProviderExtender\n"
                "\n"
                "class DemoProvider:\n"
                "    def register(self, app):\n"
                "        app.instance('alpha.provider', {'registered': app.has('app')})\n"
                "\n"
                "    def boot(self, app):\n"
                "        app.instance('alpha.provider.booted', {'booted': True})\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        ServiceProviderExtender(key='alpha.provider', provider=DemoProvider),\n"
                "    ]\n",
                encoding="utf-8",
            )

            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            registry = ExtensionRegistry(extensions_path=extensions_dir)
            application = build_extension_application(manager=registry, force=True)

            self.assertEqual(application.get_service("alpha.provider"), {
                "registered": True,
            })
            self.assertEqual(application.get_service("alpha.provider.booted"), {
                "booted": True,
            })
            self.assertEqual(application.get_service_provider_keys(extension_id="alpha-tools"), ["alpha.provider"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_service_provider_registry_replaces_same_runtime_provider_key(self):
        app = ExtensionApplication()
        booted = []

        class OldProvider:
            def register(self, host):
                host.instance("alpha.provider", {"version": "old"})

            def boot(self, host):
                booted.append("old")

        class NewProvider:
            def register(self, host):
                host.instance("alpha.provider", {"version": "new"})

            def boot(self, host):
                booted.append("new")

        app.providers.register_provider("alpha-tools", "alpha.provider", OldProvider)
        app.providers.boot()
        app.providers.register_provider("alpha-tools", "alpha.provider", NewProvider)
        app.providers.boot()

        runtime_view = app.get_runtime_view("alpha-tools")

        self.assertEqual(app.get_service("alpha.provider"), {"version": "new"})
        self.assertEqual(runtime_view.service_providers, ("alpha.provider",))
        self.assertEqual(app.get_service_provider_keys(extension_id="alpha-tools"), ["alpha.provider"])
        self.assertEqual(booted, ["old", "new"])

    def test_extension_application_supports_aliases_tags_and_bias_resource_contract(self):
        app = ExtensionApplication()
        app.instance("alpha.service", {"ready": True})
        app.alias("alpha.service", "alpha.alias")
        app.tag(["alpha.alias"], "alpha.services")

        self.assertEqual(app.make("alpha.alias"), {"ready": True})
        self.assertEqual(app.tagged("alpha.services"), [{"ready": True}])
        self.assertEqual(app.make("bias.api.resources"), [])

    def test_forum_service_replaces_same_runtime_definition_keys(self):
        from bias_core.extensions.forum_registry_types import (
            AdminPageDefinition,
            DiscussionListFilterDefinition,
            DiscussionListQueryDefinition,
            DiscussionSortDefinition,
            LanguagePackDefinition,
            NotificationTypeDefinition,
            PermissionDefinition,
            PostTypeDefinition,
            SearchFilterDefinition,
            UserPreferenceDefinition,
        )

        app = ExtensionApplication()
        extension_id = "alpha-tools"

        app.forum.register_permission(
            PermissionDefinition(
                code="alpha.use",
                label="Old",
                section="alpha",
                section_label="Alpha",
                module_id=extension_id,
            ),
            extension_id=extension_id,
        )
        app.forum.register_permission(
            PermissionDefinition(
                code="alpha.use",
                label="New",
                section="alpha",
                section_label="Alpha",
                module_id=extension_id,
            ),
            extension_id=extension_id,
        )
        app.forum.register_admin_page(
            AdminPageDefinition(
                path="/admin/alpha",
                label="Old",
                icon="fas fa-cog",
                module_id=extension_id,
            ),
            extension_id=extension_id,
        )
        app.forum.register_admin_page(
            AdminPageDefinition(
                path="/admin/alpha",
                label="New",
                icon="fas fa-cog",
                module_id=extension_id,
            ),
            extension_id=extension_id,
        )
        app.forum.register_notification_type(
            NotificationTypeDefinition(code="alphaPing", label="Old", module_id=extension_id),
            extension_id=extension_id,
        )
        app.forum.register_notification_type(
            NotificationTypeDefinition(code="alphaPing", label="New", module_id=extension_id),
            extension_id=extension_id,
        )
        app.forum.register_user_preference(
            UserPreferenceDefinition(key="notify_alpha", label="Old", module_id=extension_id),
            extension_id=extension_id,
        )
        app.forum.register_user_preference(
            UserPreferenceDefinition(key="notify_alpha", label="New", module_id=extension_id, default_value=True),
            extension_id=extension_id,
        )
        app.forum.register_language_pack(
            LanguagePackDefinition(code="en", label="Old", module_id=extension_id),
            extension_id=extension_id,
        )
        app.forum.register_language_pack(
            LanguagePackDefinition(code="en", label="New", module_id=extension_id),
            extension_id=extension_id,
        )
        app.forum.register_post_type(
            PostTypeDefinition(code="alphaPost", label="Old", module_id=extension_id),
            extension_id=extension_id,
        )
        app.forum.register_post_type(
            PostTypeDefinition(code="alphaPost", label="New", module_id=extension_id),
            extension_id=extension_id,
        )
        app.forum.register_search_filter(
            SearchFilterDefinition(
                code="alpha",
                label="Old",
                module_id=extension_id,
                target="discussion",
                parser=lambda token: None,
                applier=lambda queryset, value, context: queryset,
            ),
            extension_id=extension_id,
        )
        app.forum.register_search_filter(
            SearchFilterDefinition(
                code="alpha",
                label="New",
                module_id=extension_id,
                target="discussion",
                parser=lambda token: None,
                applier=lambda queryset, value, context: queryset,
            ),
            extension_id=extension_id,
        )
        app.forum.register_discussion_list_query(
            DiscussionListQueryDefinition(
                key="alpha",
                module_id=extension_id,
                applier=lambda queryset, context: queryset,
                description="Old",
            ),
            extension_id=extension_id,
        )
        app.forum.register_discussion_list_query(
            DiscussionListQueryDefinition(
                key="alpha",
                module_id=extension_id,
                applier=lambda queryset, context: queryset,
                description="New",
            ),
            extension_id=extension_id,
        )
        app.forum.register_discussion_sort(
            DiscussionSortDefinition(
                code="alpha",
                label="Old",
                module_id=extension_id,
                applier=lambda queryset, context: queryset,
            ),
            extension_id=extension_id,
        )
        app.forum.register_discussion_sort(
            DiscussionSortDefinition(
                code="alpha",
                label="New",
                module_id=extension_id,
                applier=lambda queryset, context: queryset,
            ),
            extension_id=extension_id,
        )
        app.forum.register_discussion_list_filter(
            DiscussionListFilterDefinition(
                code="alpha",
                label="Old",
                module_id=extension_id,
                applier=lambda queryset, context: queryset,
            ),
            extension_id=extension_id,
        )
        app.forum.register_discussion_list_filter(
            DiscussionListFilterDefinition(
                code="alpha",
                label="New",
                module_id=extension_id,
                applier=lambda queryset, context: queryset,
            ),
            extension_id=extension_id,
        )

        runtime_view = app.get_runtime_view(extension_id)

        self.assertEqual(len(runtime_view.permissions), 1)
        self.assertEqual(runtime_view.permissions[0].label, "New")
        self.assertEqual(app.forum.get_permission("alpha.use").label, "New")
        self.assertEqual(len(runtime_view.admin_pages), 1)
        self.assertEqual(runtime_view.admin_pages[0].label, "New")
        self.assertEqual(app.forum.get_admin_pages()[0].label, "New")
        self.assertEqual(len(runtime_view.notification_types), 1)
        self.assertEqual(runtime_view.notification_types[0].label, "New")
        self.assertEqual(app.forum.get_notification_type("alphaPing").label, "New")
        self.assertEqual(len(runtime_view.user_preferences), 1)
        self.assertTrue(runtime_view.user_preferences[0].default_value)
        self.assertTrue(app.forum.get_user_preferences()[0].default_value)
        self.assertEqual(len(runtime_view.language_packs), 1)
        self.assertEqual(runtime_view.language_packs[0].label, "New")
        self.assertEqual(app.forum.get_language_packs()[0].label, "New")
        self.assertEqual(len(runtime_view.post_types), 1)
        self.assertEqual(runtime_view.post_types[0].label, "New")
        self.assertEqual(app.forum.get_post_type("alphaPost").label, "New")
        self.assertEqual(len(runtime_view.search_filters), 1)
        self.assertEqual(runtime_view.search_filters[0].label, "New")
        self.assertEqual(app.forum.get_search_filters("discussion")[0].label, "New")
        self.assertEqual(len(runtime_view.discussion_list_queries), 1)
        self.assertEqual(runtime_view.discussion_list_queries[0].description, "New")
        self.assertEqual(app.forum.get_discussion_list_queries()[0].description, "New")
        self.assertEqual(len(runtime_view.discussion_sorts), 1)
        self.assertEqual(runtime_view.discussion_sorts[0].label, "New")
        self.assertEqual(app.forum.get_discussion_sort("alpha").label, "New")
        self.assertEqual(len(runtime_view.discussion_list_filters), 1)
        self.assertEqual(runtime_view.discussion_list_filters[0].label, "New")
        self.assertEqual(app.forum.get_discussion_list_filter("alpha").label, "New")

    def test_extension_application_forum_compat_registration_reuses_service_replacement(self):
        from bias_core.extensions.forum_registry_types import PermissionDefinition

        app = ExtensionApplication()
        extension = app.get_or_create_runtime_view("alpha-tools")
        app.register_permission(
            extension,
            PermissionDefinition(
                code="alpha.use",
                label="Old",
                section="alpha",
                section_label="Alpha",
                module_id="alpha-tools",
            ),
        )
        app.register_permission(
            extension,
            PermissionDefinition(
                code="alpha.use",
                label="New",
                section="alpha",
                section_label="Alpha",
                module_id="alpha-tools",
            ),
        )

        runtime_view = app.get_runtime_view("alpha-tools")

        self.assertEqual(len(runtime_view.permissions), 1)
        self.assertEqual(runtime_view.permissions[0].label, "New")
        self.assertEqual(app.forum.get_permission("alpha.use").label, "New")

    def test_policy_and_middleware_services_replace_same_runtime_mount_keys(self):
        from bias_core.extensions.policy_runtime_service import evaluate_extension_policy

        app = ExtensionApplication()
        extension_id = "alpha-tools"
        calls = []

        def middleware(request):
            return request

        def first_policy(**context):
            calls.append("first")
            return False

        def replacement_policy(**context):
            calls.append("replacement")
            return True

        replacement_policy.__module__ = first_policy.__module__
        replacement_policy.__qualname__ = first_policy.__qualname__
        replacement_policy.__name__ = first_policy.__name__

        app.middleware.mount(extension_id, "api", middleware, order=50)
        app.middleware.mount(extension_id, "api", middleware, order=20)
        app.policies.mount_key(extension_id, "alpha.use", first_policy)
        app.policies.mount_key(extension_id, "alpha.use", replacement_policy)

        runtime_view = app.get_runtime_view(extension_id)

        self.assertEqual(len(runtime_view.middleware_mounts), 1)
        self.assertEqual(runtime_view.middleware_mounts[0].order, 20)
        self.assertEqual(app.get_middleware_mounts(target="api")[0].order, 20)
        self.assertEqual(len(runtime_view.policy_mounts), 1)
        self.assertIs(runtime_view.policy_mounts[0].handler, replacement_policy)
        with patch("bias_core.extensions.policy_runtime_service.get_extension_application", return_value=app):
            self.assertTrue(evaluate_extension_policy("alpha.use", default=False))
        self.assertEqual(calls, ["replacement"])

    def test_extension_application_policy_and_middleware_compat_reuses_service_replacement(self):
        app = ExtensionApplication()
        extension = app.get_or_create_runtime_view("alpha-tools")

        def middleware(request):
            return request

        def policy(**context):
            return True

        app.register_middleware_mount(extension, "api", middleware, order=50)
        app.register_middleware_mount(extension, "api", middleware, order=20)
        app.register_policy_mount(extension, "alpha.use", policy)
        app.register_policy_mount(extension, "alpha.use", policy)

        runtime_view = app.get_runtime_view("alpha-tools")

        self.assertEqual(len(runtime_view.middleware_mounts), 1)
        self.assertEqual(runtime_view.middleware_mounts[0].order, 20)
        self.assertEqual(len(runtime_view.policy_mounts), 1)
        self.assertTrue(runtime_view.policy_mounts[0].handler())

    def test_runtime_service_proxy_refreshes_when_container_service_changes(self):
        from bias_core.extensions.runtime_core import RuntimeServiceProxy

        app = ExtensionApplication()
        app.instance("alpha.runtime", {"version": "old"})
        proxy = RuntimeServiceProxy("alpha.runtime")

        with patch("bias_core.extensions.bootstrap.get_extension_host", return_value=app):
            self.assertEqual(proxy.value("version"), "old")
            app.instance("alpha.runtime", {"version": "new"})
            self.assertEqual(proxy.value("version"), "new")

    def test_runtime_service_proxy_refreshes_when_bootstrapped_host_changes(self):
        from bias_core.extensions.bootstrap import (
            clear_bootstrapped_extension_host,
            set_bootstrapped_extension_host,
        )
        from bias_core.extensions.bootstrap_state import is_extension_host_bootstrapped
        from bias_core.extensions.runtime_core import RuntimeServiceProxy

        first = ExtensionApplication()
        second = ExtensionApplication()
        first.instance("alpha.runtime", {"version": "first"})
        second.instance("alpha.runtime", {"version": "second"})
        proxy = RuntimeServiceProxy("alpha.runtime")

        try:
            set_bootstrapped_extension_host(first)
            self.assertEqual(proxy.value("version"), "first")
            set_bootstrapped_extension_host(second)
            self.assertEqual(proxy.value("version"), "second")
        finally:
            clear_bootstrapped_extension_host()

        self.assertFalse(is_extension_host_bootstrapped())

    def test_view_extender_registers_template_namespaces(self):
        from django.template.loader import render_to_string

        from bias_core.extensions import ViewExtender
        from bias_core.extensions.template_loader import clear_extension_template_caches

        temp_dir = make_workspace_temp_dir()
        extension_dir = Path(temp_dir) / "extensions" / "alpha-tools"
        templates_dir = extension_dir / "templates"
        overrides_dir = extension_dir / "overrides"
        prepend_dir = extension_dir / "prepend"
        templates_dir.mkdir(parents=True)
        overrides_dir.mkdir(parents=True)
        prepend_dir.mkdir(parents=True)
        (templates_dir / "hello.html").write_text("Hello {{ name }}", encoding="utf-8")
        (prepend_dir / "hello.html").write_text("Override {{ name }}", encoding="utf-8")

        app = ExtensionApplication()
        app.get_or_create_runtime_view("alpha-tools", path=str(extension_dir))
        extension = SimpleNamespace(extension_id="alpha-tools")

        try:
            ViewExtender() \
                .namespace("alpha", "templates", "overrides", description="Alpha views") \
                .extend_namespace("alpha", "prepend") \
                .extend(app, extension)
            app.make("views")

            namespaces = app.views.get_namespaces(extension_id="alpha-tools")
            runtime_view = app.get_runtime_view("alpha-tools")

            self.assertEqual(len(namespaces), 2)
            self.assertEqual(namespaces[0].namespace, "alpha")
            self.assertEqual(namespaces[0].hints, (str(prepend_dir.resolve()),))
            self.assertEqual(namespaces[0].module_id, "alpha-tools")
            self.assertTrue(namespaces[0].prepend)
            self.assertEqual(namespaces[1].hints, (str(templates_dir.resolve()), str(overrides_dir.resolve())))
            self.assertEqual(runtime_view.view_namespaces, tuple(namespaces))
            with patch("bias_core.extensions.bootstrap.get_extension_host", return_value=app):
                clear_extension_template_caches()
                self.assertEqual(app.views.render("alpha::hello.html", {"name": "Bias"}), "Override Bias")
                self.assertEqual(render_to_string("alpha::hello.html", {"name": "Bias"}), "Override Bias")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extension_application_registers_provider_through_app_register(self):
        app = ExtensionApplication()

        class DemoProvider:
            def register(self, host):
                host.instance("demo.provider.value", {"registered": True})

            def boot(self, host):
                host.instance("demo.provider.booted", {"booted": True})

        key = app.register(DemoProvider, key="demo.provider", extension_id="alpha-tools")
        app.providers.boot()

        self.assertEqual(key, "demo.provider")
        self.assertEqual(app.make("demo.provider.value"), {"registered": True})
        self.assertEqual(app.make("demo.provider.booted"), {"booted": True})

    def test_validator_and_mail_extenders_register_runtime_definitions(self):
        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")

        def validate_title(value, context):
            return value

        def build_mail(message, context):
            return message

        ValidatorExtender().validator("title", "discussion", validate_title).extend(app, extension)
        MailExtender().driver("digest", build_mail).extend(app, extension)

        validators = app.make("validators").get_definitions(extension_id="alpha-tools")
        mailers = app.make("mail").get_definitions(extension_id="alpha-tools")
        runtime_view = app.get_runtime_view("alpha-tools")

        self.assertEqual(validators[0].key, "title")
        self.assertEqual(validators[0].target, "discussion")
        self.assertEqual(validators[0].module_id, "alpha-tools")
        self.assertEqual(mailers[0].key, "digest")
        self.assertEqual(mailers[0].module_id, "alpha-tools")
        self.assertEqual(runtime_view.validators, tuple(validators))
        self.assertEqual(runtime_view.mailers, tuple(mailers))

    def test_runtime_services_replace_same_runtime_definition_keys(self):
        from bias_core.extensions import ErrorHandlingExtender

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")
        calls = []

        def validate_title(value, context):
            calls.append("validate-old")
            return "old"

        def replacement_validate_title(value, context):
            calls.append("validate-new")
            return "new"

        def build_mail(message, context):
            calls.append("mail-old")
            return "old"

        def replacement_build_mail(message, context):
            calls.append("mail-new")
            return "new"

        def report_error(payload, context):
            calls.append("hook-old")
            return "old"

        def replacement_report_error(payload, context):
            calls.append("hook-new")
            return "new"

        def post_event(post, context):
            calls.append("post-old")
            return {"version": "old"}

        def replacement_post_event(post, context):
            calls.append("post-new")
            return {"version": "new"}

        replacement_validate_title.__module__ = validate_title.__module__
        replacement_validate_title.__qualname__ = validate_title.__qualname__
        replacement_validate_title.__name__ = validate_title.__name__
        replacement_build_mail.__module__ = build_mail.__module__
        replacement_build_mail.__qualname__ = build_mail.__qualname__
        replacement_build_mail.__name__ = build_mail.__name__
        replacement_report_error.__module__ = report_error.__module__
        replacement_report_error.__qualname__ = report_error.__qualname__
        replacement_report_error.__name__ = report_error.__name__
        replacement_post_event.__module__ = post_event.__module__
        replacement_post_event.__qualname__ = post_event.__qualname__
        replacement_post_event.__name__ = post_event.__name__

        ValidatorExtender().validator("title", "discussion", validate_title).extend(app, extension)
        ValidatorExtender().validator("title", "discussion", replacement_validate_title).extend(app, extension)
        MailExtender().driver("digest", build_mail).extend(app, extension)
        MailExtender().driver("digest", replacement_build_mail).extend(app, extension)
        ErrorHandlingExtender().hook("report", report_error).extend(app, extension)
        ErrorHandlingExtender().hook("report", replacement_report_error).extend(app, extension)
        PostEventExtender().type("alphaEvent", post_event).extend(app, extension)
        PostEventExtender().type("alphaEvent", replacement_post_event).extend(app, extension)

        validators = app.make("validators")
        mail = app.make("mail")
        error_handling = app.make("error.handling")
        post_events = app.make("post.events")
        runtime_view = app.get_runtime_view("alpha-tools")

        self.assertEqual(len(runtime_view.validators), 1)
        self.assertEqual(len(runtime_view.mailers), 1)
        self.assertEqual(len(runtime_view.error_handlers), 1)
        self.assertEqual(len(post_events.get_definitions(extension_id="alpha-tools", post_type="alphaEvent")), 1)
        self.assertEqual(validators.run("discussion", {"title": "x"}), ["new"])
        self.assertEqual(mail.send("digest", {"subject": "Digest"}), "new")
        self.assertEqual(error_handling.run("report"), ["new"])
        self.assertEqual(post_events.resolve(SimpleNamespace(type="alphaEvent"), {}), {"version": "new"})
        self.assertEqual(calls, ["validate-new", "mail-new", "hook-new", "post-new"])

    def test_post_event_data_service_returns_none_without_matching_resolver(self):
        app = ExtensionApplication()
        post_events = app.make("post.events")

        self.assertIsNone(post_events.resolve(SimpleNamespace(type="missingEvent"), {}))

    def test_post_event_data_service_returns_first_non_empty_resolver_result(self):
        from bias_core.extensions import PostEventExtender

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")
        calls = []

        def empty(post, context):
            calls.append("empty")
            return None

        def matched(post, context):
            calls.append("matched")
            return {"kind": "alphaEvent"}

        def later(post, context):
            calls.append("later")
            return {"kind": "laterEvent"}

        PostEventExtender().type("alphaEvent", empty, order=10).extend(app, extension)
        PostEventExtender().type("alphaEvent", matched, order=20).extend(app, extension)
        PostEventExtender().type("alphaEvent", later, order=30).extend(app, extension)
        post_events = app.make("post.events")

        self.assertEqual(post_events.resolve(SimpleNamespace(type="alphaEvent"), {}), {"kind": "alphaEvent"})
        self.assertEqual(calls, ["empty", "matched"])

    def test_mail_extender_contributes_runtime_driver_definitions(self):
        from bias_core.mail_drivers import get_driver_definitions, normalize_mail_driver

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")

        MailExtender().driver(
            "custom",
            lambda definition, context: {
                "label": "Custom",
                "description": "Runtime mail driver",
                "fields": [{"key": "mail_custom_token", "label": "Token"}],
            },
        ).extend(app, extension)
        app.make("mail")

        with patch("bias_core.extensions.bootstrap.get_extension_host", return_value=app):
            definitions = get_driver_definitions()
            self.assertEqual(normalize_mail_driver("custom"), "custom")

        self.assertEqual(definitions["custom"]["label"], "Custom")
        self.assertEqual(definitions["custom"]["fields"][0]["key"], "mail_custom_token")

    def test_mail_extender_driver_can_send_runtime_message(self):
        from bias_core.mail_drivers import send_with_extension_mail_driver

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")
        sent = []

        def send_digest(message, context):
            sent.append((message["subject"], context["source"]))
            return True

        MailExtender().driver("digest", send_digest).extend(app, extension)
        app.make("mail")

        with patch("bias_core.extensions.bootstrap.get_extension_host", return_value=app):
            result = send_with_extension_mail_driver("digest", {"subject": "Digest"}, {"source": "test"})

        self.assertEqual(result, True)
        self.assertEqual(sent, [("Digest", "test")])

    def test_system_hook_extenders_register_runtime_hooks(self):
        from bias_core.extensions import (
            AuthExtender,
            ConsoleExtender,
            ErrorHandlingExtender,
            FilesystemExtender,
            SessionExtender,
            ThemeExtender,
        )

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")

        ErrorHandlingExtender().hook("report", lambda payload, context: "error").extend(app, extension)
        AuthExtender().hook("provider", lambda payload, context: "auth").extend(app, extension)
        FilesystemExtender().hook("driver", lambda payload, context: "fs").extend(app, extension)
        ConsoleExtender().hook("command", lambda payload, context: "console").extend(app, extension)
        SessionExtender().hook("session", lambda payload, context: "session").extend(app, extension)
        ThemeExtender().hook("theme", lambda payload, context: "theme").extend(app, extension)

        self.assertEqual(app.make("error.handling").run("report")[0], "error")
        self.assertEqual(app.make("auth").run("provider")[0], "auth")
        self.assertEqual(app.make("filesystem").run("driver")[0], "fs")
        self.assertEqual(app.make("console").run("command")[0], "console")
        self.assertEqual(app.make("session").run("session")[0], "session")
        self.assertEqual(app.make("theme").run("theme")[0], "theme")
        runtime_view = app.get_runtime_view("alpha-tools")
        self.assertEqual(runtime_view.error_handlers[0].module_id, "alpha-tools")

    def test_signal_extender_registers_and_clears_runtime_receivers(self):
        from django.dispatch import Signal
        from bias_core.extensions import SignalExtender
        from bias_core.extensions.signal_runtime import (
            disconnect_runtime_signal_receivers,
            get_runtime_signal_connections,
        )

        signal = Signal()
        received = []

        def receiver(sender, **kwargs):
            received.append(kwargs["value"])

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")

        try:
            SignalExtender().connect(
                signal,
                receiver,
                sender=ExtensionApplication,
                dispatch_uid="alpha.signal.receiver",
            ).extend(app, extension)
            app.make("signals")

            signal.send(sender=ExtensionApplication, value=1)

            runtime_view = app.get_runtime_view("alpha-tools")
            self.assertEqual(received, [1])
            self.assertEqual(runtime_view.signal_handlers[0].module_id, "alpha-tools")
            self.assertEqual(get_runtime_signal_connections(extension_id="alpha-tools")[0].dispatch_uid, "alpha.signal.receiver")

            disconnect_runtime_signal_receivers()
            signal.send(sender=ExtensionApplication, value=2)
            self.assertEqual(received, [1])
        finally:
            disconnect_runtime_signal_receivers()

    def test_signal_extender_auto_dispatch_uid_keeps_distinct_lazy_receiver_targets(self):
        from django.dispatch import Signal
        from bias_core.extensions import SignalExtender
        from bias_core.extensions.signal_runtime import (
            disconnect_runtime_signal_receivers,
            get_runtime_signal_connections,
        )

        signal = Signal()
        received = []

        class FirstReceiver:
            def __call__(self, sender=None, **kwargs):
                received.append(("first", kwargs["value"]))

        class SecondReceiver:
            def __call__(self, sender=None, **kwargs):
                received.append(("second", kwargs["value"]))

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")

        try:
            SignalExtender().connect(
                signal,
                FirstReceiver,
                sender=ExtensionApplication,
            ).connect(
                signal,
                SecondReceiver,
                sender=ExtensionApplication,
            ).extend(app, extension)
            app.make("signals")

            signal.send(sender=ExtensionApplication, value=3)

            self.assertEqual(received, [("first", 3), ("second", 3)])
            dispatch_uids = [
                item.dispatch_uid
                for item in get_runtime_signal_connections(extension_id="alpha-tools")
            ]
            self.assertEqual(len(dispatch_uids), 2)
            self.assertEqual(len(set(dispatch_uids)), 2)
            self.assertTrue(any("FirstReceiver" in item for item in dispatch_uids))
            self.assertTrue(any("SecondReceiver" in item for item in dispatch_uids))
        finally:
            disconnect_runtime_signal_receivers()

    def test_signal_proxy_and_host_boot_share_auto_dispatch_uid_for_class_receiver(self):
        from django.dispatch import Signal
        from bias_core.extensions import SignalExtender
        from bias_core.extensions.signal_bootstrap import (
            bootstrap_extension_signal_proxies,
            reset_extension_signal_proxy_bootstrap,
        )
        from bias_core.extensions.signal_runtime import (
            disconnect_runtime_signal_receivers,
            get_runtime_signal_connections,
        )

        signal = Signal()
        received = []

        class ClassReceiver:
            def __call__(self, sender=None, **kwargs):
                received.append(kwargs["value"])

        class DemoModule:
            @staticmethod
            def extend():
                return [
                    SignalExtender().connect(
                        signal,
                        ClassReceiver,
                        sender=ExtensionApplication,
                    )
                ]

        extension = Extension(
            manifest=ExtensionManifest(id="alpha-tools", name="Alpha Tools", version="1.0.0"),
            module=DemoModule,
            module_ids=("alpha-tools",),
        )
        app = ExtensionApplication(extensions_to_boot=(extension,), extensions_to_catalog=(extension,))

        try:
            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )
            bootstrap_extension_signal_proxies(force=True, host=app)

            proxy_connections = get_runtime_signal_connections(extension_id="alpha-tools")
            self.assertEqual(len(proxy_connections), 1)
            proxy_uid = proxy_connections[0].dispatch_uid
            self.assertTrue(proxy_connections[0].lazy_proxy)

            app.boot()
            signal.send(sender=ExtensionApplication, value=5)

            self.assertEqual(received, [5])
            connections = get_runtime_signal_connections(extension_id="alpha-tools")
            self.assertEqual(len(connections), 1)
            self.assertEqual(connections[0].dispatch_uid, proxy_uid)
            self.assertFalse(connections[0].lazy_proxy)
        finally:
            reset_extension_signal_proxy_bootstrap()
            disconnect_runtime_signal_receivers()

    def test_signal_proxy_reset_disconnects_only_lazy_proxy_receivers(self):
        from django.dispatch import Signal
        from bias_core.extensions.signal_bootstrap import reset_extension_signal_proxy_bootstrap
        from bias_core.extensions.signal_runtime import (
            connect_runtime_signal,
            connect_runtime_signal_proxy,
            disconnect_runtime_signal_receivers,
            get_runtime_signal_connections,
        )
        from bias_core.extensions import ExtensionSignalDefinition

        proxy_signal = Signal()
        runtime_signal = Signal()
        received = []

        def proxy_receiver(sender=None, **kwargs):
            received.append(("proxy", kwargs["value"]))

        def runtime_receiver(sender=None, **kwargs):
            received.append(("runtime", kwargs["value"]))

        try:
            connect_runtime_signal_proxy(
                "alpha-tools",
                ExtensionSignalDefinition(
                    signal=proxy_signal,
                    receiver=proxy_receiver,
                    dispatch_uid="alpha.proxy.receiver",
                ),
                enabled_by_default=True,
            )
            connect_runtime_signal(
                "alpha-tools",
                ExtensionSignalDefinition(
                    signal=runtime_signal,
                    receiver=runtime_receiver,
                    dispatch_uid="alpha.runtime.receiver",
                ),
            )

            self.assertEqual(len(get_runtime_signal_connections(extension_id="alpha-tools")), 2)

            reset_extension_signal_proxy_bootstrap()
            proxy_signal.send(sender=ExtensionApplication, value=1)
            runtime_signal.send(sender=ExtensionApplication, value=2)

            self.assertEqual(received, [("runtime", 2)])
            remaining = get_runtime_signal_connections(extension_id="alpha-tools")
            self.assertEqual([item.dispatch_uid for item in remaining], ["alpha.runtime.receiver"])
        finally:
            disconnect_runtime_signal_receivers()

    def test_signal_proxy_bootstrap_uses_current_extension_host_catalog(self):
        from django.dispatch import Signal
        from bias_core.extensions import SignalExtender
        from bias_core.extensions.signal_bootstrap import (
            bootstrap_extension_signal_proxies,
            reset_extension_signal_proxy_bootstrap,
        )
        from bias_core.extensions.signal_runtime import (
            disconnect_runtime_signal_receivers,
            get_runtime_signal_connections,
        )

        signal = Signal()
        received = []

        def receiver(sender=None, **kwargs):
            received.append(kwargs["value"])

        class DemoModule:
            @staticmethod
            def extend():
                return [
                    SignalExtender().connect(
                        signal,
                        receiver,
                        sender=ExtensionApplication,
                        dispatch_uid="alpha.host.proxy.receiver",
                    )
                ]

        extension = Extension(
            manifest=ExtensionManifest(id="alpha-tools", name="Alpha Tools", version="1.0.0"),
            module=DemoModule,
            module_ids=("alpha-tools",),
        )
        app = ExtensionApplication(extensions_to_catalog=(extension,))

        try:
            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )
            bootstrap_extension_signal_proxies(force=True, host=app)

            signal.send(sender=ExtensionApplication, value=7)

            self.assertEqual(received, [7])
            connections = get_runtime_signal_connections(extension_id="alpha-tools")
            self.assertEqual([item.dispatch_uid for item in connections], ["alpha.host.proxy.receiver"])
            self.assertTrue(connections[0].lazy_proxy)
        finally:
            reset_extension_signal_proxy_bootstrap()
            disconnect_runtime_signal_receivers()

    def test_signal_proxy_force_bootstrap_clears_stale_host_catalog_proxies(self):
        from django.dispatch import Signal
        from bias_core.extensions import SignalExtender
        from bias_core.extensions.signal_bootstrap import (
            bootstrap_extension_signal_proxies,
            reset_extension_signal_proxy_bootstrap,
        )
        from bias_core.extensions.signal_runtime import (
            disconnect_runtime_signal_receivers,
            get_runtime_signal_connections,
        )

        signal = Signal()
        received = []

        def alpha_receiver(sender=None, **kwargs):
            received.append(("alpha", kwargs["value"]))

        def beta_receiver(sender=None, **kwargs):
            received.append(("beta", kwargs["value"]))

        class AlphaModule:
            @staticmethod
            def extend():
                return [
                    SignalExtender().connect(
                        signal,
                        alpha_receiver,
                        sender=ExtensionApplication,
                        dispatch_uid="alpha.host.proxy.receiver",
                    )
                ]

        class BetaModule:
            @staticmethod
            def extend():
                return [
                    SignalExtender().connect(
                        signal,
                        beta_receiver,
                        sender=ExtensionApplication,
                        dispatch_uid="beta.host.proxy.receiver",
                    )
                ]

        alpha_extension = Extension(
            manifest=ExtensionManifest(id="alpha-tools", name="Alpha Tools", version="1.0.0"),
            module=AlphaModule,
            module_ids=("alpha-tools",),
        )
        beta_extension = Extension(
            manifest=ExtensionManifest(id="beta-tools", name="Beta Tools", version="1.0.0"),
            module=BetaModule,
            module_ids=("beta-tools",),
        )
        alpha_host = ExtensionApplication(extensions_to_catalog=(alpha_extension,))
        beta_host = ExtensionApplication(extensions_to_catalog=(beta_extension,))

        try:
            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )
            ExtensionInstallation.objects.create(
                extension_id="beta-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            bootstrap_extension_signal_proxies(force=True, host=alpha_host)
            bootstrap_extension_signal_proxies(force=True, host=beta_host)

            signal.send(sender=ExtensionApplication, value=11)

            self.assertEqual(received, [("beta", 11)])
            self.assertEqual(
                [item.dispatch_uid for item in get_runtime_signal_connections(include_proxies=True)],
                ["beta.host.proxy.receiver"],
            )
        finally:
            reset_extension_signal_proxy_bootstrap()
            disconnect_runtime_signal_receivers()

    def test_signal_proxy_bootstrap_keeps_filesystem_fallback_without_host(self):
        from django.dispatch import Signal
        from bias_core.extensions import SignalExtender
        from bias_core.extensions.signal_bootstrap import (
            bootstrap_extension_signal_proxies,
            reset_extension_signal_proxy_bootstrap,
        )
        from bias_core.extensions.signal_runtime import (
            disconnect_runtime_signal_receivers,
            get_runtime_signal_connections,
        )

        signal = Signal()
        received = []

        def receiver(sender=None, **kwargs):
            received.append(kwargs["value"])

        class DemoModule:
            @staticmethod
            def extend():
                return [
                    SignalExtender().connect(
                        signal,
                        receiver,
                        sender=ExtensionApplication,
                        dispatch_uid="alpha.fallback.proxy.receiver",
                    )
                ]

        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "tests.test_extension_loader.DemoModule",
            }), encoding="utf-8")
            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            with override_settings(BASE_DIR=Path(temp_dir)):
                with patch("bias_core.extensions.extension_runtime.load_extension_backend_module", return_value=DemoModule):
                    bootstrap_extension_signal_proxies(force=True)

            signal.send(sender=ExtensionApplication, value=9)

            self.assertEqual(received, [9])
            connections = get_runtime_signal_connections(extension_id="alpha-tools")
            self.assertEqual([item.dispatch_uid for item in connections], ["alpha.fallback.proxy.receiver"])
        finally:
            reset_extension_signal_proxy_bootstrap()
            disconnect_runtime_signal_receivers()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_model_extender_declares_owned_models(self):
        from bias_core.extensions import ModelExtender

        class DemoOwnedModel:
            pass

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")

        ModelExtender().owns(
            DemoOwnedModel,
            description="Alpha owns this model.",
        ).extend(app, extension)
        app.make("models")

        runtime_view = app.get_runtime_view("alpha-tools")
        owned = app.models.get_owned_models(extension_id="alpha-tools")

        self.assertEqual(runtime_view.model_definitions[0].kind, "owner")
        self.assertEqual(runtime_view.model_definitions[0].model, DemoOwnedModel)
        self.assertEqual(owned[0].description, "Alpha owns this model.")
        self.assertEqual(app.models.get_model_owner(DemoOwnedModel), "alpha-tools")

    def test_model_service_replaces_same_runtime_definition_keys(self):
        from bias_core.extensions.types import (
            ExtensionModelCastDefinition,
            ExtensionModelDefaultDefinition,
            ExtensionModelDefinition,
            ExtensionModelRelationDefinition,
        )

        class DemoModel:
            pass

        app = ExtensionApplication()
        extension_id = "alpha-tools"

        app.models.register(
            extension_id,
            ExtensionModelDefinition(DemoModel, "meta", "old", kind="metadata"),
        )
        app.models.register(
            extension_id,
            ExtensionModelDefinition(DemoModel, "meta", "new", kind="metadata"),
        )
        app.models.register_relation(
            extension_id,
            ExtensionModelRelationDefinition(DemoModel, "owner", lambda instance: ("old", instance)),
        )
        app.models.register_relation(
            extension_id,
            ExtensionModelRelationDefinition(DemoModel, "owner", lambda instance: ("new", instance)),
        )
        app.models.register_cast(
            extension_id,
            ExtensionModelCastDefinition(DemoModel, "payload", "json"),
        )
        app.models.register_cast(
            extension_id,
            ExtensionModelCastDefinition(DemoModel, "payload", "dict"),
        )
        app.models.register_default(
            extension_id,
            ExtensionModelDefaultDefinition(DemoModel, "enabled", False),
        )
        app.models.register_default(
            extension_id,
            ExtensionModelDefaultDefinition(DemoModel, "enabled", True),
        )

        runtime_view = app.get_runtime_view(extension_id)
        instance = DemoModel()

        self.assertEqual(len(runtime_view.model_definitions), 1)
        self.assertEqual(runtime_view.model_definitions[0].handler, "new")
        self.assertEqual(app.models.get_definitions_for_model(DemoModel)[0].handler, "new")
        self.assertEqual(len(runtime_view.model_relations), 1)
        self.assertEqual(app.models.resolve_relation(DemoModel, "owner", "demo"), ("new", "demo"))
        self.assertEqual(instance.owner, ("new", instance))
        self.assertEqual(len(runtime_view.model_casts), 1)
        self.assertEqual(app.models.get_casts_for_model(DemoModel), {"payload": "dict"})
        self.assertEqual(len(runtime_view.model_defaults), 1)
        self.assertEqual(app.models.get_defaults_for_model(DemoModel), {"enabled": True})

    def test_settings_and_action_services_replace_same_runtime_keys(self):
        from bias_core.extensions import admin_action, runtime_action, setting_field
        from bias_core.extensions.types import (
            ExtensionSettingDefaultDefinition,
            ExtensionSettingForumSerializationDefinition,
            ExtensionSettingResetDefinition,
            ExtensionSettingThemeVariableDefinition,
        )

        app = ExtensionApplication()
        extension_id = "alpha-tools"

        app.settings.register_fields(
            extension_id,
            (setting_field(key="alpha.mode", label="Old", type="text"),),
            generated_page=False,
            defaults=(ExtensionSettingDefaultDefinition("alpha.mode", "old"),),
            reset_when=(ExtensionSettingResetDefinition("alpha.mode", lambda value: value == "old"),),
            theme_variables=(ExtensionSettingThemeVariableDefinition("alphaColor", "alpha.color"),),
            forum_serializations=(ExtensionSettingForumSerializationDefinition("alphaMode", "alpha.mode"),),
        )
        app.settings.register_fields(
            extension_id,
            (setting_field(key="alpha.mode", label="New", type="select"),),
            generated_page=False,
            defaults=(ExtensionSettingDefaultDefinition("alpha.mode", "new"),),
            reset_when=(ExtensionSettingResetDefinition("alpha.mode", lambda value: value == "new"),),
            theme_variables=(ExtensionSettingThemeVariableDefinition("alphaColor", "alpha.color.new"),),
            forum_serializations=(ExtensionSettingForumSerializationDefinition("alphaMode", "alpha.mode.new"),),
        )
        app.actions.register_runtime_actions(
            extension_id,
            (runtime_action(key="rebuild", label="Old", hook="old_hook"),),
        )
        app.actions.register_runtime_actions(
            extension_id,
            (runtime_action(key="rebuild", label="New", hook="new_hook"),),
        )
        app.actions.register_admin_actions(
            extension_id,
            (admin_action(key="details", label="Old", kind="route", target="/old"),),
        )
        app.actions.register_admin_actions(
            extension_id,
            (admin_action(key="details", label="New", kind="route", target="/new"),),
        )

        runtime_view = app.get_runtime_view(extension_id)

        self.assertEqual(len(runtime_view.settings_schema), 1)
        self.assertEqual(runtime_view.settings_schema[0].label, "New")
        self.assertEqual(runtime_view.settings_schema[0].type, "select")
        self.assertEqual(len(runtime_view.settings_defaults), 1)
        self.assertEqual(runtime_view.settings_defaults[0].value, "new")
        self.assertEqual(len(runtime_view.settings_reset_rules), 1)
        self.assertTrue(runtime_view.settings_reset_rules[0].callback("new"))
        self.assertEqual(len(runtime_view.settings_theme_variables), 1)
        self.assertEqual(runtime_view.settings_theme_variables[0].key, "alpha.color.new")
        self.assertEqual(len(runtime_view.settings_forum_serializations), 1)
        self.assertEqual(runtime_view.settings_forum_serializations[0].key, "alpha.mode.new")
        self.assertEqual(len(runtime_view.runtime_actions), 1)
        self.assertEqual(runtime_view.runtime_actions[0].hook, "new_hook")
        self.assertEqual(len(runtime_view.admin_actions), 1)
        self.assertEqual(runtime_view.admin_actions[0].target, "/new")

    def test_extension_application_settings_actions_and_locale_compat_reuses_service_replacement(self):
        from bias_core.extensions import admin_action, runtime_action, setting_field
        from bias_core.extensions.types import ExtensionSettingDefaultDefinition

        app = ExtensionApplication()
        extension = app.get_or_create_runtime_view("alpha-tools")

        app.register_locale_path(extension, " /tmp/alpha-locales ")
        app.register_locale_path(extension, "/tmp/alpha-locales")
        app.register_settings_fields(
            extension,
            (setting_field(key="alpha.mode", label="Old", type="text"),),
            generated_page=True,
            defaults=(ExtensionSettingDefaultDefinition("alpha.mode", "old"),),
            expose_to_forum=("alpha.mode",),
            reset_frontend_cache_for=("forum",),
        )
        app.register_settings_fields(
            extension,
            (setting_field(key="alpha.mode", label="New", type="select"),),
            generated_page=True,
            defaults=(ExtensionSettingDefaultDefinition("alpha.mode", "new"),),
            expose_to_forum=("alpha.mode",),
            reset_frontend_cache_for=("forum",),
        )
        app.register_runtime_actions(
            extension,
            (runtime_action(key="rebuild", label="Old", hook="old_hook"),),
            generated_page=True,
        )
        app.register_runtime_actions(
            extension,
            (runtime_action(key="rebuild", label="New", hook="new_hook"),),
            generated_page=True,
        )
        app.register_admin_actions(
            extension,
            (admin_action(key="details", label="Old", kind="route", target="/old"),),
            generated_permissions_page=True,
            generated_operations_page=True,
        )
        app.register_admin_actions(
            extension,
            (admin_action(key="details", label="New", kind="route", target="/new"),),
            generated_permissions_page=True,
            generated_operations_page=True,
        )
        app.mark_generated_permissions_page(extension)

        runtime_view = app.get_runtime_view("alpha-tools")

        self.assertEqual(runtime_view.locale_paths, ("/tmp/alpha-locales",))
        self.assertEqual(app.locales.get_paths(extension_id="alpha-tools"), ["/tmp/alpha-locales"])
        self.assertEqual(len(runtime_view.settings_schema), 1)
        self.assertEqual(runtime_view.settings_schema[0].label, "New")
        self.assertEqual(len(runtime_view.settings_defaults), 1)
        self.assertEqual(runtime_view.settings_defaults[0].value, "new")
        self.assertEqual(runtime_view.forum_settings_keys, ("alpha.mode",))
        self.assertEqual(runtime_view.settings_frontend_cache_keys, ("forum",))
        self.assertEqual(len(runtime_view.runtime_actions), 1)
        self.assertEqual(runtime_view.runtime_actions[0].hook, "new_hook")
        self.assertEqual(len(runtime_view.admin_actions), 1)
        self.assertEqual(runtime_view.admin_actions[0].target, "/new")
        self.assertEqual(runtime_view.settings_pages, ("/admin/extensions/alpha-tools/settings",))
        self.assertEqual(runtime_view.permissions_pages, ("/admin/extensions/alpha-tools/permissions",))
        self.assertEqual(runtime_view.operations_pages, ("/admin/extensions/alpha-tools/operations",))
        self.assertTrue(runtime_view.use_generated_settings_page)
        self.assertTrue(runtime_view.use_generated_permissions_page)
        self.assertTrue(runtime_view.use_generated_operations_page)

    def test_runtime_model_reference_resolves_model_relations_and_policies(self):
        from bias_core.extensions import ModelExtender, PolicyExtender, RuntimeModel, ServiceProviderExtender
        from bias_core.extensions.policy_runtime_service import evaluate_model_policy

        class DemoModel:
            pass

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")
        runtime_model = RuntimeModel("alpha.model")

        ServiceProviderExtender(
            key="alpha.model",
            provider=lambda: {"model": DemoModel},
        ).extend(app, extension)
        ModelExtender(model=runtime_model).belongs_to_many(
            "followers",
            runtime_model,
            resolver=lambda instance: ["alice"],
            inject_attribute=False,
        ).extend(app, extension)
        PolicyExtender().policy(
            runtime_model,
            lambda user=None, ability="", model=None, **context: ability == "view",
        ).extend(app, extension)

        app.make("models")
        app.make("policies")

        relations = app.models.get_relations_for_model(DemoModel)
        self.assertEqual(relations[0].name, "followers")
        self.assertEqual(app.models.resolve_relation(DemoModel, "followers", DemoModel()), ["alice"])
        with patch("bias_core.extensions.policy_runtime_service.get_extension_application", return_value=app):
            self.assertTrue(evaluate_model_policy("view", model=DemoModel(), default=False))

    def test_post_event_extender_registers_event_data_resolver(self):
        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")

        def resolve_alpha_event(post, context):
            return {
                "kind": post.type,
                "actor": context["user"],
            }

        PostEventExtender().type(
            "alphaEvent",
            resolve_alpha_event,
            description="Alpha event data.",
        ).types(
            ("betaEvent",),
            resolve_alpha_event,
            description="Beta event data.",
        ).extend(app, extension)

        event_data = app.make("post.events").resolve(
            SimpleNamespace(type="alphaEvent", content=""),
            {"user": "tester"},
        )

        self.assertEqual(event_data, {"kind": "alphaEvent", "actor": "tester"})
        self.assertEqual(app.make("post.events").get_definitions(post_type="alphaEvent")[0].module_id, "alpha-tools")
        self.assertEqual(app.make("post.events").get_definitions(post_type="betaEvent")[0].module_id, "alpha-tools")

    def test_conditional_extender_supports_disabled_setting_and_class_callbacks(self):
        app = ExtensionApplication()
        app._booted_extensions["beta-tools"] = SimpleNamespace(runtime=SimpleNamespace(enabled=False))
        extension = SimpleNamespace(extension_id="alpha-tools")
        Setting.objects.create(key="alpha.enabled", value="1")

        class ConditionalFields:
            def __call__(self):
                return ResourceExtender(fields=(
                    ResourceFieldDefinition(
                        resource="forum",
                        field="class_conditional",
                        module_id="",
                        resolver=lambda model, context: True,
                    ),
                ))

        ConditionalExtender() \
            .when_extension_disabled("beta-tools", lambda: [
                ResourceExtender(fields=(
                    ResourceFieldDefinition(
                        resource="forum",
                        field="disabled_conditional",
                        module_id="",
                        resolver=lambda model, context: True,
                    ),
                )),
                [
                    None,
                    ResourceExtender(fields=(
                        ResourceFieldDefinition(
                            resource="forum",
                            field="nested_conditional",
                            module_id="",
                            resolver=lambda model, context: True,
                        ),
                    )),
                ],
            ]) \
            .when_setting("alpha.enabled", "1", ConditionalFields) \
            .extend(app, extension)

        fields = {item.field: item for item in app.make("resources").get_fields("forum")}

        self.assertIn("disabled_conditional", fields)
        self.assertIn("nested_conditional", fields)
        self.assertIn("class_conditional", fields)
        self.assertEqual(fields["disabled_conditional"].module_id, "alpha-tools")
        self.assertEqual(fields["nested_conditional"].module_id, "alpha-tools")
        self.assertEqual(fields["class_conditional"].module_id, "alpha-tools")

    def test_system_hook_runtime_services_drive_error_filesystem_and_console(self):
        from bias_core.extensions import ConsoleExtender, ErrorHandlingExtender, FilesystemExtender
        from bias_core.extensions.system_runtime import (
            get_runtime_error_statuses,
            list_runtime_console_commands,
            list_runtime_console_schedules,
            list_runtime_filesystem_disks,
            report_runtime_error,
            resolve_runtime_filesystem_driver,
            run_runtime_console_command,
        )
        from bias_core.storage_service import get_storage_backend

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")
        reports = []

        class CustomStorage:
            pass

        def report(payload, context):
            reports.append((payload["error_type"], payload["operation"]))
            return True

        def filesystem(payload, context):
            if payload["driver"] == "custom":
                return CustomStorage()
            return None

        def console(payload, context):
            return {
                "name": "alpha:refresh",
                "description": "Refresh alpha",
                "handler": lambda options: {"ok": True, "scope": options.get("scope")},
            }

        ErrorHandlingExtender().hook("report", report).status("alpha_error", 409).extend(app, extension)
        FilesystemExtender().hook("driver", filesystem).disk("alpha", {"root": "/tmp/alpha"}).extend(app, extension)
        ConsoleExtender().hook("command", console).schedule("alpha:refresh", "hourly").extend(app, extension)
        app.make("error.handling")
        app.make("filesystem")
        app.make("console")

        with patch("bias_core.extensions.bootstrap.get_extension_host", return_value=app):
            report_runtime_error(ValueError("broken"), operation="unit-test")
            storage = resolve_runtime_filesystem_driver("custom", {"storage_driver": "custom"})
            storage_from_service = get_storage_backend({"storage_driver": "custom"})
            commands = list_runtime_console_commands()
            schedules = list_runtime_console_schedules()
            disks = list_runtime_filesystem_disks()
            statuses = get_runtime_error_statuses()
            result = run_runtime_console_command("alpha:refresh", options={"scope": "all"})

        self.assertEqual(reports, [("ValueError", "unit-test")])
        self.assertIsInstance(storage, CustomStorage)
        self.assertIsInstance(storage_from_service, CustomStorage)
        self.assertEqual(commands[0]["name"], "alpha:refresh")
        self.assertEqual(schedules[0]["name"], "alpha:refresh")
        self.assertEqual(disks[0]["name"], "alpha")
        self.assertEqual(statuses["alpha_error"], 409)
        self.assertEqual(result, {"ok": True, "scope": "all"})

    def test_auth_and_session_extenders_register_typed_runtime_services(self):
        from bias_core.extensions import AuthExtender, SessionExtender
        from bias_core.extensions.system_runtime import (
            get_runtime_password_checkers,
            list_runtime_session_drivers,
            resolve_runtime_session_driver,
            verify_runtime_user_password,
        )

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")

        class CustomSessionDriver:
            def __init__(self, config):
                self.config = config

        user = SimpleNamespace(username="alpha", password="unused")

        AuthExtender() \
            .remove_password_checker("django") \
            .add_password_checker("alpha", lambda current_user, raw_password: current_user.username == raw_password) \
            .extend(app, extension)
        SessionExtender().driver("alpha", CustomSessionDriver, description="Alpha session").extend(app, extension)
        app.make("auth")
        app.make("session")

        with patch("bias_core.extensions.bootstrap.get_extension_host", return_value=app):
            checkers = get_runtime_password_checkers(default_checker=lambda current_user, raw_password: False)
            accepted = verify_runtime_user_password(user, "alpha", default_checker=lambda current_user, raw_password: False)
            rejected = verify_runtime_user_password(user, "wrong", default_checker=lambda current_user, raw_password: True)
            drivers = list_runtime_session_drivers()
            resolved_driver = resolve_runtime_session_driver("alpha", {"ttl": 60})

        self.assertEqual(list(checkers.keys()), ["alpha"])
        self.assertTrue(accepted)
        self.assertFalse(rejected)
        self.assertEqual(drivers[0]["name"], "alpha")
        self.assertEqual(drivers[0]["extension_id"], "alpha-tools")
        self.assertIsInstance(resolved_driver, CustomSessionDriver)
        self.assertEqual(resolved_driver.config["ttl"], 60)

    def test_csrf_throttle_and_search_index_extenders_register_runtime_services(self):
        from bias_core.extensions import CsrfExtender, SearchIndexExtender, ThrottleApiExtender
        from bias_core.extensions.system_runtime import (
            get_runtime_api_throttlers,
            get_runtime_csrf_exempt_routes,
            should_throttle_runtime_api_request,
        )

        class Item:
            pass

        class Indexer:
            pass

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")
        indexer = Indexer()
        request = RequestFactory().get("/api/demo")

        CsrfExtender().exempt_route("alpha-webhook").extend(app, extension)
        ThrottleApiExtender().set("alpha", lambda current_request: current_request.path == "/api/demo").extend(app, extension)
        SearchIndexExtender().indexer(Item, indexer).extend(app, extension)
        app.make("csrf")
        app.make("throttle.api")
        app.make("search")

        with patch("bias_core.extensions.bootstrap.get_extension_host", return_value=app):
            routes = get_runtime_csrf_exempt_routes()
            throttlers = get_runtime_api_throttlers()
            throttled = should_throttle_runtime_api_request(request)

        self.assertEqual(routes, {"alpha-webhook"})
        self.assertEqual(list(throttlers.keys()), ["alpha"])
        self.assertTrue(throttled)
        self.assertEqual(app.search.indexers(Item), (indexer,))

    @override_settings(FRONTEND_URL="https://bias.test")
    def test_link_extender_registers_formatter_link_attribute_callbacks(self):
        from bias_core.extensions import LinkExtender
        from bias_core.extensions.formatter_service import apply_extension_formatters, clear_extension_formatter_cache

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")
        seen = []

        def rel(uri, site_url, attributes):
            seen.append((uri.netloc, site_url, attributes.get("href", "")))
            if uri.netloc == "external.test":
                return "nofollow sponsored"
            return ""

        def target(uri, site_url, attributes):
            if uri.netloc == "bias.test":
                return "_self"
            return "_blank"

        LinkExtender().set_rel(rel).set_target(target).extend(app, extension)
        app.make("formatters")

        clear_extension_formatter_cache()
        try:
            with patch("bias_core.extensions.bootstrap.get_extension_host", return_value=app):
                html = apply_extension_formatters(
                    '<p><a href="https://external.test/page">外部</a> '
                    '<a href="https://bias.test/d/1">内部</a></p>'
                )
        finally:
            clear_extension_formatter_cache()

        self.assertIn('href="https://external.test/page" rel="nofollow sponsored" target="_blank"', html)
        self.assertIn('href="https://bias.test/d/1" target="_self"', html)
        self.assertEqual(seen[0], ("external.test", "https://bias.test", "https://external.test/page"))

    def test_formatter_extender_registers_formatter_phases(self):
        from bias_core.extensions import FormatterExtender
        from bias_core.extensions.formatter_service import (
            apply_extension_formatter_config,
            apply_extension_formatter_parse,
            apply_extension_formatter_render,
            apply_extension_formatter_unparse,
            clear_extension_formatter_cache,
        )

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")

        FormatterExtender() \
            .configure(lambda config: {**config, "alpha": True}) \
            .parse(lambda text, context: text.replace(":alpha:", "alpha")) \
            .render(lambda html, context: html.replace("alpha", "<strong>alpha</strong>")) \
            .unparse(lambda text: text.replace("alpha", ":alpha:")) \
            .extend(app, extension)
        app.make("formatters")

        clear_extension_formatter_cache()
        try:
            with patch("bias_core.extensions.bootstrap.get_extension_host", return_value=app):
                self.assertTrue(apply_extension_formatter_config({})["alpha"])
                parsed = apply_extension_formatter_parse("hello :alpha:")
                rendered = apply_extension_formatter_render(parsed)
                unparsed = apply_extension_formatter_unparse("hello alpha")
        finally:
            clear_extension_formatter_cache()

        self.assertEqual(parsed, "hello alpha")
        self.assertEqual(rendered, "hello <strong>alpha</strong>")
        self.assertEqual(unparsed, "hello :alpha:")

    def test_formatter_service_replaces_same_runtime_callback_keys(self):
        from bias_core.extensions import FormatterExtender

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")
        calls = []

        def render(html, context):
            calls.append("old")
            return html.replace("alpha", "old")

        def replacement_render(html, context):
            calls.append("new")
            return html.replace("alpha", "new")

        replacement_render.__module__ = render.__module__
        replacement_render.__qualname__ = render.__qualname__
        replacement_render.__name__ = render.__name__

        FormatterExtender().render(render).extend(app, extension)
        FormatterExtender().render(replacement_render).extend(app, extension)
        formatters = app.make("formatters")
        runtime_view = app.get_runtime_view("alpha-tools")

        self.assertEqual(len(runtime_view.formatter_callbacks), 1)
        self.assertEqual(len(runtime_view.formatter_pipeline), 1)
        self.assertIs(runtime_view.formatter_callbacks[0].callback, replacement_render)
        self.assertEqual(formatters.get_pipeline(extension_id="alpha-tools"), [replacement_render])
        self.assertEqual(formatters.get_pipeline()[0]("alpha", {}), "new")
        self.assertEqual(calls, ["new"])

    def test_language_pack_extender_registers_runtime_locale_metadata(self):
        from bias_core.extensions import LanguagePackExtender

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-lang")

        LanguagePackExtender(
            code="en-US",
            label="English",
            native_label="English",
            path="extensions/alpha-lang/locale",
        ).extend(app, extension)
        app.make("forum")
        app.make("locales")

        packs = app.forum_registry.get_language_packs(module_id="alpha-lang")

        self.assertEqual(packs[0].code, "en-US")
        self.assertEqual(packs[0].label, "English")
        self.assertEqual(app.locales.get_paths(extension_id="alpha-lang"), ["extensions/alpha-lang/locale"])

    def test_post_user_and_model_private_extenders_register_core_runtime(self):
        from bias_core.extensions import ModelPrivateExtender, PostExtender, UserExtender
        from bias_core.extensions.system_runtime import (
            apply_runtime_user_group_processors,
            get_runtime_user_avatar_drivers,
            get_runtime_user_display_name_drivers,
            get_runtime_user_preference_transformers,
        )

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")

        class DemoPost:
            type = "alphaEvent"
            label = "Alpha Event"

        class DemoModel:
            pass

        def group_processor(user, group_ids):
            return [*group_ids, user.extra_group_id]

        def preference_transformer(value):
            return value == "yes"

        PostExtender().type(DemoPost, description="Alpha post event").extend(app, extension)
        UserExtender() \
            .display_name_driver("alpha", "alpha.display") \
            .avatar_driver("alpha", "alpha.avatar") \
            .permission_groups(group_processor) \
            .register_preference("alpha_pref", preference_transformer, False, label="Alpha Pref") \
            .extend(app, extension)
        private_extender = ModelPrivateExtender(DemoModel).checker(lambda instance: instance.is_private)
        private_extender.extend(app, extension)
        private_extender.extend(app, extension)
        ModelPrivateExtender(DemoModel).checker(lambda instance: instance.force_private).extend(app, extension)

        app.make("forum")
        app.make("user")
        app.make("models")

        with patch("bias_core.extensions.system_runtime.get_runtime_system_service", side_effect=lambda key: app.make(key)):
            self.assertEqual(get_runtime_user_display_name_drivers()["alpha"], "alpha.display")
            self.assertEqual(get_runtime_user_avatar_drivers()["alpha"], "alpha.avatar")
            self.assertEqual(apply_runtime_user_group_processors(SimpleNamespace(extra_group_id=9), [1, 2]), [1, 2, 9])
            self.assertTrue(get_runtime_user_preference_transformers()["alpha_pref"]["transformer"]("yes"))

        post_type = app.forum.get_post_type("alphaEvent")
        runtime_view = app.get_runtime_view("alpha-tools")

        self.assertEqual(post_type.label, "Alpha Event")
        self.assertEqual(post_type.module_id, "alpha-tools")
        self.assertEqual(runtime_view.user_preferences[0].key, "alpha_pref")
        self.assertEqual(runtime_view.user_handlers[0].key, "display_name_driver")
        self.assertEqual(runtime_view.model_definitions[-1].kind, "private_checker")
        self.assertEqual(len(app.models.get_private_checkers(DemoModel, extension_id="alpha-tools")), 2)
        self.assertEqual(len([
            definition
            for definition in runtime_view.model_definitions
            if definition.kind == "private_checker"
        ]), 2)
        self.assertTrue(app.models.is_private(DemoModel, SimpleNamespace(is_private=True, force_private=False)))
        self.assertTrue(app.models.is_private(DemoModel, SimpleNamespace(is_private=False, force_private=True)))

    def test_model_visibility_scoper_matches_subclasses(self):
        from bias_core.extensions import ExtensionModelVisibilityDefinition

        class BaseModel:
            pass

        class ChildModel(BaseModel):
            pass

        app = ExtensionApplication()
        app.models.register_visibility(
            "alpha-tools",
            ExtensionModelVisibilityDefinition(
                model=BaseModel,
                ability="view",
                scope=lambda queryset, context: (*queryset, context["ability"]),
            ),
        )

        self.assertTrue(app.models.has_visibility(ChildModel, ability="view"))
        self.assertEqual(
            app.models.apply_visibility(ChildModel, ("base",), {"ability": "view"}),
            ("base", "view"),
        )

    def test_model_visibility_scopers_follow_parent_wildcard_ability_order(self):
        from bias_core.extensions import ExtensionModelVisibilityDefinition

        class BaseModel:
            pass

        class ChildModel(BaseModel):
            pass

        def append(name):
            return lambda queryset, context: (*queryset, name)

        app = ExtensionApplication()
        for name, model, ability in (
            ("child-view", ChildModel, "view"),
            ("base-view", BaseModel, "view"),
            ("child-any", ChildModel, "*"),
            ("base-any", BaseModel, "*"),
        ):
            app.models.register_visibility(
                "alpha-tools",
                ExtensionModelVisibilityDefinition(
                    model=model,
                    ability=ability,
                    scope=append(name),
                ),
            )

        self.assertEqual(
            app.models.apply_visibility(ChildModel, (), {"ability": "view"}),
            ("base-any", "base-view", "child-any", "child-view"),
        )

    def test_core_model_visibility_scopers_follow_parent_wildcard_ability_order(self):
        from bias_core.visibility import get_core_model_visibility_scopers, register_core_model_visibility_scoper

        class BaseModel:
            pass

        class ChildModel(BaseModel):
            pass

        calls = []
        for name, model, ability in (
            ("child-view", ChildModel, "view"),
            ("base-view", BaseModel, "view"),
            ("child-any", ChildModel, "*"),
            ("base-any", BaseModel, "*"),
        ):
            register_core_model_visibility_scoper(
                model,
                lambda queryset, context, marker=name: calls.append(marker) or queryset,
                ability=ability,
            )

        for scoper in get_core_model_visibility_scopers(ChildModel, ability="view"):
            scoper([], {"ability": "view"})

        self.assertEqual(calls, ["base-any", "base-view", "child-any", "child-view"])

    def test_model_visibility_query_policy_deny_returns_empty_queryset(self):
        from bias_core.visibility import apply_model_visibility_scope

        discussion_model = Discussion.model

        app = ExtensionApplication()
        app.policies.query_model_policy(
            "alpha-tools",
            discussion_model,
            lambda **context: False if context["ability"] == "view" else None,
        )

        with patch("bias_core.extensions.policy_runtime_service.get_extension_application", return_value=app):
            queryset = apply_model_visibility_scope(
                discussion_model,
                discussion_model.objects.all(),
                user=AnonymousUser(),
                ability="view",
            )

        self.assertFalse(queryset.exists())

    def test_theme_extender_contributes_frontend_document_payload(self):
        from bias_core.extensions import SettingsExtender, ThemeExtender, setting_field
        from bias_core.extensions.frontend_runtime_service import build_enabled_frontend_document_payload

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")
        runtime_view = app.get_or_create_runtime_view("alpha-tools", name="Alpha Tools")

        ThemeExtender() \
            .variable("bias-alpha-color", "#123456") \
            .document_classes(["theme-alpha"]) \
            .head_tag("meta", {"name": "theme-alpha", "content": "1"}) \
            .extend(app, extension)
        SettingsExtender(fields=(
            setting_field({
                "key": "accent_color",
                "label": "Accent",
                "type": "text",
                "default": "#224466",
            }),
        )) \
            .theme_variable("bias-alpha-accent", "accent_color") \
            .extend(app, extension)
        app.make("theme")
        app.make("settings")

        from bias_core.extensions.frontend_runtime_service import _build_frontend_document_payload

        with patch("bias_core.extensions.frontend_runtime_service.get_extension_host", return_value=app):
            entry = {
                "id": "alpha-tools",
                "frontend_document": _build_frontend_document_payload(
                    runtime_view,
                    settings_values={"accent_color": "#335577"},
                ),
            }

        with patch("bias_core.extensions.frontend_runtime_service.get_enabled_extension_runtime_entries", return_value=[entry]):
            payload = build_enabled_frontend_document_payload()

        self.assertEqual(payload["theme_variables"]["bias-alpha-color"], "#123456")
        self.assertEqual(payload["theme_variables"]["bias-alpha-accent"], "#335577")
        self.assertEqual(payload["document_attributes"]["class"], ["theme-alpha"])
        self.assertEqual(payload["head_tags"][0]["attributes"]["name"], "theme-alpha")

    def test_settings_extender_serializes_forum_settings_with_alias_and_transform(self):
        from bias_core.extensions import SettingsExtender, setting_field
        from bias_core.extensions.frontend_runtime_service import _build_extension_forum_settings

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")

        SettingsExtender(fields=(
            setting_field({
                "key": "allow_username_format",
                "label": "Allow username format",
                "type": "boolean",
                "default": False,
            }),
        ), expose_to_forum=("allow_username_format",)) \
            .serialize_to_forum("allowUsernameMentionFormat", "allow_username_format", bool) \
            .extend(app, extension)
        app.make("settings")

        runtime_view = app.get_runtime_view("alpha-tools")
        payload = _build_extension_forum_settings(
            {
                "forum_settings_keys": tuple(runtime_view.forum_settings_keys),
                "forum_serializations": tuple(runtime_view.settings_forum_serializations),
            },
            {"allow_username_format": "1"},
        )

        self.assertEqual(payload["allow_username_format"], "1")
        self.assertTrue(payload["allowUsernameMentionFormat"])

    def test_frontend_runtime_treats_default_only_forum_settings_as_visible(self):
        from bias_core.extensions.frontend_runtime_service import _is_product_visible_frontend_extension

        extension = SimpleNamespace(source="filesystem", manifest=SimpleNamespace(extra={}))
        runtime_view = SimpleNamespace(
            settings_schema=(),
            settings_defaults=(SimpleNamespace(key="extensions.security.auth_human_verification_provider", value="off"),),
            settings_forum_serializations=(SimpleNamespace(
                attribute="auth_human_verification_provider",
                key="extensions.security.auth_human_verification_provider",
            ),),
            forum_settings_keys=(),
        )

        self.assertTrue(_is_product_visible_frontend_extension(
            extension,
            admin_entry="",
            forum_entry="",
            common_entry="",
            frontend_routes=(),
            runtime_view=runtime_view,
        ))

    def test_validator_extender_runs_during_resource_payload_application(self):
        from bias_core.resource_registry import ResourceRegistry
        from bias_core.resource_objects import Resource, ResourceField
        from bias_core.resource_errors import JsonApiValidationError

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")

        def reject_bad_title(payload, context):
            if payload["payload"].get("title") == "bad":
                raise ValueError("title rejected")

        ValidatorExtender().validator("title", "validated", reject_bad_title).extend(app, extension)
        app.make("validators")

        class Target:
            title = "old"

        class ValidatedResource(Resource):
            def type(self):
                return "validated"

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: instance.title).writable_when()]

        registry = ResourceRegistry()
        registry.register_resource(ValidatedResource())

        with patch("bias_core.extensions.bootstrap.get_extension_host", return_value=app):
            with self.assertRaises(JsonApiValidationError):
                registry.apply_resource_payload("validated", Target(), {"title": "bad"})

    def test_validator_extender_matches_instance_class_targets(self):
        from bias_core.resource_registry import ResourceRegistry
        from bias_core.resource_objects import Resource, ResourceField
        from bias_core.resource_errors import JsonApiValidationError

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")

        class Target:
            title = "old"

        def reject_by_class(payload, context):
            if payload["payload"].get("title") == "bad":
                raise ValueError("class rejected")

        ValidatorExtender().validator("target", Target.__name__, reject_by_class).extend(app, extension)
        app.make("validators")

        class ValidatedResource(Resource):
            def type(self):
                return "validated-class"

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: instance.title).writable_when()]

        registry = ResourceRegistry()
        registry.register_resource(ValidatedResource())

        with patch("bias_core.extensions.bootstrap.get_extension_host", return_value=app):
            with self.assertRaises(JsonApiValidationError):
                registry.apply_resource_payload("validated-class", Target(), {"title": "bad"})

    def test_extension_lifecycle_extender_runs_on_state_changes(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import LifecycleExtender\n"
                "from bias_core.models import ExtensionInstallation\n"
                "\n"
                "def state():\n"
                "    item = ExtensionInstallation.objects.get(extension_id='alpha-tools')\n"
                "    return item.installed, item.enabled, item.booted\n"
                "\n"
                "def install(context):\n"
                "    label = 'installed-target' if context.installed and not context.enabled and state() == (True, False, False) else 'installed-old-state'\n"
                "    return {'status': 'ok', 'status_label': label, 'message': context.extension_id}\n"
                "\n"
                "def enable(context):\n"
                "    label = 'enabled-target' if context.installed and context.enabled and context.booted and state() == (True, True, True) else 'enabled-old-state'\n"
                "    return {'status': 'ok', 'status_label': label}\n"
                "\n"
                "def disable(context):\n"
                "    label = 'disabled-target' if context.installed and not context.enabled and not context.booted and state() == (True, False, False) else 'disabled-old-state'\n"
                "    return {'status': 'ok', 'status_label': label}\n"
                "\n"
                "def uninstall(context):\n"
                "    label = 'uninstalled-target' if not context.installed and not context.enabled and not context.booted and state() == (False, False, False) else 'uninstalled-old-state'\n"
                "    return {'status': 'ok', 'status_label': label}\n"
                "\n"
                "def extend():\n"
                "    return [LifecycleExtender(install=install, enable=enable, disable=disable, uninstall=uninstall)]\n",
                encoding="utf-8",
            )

            registry = ExtensionRegistry(extensions_path=extensions_dir)
            installed = registry.install_extension("alpha-tools")
            self.assertEqual(installed.runtime.backend_hooks["run_install"]["status_label"], "installed-target")
            self.assertIn("lifecycle_results", installed.runtime.backend_hooks["run_install"]["details"])

            disabled = registry.set_extension_enabled("alpha-tools", False)
            self.assertEqual(disabled.runtime.backend_hooks["run_disable"]["status_label"], "disabled-target")
            enabled = registry.set_extension_enabled("alpha-tools", True)
            self.assertEqual(enabled.runtime.backend_hooks["run_enable"]["status_label"], "enabled-target")
            registry.set_extension_enabled("alpha-tools", False)
            uninstalled = registry.uninstall_extension("alpha-tools")
            self.assertEqual(uninstalled.runtime.backend_hooks["run_uninstall"]["status_label"], "uninstalled-target")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_application_runtime_view_records_lifecycle_hook_contracts(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import LifecycleExtender\n"
                "\n"
                "def enable(context):\n"
                "    return {'status': 'ok'}\n"
                "\n"
                "def disable(context):\n"
                "    return {'status': 'ok'}\n"
                "\n"
                "def extend():\n"
                "    return [LifecycleExtender(enable=enable, disable=disable)]\n",
                encoding="utf-8",
            )
            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            registry = ExtensionRegistry(extensions_path=extensions_dir)
            application = build_extension_application(manager=registry, force=True)
            runtime_view = application.get_runtime_view("alpha-tools")

            self.assertEqual(runtime_view.lifecycle_extender_keys, ("LifecycleExtender",))
            self.assertEqual(runtime_view.lifecycle_hook_keys, ("enable", "disable"))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extension_lifecycle_error_blocks_state_transition(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import LifecycleExtender\n"
                "\n"
                "def enable(context):\n"
                "    return {'status': 'error', 'message': 'enable failed'}\n"
                "\n"
                "def extend():\n"
                "    return [LifecycleExtender(enable=enable)]\n",
                encoding="utf-8",
            )
            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=False,
                installed=True,
                booted=False,
            )

            registry = ExtensionRegistry(extensions_path=extensions_dir)
            with self.assertRaises(ExtensionStateError) as raised:
                registry.set_extension_enabled("alpha-tools", True)

            self.assertEqual(raised.exception.code, "extension_lifecycle_failed")
            installation = ExtensionInstallation.objects.get(extension_id="alpha-tools")
            self.assertFalse(installation.enabled)
            self.assertFalse(installation.booted)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extension_asset_publish_and_runtime_rebuild_marker(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                extensions_dir = Path(temp_dir) / "extensions"
                manifest_dir = extensions_dir / "alpha-tools"
                backend_dir = manifest_dir / "backend"
                assets_dir = manifest_dir / "assets"
                manifest_dir.mkdir(parents=True, exist_ok=False)
                backend_dir.mkdir(parents=True, exist_ok=False)
                assets_dir.mkdir(parents=True, exist_ok=False)
                (assets_dir / "logo.txt").write_text("asset", encoding="utf-8")
                (manifest_dir / "extension.json").write_text(json.dumps({
                    "id": "alpha-tools",
                    "name": "Alpha Tools",
                    "version": "1.0.0",
                    "backend_entry": "extensions.alpha_tools.backend.ext",
                }, ensure_ascii=False), encoding="utf-8")
                (backend_dir / "ext.py").write_text("def extend():\n    return []\n", encoding="utf-8")

                import_map = get_extension_frontend_import_map_path()
                output_manifest = get_extension_frontend_output_manifest_path()
                build_manifest = Path(temp_dir) / "static" / "extensions" / "frontend-build-manifest.json"
                import_map.parent.mkdir(parents=True, exist_ok=True)
                output_manifest.parent.mkdir(parents=True, exist_ok=True)
                build_manifest.parent.mkdir(parents=True, exist_ok=True)
                import_map.write_text("export const staleExtensionModules = {}\n", encoding="utf-8")
                output_manifest.write_text('{"stale": true}', encoding="utf-8")
                build_manifest.write_text('{"stale": true}', encoding="utf-8")

                bootstrap_extension_runtime_event_listeners()
                registry = ExtensionRegistry(extensions_path=extensions_dir)
                with self.captureOnCommitCallbacks(execute=True):
                    installed = registry.install_extension("alpha-tools")

                published_file = Path(temp_dir) / "static" / "extensions" / "alpha-tools" / "logo.txt"
                self.assertTrue(published_file.exists())
                self.assertEqual(installed.runtime.backend_hooks["publish_assets"]["status"], "ok")
                self.assertIn("run_enable", installed.runtime.backend_hooks)
                published_details = installed.runtime.backend_hooks["publish_assets"]["details"]
                self.assertEqual(published_details["files"][0]["path"], "logo.txt")
                self.assertIn("sha256", published_details["files"][0])
                self.assertIn("/static/extensions/alpha-tools/logo.txt", published_details["files"][0]["url"])
                self.assertTrue(published_details["cache_key"])

                rebuild_marker = Setting.objects.get(key="extensions_runtime_rebuild_required")
                self.assertIn("extension_enabled", rebuild_marker.value)
                self.assertTrue(output_manifest.exists())
                self.assertTrue(build_manifest.exists())
                self.assertNotIn("stale", output_manifest.read_text(encoding="utf-8"))
                self.assertNotIn("stale", build_manifest.read_text(encoding="utf-8"))
                self.assertTrue(import_map.exists())
                import_map_source = import_map.read_text(encoding="utf-8")
                self.assertIn("generatedAdminExtensionModules", import_map_source)
                self.assertNotIn("staleExtensionModules", import_map_source)

                with self.captureOnCommitCallbacks(execute=True):
                    registry.set_extension_enabled("alpha-tools", False)
                self.assertFalse(published_file.exists())
                disabled_marker = Setting.objects.get(key="extensions_runtime_rebuild_required")
                self.assertIn("extension_disabled", disabled_marker.value)
                self.assertNotIn("alpha-tools", build_manifest.read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extension_runtime_version_survives_rebuild_marker_clear(self):
        from bias_core.extensions.lifecycle import (
            RUNTIME_REBUILD_MARKER_KEY,
            RUNTIME_VERSION_KEY,
            clear_extension_runtime_rebuild_marker,
            mark_extension_runtime_requires_rebuild,
        )

        mark_extension_runtime_requires_rebuild("extension_enabled", extension_id="alpha-tools")

        marker = Setting.objects.get(key=RUNTIME_REBUILD_MARKER_KEY)
        version = Setting.objects.get(key=RUNTIME_VERSION_KEY)
        self.assertIn("extension_enabled", marker.value)
        self.assertIn("alpha-tools", version.value)

        clear_extension_runtime_rebuild_marker()

        self.assertFalse(Setting.objects.filter(key=RUNTIME_REBUILD_MARKER_KEY).exists())
        self.assertEqual(Setting.objects.get(key=RUNTIME_VERSION_KEY).value, version.value)

    def test_extension_runtime_invalidation_middleware_rebuilds_from_persistent_version(self):
        from bias_core.extensions.lifecycle import (
            RUNTIME_REBUILD_MARKER_KEY,
            clear_extension_runtime_rebuild_marker,
            mark_extension_runtime_requires_rebuild,
            reset_extension_runtime_version_seen,
        )
        from bias_core.middleware import ExtensionRuntimeInvalidationMiddleware

        mark_extension_runtime_requires_rebuild("extension_enabled", extension_id="alpha-tools")
        clear_extension_runtime_rebuild_marker()
        reset_extension_runtime_version_seen()

        request = RequestFactory().get("/api/forum")
        middleware = ExtensionRuntimeInvalidationMiddleware(lambda current_request: HttpResponse("ok"))
        with patch("bias_core.extensions.lifecycle.rebuild_extension_runtime_state") as rebuild_runtime:
            response = middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Setting.objects.filter(key=RUNTIME_REBUILD_MARKER_KEY).exists())
        rebuild_runtime.assert_called_once_with()

    def test_extension_runtime_invalidation_middleware_uses_short_version_cache(self):
        from bias_core.extensions.lifecycle import mark_extension_runtime_version_seen, reset_extension_runtime_version_seen
        from bias_core.middleware import ExtensionRuntimeInvalidationMiddleware

        reset_extension_runtime_version_seen()
        mark_extension_runtime_version_seen("stable-version")

        request = RequestFactory().get("/api/forum")
        middleware = ExtensionRuntimeInvalidationMiddleware(lambda current_request: HttpResponse("ok"))
        with patch("bias_core.extensions.lifecycle.get_extension_runtime_version", return_value="stable-version") as get_version:
            first = middleware(request)
            second = middleware(request)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        get_version.assert_called_once_with()

    def test_maintenance_mode_exemption_skips_jwt_resolution_without_token(self):
        from bias_core.middleware import MaintenanceModeMiddleware

        request = RequestFactory().post("/api/discussions/")
        middleware = MaintenanceModeMiddleware(lambda current_request: HttpResponse("ok"))

        with patch("bias_core.middleware.resolve_authenticated_user") as resolve_user:
            exempt = middleware._is_exempt(request, mode="high")

        self.assertFalse(exempt)
        resolve_user.assert_not_called()

    def test_maintenance_mode_exemption_checks_jwt_when_token_present(self):
        from bias_core.jwt_auth import ACCESS_TOKEN_COOKIE_NAME
        from bias_core.middleware import MaintenanceModeMiddleware

        request = RequestFactory().post("/api/discussions/")
        request.COOKIES[ACCESS_TOKEN_COOKIE_NAME] = "token"
        middleware = MaintenanceModeMiddleware(lambda current_request: HttpResponse("ok"))
        staff = SimpleNamespace(is_staff=True)

        with patch("bias_core.middleware.resolve_authenticated_user", return_value=staff) as resolve_user:
            exempt = middleware._is_exempt(request, mode="high")

        self.assertTrue(exempt)
        resolve_user.assert_called_once_with(request)

    @override_settings(BIAS_EXTENSION_AUTO_FRONTEND_REBUILD=True, BIAS_EXTENSION_AUTO_FRONTEND_PUBLISH=True)
    def test_extension_runtime_invalidation_can_auto_rebuild_frontend_assets(self):
        from bias_core.extensions.lifecycle import (
            RUNTIME_REBUILD_MARKER_KEY,
            RUNTIME_VERSION_KEY,
            invalidate_extension_frontend_assets,
        )

        class CompileResult:
            def to_dict(self):
                return {"status": "ok", "message": "rebuilt"}

        Setting.objects.filter(key__in=[RUNTIME_REBUILD_MARKER_KEY, RUNTIME_VERSION_KEY]).delete()
        with patch(
            "bias_core.extensions.frontend_compiler.recompile_extension_frontend_assets",
            return_value=CompileResult(),
        ) as recompile:
            result = invalidate_extension_frontend_assets("extension_enabled", extension_id="alpha-tools")

        self.assertTrue(result["auto_rebuild"])
        self.assertTrue(result["auto_publish"])
        recompile.assert_called_once()
        self.assertTrue(recompile.call_args.kwargs["run_build"])
        self.assertTrue(recompile.call_args.kwargs["clear_marker"])
        self.assertTrue(recompile.call_args.kwargs["publish_dist"])
        self.assertFalse(Setting.objects.filter(key=RUNTIME_REBUILD_MARKER_KEY).exists())
        self.assertIn("extension_enabled", Setting.objects.get(key=RUNTIME_VERSION_KEY).value)

    def test_build_extension_frontend_command_writes_manifest(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                extensions_dir = Path(temp_dir) / "extensions"
                manifest_dir = extensions_dir / "alpha-tools"
                backend_dir = manifest_dir / "backend"
                manifest_dir.mkdir(parents=True, exist_ok=False)
                backend_dir.mkdir(parents=True, exist_ok=False)
                (manifest_dir / "extension.json").write_text(json.dumps({
                    "id": "alpha-tools",
                    "name": "Alpha Tools",
                    "version": "1.0.0",
                    "backend_entry": "extensions.alpha_tools.backend.ext",
                    "frontend_forum_entry": "extensions/alpha-tools/frontend/forum/index.js",
                }, ensure_ascii=False), encoding="utf-8")
                (backend_dir / "ext.py").write_text("def extend():\n    return []\n", encoding="utf-8")
                ExtensionInstallation.objects.create(
                    extension_id="alpha-tools",
                    version="1.0.0",
                    source="filesystem",
                    enabled=True,
                    installed=True,
                    booted=True,
                )

                call_command("build_extension_frontend", stdout=StringIO())
                manifest = json.loads((Path(temp_dir) / "static" / "extensions" / "frontend-build-manifest.json").read_text(encoding="utf-8"))
                self.assertIn("alpha-tools", manifest["extensions"])
                self.assertEqual(
                    manifest["extensions"]["alpha-tools"]["inputs"]["forum"],
                    "extensions/alpha-tools/frontend/forum/index.js",
                )
                self.assertTrue(manifest["extensions"]["alpha-tools"]["cache_key"])
                import_map = get_extension_frontend_import_map_path()
                output_manifest = get_extension_frontend_output_manifest_path()
                self.assertTrue(import_map.exists())
                self.assertTrue(output_manifest.exists())
                import_map_source = import_map.read_text(encoding="utf-8")
                self.assertIn("generatedForumExtensionModules", import_map_source)
                self.assertIn("../../../extensions/alpha-tools/frontend/forum/index.js", import_map_source)
                output_payload = json.loads(output_manifest.read_text(encoding="utf-8"))
                self.assertIn("alpha-tools", output_payload["extensions"])
                self.assertTrue(output_payload["input_revision"])
                self.assertFalse(output_payload["build"]["ran"])
                inspected = inspect_extension_frontend_output_manifest()
                self.assertEqual(inspected["input_revision"], output_payload["input_revision"])
                self.assertEqual(inspected["current_input_revision"], output_payload["input_revision"])
                self.assertFalse(inspected["input_stale"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extension_frontend_output_manifest_maps_vite_chunks(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                vite_manifest = get_frontend_vite_manifest_path()
                vite_manifest.parent.mkdir(parents=True, exist_ok=True)
                vite_manifest.write_text(json.dumps({
                    "extensions/alpha-tools/frontend/forum/index.js": {
                        "file": "assets/alpha-forum.js",
                        "css": ["assets/alpha-forum.css"],
                        "imports": ["assets/vendor.js"],
                        "dynamicImports": ["../../../extensions/alpha-tools/frontend/forum/lazy.js"],
                    },
                    "../../../extensions/alpha-tools/frontend/forum/lazy.js": {
                        "file": "assets/chunk.js",
                        "css": ["assets/chunk.css"],
                        "imports": ["assets/vendor.js"],
                    },
                    "../../../extensions/alpha-tools/frontend/forum/Page.vue": {
                        "file": "assets/page.js",
                        "css": ["assets/page.css"],
                        "imports": ["assets/vendor.js"],
                    }
                }, ensure_ascii=False), encoding="utf-8")
                output = build_extension_frontend_output_manifest({
                    "extensions": {
                        "alpha-tools": {
                            "extension_id": "alpha-tools",
                            "forum_entry": "extensions/alpha-tools/frontend/forum/index.js",
                            "admin_entry": "",
                            "routes": [{
                                "path": "/alpha",
                                "name": "alpha.page",
                                "component": "./Page.vue",
                                "frontend": "forum",
                            }],
                        }
                    }
                })

                forum_output = output["extensions"]["alpha-tools"]["outputs"]["forum"]
                self.assertTrue(output["revision"])
                self.assertTrue(output["input_revision"])
                self.assertEqual(output["extensions"]["alpha-tools"]["revision"], output["revision"])
                self.assertEqual(forum_output["revision"], output["revision"])
                self.assertEqual(forum_output["file"], "assets/alpha-forum.js")
                self.assertEqual(forum_output["css"], ["assets/alpha-forum.css"])
                self.assertEqual(forum_output["imports"], ["assets/vendor.js"])
                self.assertEqual(forum_output["dynamic_imports"], ["../../../extensions/alpha-tools/frontend/forum/lazy.js"])
                self.assertEqual(forum_output["chunks"][0]["module_id"], "frontend/forum/lazy.js")
                self.assertEqual(forum_output["chunks"][0]["file"], "assets/chunk.js")
                self.assertEqual(forum_output["chunks"][0]["css"], ["assets/chunk.css"])
                self.assertEqual(forum_output["chunks"][0]["revision"], output["revision"])
                self.assertEqual(forum_output["chunks"][1]["module_id"], "frontend/forum/Page.vue")
                self.assertEqual(forum_output["chunks"][1]["file"], "assets/page.js")
                self.assertEqual(forum_output["chunks"][1]["css"], ["assets/page.css"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extension_frontend_output_manifest_detects_stale_extension_inputs(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                first_manifest = {
                    "extensions": {
                        "alpha-tools": {
                            "extension_id": "alpha-tools",
                            "forum_entry": "extensions/alpha-tools/frontend/forum/index.js",
                        }
                    }
                }
                second_manifest = {
                    "extensions": {
                        "alpha-tools": {
                            "extension_id": "alpha-tools",
                            "forum_entry": "extensions/alpha-tools/frontend/forum/changed.js",
                        }
                    }
                }
                output = build_extension_frontend_output_manifest(first_manifest)
                write_extension_frontend_output_manifest(output)
                build_manifest_path = get_extension_frontend_build_manifest_path()
                build_manifest_path.parent.mkdir(parents=True, exist_ok=True)
                build_manifest_path.write_text(json.dumps(second_manifest, ensure_ascii=False), encoding="utf-8")

                inspected = inspect_extension_frontend_output_manifest()

                self.assertTrue(inspected["input_revision"])
                self.assertTrue(inspected["current_input_revision"])
                self.assertNotEqual(inspected["input_revision"], inspected["current_input_revision"])
                self.assertTrue(inspected["input_stale"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_recompile_extension_frontend_assets_reports_missing_npm(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                extension = SimpleNamespace(
                    id="alpha-tools",
                    source="filesystem",
                    frontend_admin_entry="",
                    frontend_forum_entry="extensions/alpha-tools/frontend/forum/index.js",
                    manifest=SimpleNamespace(path=str(Path(temp_dir) / "extensions" / "alpha-tools")),
                    runtime=SimpleNamespace(enabled=True),
                    frontend_routes=(),
                    discover=lambda: SimpleNamespace(
                        frontend_css=(),
                        frontend_js_directories=(),
                        frontend_preloads=(),
                        frontend_document_attributes=(),
                        frontend_title_driver=None,
                        frontend_routes=(),
                    ),
                )
                with patch("bias_core.extensions.frontend_compiler.subprocess.run", side_effect=FileNotFoundError("npm")):
                    result = recompile_extension_frontend_assets([extension], run_build=True)

                self.assertEqual(result.status, "error")
                self.assertEqual(result.status_label, "编译环境缺失")
                self.assertIn("npm", result.message)
                self.assertTrue(result.input_revision)
                self.assertTrue(get_extension_frontend_output_manifest_path().exists())
                payload = json.loads(get_extension_frontend_output_manifest_path().read_text(encoding="utf-8"))
                self.assertEqual(payload["status"], "error")
                self.assertEqual(payload["status_label"], "编译环境缺失")
                self.assertEqual(payload["input_revision"], result.input_revision)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extension_frontend_output_manifest_maps_route_only_components(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                vite_manifest = get_frontend_vite_manifest_path()
                vite_manifest.parent.mkdir(parents=True, exist_ok=True)
                vite_manifest.write_text(json.dumps({
                    "../../../extensions/alpha-tools/frontend/admin/Page.vue": {
                        "file": "assets/admin-page.js",
                        "css": ["assets/admin-page.css"],
                    },
                    "../../../extensions/alpha-tools/frontend/forum/Page.vue": {
                        "file": "assets/forum-page.js",
                        "css": ["assets/forum-page.css"],
                    },
                }, ensure_ascii=False), encoding="utf-8")

                output = build_extension_frontend_output_manifest({
                    "extensions": {
                        "alpha-tools": {
                            "extension_id": "alpha-tools",
                            "admin_entry": "",
                            "forum_entry": "",
                            "routes": [
                                {
                                    "path": "/admin/alpha",
                                    "name": "alpha.admin",
                                    "component": "./Page.vue",
                                    "frontend": "admin",
                                },
                                {
                                    "path": "/alpha",
                                    "name": "alpha.page",
                                    "component": "./Page.vue",
                                    "frontend": "forum",
                                },
                            ],
                        }
                    }
                })

                outputs = output["extensions"]["alpha-tools"]["outputs"]
                self.assertEqual(outputs["admin"]["chunks"][0]["module_id"], "frontend/admin/Page.vue")
                self.assertEqual(outputs["admin"]["chunks"][0]["file"], "assets/admin-page.js")
                self.assertEqual(outputs["forum"]["chunks"][0]["module_id"], "frontend/forum/Page.vue")
                self.assertEqual(outputs["forum"]["chunks"][0]["file"], "assets/forum-page.js")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extension_frontend_import_map_uses_inputs_fallback(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                path = write_extension_frontend_import_map({
                    "extensions": {
                        "alpha-tools": {
                            "extension_id": "alpha-tools",
                            "inputs": {
                                "admin": "extensions/alpha-tools/frontend/admin/index.js",
                                "forum": "extensions/alpha-tools/frontend/forum/index.js",
                            },
                        }
                    }
                })

                source = path.read_text(encoding="utf-8")
                self.assertIn("../../../extensions/alpha-tools/frontend/admin/index.js", source)
                self.assertIn("../../../extensions/alpha-tools/frontend/forum/index.js", source)
                self.assertIn('"alpha-tools": () =>', source)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extension_frontend_import_map_includes_css_and_route_components(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                path = write_extension_frontend_import_map({
                    "extensions": {
                        "alpha-tools": {
                            "extension_id": "alpha-tools",
                            "admin_entry": "extensions/alpha-tools/frontend/admin/index.js",
                            "forum_entry": "extensions/alpha-tools/frontend/forum/index.js",
                            "css": ["frontend/forum/style.css"],
                            "routes": [
                                {
                                    "path": "/admin/alpha",
                                    "name": "alpha.admin",
                                    "component": "./AdminPage.vue",
                                    "frontend": "admin",
                                },
                                {
                                    "path": "/alpha",
                                    "name": "alpha.page",
                                    "component": "./Page.vue",
                                    "frontend": "forum",
                                },
                            ],
                        }
                    }
                })

                source = path.read_text(encoding="utf-8")
                self.assertIn("loadExtensionModule", source)
                self.assertIn("../../../extensions/alpha-tools/frontend/forum/style.css", source)
                self.assertNotIn('"./AdminPage.vue": () => import(', source)
                self.assertIn('"extensions/alpha-tools/frontend/admin/AdminPage.vue": () => import("../../../extensions/alpha-tools/frontend/admin/AdminPage.vue")', source)
                self.assertIn('"alpha-tools:./AdminPage.vue": () => import("../../../extensions/alpha-tools/frontend/admin/AdminPage.vue")', source)
                self.assertNotIn('"./Page.vue": () => import(', source)
                self.assertIn('"extensions/alpha-tools/frontend/forum/Page.vue": () => import("../../../extensions/alpha-tools/frontend/forum/Page.vue")', source)
                self.assertIn('"alpha-tools:./Page.vue": () => import("../../../extensions/alpha-tools/frontend/forum/Page.vue")', source)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extension_frontend_import_map_deduplicates_keys_globally(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                path = write_extension_frontend_import_map({
                    "extensions": {
                        "alpha-tools": {
                            "extension_id": "alpha-tools",
                            "forum_entry": "extensions/alpha-tools/frontend/forum/index.js",
                            "routes": [
                                {
                                    "path": "/alpha",
                                    "name": "alpha.page",
                                    "component": "extensions/shared/frontend/forum/SharedPage.vue",
                                    "frontend": "forum",
                                },
                            ],
                        },
                        "beta-tools": {
                            "extension_id": "beta-tools",
                            "forum_entry": "extensions/beta-tools/frontend/forum/index.js",
                            "routes": [
                                {
                                    "path": "/beta",
                                    "name": "beta.page",
                                    "component": "extensions/shared/frontend/forum/SharedPage.vue",
                                    "frontend": "forum",
                                },
                            ],
                        },
                    }
                })

                source = path.read_text(encoding="utf-8")
                self.assertEqual(
                    source.count('"extensions/shared/frontend/forum/SharedPage.vue": () => import("../../../extensions/shared/frontend/forum/SharedPage.vue")'),
                    1,
                )
                self.assertEqual(
                    source.count('"../../../extensions/shared/frontend/forum/SharedPage.vue": () => import("../../../extensions/shared/frontend/forum/SharedPage.vue")'),
                    1,
                )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_copy_frontend_dist_to_static_publishes_dist(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                dist_file = Path(temp_dir) / "frontend" / "dist" / "assets" / "main.js"
                dist_file.parent.mkdir(parents=True, exist_ok=True)
                dist_file.write_text("console.log('ok')", encoding="utf-8")

                result = copy_frontend_dist_to_static()

                published = get_published_frontend_root() / "assets" / "main.js"
                self.assertEqual(result["status"], "ok")
                self.assertTrue(published.exists())
                self.assertEqual(published.read_text(encoding="utf-8"), "console.log('ok')")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_build_extension_frontend_command_flushes_generated_assets(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                import_map = get_extension_frontend_import_map_path()
                output_manifest = get_extension_frontend_output_manifest_path()
                build_manifest = Path(temp_dir) / "static" / "extensions" / "frontend-build-manifest.json"
                import_map.parent.mkdir(parents=True, exist_ok=True)
                output_manifest.parent.mkdir(parents=True, exist_ok=True)
                build_manifest.parent.mkdir(parents=True, exist_ok=True)
                import_map.write_text("export const generatedAdminExtensionModules = {}\nexport const generatedForumExtensionModules = {}\n", encoding="utf-8")
                output_manifest.write_text("{}", encoding="utf-8")
                build_manifest.write_text("{}", encoding="utf-8")

                published_root = get_published_frontend_root()
                published_root.mkdir(parents=True, exist_ok=True)
                (published_root / "index.html").write_text("", encoding="utf-8")

                call_command("build_extension_frontend", "--flush", "--flush-published", stdout=StringIO())

                self.assertTrue(import_map.exists())
                self.assertIn("generatedForumExtensionModules", import_map.read_text(encoding="utf-8"))
                self.assertFalse(output_manifest.exists())
                self.assertFalse(build_manifest.exists())
                self.assertFalse(published_root.exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_sync_extensions_command_prunes_missing_installations(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                from bias_core.extensions.manager import EXTENSION_PACKAGE_LOCK_SETTING

                ExtensionInstallation.objects.create(
                    extension_id="missing-package",
                    version="1.0.0",
                    source="python-package",
                    enabled=True,
                    installed=True,
                    booted=True,
                )

                stdout = StringIO()
                call_command("sync_extensions", stdout=stdout)
                installation = ExtensionInstallation.objects.get(extension_id="missing-package")
                self.assertFalse(installation.enabled)
                self.assertFalse(installation.booted)
                self.assertTrue(installation.meta["sync"]["missing"])
                lock = json.loads(Setting.objects.get(key=EXTENSION_PACKAGE_LOCK_SETTING).value)
                self.assertEqual(lock["schema"], 1)
                missing_package = next(item for item in lock["packages"] if item["id"] == "missing-package")
                self.assertTrue(missing_package["missing"])
                self.assertIn("包锁定:", stdout.getvalue())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_sync_extension_packages_creates_records_for_discovered_extensions(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                from bias_core.extensions.manager import EXTENSION_PACKAGE_LOCK_SETTING, ExtensionManager

                extensions_dir = Path(temp_dir) / "extensions"
                manifest_dir = extensions_dir / "alpha-tools"
                manifest_dir.mkdir(parents=True, exist_ok=False)
                (manifest_dir / "extension.json").write_text(json.dumps({
                    "id": "alpha-tools",
                    "name": "Alpha Tools",
                    "version": "1.0.0",
                    "backend_entry": "extensions.alpha_tools.backend.ext",
                }, ensure_ascii=False), encoding="utf-8")

                result = ExtensionManager(extensions_path=extensions_dir).sync_extension_packages()

                installation = ExtensionInstallation.objects.get(extension_id="alpha-tools")
                lock = json.loads(Setting.objects.get(key=EXTENSION_PACKAGE_LOCK_SETTING).value)

            self.assertEqual(result["created"], ["alpha-tools"])
            self.assertEqual(result["updated"], [])
            self.assertEqual(result["package_inspection"]["summary"]["installation_record_count"], 1)
            self.assertEqual(result["package_inspection"]["summary"]["unmanaged_discovered_count"], 1)
            self.assertFalse(installation.installed)
            self.assertFalse(installation.enabled)
            self.assertFalse(installation.booted)
            self.assertEqual(installation.version, "1.0.0")
            self.assertEqual(installation.source, "filesystem")
            self.assertTrue(installation.meta["sync"]["created"])
            self.assertEqual(lock["packages"][0]["id"], "alpha-tools")
            self.assertFalse(lock["packages"][0]["installed"])
            self.assertFalse(lock["packages"][0]["enabled"])
            self.assertFalse(lock["packages"][0]["missing"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_sync_extension_packages_preserves_auto_install_runtime_state_when_creating_records(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                from bias_core.extensions.manager import ExtensionManager

                extensions_dir = Path(temp_dir) / "extensions"
                manifest_dir = extensions_dir / "users"
                manifest_dir.mkdir(parents=True, exist_ok=False)
                (manifest_dir / "extension.json").write_text(json.dumps({
                    "id": "users",
                    "name": "Users",
                    "version": "1.0.0",
                    "extra": {
                        "auto_install": True,
                        "auto_enable": True,
                    },
                }, ensure_ascii=False), encoding="utf-8")

                result = ExtensionManager(extensions_path=extensions_dir).sync_extension_packages()

                installation = ExtensionInstallation.objects.get(extension_id="users")

            self.assertEqual(result["created"], ["users"])
            self.assertEqual(result["package_inspection"]["summary"]["installation_record_count"], 1)
            self.assertEqual(result["package_inspection"]["summary"]["unmanaged_discovered_count"], 0)
            self.assertTrue(installation.installed)
            self.assertTrue(installation.enabled)
            self.assertTrue(installation.booted)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_sync_extension_packages_preserves_packaged_auto_install_runtime_state(self):
        from bias_core.extensions.extension_runtime import Extension
        from bias_core.extensions.manager import ExtensionManager
        from bias_core.extensions.types import ExtensionManifest

        manifest = ExtensionManifest(
            id="users",
            name="Users",
            version="1.0.0",
            source="python-package",
            path="/site-packages/bias_extensions/users",
            extra={
                "auto_install": True,
                "auto_enable": True,
            },
        )
        manager = ExtensionManager(extensions_path=Path(settings.BASE_DIR) / "extensions")
        with patch.object(manager, "get_extensions", return_value=[Extension.from_manifest(manifest)]):
            result = manager.sync_extension_packages()
            installation = ExtensionInstallation.objects.get(extension_id="users")

        self.assertEqual(result["created"], ["users"])
        self.assertEqual(result["package_inspection"]["summary"]["unmanaged_discovered_count"], 0)
        self.assertTrue(installation.installed)
        self.assertTrue(installation.enabled)
        self.assertTrue(installation.booted)
        self.assertEqual(installation.source, "python-package")

    def test_protected_auto_enabled_extension_loads_enabled_from_stale_disabled_record(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                from bias_core.extensions.manager import ExtensionManager

                extensions_dir = Path(temp_dir) / "extensions"
                manifest_dir = extensions_dir / "discussions"
                manifest_dir.mkdir(parents=True, exist_ok=False)
                (manifest_dir / "extension.json").write_text(json.dumps({
                    "id": "discussions",
                    "name": "Discussions",
                    "version": "1.0.0",
                    "extra": {
                        "auto_install": True,
                        "auto_enable": True,
                        "protected": True,
                    },
                }, ensure_ascii=False), encoding="utf-8")
                ExtensionInstallation.objects.create(
                    extension_id="discussions",
                    version="1.0.0",
                    source="filesystem",
                    installed=True,
                    enabled=False,
                    booted=False,
                )

                extension = ExtensionManager(extensions_path=extensions_dir).get_extension("discussions")

            self.assertTrue(extension.runtime.installed)
            self.assertTrue(extension.runtime.enabled)
            self.assertTrue(extension.runtime.booted)
            self.assertEqual(extension.runtime.status_key, "active")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_sync_extension_packages_repairs_protected_auto_enabled_disabled_record(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                from bias_core.extensions.manager import ExtensionManager

                extensions_dir = Path(temp_dir) / "extensions"
                manifest_dir = extensions_dir / "discussions"
                manifest_dir.mkdir(parents=True, exist_ok=False)
                (manifest_dir / "extension.json").write_text(json.dumps({
                    "id": "discussions",
                    "name": "Discussions",
                    "version": "1.0.0",
                    "extra": {
                        "auto_install": True,
                        "auto_enable": True,
                        "protected": True,
                    },
                }, ensure_ascii=False), encoding="utf-8")
                ExtensionInstallation.objects.create(
                    extension_id="discussions",
                    version="1.0.0",
                    source="filesystem",
                    installed=True,
                    enabled=False,
                    booted=False,
                )

                result = ExtensionManager(extensions_path=extensions_dir).sync_extension_packages()
                installation = ExtensionInstallation.objects.get(extension_id="discussions")

            self.assertEqual(result["updated"], ["discussions"])
            self.assertTrue(installation.installed)
            self.assertTrue(installation.enabled)
            self.assertTrue(installation.booted)
            self.assertEqual(installation.meta["sync"]["reason"], "protected_extension_auto_enabled")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_rebuild_api_urlpatterns_is_idempotent_after_runtime_sync(self):
        import config.urls as root_urls

        first_patterns = root_urls.rebuild_api_urlpatterns()
        second_patterns = root_urls.rebuild_api_urlpatterns()

        self.assertTrue(first_patterns)
        self.assertTrue(second_patterns)
        self.assertNotEqual(root_urls.api.urls_namespace, "bias-api-1")

    @patch("bias_core.extensions.manifest.metadata.distributions")
    def test_sync_extension_packages_persists_distribution_package_lock(self, distributions_mock):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir), BIAS_EXTENSION_PACKAGE_DISCOVERY=True):
                from bias_core.extensions import manifest as manifest_module
                from bias_core.extensions.manager import EXTENSION_PACKAGE_LOCK_SETTING, ExtensionManager

                manifest_module._distribution_manifest_cache = None
                package_dir = Path(temp_dir) / "site-packages" / "alpha_tools" / "bias_extension"
                package_dir.mkdir(parents=True, exist_ok=False)
                (package_dir / "extension.json").write_text(json.dumps({
                    "id": "alpha-tools",
                    "name": "Alpha Tools",
                    "version": "1.2.3",
                    "abandoned": "vendor/beta-tools",
                }, ensure_ascii=False), encoding="utf-8")

                class DemoDistribution:
                    version = "1.2.3"
                    files = ("alpha_tools/bias_extension/extension.json",)
                    metadata = {"Name": "alpha-tools"}

                    def locate_file(self, file):
                        return Path(temp_dir) / "site-packages" / str(file)

                distributions_mock.return_value = [DemoDistribution()]
                ExtensionInstallation.objects.create(
                    extension_id="alpha-tools",
                    version="1.0.0",
                    source="filesystem",
                    enabled=True,
                    installed=True,
                    booted=True,
                )

                result = ExtensionManager(extensions_path=Path(temp_dir) / "extensions").sync_extension_packages()

                installation = ExtensionInstallation.objects.get(extension_id="alpha-tools")
                lock = json.loads(Setting.objects.get(key=EXTENSION_PACKAGE_LOCK_SETTING).value)

            self.assertEqual(result["discovered"], ["alpha-tools"])
            self.assertEqual(result["updated"], ["alpha-tools"])
            self.assertEqual(result["locked"], 1)
            self.assertEqual(result["package_inspection"]["summary"]["locked_count"], 1)
            self.assertEqual(result["package_inspection"]["summary"]["missing_count"], 0)
            self.assertEqual(installation.version, "1.2.3")
            self.assertEqual(installation.source, "python-package")
            self.assertEqual(lock["packages"][0]["id"], "alpha-tools")
            self.assertEqual(lock["packages"][0]["source"], "python-package")
            self.assertEqual(lock["packages"][0]["distribution"]["name"], "alpha-tools")
            self.assertEqual(lock["packages"][0]["distribution"]["version"], "1.2.3")
            self.assertTrue(lock["packages"][0]["abandoned"])
            self.assertEqual(lock["packages"][0]["replacement"], "vendor/beta-tools")
            self.assertFalse(lock["packages"][0]["missing"])
            self.assertTrue(lock["packages"][0]["discovered"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_application_bootstrap_collects_extension_middleware_and_policy_mounts(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import MiddlewareExtender, PolicyExtender\n"
                "\n"
                "def demo_middleware(request):\n"
                "    return request\n"
                "\n"
                "def can_use_demo(user=None, **kwargs):\n"
                "    return True\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        MiddlewareExtender(mounts=(('api', demo_middleware, 30),)),\n"
                "        PolicyExtender(mounts=(('demo.use', can_use_demo),)),\n"
                "    ]\n",
                encoding="utf-8",
            )

            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            registry = ExtensionRegistry(extensions_path=extensions_dir)
            application = build_extension_application(manager=registry, force=True)
            runtime_view = application.get_runtime_view("alpha-tools")

            self.assertIsNotNone(runtime_view)
            self.assertEqual(len(runtime_view.middleware_mounts), 1)
            self.assertEqual(runtime_view.middleware_mounts[0].target, "api")
            self.assertEqual(runtime_view.middleware_mounts[0].order, 30)
            self.assertEqual(len(runtime_view.policy_mounts), 1)
            self.assertEqual(runtime_view.policy_mounts[0].key, "demo.use")
            self.assertTrue(runtime_view.policy_mounts[0].handler())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_application_bootstrap_collects_extension_realtime_included_enrichers(self):
        from bias_core.forum_runtime import (
            clear_realtime_service,
            iter_realtime_included_enrichers,
            iter_realtime_discussion_transports,
            resolve_realtime_visible_discussion_ids,
        )

        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import RealtimeExtender\n"
                "\n"
                "def enrich_alpha(**kwargs):\n"
                "    return {'alpha': [{'id': '1', 'value': 'ok'}]}\n"
                "\n"
                "def visible_discussions(discussion_ids, user):\n"
                "    return [int(item) for item in discussion_ids if int(item) == 2]\n"
                "\n"
                "def broadcast_alpha(discussion_id, event_type, payload):\n"
                "    return None\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        RealtimeExtender()\n"
                "            .included_payload('alpha', enrich_alpha, description='Alpha included payload')\n"
                "            .discussion_visibility(visible_discussions, description='Alpha discussion visibility')\n"
                "            .discussion_transport('alpha.websocket', broadcast_alpha, description='Alpha discussion transport'),\n"
                "    ]\n",
                encoding="utf-8",
            )

            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            clear_realtime_service()
            registry = ExtensionRegistry(extensions_path=extensions_dir)
            application = build_extension_application(manager=registry, force=True)
            runtime_view = application.get_runtime_view("alpha-tools")

            self.assertIsNotNone(runtime_view)
            self.assertEqual(len(runtime_view.realtime_included), 1)
            self.assertEqual(runtime_view.realtime_included[0].key, "alpha")
            self.assertEqual(len(runtime_view.realtime_discussion_visibility), 1)
            self.assertEqual(len(runtime_view.realtime_discussion_transports), 1)
            self.assertEqual(application.realtime.get_included_enrichers(extension_id="alpha-tools")[0].description, "Alpha included payload")
            self.assertEqual(
                application.realtime.get_discussion_visibility_resolvers(extension_id="alpha-tools")[0].description,
                "Alpha discussion visibility",
            )
            self.assertEqual(
                application.realtime.get_discussion_transports(extension_id="alpha-tools")[0].description,
                "Alpha discussion transport",
            )
            included_payload = {}
            for enricher in iter_realtime_included_enrichers():
                included_payload.update(enricher())

            self.assertEqual(included_payload["alpha"][0]["value"], "ok")
            self.assertEqual(resolve_realtime_visible_discussion_ids([1, 2], Mock()), [2])
            self.assertEqual(len(iter_realtime_discussion_transports()), 1)
        finally:
            clear_realtime_service()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_application_bootstrap_registers_string_domain_event_listeners(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (extensions_dir / "__init__.py").write_text("", encoding="utf-8")
            package_dir = extensions_dir / "alpha_tools"
            package_backend_dir = package_dir / "backend"
            package_backend_dir.mkdir(parents=True, exist_ok=False)
            (package_dir / "__init__.py").write_text("", encoding="utf-8")
            (package_backend_dir / "__init__.py").write_text("", encoding="utf-8")
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import EventListenersExtender\n"
                "from bias_core.extensions import ExtensionEventListenerDefinition\n"
                "\n"
                "seen = []\n"
                "\n"
                "def record_alpha(event):\n"
                "    seen.append(event.value)\n"
                "\n"
                "def extend():\n"
                "    return [EventListenersExtender(listeners=(ExtensionEventListenerDefinition(\n"
                f"        event_type='{AlphaStringEvent.__module__}.{AlphaStringEvent.__name__}',\n"
                "        handler=record_alpha,\n"
                "        description='String event listener',\n"
                "    ),))]\n",
                encoding="utf-8",
            )

            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            registry = ExtensionRegistry(extensions_path=extensions_dir)
            application = build_extension_application(manager=registry, force=True)
            runtime_view = application.get_runtime_view("alpha-tools")

            application.event_bus.dispatch(AlphaStringEvent(value="ok"))
            handler_state = runtime_view.event_listeners[0].handler.__globals__["seen"]

            self.assertIsNotNone(runtime_view)
            self.assertEqual(runtime_view.event_listeners[0].event_type, AlphaStringEvent)
            self.assertEqual(handler_state, ["ok"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_event_listener_registration_replaces_same_runtime_key(self):
        from bias_core.domain_events import DomainEvent
        from bias_core.extensions import EventListenersExtender, ExtensionEventListenerDefinition

        class AlphaRuntimeEvent(DomainEvent):
            pass

        received = []

        def first_handler(event):
            received.append("first")

        def replacement_handler(event):
            received.append("replacement")

        replacement_handler.__module__ = first_handler.__module__
        replacement_handler.__qualname__ = first_handler.__qualname__
        replacement_handler.__name__ = first_handler.__name__

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")
        first_definition = ExtensionEventListenerDefinition(
            event_type=AlphaRuntimeEvent,
            handler=first_handler,
        )
        replacement_definition = ExtensionEventListenerDefinition(
            event_type=AlphaRuntimeEvent,
            handler=replacement_handler,
        )

        EventListenersExtender(listeners=(first_definition,)).extend(app, extension)
        app.make("events")
        EventListenersExtender(listeners=(replacement_definition,)).extend(app, extension)
        app.make("events")

        app.event_bus.dispatch(AlphaRuntimeEvent())

        self.assertEqual(received, ["replacement"])
        listeners = app.events.get_listeners(extension_id="alpha-tools")
        self.assertEqual(len(listeners), 1)
        self.assertIs(listeners[0].handler, replacement_handler)

    def test_extension_application_resource_and_event_compat_reuses_service_replacement(self):
        from bias_core.domain_events import DomainEvent
        from bias_core.extensions import (
            ExtensionEventListenerDefinition,
            ExtensionResourceDefinition,
            ExtensionResourceFieldDefinition,
            ExtensionResourceRelationshipDefinition,
        )

        class AlphaRuntimeEvent(DomainEvent):
            pass

        calls = []

        def first_handler(event):
            calls.append("first")

        def replacement_handler(event):
            calls.append("replacement")

        replacement_handler.__module__ = first_handler.__module__
        replacement_handler.__qualname__ = first_handler.__qualname__
        replacement_handler.__name__ = first_handler.__name__

        app = ExtensionApplication()
        extension = app.get_or_create_runtime_view("alpha-tools")
        first_resource = ExtensionResourceDefinition(
            resource="alpha",
            module_id="alpha-tools",
            resolver=lambda instance, context: {"name": "old"},
        )
        replacement_resource = ExtensionResourceDefinition(
            resource="alpha",
            module_id="alpha-tools",
            resolver=lambda instance, context: {"name": "new"},
        )
        first_field = ExtensionResourceFieldDefinition(
            resource="alpha",
            field="label",
            module_id="alpha-tools",
            resolver=lambda instance, context: "old",
        )
        replacement_field = ExtensionResourceFieldDefinition(
            resource="alpha",
            field="label",
            module_id="alpha-tools",
            resolver=lambda instance, context: "new",
        )
        first_relationship = ExtensionResourceRelationshipDefinition(
            resource="alpha",
            relationship="owner",
            module_id="alpha-tools",
            resolver=lambda instance, context: {"id": "old"},
        )
        replacement_relationship = ExtensionResourceRelationshipDefinition(
            resource="alpha",
            relationship="owner",
            module_id="alpha-tools",
            resolver=lambda instance, context: {"id": "new"},
        )

        app.register_resource(extension, first_resource)
        app.register_resource(extension, replacement_resource)
        app.register_resource_field(extension, first_field)
        app.register_resource_field(extension, replacement_field)
        app.register_resource_relationship(extension, first_relationship)
        app.register_resource_relationship(extension, replacement_relationship)
        app.register_event_listener(
            extension,
            ExtensionEventListenerDefinition(AlphaRuntimeEvent, first_handler),
        )
        app.register_event_listener(
            extension,
            ExtensionEventListenerDefinition(AlphaRuntimeEvent, replacement_handler),
        )

        runtime_view = app.get_runtime_view("alpha-tools")
        app.event_bus.dispatch(AlphaRuntimeEvent())

        self.assertEqual(len(runtime_view.resource_definitions), 1)
        self.assertEqual(runtime_view.resource_definitions[0].resolver(None, {}), {"name": "new"})
        self.assertEqual(app.resources.get_resource("alpha").resolver(None, {}), {"name": "new"})
        self.assertEqual(len(runtime_view.resource_fields), 1)
        self.assertEqual(runtime_view.resource_fields[0].resolver(None, {}), "new")
        self.assertEqual(app.resources.get_fields("alpha")[0].resolver(None, {}), "new")
        self.assertEqual(len(runtime_view.resource_relationships), 1)
        self.assertEqual(runtime_view.resource_relationships[0].resolver(None, {}), {"id": "new"})
        self.assertEqual(app.resources.get_relationships("alpha")[0].resolver(None, {}), {"id": "new"})
        self.assertEqual(len(runtime_view.event_listeners), 1)
        self.assertIs(runtime_view.event_listeners[0].handler, replacement_handler)
        self.assertEqual(calls, ["replacement"])

    def test_application_bootstrap_registers_extension_realtime_discussion_broadcasts(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (extensions_dir / "__init__.py").write_text("", encoding="utf-8")
            package_dir = extensions_dir / "alpha_tools"
            package_backend_dir = package_dir / "backend"
            package_backend_dir.mkdir(parents=True, exist_ok=False)
            (package_dir / "__init__.py").write_text("", encoding="utf-8")
            (package_backend_dir / "__init__.py").write_text("", encoding="utf-8")
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from dataclasses import dataclass\n"
                "from bias_core.domain_events import DomainEvent\n"
                "from bias_core.extensions import RealtimeExtender\n"
                "\n"
                "@dataclass(frozen=True)\n"
                "class AlphaDiscussionCreatedEvent(DomainEvent):\n"
                "    discussion_id: int\n"
                "    actor_user_id: int\n"
                "    is_approved: bool = True\n"
                "\n"
                "@dataclass(frozen=True)\n"
                "class AlphaDiscussionRenamedEvent(DomainEvent):\n"
                "    discussion_id: int\n"
                "    actor_user_id: int\n"
                "    old_title: str\n"
                "    new_title: str\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        RealtimeExtender().broadcast_discussion_event(\n"
                "            AlphaDiscussionRenamedEvent,\n"
                "            'discussion.renamed',\n"
                "            include_discussion=True,\n"
                "            description='Alpha realtime broadcast',\n"
                "        ).broadcast_discussion_event(\n"
                "            AlphaDiscussionCreatedEvent,\n"
                "            'discussion.created',\n"
                "            include_discussion=True,\n"
                "            condition=lambda event: event.is_approved,\n"
                "            description='Approved discussion broadcast',\n"
                "        ),\n"
                "    ]\n",
                encoding="utf-8",
            )

            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            registry = ExtensionRegistry(extensions_path=extensions_dir)
            application = build_extension_application(manager=registry, force=True)
            runtime_view = application.get_runtime_view("alpha-tools")

            self.assertIsNotNone(runtime_view)
            self.assertEqual(len(runtime_view.realtime_discussion_broadcasts), 2)
            self.assertEqual(
                application.realtime.get_discussion_broadcasts(extension_id="alpha-tools")[0].description,
                "Alpha realtime broadcast",
            )
            broadcasts = application.realtime.get_discussion_broadcasts(extension_id="alpha-tools")
            renamed_event_type = broadcasts[0].event_type
            created_event_type = broadcasts[1].event_type
            broadcast = Mock()
            application.instance("realtime.discussion_broadcaster", broadcast)
            application.event_bus.dispatch(renamed_event_type(
                discussion_id=7,
                actor_user_id=3,
                old_title="Old title",
                new_title="New title",
            ))

            broadcast.assert_called_once_with(
                7,
                "discussion.renamed",
                include_discussion=True,
                include_post=False,
                post_id=None,
                post_id_getter=None,
                extension_context=None,
            )
            broadcast.reset_mock()

            application.event_bus.dispatch(created_event_type(
                discussion_id=8,
                actor_user_id=3,
                is_approved=False,
            ))
            application.event_bus.dispatch(created_event_type(
                discussion_id=8,
                actor_user_id=3,
                is_approved=True,
            ))

            broadcast.assert_called_once_with(
                8,
                "discussion.created",
                include_discussion=True,
                include_post=False,
                post_id=None,
                post_id_getter=None,
                extension_context=None,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_realtime_discussion_broadcast_registration_replaces_same_runtime_key(self):
        from bias_core.domain_events import DomainEvent
        from bias_core.extensions import RealtimeExtender

        class AlphaDiscussionEvent(DomainEvent):
            def __init__(self, discussion_id: int):
                self.discussion_id = discussion_id

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")
        broadcast = Mock()

        app.instance("realtime.discussion_broadcaster", broadcast)
        RealtimeExtender().broadcast_discussion_event(
            AlphaDiscussionEvent,
            "discussion.updated",
            include_discussion=False,
        ).extend(app, extension)
        app.make("realtime")
        RealtimeExtender().broadcast_discussion_event(
            AlphaDiscussionEvent,
            "discussion.updated",
            include_discussion=True,
        ).extend(app, extension)
        app.make("realtime")

        app.event_bus.dispatch(AlphaDiscussionEvent(discussion_id=12))

        broadcast.assert_called_once_with(
            12,
            "discussion.updated",
            include_discussion=True,
            include_post=False,
            post_id=None,
            post_id_getter=None,
            extension_context=None,
        )
        broadcasts = app.realtime.get_discussion_broadcasts(extension_id="alpha-tools")
        self.assertEqual(len(broadcasts), 1)
        self.assertTrue(broadcasts[0].include_discussion)

    def test_application_bootstrap_collects_extension_forum_permission_checkers(self):
        from bias_core.forum_permissions import clear_forum_permission_checkers, has_forum_permission

        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import ForumPermissionExtender\n"
                "\n"
                "def can_use_alpha(user, permission_names):\n"
                "    return 'alpha.use' in permission_names\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        ForumPermissionExtender().checker('alpha', can_use_alpha, description='Alpha permission checker'),\n"
                "    ]\n",
                encoding="utf-8",
            )

            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            clear_forum_permission_checkers()
            registry = ExtensionRegistry(extensions_path=extensions_dir)
            application = build_extension_application(manager=registry, force=True)
            runtime_view = application.get_runtime_view("alpha-tools")
            user = Mock(is_authenticated=True, is_superuser=False)

            self.assertIsNotNone(runtime_view)
            self.assertEqual(len(runtime_view.forum_permission_checkers), 1)
            self.assertEqual(runtime_view.forum_permission_checkers[0].key, "alpha")
            self.assertEqual(application.forum_permissions.get_checkers(extension_id="alpha-tools")[0].description, "Alpha permission checker")
            self.assertTrue(has_forum_permission(user, "alpha.use"))
            self.assertFalse(has_forum_permission(user, "alpha.missing"))
        finally:
            clear_forum_permission_checkers()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_application_bootstrap_collects_extension_discussion_lifecycle_handlers(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import DiscussionLifecycleExtender\n"
                "\n"
                "def prepare_create(**kwargs):\n"
                "    return {'prepared': kwargs['payload']['alpha']}\n"
                "\n"
                "def apply_create(state=None, **kwargs):\n"
                "    return {'applied': state['prepared']}\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        DiscussionLifecycleExtender().handler('alpha', prepare_create=prepare_create, apply_create=apply_create, description='Alpha discussion lifecycle'),\n"
                "    ]\n",
                encoding="utf-8",
            )

            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            registry = ExtensionRegistry(extensions_path=extensions_dir)
            application = build_extension_application(manager=registry, force=True)
            runtime_view = application.get_runtime_view("alpha-tools")

            self.assertIsNotNone(runtime_view)
            self.assertEqual(len(runtime_view.discussion_lifecycle), 1)
            self.assertEqual(runtime_view.discussion_lifecycle[0].key, "alpha")
            states = application.discussion_lifecycle.prepare_create(
                user=None,
                payload={"alpha": "ok"},
            )
            self.assertEqual(states["alpha"]["prepared"], "ok")
            results = application.discussion_lifecycle.apply_create(
                discussion=SimpleNamespace(id=1),
                states=states,
            )
            self.assertEqual(results["alpha"]["applied"], "ok")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_application_bootstrap_collects_extension_post_lifecycle_handlers(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import PostLifecycleExtender\n"
                "\n"
                "def apply_created(**kwargs):\n"
                "    return {'post_id': kwargs['post'].id, 'value': kwargs['context']['alpha']}\n"
                "\n"
                "def apply_hidden(**kwargs):\n"
                "    return {'post_id': kwargs['post'].id, 'hidden': kwargs['context']['is_hidden']}\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        PostLifecycleExtender().handler('alpha', apply_created=apply_created, apply_hidden=apply_hidden, description='Alpha post lifecycle'),\n"
                "    ]\n",
                encoding="utf-8",
            )

            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            registry = ExtensionRegistry(extensions_path=extensions_dir)
            application = build_extension_application(manager=registry, force=True)
            runtime_view = application.get_runtime_view("alpha-tools")

            self.assertIsNotNone(runtime_view)
            self.assertEqual(len(runtime_view.post_lifecycle), 1)
            self.assertEqual(runtime_view.post_lifecycle[0].key, "alpha")
            results = application.post_lifecycle.apply_created(
                post=SimpleNamespace(id=7),
                context={"alpha": "ok"},
            )
            self.assertEqual(results["alpha"]["post_id"], 7)
            self.assertEqual(results["alpha"]["value"], "ok")
            hidden_results = application.post_lifecycle.apply_hidden(
                post=SimpleNamespace(id=8),
                context={"is_hidden": True},
            )
            self.assertEqual(hidden_results["alpha"]["post_id"], 8)
            self.assertTrue(hidden_results["alpha"]["hidden"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_api_application_is_built_from_extension_host_routes(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from ninja import Router\n"
                "from bias_core.extensions import ApiRoutesExtender\n"
                "router = Router()\n"
                "@router.get('/ping')\n"
                "def ping(request):\n"
                "    return {'ok': True}\n"
                "def extend():\n"
                "    return [ApiRoutesExtender(mounts=(('/ext/alpha-tools', router),), tags=('Alpha',))]\n",
                encoding="utf-8",
            )
            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            registry = ExtensionRegistry(extensions_path=extensions_dir)
            application = build_extension_application(manager=registry, force=True)
            api = application.make("api.application")

            paths = {item[0] for item in api._routers}
            self.assertIn("/ext/alpha-tools", paths)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_bias_style_conditional_model_search_and_api_resource_extenders(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import ApiResourceExtender, ConditionalExtender, FrontendExtender, ModelExtender, ModelVisibilityExtender, SearchDriverExtender\n"
                "from bias_core.extensions import ExtensionModelCastDefinition, ExtensionModelDefaultDefinition, ExtensionModelDefinition, ExtensionModelRelationDefinition, ExtensionModelVisibilityDefinition, ExtensionResourceEndpointDefinition, ExtensionResourceFieldDefinition, ExtensionResourceFieldMutatorDefinition, ExtensionResourceRelationshipDefinition, ExtensionResourceSortDefinition, ExtensionSearchDriverDefinition\n"
                "from bias_core.extensions import SearchFilterDefinition\n"
                "from bias_core.resource_objects import Resource, ResourceEndpoint, ResourceField, ResourceSort\n"
                "\n"
                "class DemoModel:\n"
                "    pass\n"
                "\n"
                "class ChildDemoModel(DemoModel):\n"
                "    pass\n"
                "\n"
                "class AlphaResource(Resource):\n"
                "    module_id = 'alpha-tools'\n"
                "    def type(self):\n"
                "        return 'alpha_resource'\n"
                "    def base(self, model, context):\n"
                "        return {'id': 'alpha'}\n"
                "    def fields(self):\n"
                "        return [ResourceField('title', resolver=lambda model, context: 'alpha')]\n"
                "    def endpoints(self):\n"
                "        return [ResourceEndpoint('show', handler=lambda context: {'version': 1})]\n"
                "    def sorts(self):\n"
                "        return [ResourceSort('hot', handler=('hot',))]\n"
                "\n"
                "def visibility(queryset, context):\n"
                "    return ('visible', queryset, context['ability'])\n"
                "\n"
                "def parse(value):\n"
                "    return value.split(':', 1)[1] if value.startswith('alpha:') else None\n"
                "\n"
                "def apply(queryset, value, context):\n"
                "    return queryset\n"
                "\n"
                "def mutate(queryset, context):\n"
                "    return ('mutated', queryset, context['target'])\n"
                "\n"
                "def mutate_endpoint(endpoint):\n"
                "    return ('endpoint', endpoint)\n"
                "\n"
                "def mutate_owner_relationship(relationship):\n"
                "    return mutated_owner_relationship\n"
                "\n"
                "def mutate_sort(sort):\n"
                "    # sort is the resolved handler (dict), e.g. {'name': 'newest'}\n"
                "    return ExtensionResourceSortDefinition(resource='forum', sort='newest', module_id='alpha-tools', handler={'name': 'newest-mutated'}, operation='add')\n"
                "\n"
                "def mutate_alpha_field(field):\n"
                "    return ExtensionResourceFieldDefinition(resource='alpha_resource', field=field.field, module_id='', resolver=lambda model, context: 'ALPHA')\n"
                "\n"
                "def mutate_alpha_endpoint(endpoint):\n"
                "    return ExtensionResourceEndpointDefinition(resource='alpha_resource', endpoint=endpoint.endpoint, module_id='', handler=lambda context: {'version': 2})\n"
                "\n"
                "def mutate_alpha_sort(sort):\n"
                "    return ExtensionResourceSortDefinition(resource='alpha_resource', sort=sort.sort, module_id='', handler=('-hot',))\n"
                "\n"
                "field = ExtensionResourceFieldDefinition(resource='forum', field='alpha', module_id='alpha-tools', resolver=lambda model, context: True)\n"
                "before_field = ExtensionResourceFieldDefinition(resource='forum', field='before_title', module_id='', resolver=lambda model, context: True)\n"
                "owner_relationship = ExtensionResourceRelationshipDefinition(resource='forum', relationship='owner', module_id='alpha-tools', resolver=lambda model, context: {'name': 'owner'}, select_related=('owner',))\n"
                "mutated_owner_relationship = ExtensionResourceRelationshipDefinition(resource='forum', relationship='owner', module_id='', resolver=lambda model, context: {'name': 'mutated'}, select_related=('owner_profile',))\n"
                "search_filter = SearchFilterDefinition(code='alpha', label='Alpha', module_id='alpha-tools', target='discussion', parser=parse, applier=apply)\n"
                "endpoint_add = ExtensionResourceEndpointDefinition(resource='forum', endpoint='store', module_id='alpha-tools', operation='add', mutator=lambda endpoint: {'name': 'store'})\n"
                "endpoint_before = ExtensionResourceEndpointDefinition(resource='forum', endpoint='before_store', module_id='', operation='add', mutator=lambda endpoint: {'name': 'before_store'})\n"
                "endpoint_first = ExtensionResourceEndpointDefinition(resource='forum', endpoint='first', module_id='', operation='add', mutator=lambda endpoint: {'name': 'first'})\n"
                "field_mutator = ExtensionResourceFieldMutatorDefinition(resource='forum', field='title', module_id='alpha-tools', mutator=lambda field: {'name': 'title', 'mutated': True})\n"
                "sort = ExtensionResourceSortDefinition(resource='forum', sort='newest', module_id='alpha-tools', handler={'name': 'newest'}, operation='add')\n"
                "old_sort = ExtensionResourceSortDefinition(resource='forum', sort='old', module_id='', handler={'name': 'old'}, operation='add')\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        FrontendExtender(forum_entry='forum.js').css('forum.css').js_directory('chunks').preload({'href': '/x.js', 'as': 'script'}).extra_document_attributes({'data-alpha': '1'}).extra_document_classes(['alpha-page', {'beta-page': True}]).title('AlphaTitle').route('/alpha', 'alpha', 'AlphaView', title='Alpha').remove_route('old-alpha'),\n"
                "        ApiResourceExtender(fields=(field,)).fields_before('title', before_field).relationships_with(owner_relationship).field(field_mutator).field(\n"
                "            'owner', mutate_owner_relationship\n"
                "        ).remove_fields('hidden').endpoint('show', mutate_endpoint).endpoint(endpoint_add).endpoints_before('store', endpoint_before).endpoints_before_all(endpoint_first).sort(sort, old_sort).sort('newest', mutate_sort).remove_sorts('old'),\n"
                "        ApiResourceExtender.from_resource(AlphaResource).field('title', mutate_alpha_field).endpoint('show', mutate_alpha_endpoint).sort('hot', mutate_alpha_sort),\n"
                "        ModelExtender(definitions=(ExtensionModelDefinition(model=DemoModel, key='alpha', handler='belongsToMany'),)).relationship(\n"
                "            ExtensionModelRelationDefinition(model=DemoModel, name='owner', resolver=lambda model: ('owner', model), relation_type='belongsTo')\n"
                "        ).has_one(\n"
                "            'owner_profile', DemoModel, model=DemoModel, foreign_key='owner_id', local_key='id'\n"
                "        ).has_many(\n"
                "            'children', DemoModel, model=DemoModel, foreign_key='parent_id', local_key='id'\n"
                "        ).cast(\n"
                "            ExtensionModelCastDefinition(model=DemoModel, attribute='meta', cast='json')\n"
                "        ).default(\n"
                "            ExtensionModelDefaultDefinition(model=DemoModel, attribute='enabled', value=True)\n"
                "        ),\n"
                "        ModelVisibilityExtender(definitions=(ExtensionModelVisibilityDefinition(model=DemoModel, ability='view', scope=visibility),)),\n"
                "        SearchDriverExtender(drivers=(ExtensionSearchDriverDefinition(target='discussion', driver='database', filters=(search_filter,), mutators=(mutate,), searchers=('tag-searcher',), fulltext='fulltext'),)),\n"
                "        ConditionalExtender().when_extension_enabled('alpha-tools', lambda: ApiResourceExtender(fields=(\n"
                "            ExtensionResourceFieldDefinition(resource='forum', field='conditional', module_id='alpha-tools', resolver=lambda model, context: True),\n"
                "        ))),\n"
                "    ]\n",
                encoding="utf-8",
            )
            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            registry = ExtensionRegistry(extensions_path=extensions_dir)
            application = build_extension_application(manager=registry, force=True)
            runtime_view = application.get_runtime_view("alpha-tools")

            self.assertEqual([item.field for item in runtime_view.resource_fields], ["alpha", "conditional"])
            self.assertEqual([item.module_id for item in runtime_view.resource_field_mutators if item.field in {"before_title", "owner", "hidden"}], ["alpha-tools", "alpha-tools", "alpha-tools"])
            self.assertEqual(runtime_view.resource_endpoints[0].endpoint, "show")
            self.assertEqual(runtime_view.resource_sorts[0].sort, "newest")
            self.assertEqual(runtime_view.model_definitions[0].key, "alpha")
            self.assertEqual(runtime_view.model_relations[0].name, "owner")
            self.assertEqual([item.relation_type for item in runtime_view.model_relations], ["belongsTo", "hasOne", "hasMany"])
            self.assertEqual(runtime_view.model_relations[1].foreign_key, "owner_id")
            self.assertEqual(runtime_view.model_relations[2].owner_key, "id")
            self.assertEqual(runtime_view.model_casts[0].attribute, "meta")
            self.assertEqual(runtime_view.model_defaults[0].attribute, "enabled")
            self.assertEqual(runtime_view.frontend_forum_entry, "forum.js")
            self.assertEqual(runtime_view.frontend_css, ("forum.css",))
            self.assertEqual(runtime_view.frontend_js_directories, ("chunks",))
            self.assertEqual(runtime_view.frontend_preloads[0]["as"], "script")
            self.assertEqual(runtime_view.frontend_document_attributes[0]["data-alpha"], "1")
            self.assertEqual(runtime_view.frontend_title_driver, "AlphaTitle")
            self.assertEqual(runtime_view.frontend_routes[0].path, "/alpha")
            self.assertEqual(runtime_view.frontend_routes[0].module_id, "alpha-tools")
            self.assertEqual(runtime_view.frontend_routes[1].name, "old-alpha")
            self.assertTrue(runtime_view.frontend_routes[1].removed)
            self.assertIn({"class": ["alpha-page", {"beta-page": True}]}, runtime_view.frontend_document_attributes)
            self.assertEqual(runtime_view.search_drivers[0].target, "discussion")
            self.assertEqual(runtime_view.search_drivers[0].mutators[0].__name__, "mutate")
            self.assertEqual(runtime_view.search_drivers[0].searchers, ("tag-searcher",))
            self.assertEqual(runtime_view.search_drivers[0].fulltext, "fulltext")
            self.assertFalse(any(item.code == "alpha" for item in application.forum.get_search_filters("discussion")))
            self.assertEqual(
                application.models.get_definitions_for_model(runtime_view.model_definitions[0].model)[0].key,
                "alpha",
            )
            child_model = runtime_view.model_relations[0].resolver.__globals__["ChildDemoModel"]
            self.assertEqual(application.models.get_definitions_for_model(child_model)[0].key, "alpha")
            self.assertEqual(
                application.models.apply_visibility(runtime_view.model_definitions[0].model, "base", {"ability": "view"}),
                ("visible", "base", "view"),
            )
            self.assertEqual(
                application.models.apply_visibility(runtime_view.model_definitions[0].model, "base", {"ability": "edit"}),
                "base",
            )
            self.assertEqual(application.search.get_searchers("discussion"), ["tag-searcher"])
            self.assertEqual(application.search.get_fulltext_handlers("discussion"), ["fulltext"])
            self.assertEqual(application.search.apply_mutators("discussion", "base", {"target": "discussion"}), ("mutated", "base", "discussion"))
            self.assertEqual(application.resources.apply_endpoint_mutators("forum", "show", "base"), ("endpoint", "base"))
            self.assertEqual(
                application.resources.apply_endpoint_definitions("forum", [{"name": "index"}]),
                [{"name": "first"}, {"name": "index"}, {"name": "before_store"}, {"name": "store"}],
            )
            self.assertEqual(
                application.resources.apply_endpoint_definitions("forum", [{"name": "store"}]),
                [{"name": "first"}, {"name": "before_store"}, {"name": "store"}, {"name": "store"}],
            )
            field_definitions = application.resources.apply_field_definitions("forum", [{"name": "title"}, {"name": "hidden"}])
            self.assertEqual(getattr(field_definitions[0], "field", ""), "before_title")
            self.assertEqual(field_definitions[1], {"name": "title", "mutated": True})
            self.assertEqual(len(field_definitions), 2)
            self.assertEqual(
                application.resources.apply_payload_field_mutators("forum", {"title": {"name": "title"}}),
                {"title": {"name": "title", "mutated": True}},
            )
            resource_payload = application.resources.serialize("forum", SimpleNamespace(), include=("owner",))
            resource_plan = application.resources.build_preload_plan("forum", include=("owner",))
            self.assertEqual(resource_payload["owner"], {"name": "mutated"})
            self.assertEqual(resource_plan.select_related, ("owner_profile",))
            self.assertEqual(application.resources.apply_sort_definitions("forum", []), [{"name": "newest-mutated"}])
            alpha_payload = application.resources.serialize("alpha_resource", SimpleNamespace())
            alpha_endpoint = application.resources.get_dispatch_endpoint("alpha_resource", "show", "GET")
            alpha_queryset = Mock()
            alpha_ordered_queryset = Mock()
            alpha_queryset.order_by.return_value = alpha_ordered_queryset
            self.assertEqual(alpha_payload, {"id": "alpha", "title": "ALPHA"})
            self.assertEqual(alpha_endpoint.handler({}), {"version": 2})
            self.assertIs(application.resources.apply_named_sort("alpha_resource", alpha_queryset, "hot"), alpha_ordered_queryset)
            alpha_queryset.order_by.assert_called_once_with("-hot")
            self.assertEqual(application.models.resolve_relation(runtime_view.model_definitions[0].model, "owner", "demo"), ("owner", "demo"))
            self.assertEqual(application.models.resolve_relation(child_model, "owner", "child"), ("owner", "child"))
            child_instance = child_model()
            self.assertEqual(child_instance.owner, ("owner", child_instance))
            self.assertEqual(application.models.get_casts_for_model(runtime_view.model_definitions[0].model), {"meta": "json"})
            self.assertEqual(application.models.get_casts_for_model(child_model), {"meta": "json"})
            self.assertEqual(application.models.get_defaults_for_model(runtime_view.model_definitions[0].model), {"enabled": True})
            self.assertEqual(application.models.get_defaults_for_model(child_model), {"enabled": True})
            runtime_text_query, runtime_filters = application.search.extract_filter_tokens(
                "alpha:1 body",
                targets=("discussion",),
            )
            self.assertEqual(runtime_text_query, "body")
            self.assertEqual(runtime_filters["discussion"][0][0].code, "alpha")
            self.assertTrue(any(
                item.code == "alpha"
                for item in application.search.get_available_filters(targets=("discussion",))
            ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extension_dependency_sort_detects_cycles_and_persists_enabled_order(self):
        alpha = Extension.from_manifest(ExtensionManifest(
            id="alpha",
            name="Alpha",
            version="1.0.0",
            dependencies=("beta",),
            source="filesystem",
        ))
        beta = Extension.from_manifest(ExtensionManifest(
            id="beta",
            name="Beta",
            version="1.0.0",
            dependencies=("alpha",),
            source="filesystem",
        ))
        manager = ExtensionRegistry()
        with self.assertRaises(ExtensionStateError) as raised:
            manager.sort_extensions_for_boot([alpha, beta])
        self.assertEqual(raised.exception.code, "extension_dependency_cycle")

        core = Extension.from_manifest(ExtensionManifest(
            id="core",
            name="Core",
            version="1.0.0",
            source="filesystem",
        ))
        tags = Extension.from_manifest(ExtensionManifest(
            id="tags",
            name="Tags",
            version="1.0.0",
            dependencies=("core",),
            source="filesystem",
        ))
        ordered = manager.sort_extensions_for_boot([tags, core])
        self.assertEqual([item.id for item in ordered], ["core", "tags"])

        notifications = Extension.from_manifest(ExtensionManifest(
            id="notifications",
            name="Notifications",
            version="1.0.0",
            dependencies=("core",),
            source="filesystem",
        ))
        likes = Extension.from_manifest(ExtensionManifest(
            id="likes",
            name="Likes",
            version="1.0.0",
            dependencies=("notifications",),
            source="filesystem",
        ))
        ordered = manager.sort_extensions_for_boot([likes, tags, notifications, core])
        self.assertEqual([item.id for item in ordered], ["core", "notifications", "tags", "likes"])

    def test_extension_dependency_sort_orders_enabled_optional_dependencies(self):
        realtime = Extension.from_manifest(ExtensionManifest(
            id="realtime",
            name="Realtime",
            version="1.0.0",
            source="filesystem",
        ))
        tags = Extension.from_manifest(ExtensionManifest(
            id="tags",
            name="Tags",
            version="1.0.0",
            optional_dependencies=("realtime",),
            source="filesystem",
        ))
        manager = ExtensionRegistry()

        ordered = manager.sort_extensions_for_boot([tags, realtime])

        self.assertEqual([item.id for item in ordered], ["realtime", "tags"])

    def test_extension_dependency_sort_ignores_missing_optional_dependencies(self):
        tags = Extension.from_manifest(ExtensionManifest(
            id="tags",
            name="Tags",
            version="1.0.0",
            optional_dependencies=("realtime",),
            source="filesystem",
        ))
        manager = ExtensionRegistry()

        ordered = manager.sort_extensions_for_boot([tags])

        self.assertEqual([item.id for item in ordered], ["tags"])

    def test_extension_dependency_sort_detects_optional_dependency_cycles(self):
        discussions = Extension.from_manifest(ExtensionManifest(
            id="discussions",
            name="Discussions",
            version="1.0.0",
            optional_dependencies=("posts",),
            source="filesystem",
        ))
        posts = Extension.from_manifest(ExtensionManifest(
            id="posts",
            name="Posts",
            version="1.0.0",
            dependencies=("discussions",),
            source="filesystem",
        ))
        manager = ExtensionRegistry()

        with self.assertRaises(ExtensionStateError) as raised:
            manager.sort_extensions_for_boot([posts, discussions])

        self.assertEqual(raised.exception.code, "extension_dependency_cycle")

    def test_optional_dependency_status_payload_reports_missing_disabled_and_enabled_states(self):
        from bias_core.extensions.manager_dependencies import build_optional_dependency_status_payload

        realtime = Extension.from_manifest(ExtensionManifest(
            id="realtime",
            name="Realtime",
            version="1.0.0",
            source="filesystem",
        ))
        realtime = Extension(
            **{
                **realtime.__dict__,
                "runtime": type(realtime.runtime)(
                    **{
                        **realtime.runtime.__dict__,
                        "installed": True,
                        "enabled": False,
                    }
                ),
            }
        )
        audit = Extension.from_manifest(ExtensionManifest(
            id="audit",
            name="Audit",
            version="1.0.0",
            source="filesystem",
        ))
        tags = Extension.from_manifest(ExtensionManifest(
            id="tags",
            name="Tags",
            version="1.0.0",
            optional_dependencies=("realtime", "audit", "missing-tools"),
            source="filesystem",
        ))

        payload = build_optional_dependency_status_payload(tags, [tags, realtime, audit])

        self.assertEqual(
            [(item["id"], item["state"], item["contributes_to_boot_order"]) for item in payload],
            [
                ("realtime", "disabled", False),
                ("audit", "enabled", True),
                ("missing-tools", "missing", False),
            ],
        )

    def test_extension_enabled_order_sync_reports_and_repairs_drift(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            beta_dir = extensions_dir / "beta"
            alpha_dir = extensions_dir / "alpha"
            beta_dir.mkdir(parents=True, exist_ok=False)
            alpha_dir.mkdir(parents=True, exist_ok=False)
            (beta_dir / "extension.json").write_text(json.dumps({
                "id": "beta",
                "name": "Beta",
                "version": "1.0.0",
                "dependencies": ["alpha"],
            }, ensure_ascii=False), encoding="utf-8")
            (alpha_dir / "extension.json").write_text(json.dumps({
                "id": "alpha",
                "name": "Alpha",
                "version": "1.0.0",
            }, ensure_ascii=False), encoding="utf-8")
            ExtensionInstallation.objects.create(
                extension_id="alpha",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )
            ExtensionInstallation.objects.create(
                extension_id="beta",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )
            Setting.objects.update_or_create(
                key="extensions_enabled_order",
                defaults={"value": json.dumps(["beta", "alpha", "missing"], ensure_ascii=False)},
            )

            manager = ExtensionRegistry(extensions_path=extensions_dir)
            before = manager.inspect_enabled_extension_order(force=True)
            self.assertTrue(before["drift"])
            self.assertEqual(before["persisted"], ["beta", "alpha", "missing"])
            self.assertEqual(before["resolved"], ["alpha", "beta"])
            self.assertEqual(before["stale"], ["missing"])

            result = manager.sync_enabled_extension_order()

            self.assertTrue(result["changed"])
            self.assertEqual(result["after"]["persisted"], ["alpha", "beta"])
            self.assertFalse(result["after"]["drift"])
            persisted = Setting.objects.get(key="extensions_enabled_order")
            self.assertEqual(json.loads(persisted.value), ["alpha", "beta"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_site_extend_file_contributes_runtime_extenders_without_module_registration(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                extensions_dir = Path(temp_dir) / "extensions"
                extensions_dir.mkdir(parents=True, exist_ok=False)
                (Path(temp_dir) / "extend.py").write_text(
                    "from bias_core.extensions import SettingsExtender\n"
                    "\n"
                    "def extend():\n"
                    "    return [SettingsExtender().default('site.local_enabled', True)]\n",
                    encoding="utf-8",
                )

                application = build_extension_application(
                    manager=ExtensionRegistry(extensions_path=extensions_dir),
                    forum_registry=ForumRegistry(),
                    event_bus=DomainEventBus(),
                    force=True,
                )
                application.make("settings")

                site_view = application.get_runtime_view("site")
                self.assertIsNotNone(site_view)
                self.assertEqual(site_view.source, "site")
                self.assertTrue(any(
                    item.key == "site.local_enabled"
                    and item.value is True
                    and item.module_id == "site"
                    for item in site_view.settings_defaults
                ))
                self.assertNotIn(
                    "site",
                    {module.module_id for module in application.forum.get_modules()},
                )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_bootstrap_extension_application_returns_booted_application(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                extensions_dir = Path(temp_dir) / "extensions"
                extensions_dir.mkdir(parents=True, exist_ok=False)
                (Path(temp_dir) / "extend.py").write_text(
                    "from bias_core.extensions import SettingsExtender\n"
                    "\n"
                    "def extend():\n"
                    "    return [SettingsExtender().default('site.bootstrap_enabled', True)]\n",
                    encoding="utf-8",
                )
                registry = ExtensionRegistry(extensions_path=extensions_dir)
                forum_registry = ForumRegistry()
                event_bus = DomainEventBus()
                resource_registry = ResourceRegistry()

                with patch("bias_core.extensions.bootstrap.get_extension_registry", return_value=registry), patch(
                    "bias_core.forum_registry.get_forum_registry",
                    return_value=forum_registry,
                ), patch(
                    "bias_core.domain_events.get_forum_event_bus",
                    return_value=event_bus,
                ), patch(
                    "bias_core.resource_registry.get_resource_registry",
                    return_value=resource_registry,
                ):
                    application = bootstrap_extension_application(force=True)

                self.assertIsInstance(application, ExtensionApplication)
                self.assertTrue(application.is_booted())
                application.make("settings")
                site_view = application.get_runtime_view("site")
                self.assertIsNotNone(site_view)
                self.assertTrue(any(
                    item.key == "site.bootstrap_enabled"
                    and item.value is True
                    and item.module_id == "site"
                    for item in site_view.settings_defaults
                ))
        finally:
            reset_extension_application_bootstrap_state()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_site_extend_file_errors_are_not_silently_ignored(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                extensions_dir = Path(temp_dir) / "extensions"
                extensions_dir.mkdir(parents=True, exist_ok=False)
                (Path(temp_dir) / "extend.py").write_text(
                    "def extend():\n"
                    "    raise RuntimeError('broken site extension')\n",
                    encoding="utf-8",
                )

                with self.assertRaisesMessage(RuntimeError, "broken site extension"):
                    build_extension_application(
                        manager=ExtensionRegistry(extensions_path=extensions_dir),
                        forum_registry=ForumRegistry(),
                        event_bus=DomainEventBus(),
                        resource_registry=ResourceRegistry(),
                        force=True,
                    )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extension_application_bootstrap_populates_shared_registries_at_startup(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            manifest_dir = extensions_dir / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import AdminSurfaceExtender, ApiResourceExtender, EventListenersExtender\n"
                "from bias_core.extensions import ExtensionEventListenerDefinition, ExtensionResourceDefinition\n"
                "from bias_core.extensions import PermissionDefinition\n"
                "\n"
                "def _serialize(instance, context):\n"
                "    return {'ok': True}\n"
                "\n"
                "def _handle(event):\n"
                "    return None\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        AdminSurfaceExtender(permissions=(\n"
                "            PermissionDefinition(code='alpha.manage', label='管理 Alpha', section='admin', section_label='后台', module_id='alpha-tools'),\n"
                "        )),\n"
                "        ApiResourceExtender.from_resource(\n"
                "            ExtensionResourceDefinition(resource='alpha', module_id='alpha-tools', resolver=_serialize),\n"
                "        ),\n"
                "        EventListenersExtender(listeners=(\n"
                "            ExtensionEventListenerDefinition(event_type=object, handler=_handle),\n"
                "        )),\n"
                "    ]\n",
                encoding="utf-8",
            )

            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )

            manager = ExtensionRegistry(extensions_path=extensions_dir)
            forum_registry = ForumRegistry()
            event_bus = DomainEventBus()
            resource_registry = ResourceRegistry()

            with patch("bias_core.extensions.bootstrap.get_extension_registry", return_value=manager), patch(
                "bias_core.forum_registry.get_forum_registry",
                return_value=forum_registry,
            ), patch(
                "bias_core.domain_events.get_forum_event_bus",
                return_value=event_bus,
            ), patch(
                "bias_core.resource_registry.get_resource_registry",
                return_value=resource_registry,
            ):
                application = bootstrap_extension_application(force=True)

            self.assertIsNotNone(application)
            self.assertTrue(any(item.code == "alpha.manage" for item in forum_registry.get_all_permissions()))
            self.assertIsNotNone(resource_registry.get_resource("alpha"))
            self.assertIn(object, event_bus._listeners)
        finally:
            reset_extension_application_bootstrap_state()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extension_application_catalogs_disabled_extensions_without_running_extenders(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            for extension_id, permission in (
                ("alpha-tools", "alpha.manage"),
                ("beta-tools", "beta.manage"),
            ):
                manifest_dir = extensions_dir / extension_id
                backend_dir = manifest_dir / "backend"
                manifest_dir.mkdir(parents=True, exist_ok=False)
                backend_dir.mkdir(parents=True, exist_ok=False)
                (manifest_dir / "extension.json").write_text(json.dumps({
                    "id": extension_id,
                    "name": extension_id.title(),
                    "version": "1.0.0",
                    "backend_entry": f"extensions.{extension_id.replace('-', '_')}.backend.ext",
                }, ensure_ascii=False), encoding="utf-8")
                (backend_dir / "ext.py").write_text(
                    "from ninja import Router\n"
                    "from bias_core.extensions import (\n"
                    "    AdminSurfaceExtender,\n"
                    "    ApiResourceExtender,\n"
                    "    ApiRoutesExtender,\n"
                    "    EventListenersExtender,\n"
                    "    ExtensionEventListenerDefinition,\n"
                    "    FrontendExtender,\n"
                    "    ForumCapabilitiesExtender,\n"
                    "    RealtimeExtender,\n"
                    "    ResourceFieldDefinition,\n"
                    "    SearchFilterDefinition,\n"
                    "    WebSocketRoutesExtender,\n"
                    ")\n"
                    "from bias_core.extensions import PermissionDefinition\n"
                    "from channels.generic.websocket import AsyncWebsocketConsumer\n"
                    "\n"
                    "router = Router()\n"
                    "\n"
                    "@router.get('/ping')\n"
                    "def ping(request):\n"
                    "    return {'ok': True}\n"
                    "\n"
                    "class AlphaConsumer(AsyncWebsocketConsumer):\n"
                    "    pass\n"
                    "\n"
                    "class AlphaEvent:\n"
                    "    pass\n"
                    "\n"
                    "def parse_filter(token):\n"
                    "    return True if token == 'alpha:yes' else None\n"
                    "\n"
                    "def apply_filter(queryset, value, context):\n"
                    "    return queryset\n"
                    "\n"
                    "def resolve_field(resource, context):\n"
                    "    return True\n"
                    "\n"
                    "def handle_event(event):\n"
                    "    return None\n"
                    "\n"
                    "def transport(event):\n"
                    "    return None\n"
                    "\n"
                    "def extend():\n"
                    "    return [\n"
                    "        AdminSurfaceExtender(permissions=(\n"
                    f"        PermissionDefinition(code='{permission}', label='{permission}', section='admin', section_label='后台', module_id='{extension_id}'),\n"
                    "        )),\n"
                    f"        FrontendExtender(forum_entry='extensions/{extension_id}/frontend/forum/index.js'),\n"
                    f"        ApiRoutesExtender(mounts=(('/{extension_id}', router),), tags=('{extension_id}',)),\n"
                    f"        WebSocketRoutesExtender().route(r'ws/{extension_id}/$', '{extension_id}.socket', AlphaConsumer),\n"
                    "        ApiResourceExtender('forum').fields(lambda: (\n"
                    f"            ResourceFieldDefinition(resource='forum', field='{extension_id.replace('-', '_')}_field', module_id='{extension_id}', resolver=resolve_field),\n"
                    "        )),\n"
                    "        ForumCapabilitiesExtender(search_filters=(\n"
                    f"            SearchFilterDefinition(code='{extension_id}', label='{extension_id}', module_id='{extension_id}', target='discussion', parser=parse_filter, applier=apply_filter, syntax='{extension_id}:yes'),\n"
                    "        )),\n"
                    "        EventListenersExtender(listeners=(\n"
                    "            ExtensionEventListenerDefinition(event_type=AlphaEvent, handler=handle_event),\n"
                    "        )),\n"
                    "        RealtimeExtender().discussion_transport(\n"
                    f"            '{extension_id}.transport', transport, description='{extension_id} transport'\n"
                    "        ).included_payload(\n"
                    f"            '{extension_id}.included', lambda payload, context: payload, description='{extension_id} included'\n"
                    "        ).discussion_visibility(\n"
                    f"            lambda user=None, discussion_ids=(), **kwargs: discussion_ids, key='{extension_id}.visibility'\n"
                    "        ),\n"
                    "    ]\n",
                    encoding="utf-8",
                )

            ExtensionInstallation.objects.create(
                extension_id="alpha-tools",
                version="1.0.0",
                source="filesystem",
                enabled=True,
                installed=True,
                booted=True,
            )
            ExtensionInstallation.objects.create(
                extension_id="beta-tools",
                version="1.0.0",
                source="filesystem",
                enabled=False,
                installed=True,
                booted=False,
            )

            application = build_extension_application(
                manager=ExtensionRegistry(extensions_path=extensions_dir),
                forum_registry=ForumRegistry(),
                resource_registry=ResourceRegistry(),
                event_bus=DomainEventBus(),
                force=True,
            )
            modules = {module.module_id: module for module in application.forum.get_modules()}

            self.assertTrue(modules["alpha-tools"].enabled)
            self.assertFalse(modules["beta-tools"].enabled)
            self.assertTrue(any(item.code == "alpha.manage" for item in application.forum.get_all_permissions()))
            self.assertFalse(any(item.code == "beta.manage" for item in application.forum.get_all_permissions()))
            self.assertIsNotNone(application.get_runtime_view("alpha-tools"))
            self.assertIsNone(application.get_runtime_view("beta-tools"))
            self.assertEqual(len(application.get_route_mounts()), 1)
            self.assertEqual(application.get_route_mounts()[0].prefix, "/alpha-tools")
            self.assertEqual(len(application.get_websocket_routes()), 1)
            self.assertEqual(application.get_websocket_routes()[0].name, "alpha-tools.socket")
            self.assertTrue(any(
                item.field == "alpha_tools_field"
                for item in application.resource_registry.get_all_fields()
            ))
            self.assertFalse(any(
                item.field == "beta_tools_field"
                for item in application.resource_registry.get_all_fields()
            ))
            self.assertTrue(any(
                item.code == "alpha-tools"
                for item in application.search.get_available_filters(targets=("discussion",))
            ))
            self.assertFalse(any(
                item.code == "beta-tools"
                for item in application.search.get_available_filters(targets=("discussion",))
            ))
            self.assertEqual(len(application.events.get_listeners(extension_id="alpha-tools")), 1)
            self.assertEqual(application.events.get_listeners(extension_id="beta-tools"), [])
            self.assertEqual(len(application.realtime.get_discussion_transports(extension_id="alpha-tools")), 1)
            self.assertEqual(application.realtime.get_discussion_transports(extension_id="beta-tools"), [])
            self.assertTrue(application.get_frontend_extension("alpha-tools"))
            self.assertIsNone(application.get_frontend_extension("beta-tools"))

            from bias_core.extensions.frontend_runtime_service import (
                build_enabled_frontend_document_payload,
                get_enabled_extension_runtime_entries,
            )

            with patch("bias_core.extensions.frontend_runtime_service.get_extension_host", return_value=application):
                frontend_entries = get_enabled_extension_runtime_entries(product_visible_only=False)
                frontend_document = build_enabled_frontend_document_payload()

            frontend_ids = {item["id"] for item in frontend_entries}
            self.assertIn("alpha-tools", frontend_ids)
            self.assertNotIn("beta-tools", frontend_ids)
            self.assertFalse(any(
                item.get("extension_id") == "beta-tools"
                for item in frontend_document["title_drivers"]
            ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extension_application_resolving_callbacks_do_not_reapply_previous_callbacks(self):
        application = ExtensionApplication()
        application.instance("actions", [])

        application.resolving("actions", lambda actions, host: [*actions, "first"])
        application.resolving("actions", lambda actions, host: [*actions, "second"])

        self.assertEqual(application.get("actions"), ["first", "second"])


    def test_loader_rejects_invalid_extension_id_and_version(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "Bad_Extension"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "Bad_Extension",
                "name": "Bad Extension",
                "version": "1.0",
            }, ensure_ascii=False), encoding="utf-8")

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            with self.assertRaisesMessage(Exception, f"扩展清单 id 非法: {manifest_dir / 'extension.json'}"):
                loader.discover()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

