from tests.common import *

def build_minimal_contract_snapshot(extension_id):
    return {
        "schema_version": 1,
        "extension_id": extension_id,
        "admin": {},
        "backend": {},
        "events": {},
        "forum": {},
        "frontend": {},
        "lifecycle": {},
        "models": {},
        "presentation": {},
        "resources": {},
        "runtime": {},
        "search": {},
        "settings": {},
        "summary": {},
    }


class ExtensionManagementCommandTests(TestCase):
    def test_extension_management_commands_skip_django_system_checks(self):
        from bias_core.management.commands.create_extension import Command as CreateExtensionCommand
        from bias_core.management.commands.extension_console import Command as ExtensionConsoleCommand
        from bias_core.management.commands.inspect_extensions import Command as InspectExtensionsCommand
        from bias_core.management.commands.inspect_extension_imports import Command as InspectExtensionImportsCommand
        from bias_core.management.commands.inspect_extension_packages import Command as InspectExtensionPackagesCommand
        from bias_core.management.commands.sync_extension_package_metadata import Command as SyncPackageMetadataCommand
        from bias_core.management.commands.validate_extensions import Command as ValidateExtensionsCommand

        self.assertEqual(CreateExtensionCommand.requires_system_checks, [])
        self.assertEqual(ExtensionConsoleCommand.requires_system_checks, [])
        self.assertEqual(InspectExtensionsCommand.requires_system_checks, [])
        self.assertEqual(InspectExtensionImportsCommand.requires_system_checks, [])
        self.assertEqual(InspectExtensionPackagesCommand.requires_system_checks, [])
        self.assertEqual(SyncPackageMetadataCommand.requires_system_checks, [])
        self.assertEqual(ValidateExtensionsCommand.requires_system_checks, [])

    def test_ci_runs_extension_import_boundary_audit_when_split_workspace_is_available(self):
        workflow_path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
        workflow = workflow_path.read_text(encoding="utf-8")

        self.assertIn("Audit extension backend import boundaries", workflow)
        self.assertIn("python -m django inspect_extension_imports", workflow)
        self.assertIn("python -m django inspect_extension_packages", workflow)
        self.assertIn("--require-extensions", workflow)
        self.assertIn("--migration-smoke", workflow)

    def test_extension_console_command_lists_and_runs_runtime_commands(self):
        commands = [{
            "name": "alpha:refresh",
            "description": "Refresh alpha",
            "handler": lambda options: {"ok": True, "scope": options.get("scope")},
        }]

        with patch("bias_core.management.commands.extension_console.list_runtime_console_commands", return_value=commands):
            stdout = StringIO()
            call_command("extension_console", "--list", "--format", "json", stdout=stdout)
            payload = json.loads(stdout.getvalue())

        self.assertEqual(payload["commands"][0]["name"], "alpha:refresh")

        with patch("bias_core.management.commands.extension_console.list_runtime_console_schedules", return_value=[{
            "name": "alpha:refresh",
            "description": "Refresh alpha",
            "schedule": "hourly",
            "args": {"scope": "all"},
        }]):
            stdout = StringIO()
            call_command("extension_console", "--scheduled", "--format", "json", stdout=stdout)
            payload = json.loads(stdout.getvalue())

        self.assertEqual(payload["schedules"][0]["schedule"], "hourly")

        with patch(
            "bias_core.management.commands.extension_console.run_runtime_console_command",
            return_value={"ok": True, "scope": "all"},
        ):
            stdout = StringIO()
            call_command(
                "extension_console",
                "alpha:refresh",
                "--payload",
                '{"scope":"all"}',
                "--format",
                "json",
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(payload["result"], {"ok": True, "scope": "all"})

    @patch("bias_core.management.commands.validate_extensions.get_core_module_ids", return_value=("core",))
    def test_validate_extensions_command_uses_core_and_filesystem_extension_ids(self, get_core_module_ids_mock):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(
                BASE_DIR=Path(temp_dir),
                BIAS_EXTENSION_WORKSPACE_ROOT=Path(temp_dir),
            ):
                call_command_quietly("create_extension", "alpha-tools")
                call_command_quietly("create_extension", "beta-tools")
                alpha_migrations_dir = (
                    Path(temp_dir)
                    / "bias-ext-alpha-tools"
                    / "bias_ext_alpha_tools"
                    / "backend"
                    / "django_migrations"
                )
                (alpha_migrations_dir / "0001_bootstrap.py").write_text(
                    "from django.db import migrations\n"
                    "\n"
                    "\n"
                    "class Migration(migrations.Migration):\n"
                    "    dependencies = []\n"
                    "    operations = []\n",
                    encoding="utf-8",
                )
                beta_manifest_path = Path(temp_dir) / "bias-ext-beta-tools" / "extension.json"
                beta_manifest = json.loads(beta_manifest_path.read_text(encoding="utf-8"))
                beta_manifest["dependencies"] = ["alpha-tools"]
                beta_manifest_path.write_text(json.dumps(beta_manifest, ensure_ascii=False), encoding="utf-8")
                beta_pyproject_path = Path(temp_dir) / "bias-ext-beta-tools" / "pyproject.toml"
                beta_pyproject = beta_pyproject_path.read_text(encoding="utf-8")
                beta_pyproject = beta_pyproject.replace(
                    'dependencies = ["bias-core>=0.1,<0.2"]',
                    'dependencies = ["bias-core>=0.1,<0.2", "bias-ext-alpha-tools>=0.1,<0.2"]',
                    1,
                )
                beta_pyproject_path.write_text(beta_pyproject, encoding="utf-8")
                call_command_quietly(
                    "validate_extensions",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--strict",
                )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        get_core_module_ids_mock.assert_called_once_with()

    def test_create_extension_command_scaffolds_minimal_extension_entry(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly(
                    "create_extension",
                    "alpha-tools",
                    "--name",
                    "Alpha Tools",
                    "--description",
                    "用于测试脚手架",
                )

                extension_dir = Path(temp_dir) / "bias-ext-alpha-tools"
                manifest = json.loads((extension_dir / "extension.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["id"], "alpha-tools")
                self.assertEqual(manifest["name"], "Alpha Tools")
                self.assertEqual(manifest["backend"]["entry"], "bias_ext_alpha_tools.backend.ext")
                self.assertEqual(
                    manifest["django"]["app_config"],
                    "bias_ext_alpha_tools.backend.apps.AlphaToolsExtensionConfig",
                )
                self.assertEqual(manifest["django"]["app_label"], "alpha_tools")
                self.assertEqual(manifest["django"]["migration_module"], "bias_ext_alpha_tools.backend.django_migrations")
                self.assertNotIn("backend_entry", manifest)
                self.assertNotIn("django_app_config", manifest)
                self.assertNotIn("django_app_label", manifest)
                self.assertNotIn("django_migration_module", manifest)
                self.assertNotIn("frontend_admin_entry", manifest)
                self.assertNotIn("frontend_forum_entry", manifest)
                self.assertNotIn("migration_namespace", manifest)
                self.assertEqual(manifest["compatibility"]["bias_version"], ">=0.1.0 <0.2.0")
                self.assertEqual(manifest["compatibility"]["api_stability"], "experimental")
                self.assertEqual(manifest["distribution"]["channel"], "private")
                self.assertEqual(manifest["security"]["support_email"], "security@example.com")
                import tomllib

                pyproject = tomllib.loads((extension_dir / "pyproject.toml").read_text(encoding="utf-8"))
                self.assertEqual(pyproject["project"]["name"], "bias-ext-alpha-tools")
                self.assertEqual(pyproject["project"]["version"], "0.1.0")
                self.assertEqual(pyproject["project"]["entry-points"]["bias.extensions"]["alpha_tools"], "bias_ext_alpha_tools.backend.ext:extend")
                self.assertEqual(
                    pyproject["tool"]["setuptools"]["packages"]["find"]["include"],
                    ["bias_ext_alpha_tools*"],
                )
                data_files = pyproject["tool"]["setuptools"]["data-files"]
                self.assertEqual(data_files["bias_extensions/alpha-tools"], ["extension.json"])
                self.assertEqual(data_files["bias_extensions/alpha-tools/frontend/admin"], ["frontend/admin/index.js"])
                self.assertEqual(data_files["bias_extensions/alpha-tools/frontend/forum"], ["frontend/forum/index.js"])
                self.assertEqual(data_files["bias_extensions/alpha-tools/locale"], ["locale/zh-CN.json"])
                manifest_in_source = (extension_dir / "MANIFEST.in").read_text(encoding="utf-8")
                self.assertIn("include extension.json", manifest_in_source)
                self.assertIn("recursive-include frontend *", manifest_in_source)
                self.assertIn("recursive-include locale *", manifest_in_source)
                self.assertTrue((extension_dir / "frontend" / "admin" / "index.js").exists())
                self.assertFalse((extension_dir / "frontend" / "admin" / "DetailPage.vue").exists())
                self.assertFalse((extension_dir / "frontend" / "admin" / "SettingsPage.vue").exists())
                self.assertFalse((extension_dir / "frontend" / "admin" / "PermissionsPage.vue").exists())
                self.assertFalse((extension_dir / "frontend" / "admin" / "OperationsPage.vue").exists())
                self.assertTrue((extension_dir / "frontend" / "forum" / "index.js").exists())
                backend_dir = extension_dir / "bias_ext_alpha_tools" / "backend"
                self.assertTrue((backend_dir / "ext.py").exists())
                self.assertTrue((backend_dir / "apps.py").exists())
                self.assertTrue((backend_dir / "constants.py").exists())
                self.assertTrue((backend_dir / "frontend.py").exists())
                self.assertTrue((backend_dir / "settings.py").exists())
                self.assertTrue((backend_dir / "resources.py").exists())
                self.assertTrue((backend_dir / "policies.py").exists())
                self.assertTrue((backend_dir / "listeners.py").exists())
                self.assertTrue((backend_dir / "runtime.py").exists())
                self.assertTrue((backend_dir / "admin_surface.py").exists())
                self.assertTrue((backend_dir / "django_migrations" / "__init__.py").exists())
                self.assertFalse((backend_dir / "migrations").exists())
                self.assertTrue((extension_dir / "README.md").exists())
                self.assertTrue((extension_dir / "docs" / "README.md").exists())
                self.assertTrue((extension_dir / "locale" / "zh-CN.json").exists())
                backend_source = (backend_dir / "ext.py").read_text(encoding="utf-8")
                self.assertIn("def extend():", backend_source)
                self.assertIn("from .frontend import frontend_extender", backend_source)
                self.assertIn("frontend_extender()", backend_source)
                self.assertNotIn("FrontendExtender()", backend_source)
                self.assertNotIn("frontend/admin/index.js", backend_source)
                self.assertNotIn("from bias_core.", backend_source.replace("from bias_core.extensions", ""))
                frontend_backend_source = (backend_dir / "frontend.py").read_text(encoding="utf-8")
                self.assertIn("from bias_core.extensions import FrontendExtender", frontend_backend_source)
                self.assertIn("FrontendExtender()", frontend_backend_source)
                self.assertIn("frontend/admin/index.js", frontend_backend_source)
                constants_source = (backend_dir / "constants.py").read_text(encoding="utf-8")
                self.assertIn("EXTENSION_ID = 'alpha-tools'", constants_source)
                self.assertIn("EXTENSION_NAME = 'Alpha Tools'", constants_source)
                settings_source = (backend_dir / "settings.py").read_text(encoding="utf-8")
                resources_source = (backend_dir / "resources.py").read_text(encoding="utf-8")
                policies_source = (backend_dir / "policies.py").read_text(encoding="utf-8")
                listeners_source = (backend_dir / "listeners.py").read_text(encoding="utf-8")
                runtime_source = (backend_dir / "runtime.py").read_text(encoding="utf-8")
                admin_surface_source = (backend_dir / "admin_surface.py").read_text(encoding="utf-8")
                self.assertIn("def setting_field_definitions():", settings_source)
                self.assertIn("def resource_definitions():", resources_source)
                self.assertIn("def policy_definitions():", policies_source)
                self.assertIn("def event_listener_definitions():", listeners_source)
                self.assertIn("def service_providers():", runtime_source)
                self.assertIn("def admin_page_definitions():", admin_surface_source)
                apps_source = (backend_dir / "apps.py").read_text(encoding="utf-8")
                self.assertIn("class AlphaToolsExtensionConfig(AppConfig):", apps_source)
                self.assertIn('label = "alpha_tools"', apps_source)
                self.assertNotIn("LifecycleExtender", backend_source)
                self.assertNotIn("def install(context):", backend_source)
                self.assertNotIn("def run_migrations(context):", backend_source)
                self.assertNotIn("def rollback_migrations(context):", backend_source)
                self.assertNotIn("def uninstall(context):", backend_source)
                self.assertNotIn("SettingsExtender", backend_source)
                self.assertNotIn("ApiResourceExtender", backend_source)
                self.assertNotIn("RuntimeActionsExtender", backend_source)
                self.assertNotIn("AdminNavigationExtender", backend_source)
                admin_source = (extension_dir / "frontend" / "admin" / "index.js").read_text(encoding="utf-8")
                forum_source = (extension_dir / "frontend" / "forum" / "index.js").read_text(encoding="utf-8")
                self.assertIn("from '@bias/core/admin'", admin_source)
                self.assertIn("export const extend", admin_source)
                self.assertIn("extendAdmin(admin => admin", admin_source)
                self.assertIn("export function resolveDetailPage()", admin_source)
                self.assertIn("return null", admin_source)
                self.assertNotIn(".page({", admin_source)
                self.assertIn("from '@bias/core/forum'", forum_source)
                self.assertIn("extendForum(forum => forum", forum_source)
                self.assertNotIn(".navItem({", forum_source)
                readme_source = (extension_dir / "README.md").read_text(encoding="utf-8")
                self.assertIn("backend/ext.py", readme_source)
                self.assertIn("backend/frontend.py", readme_source)
                self.assertIn("resources.py", readme_source)
                self.assertIn("settings.py", readme_source)
                self.assertIn("policies.py", readme_source)
                self.assertIn("listeners.py", readme_source)
                self.assertIn("runtime.py", readme_source)
                self.assertIn("admin_surface.py", readme_source)
                self.assertIn("validate_extensions --strict", readme_source)
                self.assertIn("build_extension_frontend --rebuild", readme_source)
                self.assertIn("ApiResourceExtender(...)", readme_source)
                self.assertIn("pyproject.toml", readme_source)
                self.assertIn("MANIFEST.in", readme_source)
                self.assertIn("bias_core.extensions.runtime", readme_source)
                self.assertIn("bias_core.extensions.platform", readme_source)
                self.assertNotIn("bias_core.extensions.forum", readme_source)
                self.assertIn("backend/apps.py", readme_source)
                self.assertIn("backend/django_migrations", readme_source)
                self.assertNotIn("migration_namespace", readme_source)
                docs_readme_source = (extension_dir / "docs" / "README.md").read_text(encoding="utf-8")
                self.assertEqual(docs_readme_source, readme_source)

                from bias_core.extension_django_apps import (
                    discover_extension_django_apps,
                    discover_extension_django_migration_modules,
                )

                self.assertEqual(
                    discover_extension_django_apps(Path(temp_dir)),
                    ["bias_ext_alpha_tools.backend.apps.AlphaToolsExtensionConfig"],
                )
                self.assertEqual(
                    discover_extension_django_migration_modules(Path(temp_dir)),
                    {"alpha_tools": "bias_ext_alpha_tools.backend.django_migrations"},
                )

                import bias_core.extensions.manifest as manifest_module

                package_manifest_file = "bias_ext_alpha_tools-0.1.0.data/data/bias_extensions/alpha-tools/extension.json"
                package_manifest_path = Path(temp_dir) / package_manifest_file
                package_manifest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(extension_dir / "extension.json", package_manifest_path)
                distribution = SimpleNamespace(
                    files=[package_manifest_file],
                    metadata={"Name": "bias-ext-alpha-tools"},
                    version="0.1.0",
                    locate_file=lambda file: Path(temp_dir) / str(file),
                )
                manifest_module._distribution_manifest_cache = None
                try:
                    with patch("bias_core.extensions.manifest.metadata.distributions", return_value=[distribution]):
                        discovered = manifest_module.ExtensionManifestLoader(
                            Path(temp_dir) / "extensions",
                            include_workspace=False,
                            include_distributions=True,
                        ).discover_manifests()
                finally:
                    manifest_module._distribution_manifest_cache = None

                self.assertEqual([item.id for item in discovered], ["alpha-tools"])
                self.assertEqual(discovered[0].source, "python-package")
                self.assertEqual(discovered[0].extra["python_distribution"]["name"], "bias-ext-alpha-tools")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_create_extension_command_places_split_package_next_to_bias_site_host(self):
        temp_dir = make_workspace_temp_dir()
        try:
            workspace_root = Path(temp_dir)
            site_host = workspace_root / "bias"
            site_host.mkdir(parents=True, exist_ok=False)

            with override_settings(BASE_DIR=site_host, BIAS_EXTENSION_WORKSPACE_ROOT=workspace_root):
                call_command_quietly("create_extension", "alpha-tools")

            self.assertTrue((workspace_root / "bias-ext-alpha-tools" / "extension.json").exists())
            self.assertFalse((site_host / "bias-ext-alpha-tools").exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_create_extension_command_frontend_entries_use_public_sdks(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")

                entry_source = (Path(temp_dir) / "bias-ext-alpha-tools" / "frontend" / "admin" / "index.js").read_text(encoding="utf-8")
                self.assertIn("export function resolveDetailPage()", entry_source)
                self.assertIn("return null", entry_source)
                self.assertNotIn("import DetailPage", entry_source)
                self.assertNotIn("export function resolvePermissionsPage()", entry_source)
                self.assertIn("extendAdmin(admin => admin", entry_source)
                forum_entry_source = (Path(temp_dir) / "bias-ext-alpha-tools" / "frontend" / "forum" / "index.js").read_text(encoding="utf-8")
                self.assertIn("export const extend", forum_entry_source)
                self.assertIn("extendForum(forum => forum", forum_entry_source)
                self.assertNotIn(".navItem({", forum_entry_source)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_create_extension_command_rejects_existing_directory_without_force(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extension_dir = Path(temp_dir) / "bias-ext-alpha-tools"
            extension_dir.mkdir(parents=True, exist_ok=False)
            with override_settings(BASE_DIR=Path(temp_dir)):
                with self.assertRaisesMessage(CommandError, f"扩展目录已存在: {extension_dir}。如需覆盖，请传 --force"):
                    call_command_quietly("create_extension", "alpha-tools")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_reports_manifest_errors(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["missing-one"],
                "frontend_admin_entry": "extensions/alpha-tools/frontend/admin/index.js",
                "settings_pages": ["/admin/extensions/alpha-tools/settings"],
            }, ensure_ascii=False), encoding="utf-8")

            with self.assertRaisesMessage(CommandError, "扩展校验失败，共 2 个错误"):
                call_command_quietly("validate_extensions", "--extensions-path", str(Path(temp_dir) / "extensions"))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_can_pass_in_strict_mode(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")
                call_command_quietly(
                    "validate_extensions",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--strict",
                )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_reports_unpackaged_frontend_resources(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")
                extra_resource = Path(temp_dir) / "bias-ext-alpha-tools" / "frontend" / "forum" / "extra.js"
                extra_resource.write_text("export const extra = true\n", encoding="utf-8")

                output = StringIO()
                call_command(
                    "validate_extensions",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--format",
                    "json",
                    stdout=output,
                )

                payload = json.loads(output.getvalue())
                self.assertEqual(payload["summary"]["error_count"], 0)
                issue = next(
                    item
                    for item in payload["issues"]
                    if item["code"] == "extension_package_resource_missing"
                )
                self.assertEqual(issue["extension_id"], "alpha-tools")
                self.assertEqual(issue["field"], "pyproject.toml")
                self.assertIn("frontend/forum/extra.js", issue["message"])

                with self.assertRaisesMessage(CommandError, "扩展严格校验失败"):
                    call_command_quietly(
                        "validate_extensions",
                        "--extensions-path",
                        str(Path(temp_dir) / "extensions"),
                        "--strict",
                    )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_rejects_invalid_package_metadata(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")
                pyproject_path = Path(temp_dir) / "bias-ext-alpha-tools" / "pyproject.toml"
                source = pyproject_path.read_text(encoding="utf-8")
                source = source.replace("name = 'bias-ext-alpha-tools'", "name = 'wrong-package'", 1)
                source = source.replace("version = '0.1.0'", "version = '0.2.0'", 1)
                source = source.replace('dependencies = ["bias-core>=0.1,<0.2"]\n', "", 1)
                source = source.replace(
                    'alpha_tools = "bias_ext_alpha_tools.backend.ext:extend"',
                    'alpha_tools = "wrong.backend.ext:extend"',
                    1,
                )
                source = source.replace('"bias_extensions/alpha-tools" = ["extension.json"]\n', "", 1)
                pyproject_path.write_text(source, encoding="utf-8")

                output = StringIO()
                with self.assertRaisesMessage(CommandError, "扩展校验失败"):
                    call_command(
                        "validate_extensions",
                        "--extensions-path",
                        str(Path(temp_dir) / "extensions"),
                        "--format",
                        "json",
                        stdout=output,
                    )

                payload = json.loads(output.getvalue())
                issues = [
                    item
                    for item in payload["issues"]
                    if item["code"] == "extension_package_metadata_invalid"
                ]
                self.assertEqual(len(issues), 5)
                self.assertTrue(any("project.name 应为 bias-ext-alpha-tools" in item["message"] for item in issues))
                self.assertTrue(any("project.version 应与 extension.json version 一致: 0.1.0" in item["message"] for item in issues))
                self.assertTrue(any("project.dependencies 必须声明 bias-core 依赖" in item["message"] for item in issues))
                self.assertTrue(any("project.entry-points.bias.extensions.alpha_tools" in item["message"] for item in issues))
                self.assertTrue(any("tool.setuptools.data-files.bias_extensions/alpha-tools" in item["message"] for item in issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_rejects_missing_package_dependency_metadata(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")
                call_command_quietly("create_extension", "beta-tools")
                manifest_path = Path(temp_dir) / "bias-ext-beta-tools" / "extension.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["dependencies"] = ["core", "alpha-tools"]
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

                output = StringIO()
                with self.assertRaisesMessage(CommandError, "扩展校验失败"):
                    call_command(
                        "validate_extensions",
                        "--extensions-path",
                        str(Path(temp_dir) / "extensions"),
                        "--format",
                        "json",
                        stdout=output,
                    )

                payload = json.loads(output.getvalue())
                self.assertTrue(any(
                    item["code"] == "extension_package_metadata_invalid"
                    and item["extension_id"] == "beta-tools"
                    and "project.dependencies 必须声明扩展依赖 bias-ext-alpha-tools" in item["message"]
                    for item in payload["issues"]
                ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_sync_extension_package_metadata_command_reports_drift_in_check_mode(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")
                pyproject_path = Path(temp_dir) / "bias-ext-alpha-tools" / "pyproject.toml"
                pyproject_path.write_text(
                    pyproject_path.read_text(encoding="utf-8").replace(
                        "name = 'bias-ext-alpha-tools'",
                        "name = 'wrong-package'",
                        1,
                    ),
                    encoding="utf-8",
                )

                output = StringIO()
                with self.assertRaisesMessage(CommandError, "扩展包元数据存在漂移"):
                    call_command(
                        "sync_extension_package_metadata",
                        "--extensions-path",
                        str(Path(temp_dir) / "extensions"),
                        "--format",
                        "json",
                        stdout=output,
                    )

                payload = json.loads(output.getvalue())
                self.assertEqual(payload["summary"]["manifest_count"], 1)
                self.assertEqual(payload["summary"]["changed_count"], 1)
                self.assertEqual(payload["summary"]["error_count"], 0)
                self.assertFalse(payload["summary"]["ok"])
                self.assertEqual(payload["results"][0]["extension_id"], "alpha-tools")
                self.assertIn("project.name", payload["results"][0]["updates"])
                self.assertIn("wrong-package", pyproject_path.read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_sync_extension_package_metadata_command_writes_manifest_dependencies_and_resources(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")
                call_command_quietly("create_extension", "beta-tools")
                beta_dir = Path(temp_dir) / "bias-ext-beta-tools"
                manifest_path = beta_dir / "extension.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["dependencies"] = ["core", "alpha-tools"]
                manifest["optional_dependencies"] = ["gamma-tools"]
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
                extra_resource = beta_dir / "frontend" / "forum" / "extra.js"
                extra_resource.write_text("export const extra = true\n", encoding="utf-8")
                pyproject_path = beta_dir / "pyproject.toml"
                pyproject_source = pyproject_path.read_text(encoding="utf-8").replace(
                    'dependencies = ["bias-core>=0.1,<0.2"]',
                    'dependencies = ["bias-core>=0.1,<0.2", "httpx>=0.27,<0.28"]',
                    1,
                )
                pyproject_path.write_text(pyproject_source, encoding="utf-8")

                output = StringIO()
                call_command(
                    "sync_extension_package_metadata",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--extension-id",
                    "beta-tools",
                    "--write",
                    "--format",
                    "json",
                    stdout=output,
                )

                payload = json.loads(output.getvalue())
                self.assertTrue(payload["summary"]["ok"])
                self.assertEqual(payload["summary"]["changed_count"], 1)
                import tomllib

                pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
                self.assertEqual(pyproject["project"]["name"], "bias-ext-beta-tools")
                self.assertEqual(pyproject["project"]["version"], "0.1.0")
                self.assertEqual(
                    pyproject["project"]["dependencies"],
                    [
                        "bias-core>=0.1,<0.2",
                        "bias-ext-alpha-tools>=0.1,<0.2",
                        "httpx>=0.27,<0.28",
                    ],
                )
                self.assertNotIn("bias-ext-gamma-tools>=0.1,<0.2", pyproject["project"]["dependencies"])
                self.assertEqual(
                    pyproject["project"]["entry-points"]["bias.extensions"]["beta_tools"],
                    "bias_ext_beta_tools.backend.ext:extend",
                )
                data_files = pyproject["tool"]["setuptools"]["data-files"]
                self.assertEqual(data_files["bias_extensions/beta-tools"], ["extension.json"])
                self.assertIn("frontend/forum/extra.js", data_files["bias_extensions/beta-tools/frontend/forum"])

                call_command_quietly(
                    "validate_extensions",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--strict",
                )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extension_wheel_contains_manifest_resources_and_entry_point(self):
        import subprocess
        import zipfile

        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")

            extension_dir = Path(temp_dir) / "bias-ext-alpha-tools"
            dist_dir = extension_dir / "dist"
            result = subprocess.run(
                [sys.executable, "-m", "build", "--wheel", "--no-isolation"],
                cwd=extension_dir,
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

            wheels = sorted(dist_dir.glob("*.whl"))
            self.assertEqual(len(wheels), 1)
            with zipfile.ZipFile(wheels[0]) as archive:
                names = set(archive.namelist())
                self.assertIn(
                    "bias_ext_alpha_tools-0.1.0.data/data/bias_extensions/alpha-tools/extension.json",
                    names,
                )
                self.assertIn(
                    "bias_ext_alpha_tools-0.1.0.data/data/bias_extensions/alpha-tools/frontend/forum/index.js",
                    names,
                )
                entry_points_name = next(
                    name
                    for name in names
                    if name.endswith(".dist-info/entry_points.txt")
                )
                entry_points = archive.read(entry_points_name).decode("utf-8")
                self.assertIn("[bias.extensions]", entry_points)
                self.assertIn("alpha_tools = bias_ext_alpha_tools.backend.ext:extend", entry_points)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_packages_command_builds_and_audits_wheel(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")

                output = StringIO()
                call_command(
                    "inspect_extension_packages",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--extension-id",
                    "alpha-tools",
                    "--build",
                    "--format",
                    "json",
                    stdout=output,
                )

            payload = json.loads(output.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertEqual(payload["summary"]["manifest_count"], 1)
            self.assertEqual(payload["results"][0]["extension_id"], "alpha-tools")
            self.assertTrue(payload["results"][0]["built"])
            self.assertGreater(payload["results"][0]["source_file_count"], 0)
            self.assertGreater(payload["results"][0]["packaged_file_count"], 0)
            self.assertEqual(payload["results"][0]["errors"], [])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_packages_command_smokes_installed_wheel_discovery(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")

                output = StringIO()
                call_command(
                    "inspect_extension_packages",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--extension-id",
                    "alpha-tools",
                    "--build",
                    "--install-smoke",
                    "--format",
                    "json",
                    stdout=output,
                )

            payload = json.loads(output.getvalue())
            result = payload["results"][0]
            self.assertTrue(payload["summary"]["ok"])
            self.assertTrue(result["install_smoke"])
            self.assertEqual(result["discovered_extension_id"], "alpha-tools")
            self.assertEqual(result["discovered_source"], "python-package")
            self.assertEqual(result["errors"], [])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_packages_command_smokes_installed_wheel_set(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")
                call_command_quietly("create_extension", "beta-tools")
                alpha_migrations_dir = (
                    Path(temp_dir)
                    / "bias-ext-alpha-tools"
                    / "bias_ext_alpha_tools"
                    / "backend"
                    / "django_migrations"
                )
                (alpha_migrations_dir / "0001_bootstrap.py").write_text(
                    "from django.db import migrations\n"
                    "\n"
                    "\n"
                    "class Migration(migrations.Migration):\n"
                    "    dependencies = []\n"
                    "    operations = []\n",
                    encoding="utf-8",
                )
                beta_manifest_path = Path(temp_dir) / "bias-ext-beta-tools" / "extension.json"
                beta_manifest = json.loads(beta_manifest_path.read_text(encoding="utf-8"))
                beta_manifest["dependencies"] = ["alpha-tools"]
                beta_manifest_path.write_text(json.dumps(beta_manifest, ensure_ascii=False), encoding="utf-8")
                call_command_quietly(
                    "sync_extension_package_metadata",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--extension-id",
                    "beta-tools",
                    "--write",
                )

                output = StringIO()
                call_command(
                    "inspect_extension_packages",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--build",
                    "--install-set-smoke",
                    "--migration-smoke",
                    "--format",
                    "json",
                    stdout=output,
                )

            payload = json.loads(output.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertIsNotNone(payload["install_set"])
            self.assertEqual(
                payload["install_set"]["discovered_extension_ids"],
                ["alpha-tools", "beta-tools"],
            )
            self.assertEqual(
                payload["install_set"]["discovered_migration_modules"]["alpha_tools"],
                "bias_ext_alpha_tools.backend.django_migrations",
            )
            self.assertTrue(payload["install_set"]["migration_smoke"])
            self.assertIn(
                "0001_bootstrap.py",
                payload["install_set"]["applied_migration_files"]["alpha_tools"],
            )
            self.assertEqual(
                [
                    item
                    for item in payload["install_set"]["boot_order"]
                    if item in {"alpha-tools", "beta-tools"}
                ],
                ["alpha-tools", "beta-tools"],
            )
            self.assertEqual(payload["install_set"]["errors"], [])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_packages_migration_smoke_requires_install_set_smoke(self):
        with self.assertRaisesMessage(CommandError, "--migration-smoke 必须配合 --install-set-smoke 使用"):
            call_command(
                "inspect_extension_packages",
                "--extensions-path",
                str(Path(settings.BASE_DIR) / "extensions"),
                "--migration-smoke",
            )

    def test_manifest_loader_can_scan_only_installed_distribution_path(self):
        import subprocess
        import bias_core.extensions.manifest as manifest_module

        temp_dir = make_workspace_temp_dir()
        original_path = list(sys.path)
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")

            extension_dir = Path(temp_dir) / "bias-ext-alpha-tools"
            dist_dir = extension_dir / "dist"
            build_result = subprocess.run(
                [sys.executable, "-m", "build", "--wheel", "--no-isolation"],
                cwd=extension_dir,
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(build_result.returncode, 0, build_result.stderr + build_result.stdout)
            wheel_path = next(dist_dir.glob("*.whl"))
            target_dir = Path(temp_dir) / "site"
            install_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--no-deps",
                    "--disable-pip-version-check",
                    "--target",
                    str(target_dir),
                    str(wheel_path),
                ],
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(install_result.returncode, 0, install_result.stderr + install_result.stdout)

            manifest_module._distribution_manifest_cache = None
            try:
                sys.path.insert(0, str(target_dir))
                manifests = manifest_module.ExtensionManifestLoader(
                    Path(temp_dir) / "empty-extensions",
                    include_workspace=False,
                    include_distributions=True,
                    distribution_path=target_dir,
                ).discover_manifests()
            finally:
                manifest_module._distribution_manifest_cache = None
                sys.path[:] = original_path

            self.assertEqual([manifest.id for manifest in manifests], ["alpha-tools"])
            self.assertEqual(manifests[0].source, "python-package")
            self.assertEqual(manifests[0].extra["python_distribution"]["name"], "bias-ext-alpha-tools")
        finally:
            manifest_module._distribution_manifest_cache = None
            sys.path[:] = original_path
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_packages_command_reports_wheel_missing_resource(self):
        import zipfile

        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")

            extension_dir = Path(temp_dir) / "bias-ext-alpha-tools"
            dist_dir = extension_dir / "dist"
            dist_dir.mkdir(parents=True, exist_ok=True)
            wheel_path = dist_dir / "bias_ext_alpha_tools-0.1.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel_path, "w") as archive:
                archive.writestr(
                    "bias_ext_alpha_tools/backend/ext.py",
                    "def extend():\n    return []\n",
                )
                archive.writestr(
                    "bias_ext_alpha_tools-0.1.0.dist-info/entry_points.txt",
                    "[bias.extensions]\nalpha_tools = bias_ext_alpha_tools.backend.ext:extend\n",
                )
                archive.writestr(
                    "bias_ext_alpha_tools-0.1.0.data/data/bias_extensions/alpha-tools/extension.json",
                    "{}\n",
                )

            output = StringIO()
            with self.assertRaisesMessage(CommandError, "扩展 wheel 审计失败"):
                call_command(
                    "inspect_extension_packages",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--extension-id",
                    "alpha-tools",
                    "--format",
                    "json",
                    stdout=output,
                )

            payload = json.loads(output.getvalue())
            self.assertFalse(payload["summary"]["ok"])
            self.assertTrue(any("frontend/forum/index.js" in error for error in payload["results"][0]["errors"]))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_packages_install_smoke_does_not_import_workspace_backend(self):
        import zipfile

        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")

            extension_dir = Path(temp_dir) / "bias-ext-alpha-tools"
            dist_dir = extension_dir / "dist"
            dist_dir.mkdir(parents=True, exist_ok=True)
            wheel_path = dist_dir / "bias_ext_alpha_tools-0.1.0-py3-none-any.whl"
            manifest_payload = {
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "0.1.0",
                "backend": {"entry": "bias_ext_alpha_tools.backend.ext"},
                "frontend": {
                    "admin": "extensions/alpha-tools/frontend/admin/index.js",
                    "forum": "extensions/alpha-tools/frontend/forum/index.js",
                },
            }
            wheel_files = {
                "bias_ext_alpha_tools-0.1.0.dist-info/METADATA": (
                    "Metadata-Version: 2.1\nName: bias-ext-alpha-tools\nVersion: 0.1.0\n"
                ),
                "bias_ext_alpha_tools-0.1.0.dist-info/WHEEL": (
                    "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
                ),
                "bias_ext_alpha_tools-0.1.0.dist-info/entry_points.txt": (
                    "[bias.extensions]\nalpha_tools = bias_ext_alpha_tools.backend.ext:extend\n"
                ),
                "bias_ext_alpha_tools-0.1.0.data/data/bias_extensions/alpha-tools/extension.json": (
                    json.dumps(manifest_payload, ensure_ascii=False)
                ),
                "bias_ext_alpha_tools-0.1.0.data/data/bias_extensions/alpha-tools/frontend/admin/index.js": (
                    "export const extend = []\n"
                ),
                "bias_ext_alpha_tools-0.1.0.data/data/bias_extensions/alpha-tools/frontend/forum/index.js": (
                    "export function extend() {}\n"
                ),
                "bias_ext_alpha_tools-0.1.0.data/data/bias_extensions/alpha-tools/locale/zh-CN.json": "{}\n",
            }
            record_name = "bias_ext_alpha_tools-0.1.0.dist-info/RECORD"
            record_payload = "".join(f"{name},,\n" for name in [*wheel_files.keys(), record_name])
            with zipfile.ZipFile(wheel_path, "w") as archive:
                for name, content in wheel_files.items():
                    archive.writestr(name, content)
                archive.writestr(record_name, record_payload)

            output = StringIO()
            with self.assertRaisesMessage(CommandError, "扩展 wheel 审计失败"):
                call_command(
                    "inspect_extension_packages",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--extension-id",
                    "alpha-tools",
                    "--install-smoke",
                    "--format",
                    "json",
                    stdout=output,
                )

            payload = json.loads(output.getvalue())
            errors = payload["results"][0]["errors"]
            self.assertTrue(any("安装态后端入口不可导入" in error for error in errors), errors)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_rejects_low_level_resource_extender_in_extension_source(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")
                backend_path = Path(temp_dir) / "bias-ext-alpha-tools" / "bias_ext_alpha_tools" / "backend" / "ext.py"
                backend_path.write_text(
                    backend_path.read_text(encoding="utf-8")
                    + "\nfrom bias_core.extensions.extenders import ResourceExtender\n",
                    encoding="utf-8",
                )

                with self.assertRaisesMessage(CommandError, "扩展校验失败"):
                    call_command_quietly(
                        "validate_extensions",
                        "--extensions-path",
                        str(Path(temp_dir) / "extensions"),
                    )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_reports_optional_dependency_top_level_import_before_backend_load(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            alpha_dir = extensions_dir / "alpha-tools"
            beta_dir = extensions_dir / "beta-tools"
            alpha_backend_dir = alpha_dir / "backend"
            alpha_backend_dir.mkdir(parents=True, exist_ok=False)
            beta_dir.mkdir(parents=True, exist_ok=False)
            (alpha_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
                "optional_dependencies": ["beta-tools"],
            }, ensure_ascii=False), encoding="utf-8")
            (alpha_backend_dir / "ext.py").write_text(
                "from extensions.beta_tools.backend.models import BetaThing\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )
            (beta_dir / "extension.json").write_text(json.dumps({
                "id": "beta-tools",
                "name": "Beta Tools",
                "version": "1.0.0",
            }, ensure_ascii=False), encoding="utf-8")

            output = StringIO()
            with self.assertRaisesMessage(CommandError, "扩展校验失败，共 1 个错误"):
                call_command(
                    "validate_extensions",
                    "--extensions-path",
                    str(extensions_dir),
                    stdout=output,
                    stderr=StringIO(),
                )

            self.assertIn("forbidden_cross_extension_internal_import", output.getvalue())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_rejects_external_project_name_residue_in_extension_source(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")
                backend_path = Path(temp_dir) / "bias-ext-alpha-tools" / "bias_ext_alpha_tools" / "backend" / "ext.py"
                external_project_name = "fla" + "rum"
                backend_path.write_text(
                    backend_path.read_text(encoding="utf-8")
                    + f"\n# {external_project_name} naming residue must not enter Bias extensions\n",
                    encoding="utf-8",
                )

                with self.assertRaisesMessage(CommandError, "扩展校验失败，共 1 个错误"):
                    call_command_quietly(
                        "validate_extensions",
                        "--extensions-path",
                        str(Path(temp_dir) / "extensions"),
                    )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_allows_direct_admin_frontend_extender(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")
                admin_path = Path(temp_dir) / "bias-ext-alpha-tools" / "frontend" / "admin" / "index.js"
                admin_path.write_text(
                    "export const extend = [\n"
                    "  new AdminExtender().page({ path: '/admin/direct' }),\n"
                    "]\n"
                    "export function resolveDetailPage() { return null }\n",
                    encoding="utf-8",
                )

                call_command_quietly(
                    "validate_extensions",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_rejects_core_internal_imports_by_default(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["core"],
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.models import Setting\n"
                "from bias_core.extensions.backend import _build_runtime_action_definition\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            with self.assertRaisesMessage(CommandError, "扩展校验失败"):
                call_command_quietly("validate_extensions", "--extensions-path", str(Path(temp_dir) / "extensions"))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_allows_public_extension_facades_by_default(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["core"],
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import FrontendExtender, runtime_action\n"
                "from bias_core.extensions.runtime import get_runtime_user_by_id\n"
                "from bias_core.extensions.platform import api_error, get_forum_registry\n"
                "from bias_core.extensions.contracts import PermissionDefinition\n"
                "from bias_core.extensions.testing import ExtensionRuntimeTestMixin\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            call_command_quietly("validate_extensions", "--extensions-path", str(Path(temp_dir) / "extensions"))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_internal_mode_allows_core_internal_imports(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["core"],
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.models import Setting\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            call_command_quietly("validate_extensions", "--extensions-path", str(Path(temp_dir) / "extensions"), "--internal")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_imports_command_rejects_core_internal_imports_by_default(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["core"],
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.models import Setting\n"
                "from bias_core.extensions import FrontendExtender\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            output = StringIO()
            with self.assertRaisesMessage(CommandError, "扩展 import 边界审计失败"):
                call_command(
                    "inspect_extension_imports",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--format",
                    "json",
                    stdout=output,
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(payload["summary"]["manifest_count"], 1)
            self.assertFalse(payload["summary"]["ok"])
            self.assertTrue(any(
                item["code"] == "forbidden_core_internal_import"
                and item["extension_id"] == "alpha-tools"
                for item in payload["issues"]
            ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_imports_command_internal_mode_allows_core_internal_imports(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["core"],
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.models import Setting\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            output = StringIO()
            call_command(
                "inspect_extension_imports",
                "--extensions-path",
                str(Path(temp_dir) / "extensions"),
                "--internal",
                "--format",
                "json",
                stdout=output,
            )

            payload = json.loads(output.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertEqual(payload["summary"]["error_count"], 0)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_imports_command_scans_tests_when_requested(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["core"],
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions import FrontendExtender\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )
            (backend_dir / "tests.py").write_text(
                "from bias_core.models import Setting\n"
                "from bias_core.extensions.testing import ExtensionRuntimeTestMixin\n",
                encoding="utf-8",
            )

            default_output = StringIO()
            call_command(
                "inspect_extension_imports",
                "--extensions-path",
                str(Path(temp_dir) / "extensions"),
                "--format",
                "json",
                stdout=default_output,
            )
            default_payload = json.loads(default_output.getvalue())
            self.assertTrue(default_payload["summary"]["ok"])
            self.assertFalse(default_payload["include_tests"])

            include_tests_output = StringIO()
            with self.assertRaisesMessage(CommandError, "扩展 import 边界审计失败"):
                call_command(
                    "inspect_extension_imports",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--include-tests",
                    "--format",
                    "json",
                    stdout=include_tests_output,
                )

            include_tests_payload = json.loads(include_tests_output.getvalue())
            self.assertTrue(include_tests_payload["include_tests"])
            self.assertTrue(any(
                item["code"] == "forbidden_core_internal_import"
                and item["field"].endswith("backend/tests.py")
                for item in include_tests_payload["issues"]
            ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_reports_missing_frontend_admin_exports(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            admin_dir = manifest_dir / "frontend" / "admin"
            admin_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["core"],
                "frontend_admin_entry": "extensions/alpha-tools/frontend/admin/index.js",
                "settings_pages": ["/admin/extensions/alpha-tools/settings"],
                "operations_pages": ["/admin/extensions/alpha-tools/operations"],
            }, ensure_ascii=False), encoding="utf-8")
            (admin_dir / "index.js").write_text(
                "export function resolveSettingsPage() { return null }\n",
                encoding="utf-8",
            )

            with self.assertRaisesMessage(CommandError, "扩展校验失败，共 1 个错误"):
                call_command_quietly("validate_extensions", "--extensions-path", str(Path(temp_dir) / "extensions"))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_allows_generated_permissions_and_operations_surfaces(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            admin_dir = manifest_dir / "frontend" / "admin"
            admin_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["core"],
                "frontend_admin_entry": "extensions/alpha-tools/frontend/admin/index.js",
                "permissions_pages": ["/admin/extensions/alpha-tools/permissions"],
                "operations_pages": ["/admin/extensions/alpha-tools/operations"],
                "admin_actions": [
                    {
                        "key": "details",
                        "label": "查看详情",
                        "kind": "route",
                        "target": "/admin/extensions/alpha-tools",
                    }
                ],
            }, ensure_ascii=False), encoding="utf-8")
            (admin_dir / "index.js").write_text(
                "export function resolveDetailPage() { return null }\n",
                encoding="utf-8",
            )

            call_command_quietly("validate_extensions", "--extensions-path", str(Path(temp_dir) / "extensions"))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_reports_missing_frontend_admin_entry_declaration(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["core"],
                "settings_pages": ["/admin/extensions/alpha-tools/settings"],
            }, ensure_ascii=False), encoding="utf-8")

            with self.assertRaisesMessage(CommandError, "扩展校验失败，共 1 个错误"):
                call_command_quietly("validate_extensions", "--extensions-path", str(Path(temp_dir) / "extensions"))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_can_emit_json_payload(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")
                stdout = StringIO()
                call_command_quietly(
                    "validate_extensions",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--format",
                    "json",
                    stdout=stdout,
                )

                payload = json.loads(stdout.getvalue())
                self.assertEqual(payload["summary"]["manifest_count"], 1)
                self.assertEqual(payload["summary"]["error_count"], 0)
                self.assertEqual(payload["summary"]["warning_count"], 0)
                self.assertTrue(payload["summary"]["ok"])
                self.assertEqual(payload["manifests"][0]["id"], "alpha-tools")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_json_payload_still_fails_on_errors(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["missing-one"],
                "frontend_admin_entry": "extensions/alpha-tools/frontend/admin/index.js",
                "settings_pages": ["/admin/extensions/alpha-tools/settings"],
            }, ensure_ascii=False), encoding="utf-8")

            stdout = StringIO()
            with self.assertRaisesMessage(CommandError, "扩展校验失败，共 2 个错误"):
                call_command_quietly(
                    "validate_extensions",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["summary"]["error_count"], 2)
            self.assertFalse(payload["summary"]["ok"])
            self.assertTrue(any(item["code"] == "missing_dependency" for item in payload["issues"]))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_reports_frontend_route_conflicts_in_json(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            for extension_id, component_name in (
                ("alpha-tools", "AlphaView"),
                ("beta-tools", "BetaView"),
            ):
                manifest_dir = extensions_dir / extension_id
                backend_dir = manifest_dir / "backend"
                backend_dir.mkdir(parents=True, exist_ok=False)
                (manifest_dir / "extension.json").write_text(json.dumps({
                    "id": extension_id,
                    "name": extension_id.title(),
                    "version": "1.0.0",
                    "dependencies": ["core"],
                    "backend_entry": f"extensions.{extension_id.replace('-', '_')}.backend.ext",
                    "frontend_forum_entry": "frontend/forum/index.js",
                }, ensure_ascii=False), encoding="utf-8")
                (backend_dir / "ext.py").write_text(
                    "from bias_core.extensions import FrontendExtender\n"
                    "\n"
                    "def extend():\n"
                    "    return [\n"
                    "        FrontendExtender(forum_entry='frontend/forum/index.js').route(\n"
                    f"            '/alpha', 'alpha', './{component_name}.vue'\n"
                    "        ),\n"
                    "    ]\n",
                    encoding="utf-8",
                )
                forum_dir = manifest_dir / "frontend" / "forum"
                forum_dir.mkdir(parents=True, exist_ok=False)
                (forum_dir / "index.js").write_text(
                    "export function extend() { return null }\n",
                    encoding="utf-8",
                )

            stdout = StringIO()
            with self.assertRaisesMessage(CommandError, "扩展校验失败"):
                call_command(
                    "validate_extensions",
                    "--extensions-path",
                    str(extensions_dir),
                    "--format",
                    "json",
                    stdout=stdout,
                    stderr=StringIO(),
                )

            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["summary"]["ok"])
            self.assertTrue(any(item["code"] == "duplicate_frontend_route_name" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_frontend_route_path" for item in payload["issues"]))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_reports_backend_route_conflicts_in_json(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            for extension_id in ("alpha-tools", "beta-tools"):
                manifest_dir = extensions_dir / extension_id
                backend_dir = manifest_dir / "backend"
                backend_dir.mkdir(parents=True, exist_ok=False)
                (manifest_dir / "extension.json").write_text(json.dumps({
                    "id": extension_id,
                    "name": extension_id.title(),
                    "version": "1.0.0",
                    "dependencies": ["core"],
                    "backend_entry": f"extensions.{extension_id.replace('-', '_')}.backend.ext",
                }, ensure_ascii=False), encoding="utf-8")
                (backend_dir / "ext.py").write_text(
                    "from bias_core.extensions import ApiRoutesExtender, RoutesExtender, WebSocketRoutesExtender\n"
                    "from channels.generic.websocket import AsyncWebsocketConsumer\n"
                    "from ninja import Router\n"
                    "\n"
                    "router = Router()\n"
                    "\n"
                    "@router.get('/ping')\n"
                    "def ping(request):\n"
                    "    return {'ok': True}\n"
                    "\n"
                    "def handle_ping(request):\n"
                    "    return {'ok': True}\n"
                    "\n"
                    "class AlphaConsumer(AsyncWebsocketConsumer):\n"
                    "    pass\n"
                    "\n"
                    "def extend():\n"
                    "    return [\n"
                    "        ApiRoutesExtender(mounts=(('/alpha', router),), tags=('Alpha',)),\n"
                    "        RoutesExtender().get('/alpha', 'alpha.index', handle_ping),\n"
                    "        WebSocketRoutesExtender().route(r'^ws/alpha/$', 'alpha.socket', AlphaConsumer),\n"
                    "    ]\n",
                    encoding="utf-8",
                )

            stdout = StringIO()
            with self.assertRaisesMessage(CommandError, "扩展校验失败"):
                call_command(
                    "validate_extensions",
                    "--extensions-path",
                    str(extensions_dir),
                    "--format",
                    "json",
                    stdout=stdout,
                    stderr=StringIO(),
                )

            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["summary"]["ok"])
            self.assertTrue(any(item["code"] == "duplicate_api_route_name" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_api_route_path" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_websocket_route_name" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_websocket_route_path" for item in payload["issues"]))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_reports_runtime_capability_conflicts_in_json(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            for extension_id in ("alpha-tools", "beta-tools"):
                manifest_dir = extensions_dir / extension_id
                backend_dir = manifest_dir / "backend"
                backend_dir.mkdir(parents=True, exist_ok=False)
                (manifest_dir / "extension.json").write_text(json.dumps({
                    "id": extension_id,
                    "name": extension_id.title(),
                    "version": "1.0.0",
                    "dependencies": ["core"],
                    "backend_entry": f"extensions.{extension_id.replace('-', '_')}.backend.ext",
                }, ensure_ascii=False), encoding="utf-8")
                (backend_dir / "ext.py").write_text(
                    "from bias_core.extensions import (\n"
                    "    AdminPageDefinition,\n"
                    "    AdminSurfaceExtender,\n"
                    "    ApiResourceExtender,\n"
                    "    DiscussionListFilterDefinition,\n"
                    "    DiscussionListQueryDefinition,\n"
                    "    DiscussionSortDefinition,\n"
                    "    ExtensionModelCastDefinition,\n"
                    "    ExtensionModelDefaultDefinition,\n"
                    "    ExtensionModelDefinition,\n"
                    "    ExtensionModelRelationDefinition,\n"
                    "    ExtensionResourceDefinition,\n"
                    "    ExtensionResourceEndpointDefinition,\n"
                    "    ExtensionResourceFieldDefinition,\n"
                    "    ExtensionResourceFilterDefinition,\n"
                    "    ExtensionResourceRelationshipDefinition,\n"
                    "    ExtensionResourceSortDefinition,\n"
                    "    LanguagePackExtender,\n"
                    "    ModelExtender,\n"
                    "    ModelUrlExtender,\n"
                    "    ForumCapabilitiesExtender,\n"
                    "    NotificationsExtender,\n"
                    "    PermissionDefinition,\n"
                    "    PostTypeDefinition,\n"
                    "    SearchDriverExtender,\n"
                    "    SearchFilterDefinition,\n"
                    "    SearchIndexExtender,\n"
                    "    UserPreferenceDefinition,\n"
                    ")\n"
                    "\n"
                    "ALPHA_MODEL = 'shared.model'\n"
                    "\n"
                    "def parse_alpha(token):\n"
                    "    return token if token.startswith('alpha:') else None\n"
                    "\n"
                    "def apply_alpha(queryset, value, context):\n"
                    "    return queryset\n"
                    "\n"
                    "def resolve_alpha(instance, context):\n"
                    "    return True\n"
                    "\n"
                    "def handle_alpha(context):\n"
                    "    return {'ok': True}\n"
                    "\n"
                    "def extend():\n"
                    "    return [\n"
                    "        AdminSurfaceExtender(\n"
                    "            permissions=(PermissionDefinition(\n"
                    "                code='alpha.manage', label='Alpha', section='alpha', section_label='Alpha', module_id='',\n"
                    "            ),),\n"
                    "            admin_pages=(AdminPageDefinition(path='/admin/alpha', label='Alpha', icon='alpha', module_id=''),),\n"
                    "        ),\n"
                    "        NotificationsExtender().type('alphaPing', label='Alpha Ping'),\n"
                    "        NotificationsExtender(user_preferences=(UserPreferenceDefinition(\n"
                    "            key='alpha.enabled', label='Alpha Enabled', module_id='',\n"
                    "        ),)),\n"
                    "        ForumCapabilitiesExtender(search_filters=(SearchFilterDefinition(\n"
                    "            code='alpha', label='Alpha', module_id='', target='discussion', parser=parse_alpha, applier=apply_alpha,\n"
                    "        ),), post_types=(PostTypeDefinition(\n"
                    "            code='alpha', label='Alpha', module_id='',\n"
                    "        ),), discussion_list_queries=(DiscussionListQueryDefinition(\n"
                    "            key='alpha', module_id='', applier=lambda queryset, context: queryset,\n"
                    "        ),), discussion_sorts=(DiscussionSortDefinition(\n"
                    "            code='alpha', label='Alpha', module_id='', applier=lambda queryset, context: queryset,\n"
                    "        ),), discussion_list_filters=(DiscussionListFilterDefinition(\n"
                    "            code='alpha', label='Alpha', module_id='', applier=lambda queryset, context: queryset,\n"
                    "        ),)),\n"
                    "        LanguagePackExtender(code='en', label='English'),\n"
                    "        ApiResourceExtender.from_resource(ExtensionResourceDefinition(\n"
                    "            resource='alpha', module_id='', resolver=resolve_alpha,\n"
                    "        )),\n"
                    "        ApiResourceExtender('forum').fields((ExtensionResourceFieldDefinition(\n"
                    "            resource='forum', field='alpha', module_id='', resolver=resolve_alpha,\n"
                    "        ),)),\n"
                    "        ApiResourceExtender('discussion').relationships((ExtensionResourceRelationshipDefinition(\n"
                    "            resource='discussion', relationship='alpha', module_id='', resolver=resolve_alpha,\n"
                    "        ),)),\n"
                    "        ApiResourceExtender('alpha').endpoints((ExtensionResourceEndpointDefinition(\n"
                    "            resource='alpha', endpoint='inspect', module_id='', handler=handle_alpha,\n"
                    "        ),)),\n"
                    "        ApiResourceExtender('alpha').sorts((ExtensionResourceSortDefinition(\n"
                    "            resource='alpha', sort='recent', module_id='',\n"
                    "        ),)),\n"
                    "        ApiResourceExtender('alpha').filters((ExtensionResourceFilterDefinition(\n"
                    "            resource='alpha', filter='visible', module_id='', handler=apply_alpha,\n"
                    "        ),)),\n"
                    "        ModelExtender(definitions=(ExtensionModelDefinition(\n"
                    "            model=ALPHA_MODEL, key='owner', handler=object(), kind='owner',\n"
                    "        ),), relations=(ExtensionModelRelationDefinition(\n"
                    "            model=ALPHA_MODEL, name='tags', resolver=lambda instance: (), inject_attribute=False,\n"
                    "        ),), casts=(ExtensionModelCastDefinition(\n"
                    "            model=ALPHA_MODEL, attribute='meta', cast=dict,\n"
                    "        ),), defaults=(ExtensionModelDefaultDefinition(\n"
                    "            model=ALPHA_MODEL, attribute='status', value='new',\n"
                    "        ),)),\n"
                    "        ModelUrlExtender(ALPHA_MODEL).add_slug_driver('default', object()),\n"
                    "        SearchDriverExtender().add_searcher(ALPHA_MODEL, object(), target='alpha'),\n"
                    "        SearchIndexExtender().postgres_index('alpha_index', drop='', create=''),\n"
                    "    ]\n",
                    encoding="utf-8",
                )

            stdout = StringIO()
            with self.assertRaisesMessage(CommandError, "扩展校验失败"):
                call_command(
                    "validate_extensions",
                    "--extensions-path",
                    str(extensions_dir),
                    "--format",
                    "json",
                    stdout=stdout,
                    stderr=StringIO(),
                )

            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["summary"]["ok"])
            self.assertTrue(any(item["code"] == "duplicate_permission" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_admin_page" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_notification_type" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_user_preference" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_language_pack" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_post_type" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_search_filter" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_discussion_list_query" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_discussion_sort" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_discussion_list_filter" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_resource_definition" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_resource_field" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_resource_relationship" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_resource_endpoint" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_resource_sort" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_resource_filter" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_model_definition" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_model_relation" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_model_cast" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_model_default" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_model_slug_driver" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_search_driver" for item in payload["issues"]))
            self.assertTrue(any(item["code"] == "duplicate_search_index" for item in payload["issues"]))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_strict_reports_missing_backend_hook(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["core"],
                "backend_entry": "extensions.alpha_tools.backend.ext",
                "runtime_actions": [
                    {
                        "key": "rebuild-cache",
                        "label": "刷新缓存",
                        "hook": "run_rebuild_cache",
                    }
                ],
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "def run_install(context):\n"
                "    return {'status': 'ok'}\n",
                encoding="utf-8",
            )

            with self.assertRaisesMessage(CommandError, "扩展校验失败，共 1 个错误"):
                call_command_quietly(
                    "validate_extensions",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--strict",
                )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extensions_command_outputs_extension_snapshot(self):
        stdout = StringIO()
        call_command("inspect_extensions", stdout=stdout)
        payload = json.loads(stdout.getvalue())

        self.assertIn("summary", payload)
        self.assertIn("extensions", payload)
        self.assertIn("meta", payload)
        self.assertGreaterEqual(payload["summary"]["extension_count"], 1)
        self.assertIn("attention_count", payload["summary"])
        self.assertIn("blocking_count", payload["summary"])
        self.assertIn("warning_count", payload["summary"])
        self.assertIn("frontend_bundle_count", payload["summary"])
        self.assertIn("migration_bundle_count", payload["summary"])
        self.assertIn("package_lock", payload["runtime"])
        self.assertIn("summary", payload["runtime"]["package_lock"])
        self.assertIn("packages", payload["runtime"]["package_lock"])
        self.assertIn("diagnostics", payload["extensions"][0])
        self.assertTrue(any(item["id"] == "core" for item in payload["extensions"]))
        self.assertTrue(any(item["id"] == "tags" for item in payload["extensions"]))
        core_extension = next(item for item in payload["extensions"] if item["id"] == "core")
        self.assertEqual(core_extension["source"], "core-module")
        self.assertFalse(core_extension["lifecycle_plan"]["disable"]["can_execute"])
        self.assertIn("core_module", core_extension["lifecycle_plan"]["disable"]["blockers"])
        alpha_extension = next((item for item in payload["extensions"] if item["id"] == "alpha-tools"), None)
        if alpha_extension is not None:
            self.assertFalse(alpha_extension["product_visible"])

    def test_inspect_extensions_counts_real_django_migration_bundle(self):
        from bias_core.extension_detail.forum_domain import _build_extension_delivery_assets
        from bias_core.extension_diagnostics import summarize_extension_delivery
        from bias_core.extensions.extension_runtime import Extension
        from bias_core.extensions.manifest import ExtensionManifestLoader

        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")
                migrations_dir = (
                    Path(temp_dir)
                    / "bias-ext-alpha-tools"
                    / "bias_ext_alpha_tools"
                    / "backend"
                    / "django_migrations"
                )
                (migrations_dir / "0001_bootstrap.py").write_text(
                    "from django.db import migrations\n"
                    "\n"
                    "\n"
                    "class Migration(migrations.Migration):\n"
                    "    dependencies = []\n"
                    "    operations = []\n",
                    encoding="utf-8",
                )

                manifest = ExtensionManifestLoader(
                    Path(temp_dir) / "extensions",
                    include_workspace=True,
                    workspace_root=Path(temp_dir),
                ).discover_manifests()[0]
                extension = Extension.from_manifest(manifest)
                delivery_assets = _build_extension_delivery_assets(extension)

            migration_asset = next(
                item for item in delivery_assets["assets"]
                if item["key"] == "migrations"
            )
            self.assertTrue(migration_asset["exists"])
            self.assertIn("django_migrations", migration_asset["path"])
            self.assertEqual(
                summarize_extension_delivery([{"delivery_assets": delivery_assets}])["migration_bundle_count"],
                1,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extension_diagnostics_report_inactive_optional_dependencies_as_warning(self):
        from bias_core.extension_diagnostics import classify_extension_diagnostics

        diagnostics = classify_extension_diagnostics({
            "healthy": True,
            "dependency_state": "healthy",
            "optional_dependency_status": [
                {
                    "id": "realtime",
                    "state": "disabled",
                    "installed": True,
                    "enabled": False,
                    "active": False,
                },
            ],
        })

        self.assertFalse(diagnostics["blocking"])
        self.assertTrue(diagnostics["warning"])
        self.assertIn("可选依赖未启用：realtime", diagnostics["warning_reasons"])

    def test_inspect_extensions_command_can_focus_single_extension_with_permissions(self):
        stdout = StringIO()
        call_command(
            "inspect_extensions",
            "--extension-id",
            "tags",
            "--include-permissions",
            stdout=stdout,
        )
        payload = json.loads(stdout.getvalue())

        self.assertEqual(payload["summary"]["extension_count"], 1)
        self.assertEqual(payload["meta"]["extension_id"], "tags")
        self.assertEqual(payload["extensions"][0]["id"], "tags")
        self.assertIn("permission_sections", payload["extensions"][0])
        self.assertIn("package_lock", payload)
        self.assertIn("summary", payload["package_lock"])
        self.assertIn("packages", payload["package_lock"])
        self.assertIn("dependency_resolution", payload["package_lock"])
        self.assertIn("boot_order", payload["package_lock"]["dependency_resolution"])
        self.assertIn("graph", payload["package_lock"]["dependency_resolution"])

    def test_inspect_extensions_command_reports_model_ownership_audit(self):
        stdout = StringIO()
        call_command(
            "inspect_extensions",
            "--extension-id",
            "tags",
            stdout=stdout,
        )
        payload = json.loads(stdout.getvalue())
        extension = payload["extensions"][0]
        audit = extension["model_ownership_audit"]

        self.assertEqual(extension["id"], "tags")
        self.assertIn("owned_model_count", audit)
        self.assertIn("items", audit)
        self.assertIn("target_app_label", audit)
        self.assertIn("model_package_migration_required_count", extension["capability_summary"])

    def test_inspect_extensions_command_reports_contract_snapshot(self):
        stdout = StringIO()
        call_command(
            "inspect_extensions",
            "--extension-id",
            "tags",
            stdout=stdout,
        )
        payload = json.loads(stdout.getvalue())
        extension = payload["extensions"][0]
        snapshot = extension["contract_snapshot"]

        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual(snapshot["extension_id"], "tags")
        self.assertTrue(any(item["id"] == "flags" for item in extension["optional_dependency_status"]))
        self.assertIn("frontend", snapshot)
        self.assertIn("forum", snapshot)
        self.assertIn("resources", snapshot)
        self.assertIn("models", snapshot)
        self.assertIn("presentation", snapshot)
        self.assertIn("runtime", snapshot)
        self.assertIn("lifecycle", snapshot)
        self.assertIn("search", snapshot)
        self.assertIn("settings", snapshot)
        self.assertIn("summary", snapshot)
        self.assertIn("optional_dependency_status", snapshot)
        self.assertTrue(any(item["id"] == "flags" for item in snapshot["optional_dependency_status"]))
        self.assertTrue(any(item["resource"] == "tag" for item in snapshot["resources"]["definitions"]))
        self.assertTrue(any(item["resource"] == "discussion" and item["field"] == "tags" for item in snapshot["resources"]["fields"]))
        self.assertTrue(any(item["resource"] == "tag" for item in snapshot["resources"]["endpoints"]))
        self.assertTrue(any(item["target"] == "discussion" for item in snapshot["forum"]["search_filters"]))
        self.assertEqual(snapshot["summary"]["resource_definition_count"], len(snapshot["resources"]["definitions"]))
        self.assertEqual(snapshot["summary"]["resource_field_count"], len(snapshot["resources"]["fields"]))
        self.assertEqual(snapshot["summary"]["resource_endpoint_count"], len(snapshot["resources"]["endpoints"]))
        self.assertEqual(
            snapshot["resources"]["definitions"],
            sorted(snapshot["resources"]["definitions"], key=lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True)),
        )
        self.assertIn("hooks", snapshot["lifecycle"])
        self.assertEqual(snapshot["lifecycle"]["hooks"], sorted(snapshot["lifecycle"]["hooks"]))

    def test_inspect_extensions_command_reports_runtime_contract_snapshot(self):
        stdout = StringIO()
        call_command(
            "inspect_extensions",
            "--extension-id",
            "realtime",
            stdout=stdout,
        )
        payload = json.loads(stdout.getvalue())
        snapshot = payload["extensions"][0]["contract_snapshot"]

        self.assertTrue(any(item["name"] == "realtime.notifications" for item in snapshot["runtime"]["websocket_routes"]))
        self.assertGreaterEqual(snapshot["summary"]["websocket_route_count"], 1)
        self.assertGreaterEqual(snapshot["summary"]["route_mount_count"], 1)
        self.assertTrue(any(item["event"] == "NotificationCreatedEvent" for item in snapshot["events"]["listeners"]))

        stdout = StringIO()
        call_command(
            "inspect_extensions",
            "--extension-id",
            "security",
            stdout=stdout,
        )
        payload = json.loads(stdout.getvalue())
        security_snapshot = payload["extensions"][0]["contract_snapshot"]

        self.assertTrue(any(item["key"] == "human_verification" for item in security_snapshot["runtime"]["auth_handlers"]))
        self.assertGreaterEqual(security_snapshot["summary"]["auth_handler_count"], 1)

    def test_inspect_extensions_command_reports_settings_contract_snapshot(self):
        stdout = StringIO()
        call_command(
            "inspect_extensions",
            "--extension-id",
            "emoji",
            stdout=stdout,
        )
        payload = json.loads(stdout.getvalue())
        snapshot = payload["extensions"][0]["contract_snapshot"]
        settings = snapshot["settings"]

        self.assertTrue(any(item["key"] == "cdn_url" and item["type"] == "text" for item in settings["fields"]))
        self.assertTrue(any(item["key"] == "cdn_url" for item in settings["defaults"]))
        self.assertEqual(settings["forum_settings_keys"], ["cdn_url"])
        self.assertEqual(settings["frontend_cache_keys"], ["cdn_url"])
        self.assertTrue(any(item["name"] == "bias-emoji-cdn" and item["key"] == "cdn_url" for item in settings["theme_variables"]))
        self.assertGreaterEqual(snapshot["summary"]["settings_field_count"], 1)
        self.assertGreaterEqual(snapshot["summary"]["forum_settings_key_count"], 1)

    def test_inspect_extensions_command_reports_presentation_contract_snapshot(self):
        stdout = StringIO()
        call_command(
            "inspect_extensions",
            "--extension-id",
            "emoji",
            stdout=stdout,
        )
        payload = json.loads(stdout.getvalue())
        snapshot = payload["extensions"][0]["contract_snapshot"]
        presentation = snapshot["presentation"]

        self.assertEqual(presentation["frontend_assets"]["css"], [])
        self.assertIn("extensions/emoji/frontend/forum/index.js", snapshot["frontend"]["forum_entry"])
        self.assertTrue(any(str(path).endswith("bias-ext-emoji\\locale") or str(path).endswith("bias-ext-emoji/locale") for path in presentation["locale_paths"]))
        self.assertTrue(any(
            item["phase"] == "parse"
            and item["module_id"] == "emoji"
            and item["callback"].endswith("parse_emoticons")
            for item in presentation["formatter_callbacks"]
        ))
        self.assertGreaterEqual(snapshot["summary"]["locale_path_count"], 1)
        self.assertGreaterEqual(snapshot["summary"]["formatter_callback_count"], 1)

    def test_inspect_extensions_command_can_emit_contract_baseline(self):
        stdout = StringIO()
        call_command(
            "inspect_extensions",
            "--extension-id",
            "tags",
            "--contract-baseline-only",
            stdout=stdout,
        )
        payload = json.loads(stdout.getvalue())

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["meta"]["source"], "inspect_extensions")
        self.assertEqual(payload["meta"]["extension_count"], 1)
        self.assertEqual(set(payload["contract_snapshots"].keys()), {"tags"})
        self.assertEqual(payload["contract_snapshots"]["tags"]["extension_id"], "tags")

    def test_inspect_extensions_command_can_write_utf8_json_output(self):
        temp_dir = make_workspace_temp_dir()
        try:
            output_path = Path(temp_dir) / "baseline.json"
            stdout = StringIO()
            call_command(
                "inspect_extensions",
                "--extension-id",
                "tags",
                "--contract-baseline-only",
                "--output",
                str(output_path),
                stdout=stdout,
            )

            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertEqual(set(payload["contract_snapshots"].keys()), {"tags"})
            self.assertIn(str(output_path), stdout.getvalue())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extensions_command_can_filter_attention_only(self):
        ExtensionInstallation.objects.create(
            extension_id="notifications",
            version="0.1.0",
            source="filesystem",
            enabled=True,
            installed=True,
            booted=True,
            meta={
                "migration_execution": {
                    "status": "error",
                    "status_label": "失败",
                    "message": "迁移执行失败",
                },
            },
        )

        stdout = StringIO()
        call_command("inspect_extensions", "--only-attention", stdout=stdout)
        payload = json.loads(stdout.getvalue())

        self.assertGreaterEqual(payload["summary"]["attention_count"], 1)
        self.assertTrue(any(item["id"] == "notifications" for item in payload["extensions"]))
        self.assertTrue(all("django_app_label" in item for item in payload["extensions"]))

    def test_inspect_extensions_command_can_filter_blocking_only(self):
        ExtensionInstallation.objects.create(
            extension_id="notifications",
            version="0.1.0",
            source="filesystem",
            enabled=True,
            installed=True,
            booted=True,
            meta={
                "migration_execution": {
                    "status": "error",
                    "status_label": "失败",
                    "message": "迁移执行失败",
                },
            },
        )

        stdout = StringIO()
        call_command("inspect_extensions", "--only-blocking", stdout=stdout)
        payload = json.loads(stdout.getvalue())

        self.assertGreaterEqual(payload["summary"]["blocking_count"], 1)
        self.assertTrue(all(item["diagnostics"]["blocking"] for item in payload["extensions"]))

    def test_inspect_extensions_command_reports_unmigrated_database_as_blocking_json(self):
        stdout = StringIO()
        with patch(
            "bias_core.management.commands.inspect_extensions.get_extension_registry",
            side_effect=OperationalError("no such table: extension_installations"),
        ):
            call_command("inspect_extensions", "--format", "json", "--only-blocking", stdout=stdout)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["summary"]["status"], "blocked")
        self.assertEqual(payload["summary"]["blocking_count"], 1)
        self.assertEqual(payload["diagnostics"][0]["code"], "database_migrations_unapplied")
        self.assertFalse(payload["meta"]["database_ready"])
        self.assertEqual(payload["extensions"], [])

    def test_distribution_manifest_loader_detects_packaged_extension_data_files(self):
        from bias_core.extensions.manifest import ExtensionManifestLoader

        loader = ExtensionManifestLoader(Path(settings.BASE_DIR) / "extensions")
        self.assertTrue(loader._is_distribution_manifest_file(
            "bias_ext_users-0.1.0.data/data/bias_extensions/users/extension.json"
        ))
        self.assertTrue(loader._is_distribution_manifest_file(
            "bias_extensions/users/extension.json"
        ))

    def test_extension_django_app_discovery_reads_packaged_distribution_manifests(self):
        from bias_core.conf.extension_discovery import (
            discover_extension_migration_modules,
            discover_installed_extension_django_apps,
        )

        temp_dir = make_workspace_temp_dir()
        try:
            manifest_path = temp_dir / "bias_ext_users-0.1.0.data" / "data" / "bias_extensions" / "users" / "extension.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps({
                "id": "users",
                "name": "Users",
                "version": "0.1.0",
                "django": {
                    "app_config": "bias_ext_users.backend.apps.UsersExtensionConfig",
                    "app_label": "users",
                    "migration_module": "bias_ext_users.backend.django_migrations",
                },
            }, ensure_ascii=False), encoding="utf-8")

            distribution = SimpleNamespace(
                files=["bias_ext_users-0.1.0.data/data/bias_extensions/users/extension.json"],
                metadata={"Name": "bias-ext-users"},
                locate_file=lambda file: temp_dir / str(file),
            )
            with patch("bias_core.conf.extension_discovery.metadata.distributions", return_value=[distribution]):
                self.assertIn(
                    "bias_ext_users.backend.apps.UsersExtensionConfig",
                    discover_installed_extension_django_apps(temp_dir / "empty"),
                )
                self.assertEqual(
                    discover_extension_migration_modules(temp_dir / "empty")["users"],
                    "bias_ext_users.backend.django_migrations",
                )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_distribution_manifest_loader_resolves_packaged_frontend_resources(self):
        import bias_core.extensions.manifest as manifest_module
        from bias_core.extensions.validation_inspection import inspect_frontend_forum_entry

        temp_dir = make_workspace_temp_dir()
        try:
            data_root = temp_dir / "bias_ext_users-0.1.0.data" / "data" / "bias_extensions" / "users"
            forum_entry = data_root / "frontend" / "forum" / "index.js"
            forum_entry.parent.mkdir(parents=True, exist_ok=True)
            forum_entry.write_text("export function extend(app) { return app }\n", encoding="utf-8")
            manifest_path = data_root / "extension.json"
            manifest_path.write_text(json.dumps({
                "id": "users",
                "name": "Users",
                "version": "0.1.0",
                "frontend": {
                    "forum": "extensions/users/frontend/forum/index.js",
                },
            }, ensure_ascii=False), encoding="utf-8")

            distribution = SimpleNamespace(
                files=[
                    "bias_ext_users-0.1.0.data/data/bias_extensions/users/extension.json",
                    "bias_ext_users-0.1.0.data/data/bias_extensions/users/frontend/forum/index.js",
                ],
                metadata={"Name": "bias-ext-users"},
                version="0.1.0",
                locate_file=lambda file: temp_dir / str(file),
            )
            manifest_module._distribution_manifest_cache = None
            try:
                with patch("bias_core.extensions.manifest.metadata.distributions", return_value=[distribution]):
                    manifests = manifest_module.ExtensionManifestLoader(
                        temp_dir / "empty",
                        include_workspace=False,
                        include_distributions=True,
                    ).discover_manifests()
            finally:
                manifest_module._distribution_manifest_cache = None

            self.assertEqual(len(manifests), 1)
            inspection = inspect_frontend_forum_entry(manifests[0], extensions_base_path=temp_dir / "empty")

            self.assertTrue(inspection["exists"], inspection)
            self.assertIn("extend", inspection["available_exports"])
            self.assertEqual(inspection["entry_key"], "extensions/users/frontend/forum/index.js")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_distribution_manifest_loader_resolves_python_package_backend_entry(self):
        import bias_core.extensions.manifest as manifest_module
        from bias_core.extensions.validation_inspection import inspect_backend_entry

        temp_dir = make_workspace_temp_dir()
        module_name = "bias_ext_users"
        original_path = list(sys.path)
        try:
            package_root = temp_dir / module_name / "backend"
            package_root.mkdir(parents=True, exist_ok=True)
            (temp_dir / module_name / "__init__.py").write_text("", encoding="utf-8")
            (package_root / "__init__.py").write_text("", encoding="utf-8")
            (package_root / "ext.py").write_text(
                "def extend():\n"
                "    return []\n"
                "\n"
                "def run_rebuild_cache(context):\n"
                "    return {'status': 'ok'}\n",
                encoding="utf-8",
            )
            data_root = temp_dir / "bias_ext_users-0.1.0.data" / "data" / "bias_extensions" / "users"
            data_root.mkdir(parents=True, exist_ok=True)
            manifest_path = data_root / "extension.json"
            manifest_path.write_text(json.dumps({
                "id": "users",
                "name": "Users",
                "version": "0.1.0",
                "backend": {
                    "entry": "bias_ext_users.backend.ext",
                },
            }, ensure_ascii=False), encoding="utf-8")

            distribution = SimpleNamespace(
                files=["bias_ext_users-0.1.0.data/data/bias_extensions/users/extension.json"],
                metadata={"Name": "bias-ext-users"},
                version="0.1.0",
                locate_file=lambda file: temp_dir / str(file),
            )
            sys.path.insert(0, str(temp_dir))
            for key in list(sys.modules):
                if key == module_name or key.startswith(f"{module_name}."):
                    sys.modules.pop(key, None)
            manifest_module._distribution_manifest_cache = None
            try:
                with patch("bias_core.extensions.manifest.metadata.distributions", return_value=[distribution]):
                    manifests = manifest_module.ExtensionManifestLoader(
                        temp_dir / "empty",
                        include_workspace=False,
                        include_distributions=True,
                    ).discover_manifests()
            finally:
                manifest_module._distribution_manifest_cache = None

            self.assertEqual(len(manifests), 1)
            inspection = inspect_backend_entry(manifests[0], extensions_base_path=temp_dir / "empty")

            self.assertEqual(inspection["entry_type"], "python-package")
            self.assertTrue(inspection["exists"], inspection)
            self.assertEqual(inspection["resolved_path"], "bias_ext_users.backend.ext")
            self.assertIn("extend", inspection["available_hooks"])
            self.assertIn("run_rebuild_cache", inspection["available_hooks"])
        finally:
            sys.path[:] = original_path
            for key in list(sys.modules):
                if key == module_name or key.startswith(f"{module_name}."):
                    sys.modules.pop(key, None)
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_reports_dependency_cycles_in_json(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            alpha_dir = extensions_dir / "alpha-tools"
            beta_dir = extensions_dir / "beta-tools"
            alpha_dir.mkdir(parents=True, exist_ok=False)
            beta_dir.mkdir(parents=True, exist_ok=False)
            (alpha_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["beta-tools"],
            }, ensure_ascii=False), encoding="utf-8")
            (beta_dir / "extension.json").write_text(json.dumps({
                "id": "beta-tools",
                "name": "Beta Tools",
                "version": "1.0.0",
                "optional_dependencies": ["alpha-tools"],
            }, ensure_ascii=False), encoding="utf-8")

            output = StringIO()
            with self.assertRaisesMessage(CommandError, "扩展校验失败"):
                call_command(
                    "validate_extensions",
                    "--extensions-path",
                    str(extensions_dir),
                    "--format",
                    "json",
                    stdout=output,
                    stderr=StringIO(),
                )

            payload = json.loads(output.getvalue())
            self.assertFalse(payload["summary"]["ok"])
            self.assertTrue(any(item["code"] == "dependency_cycle" for item in payload["issues"]))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extensions_command_reports_missing_extension(self):
        with self.assertRaisesMessage(CommandError, "扩展不存在: missing-extension"):
            call_command("inspect_extensions", "--extension-id", "missing-extension")

    def test_validate_extensions_command_discovers_split_workspace_extensions(self):
        temp_dir = make_workspace_temp_dir()
        try:
            workspace_root = Path(temp_dir)
            extensions_dir = workspace_root / "extensions"
            manifest_dir = workspace_root / "bias-ext-alpha"
            extensions_dir.mkdir(parents=True, exist_ok=False)
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha",
                "name": "Alpha",
                "version": "1.0.0",
            }, ensure_ascii=False), encoding="utf-8")

            stdout = StringIO()
            call_command(
                "validate_extensions",
                "--extensions-path",
                str(extensions_dir),
                "--format",
                "json",
                "--require-extensions",
                stdout=stdout,
            )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertEqual(payload["summary"]["manifest_count"], 1)
            self.assertEqual(payload["manifests"][0]["id"], "alpha")
            self.assertEqual(payload["manifests"][0]["path"], str(manifest_dir))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_can_fail_when_no_extensions_are_discovered(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            extensions_dir.mkdir(parents=True, exist_ok=False)
            stdout = StringIO()

            with self.assertRaisesMessage(CommandError, "扩展校验未发现任何扩展"):
                call_command(
                    "validate_extensions",
                    "--extensions-path",
                    str(extensions_dir),
                    "--format",
                    "json",
                    "--require-extensions",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["summary"]["ok"])
            self.assertEqual(payload["summary"]["manifest_count"], 0)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prepare_release_requires_extension_validation_to_discover_extensions(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            (base_dir / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            frontend_dir = base_dir / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=False)
            (frontend_dir / "package.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
            (frontend_dir / "package-lock.json").write_text(json.dumps({
                "version": "1.2.3",
                "packages": {"": {"version": "1.2.3"}},
            }), encoding="utf-8")
            calls = []

            def fake_call_command(name, *args, **kwargs):
                calls.append((name, args))
                if name == "inspect_extensions":
                    kwargs["stdout"].write(json.dumps({
                        "summary": {
                            "blocking_count": 0,
                            "warning_count": 0,
                            "attention_count": 0,
                            "asset_count": 0,
                            "frontend_bundle_count": 0,
                            "migration_bundle_count": 0,
                            "locale_bundle_count": 0,
                            "signed_extension_count": 0,
                        },
                        "extensions": [
                            {
                                "id": "alpha",
                                "contract_snapshot": build_minimal_contract_snapshot("alpha"),
                            },
                        ],
                    }))
                return None

            with override_settings(BASE_DIR=base_dir, BIAS_FRONTEND_DIR=frontend_dir):
                with patch("bias_core.management.commands.prepare_release.run_git_command") as git_mock:
                    git_mock.return_value = SimpleNamespace(stdout="")
                    with patch("bias_core.management.commands.prepare_release.call_command", side_effect=fake_call_command):
                        call_command_quietly(
                            "prepare_release",
                            "--skip-frontend-platform-check",
                            "--set-version",
                            "1.2.3",
                            "--dry-run",
                        )

            validate_call = next((args for name, args in calls if name == "validate_extensions"), None)
            sync_call = next((args for name, args in calls if name == "sync_extension_package_metadata"), None)
            import_call = next((args for name, args in calls if name == "inspect_extension_imports"), None)
            package_call = next((args for name, args in calls if name == "inspect_extension_packages"), None)
            self.assertIsNotNone(sync_call)
            self.assertIn("--extensions-path", sync_call)
            self.assertIsNotNone(import_call)
            self.assertNotIn("--internal", import_call)
            self.assertIn("--require-extensions", import_call)
            self.assertIn("--extensions-path", import_call)
            self.assertIsNotNone(package_call)
            self.assertIn("--install-set-smoke", package_call)
            self.assertIn("--migration-smoke", package_call)
            self.assertIsNotNone(validate_call)
            self.assertIn("--strict", validate_call)
            self.assertIn("--internal", validate_call)
            self.assertIn("--require-extensions", validate_call)
            self.assertIn("--extensions-path", validate_call)
            self.assertTrue(any(name == "inspect_extensions" for name, _args in calls))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prepare_release_validates_extensions_from_configured_workspace_root(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir) / "bias_core"
            workspace_root = Path(temp_dir)
            base_dir.mkdir(parents=True, exist_ok=False)
            (base_dir / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            frontend_dir = base_dir / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=False)
            (frontend_dir / "package.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
            (frontend_dir / "package-lock.json").write_text(json.dumps({
                "version": "1.2.3",
                "packages": {"": {"version": "1.2.3"}},
            }), encoding="utf-8")
            calls = []

            def fake_call_command(name, *args, **kwargs):
                calls.append((name, args))
                if name == "inspect_extensions":
                    kwargs["stdout"].write(json.dumps({
                        "summary": {
                            "blocking_count": 0,
                            "warning_count": 0,
                            "attention_count": 0,
                            "asset_count": 0,
                            "frontend_bundle_count": 0,
                            "migration_bundle_count": 0,
                            "locale_bundle_count": 0,
                            "signed_extension_count": 0,
                        },
                        "extensions": [
                            {
                                "id": "alpha",
                                "contract_snapshot": build_minimal_contract_snapshot("alpha"),
                            },
                        ],
                    }))
                return None

            with override_settings(BASE_DIR=base_dir, BIAS_EXTENSION_WORKSPACE_ROOT=workspace_root, BIAS_FRONTEND_DIR=frontend_dir):
                with patch("bias_core.management.commands.prepare_release.run_git_command") as git_mock:
                    git_mock.return_value = SimpleNamespace(stdout="")
                    with patch("bias_core.management.commands.prepare_release.call_command", side_effect=fake_call_command):
                        call_command_quietly(
                            "prepare_release",
                            "--skip-frontend-platform-check",
                            "--set-version",
                            "1.2.3",
                            "--dry-run",
                        )

            validate_call = next(args for name, args in calls if name == "validate_extensions")
            sync_call = next(args for name, args in calls if name == "sync_extension_package_metadata")
            import_call = next(args for name, args in calls if name == "inspect_extension_imports")
            sync_extensions_path = sync_call[sync_call.index("--extensions-path") + 1]
            import_extensions_path = import_call[import_call.index("--extensions-path") + 1]
            extensions_path = validate_call[validate_call.index("--extensions-path") + 1]
            self.assertEqual(sync_extensions_path, str(workspace_root / "extensions"))
            self.assertEqual(import_extensions_path, str(workspace_root / "extensions"))
            self.assertEqual(extensions_path, str(workspace_root / "extensions"))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prepare_release_stops_when_extension_package_metadata_drift_is_found(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            (base_dir / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            frontend_dir = base_dir / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=False)
            (frontend_dir / "package.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
            (frontend_dir / "package-lock.json").write_text(json.dumps({
                "version": "1.2.3",
                "packages": {"": {"version": "1.2.3"}},
            }), encoding="utf-8")

            def fake_call_command(name, *args, **kwargs):
                if name == "sync_extension_package_metadata":
                    raise CommandError("扩展包元数据存在漂移")
                if name in {"validate_extensions", "inspect_extensions"}:
                    self.fail("prepare_release should stop before extension validation when package metadata drifts")
                return None

            with override_settings(BASE_DIR=base_dir, BIAS_FRONTEND_DIR=frontend_dir):
                with patch("bias_core.management.commands.prepare_release.run_git_command") as git_mock:
                    git_mock.return_value = SimpleNamespace(stdout="")
                    with patch("bias_core.management.commands.prepare_release.call_command", side_effect=fake_call_command):
                        with self.assertRaisesMessage(CommandError, "扩展包元数据存在漂移"):
                            call_command_quietly(
                                "prepare_release",
                                "--skip-frontend-platform-check",
                                "--set-version",
                                "1.2.3",
                                "--dry-run",
                            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prepare_release_stops_when_extension_import_boundary_fails(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            (base_dir / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            frontend_dir = base_dir / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=False)
            (frontend_dir / "package.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
            (frontend_dir / "package-lock.json").write_text(json.dumps({
                "version": "1.2.3",
                "packages": {"": {"version": "1.2.3"}},
            }), encoding="utf-8")

            def fake_call_command(name, *args, **kwargs):
                if name == "inspect_extension_imports":
                    raise CommandError("扩展 import 边界审计失败")
                if name in {"validate_extensions", "inspect_extensions"}:
                    self.fail("prepare_release should stop before extension validation when import boundary fails")
                return None

            with override_settings(BASE_DIR=base_dir, BIAS_FRONTEND_DIR=frontend_dir):
                with patch("bias_core.management.commands.prepare_release.run_git_command") as git_mock:
                    git_mock.return_value = SimpleNamespace(stdout="")
                    with patch("bias_core.management.commands.prepare_release.call_command", side_effect=fake_call_command):
                        with self.assertRaisesMessage(CommandError, "扩展 import 边界审计失败"):
                            call_command_quietly(
                                "prepare_release",
                                "--skip-frontend-platform-check",
                                "--set-version",
                                "1.2.3",
                                "--dry-run",
                            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prepare_release_accepts_contract_baseline_when_current_snapshot_is_compatible(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            (base_dir / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            frontend_dir = base_dir / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=False)
            (frontend_dir / "package.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
            (frontend_dir / "package-lock.json").write_text(json.dumps({
                "version": "1.2.3",
                "packages": {"": {"version": "1.2.3"}},
            }), encoding="utf-8")
            baseline_snapshot = build_minimal_contract_snapshot("alpha")
            baseline_snapshot["resources"] = {
                "definitions": [{"resource": "discussion", "module_id": "alpha"}],
            }
            current_snapshot = build_minimal_contract_snapshot("alpha")
            current_snapshot["resources"] = {
                "definitions": [
                    {"resource": "discussion", "module_id": "alpha"},
                    {"resource": "post", "module_id": "alpha"},
                ],
            }
            baseline_path = base_dir / "extension-contract-baseline.json"
            baseline_path.write_text(json.dumps({
                "extensions": [{
                    "id": "alpha",
                    "contract_snapshot": baseline_snapshot,
                }],
            }, ensure_ascii=False), encoding="utf-8")

            def fake_call_command(name, *args, **kwargs):
                if name == "inspect_extensions":
                    kwargs["stdout"].write(json.dumps({
                        "summary": {
                            "blocking_count": 0,
                            "warning_count": 0,
                            "attention_count": 0,
                            "asset_count": 0,
                            "frontend_bundle_count": 0,
                            "migration_bundle_count": 0,
                            "locale_bundle_count": 0,
                            "signed_extension_count": 0,
                        },
                        "extensions": [
                            {
                                "id": "alpha",
                                "contract_snapshot": current_snapshot,
                            },
                        ],
                    }))
                return None

            with override_settings(BASE_DIR=base_dir, BIAS_FRONTEND_DIR=frontend_dir):
                with patch("bias_core.management.commands.prepare_release.run_git_command") as git_mock:
                    git_mock.return_value = SimpleNamespace(stdout="")
                    with patch("bias_core.management.commands.prepare_release.call_command", side_effect=fake_call_command):
                        call_command_quietly(
                            "prepare_release",
                            "--skip-frontend-platform-check",
                            "--set-version",
                            "1.2.3",
                            "--dry-run",
                            "--contract-baseline",
                            str(baseline_path),
                        )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prepare_release_blocks_pending_extension_migration_summary(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            (base_dir / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            frontend_dir = base_dir / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=False)
            (frontend_dir / "package.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
            (frontend_dir / "package-lock.json").write_text(json.dumps({
                "version": "1.2.3",
                "packages": {"": {"version": "1.2.3"}},
            }), encoding="utf-8")

            def fake_call_command(name, *args, **kwargs):
                if name == "inspect_extensions":
                    kwargs["stdout"].write(json.dumps({
                        "summary": {
                            "blocking_count": 0,
                            "warning_count": 1,
                            "attention_count": 1,
                            "asset_count": 1,
                            "frontend_bundle_count": 0,
                            "migration_bundle_count": 1,
                            "locale_bundle_count": 0,
                            "signed_extension_count": 0,
                        },
                        "extensions": [
                            {
                                "id": "alpha",
                                "contract_snapshot": build_minimal_contract_snapshot("alpha"),
                                "migration_plan": {
                                    "pending_files": ["0001_bootstrap.py", "0002_extra.py"],
                                },
                            },
                        ],
                    }))
                return None

            with override_settings(BASE_DIR=base_dir, BIAS_FRONTEND_DIR=frontend_dir):
                with patch("bias_core.management.commands.prepare_release.run_git_command") as git_mock:
                    git_mock.return_value = SimpleNamespace(stdout="")
                    with patch("bias_core.management.commands.prepare_release.call_command", side_effect=fake_call_command):
                        with self.assertRaisesMessage(CommandError, "扩展迁移摘要未同步: alpha(2)"):
                            call_command_quietly(
                                "prepare_release",
                                "--skip-frontend-platform-check",
                                "--set-version",
                                "1.2.3",
                                "--dry-run",
                            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prepare_release_allows_pending_extension_migration_summary_when_explicit(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            (base_dir / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            frontend_dir = base_dir / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=False)
            (frontend_dir / "package.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
            (frontend_dir / "package-lock.json").write_text(json.dumps({
                "version": "1.2.3",
                "packages": {"": {"version": "1.2.3"}},
            }), encoding="utf-8")

            def fake_call_command(name, *args, **kwargs):
                if name == "inspect_extensions":
                    kwargs["stdout"].write(json.dumps({
                        "summary": {
                            "blocking_count": 0,
                            "warning_count": 1,
                            "attention_count": 1,
                            "asset_count": 1,
                            "frontend_bundle_count": 0,
                            "migration_bundle_count": 1,
                            "locale_bundle_count": 0,
                            "signed_extension_count": 0,
                        },
                        "extensions": [
                            {
                                "id": "alpha",
                                "contract_snapshot": build_minimal_contract_snapshot("alpha"),
                                "migration_plan": {
                                    "pending_files": ["0001_bootstrap.py"],
                                },
                            },
                        ],
                    }))
                return None

            with override_settings(BASE_DIR=base_dir, BIAS_FRONTEND_DIR=frontend_dir):
                with patch("bias_core.management.commands.prepare_release.run_git_command") as git_mock:
                    git_mock.return_value = SimpleNamespace(stdout="")
                    with patch("bias_core.management.commands.prepare_release.call_command", side_effect=fake_call_command):
                        call_command_quietly(
                            "prepare_release",
                            "--skip-frontend-platform-check",
                            "--set-version",
                            "1.2.3",
                            "--dry-run",
                            "--allow-extension-attention",
                        )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prepare_release_uses_default_contract_baseline_when_available(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            (base_dir / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            frontend_dir = base_dir / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=False)
            (frontend_dir / "package.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
            (frontend_dir / "package-lock.json").write_text(json.dumps({
                "version": "1.2.3",
                "packages": {"": {"version": "1.2.3"}},
            }), encoding="utf-8")
            baseline_snapshot = build_minimal_contract_snapshot("alpha")
            baseline_snapshot["frontend"] = {
                "routes": [{"frontend": "forum", "name": "alpha", "path": "/alpha", "component": "./Alpha.vue"}],
            }
            current_snapshot = build_minimal_contract_snapshot("alpha")
            current_snapshot["frontend"] = {"routes": []}
            (base_dir / "extension-contract-baseline.json").write_text(json.dumps({
                "contract_snapshots": {
                    "alpha": baseline_snapshot,
                },
            }, ensure_ascii=False), encoding="utf-8")

            def fake_call_command(name, *args, **kwargs):
                if name == "inspect_extensions":
                    kwargs["stdout"].write(json.dumps({
                        "summary": {
                            "blocking_count": 0,
                            "warning_count": 0,
                            "attention_count": 0,
                            "asset_count": 0,
                            "frontend_bundle_count": 0,
                            "migration_bundle_count": 0,
                            "locale_bundle_count": 0,
                            "signed_extension_count": 0,
                        },
                        "extensions": [
                            {
                                "id": "alpha",
                                "contract_snapshot": current_snapshot,
                            },
                        ],
                    }))
                return None

            with override_settings(BASE_DIR=base_dir, BIAS_FRONTEND_DIR=frontend_dir):
                with patch("bias_core.management.commands.prepare_release.run_git_command") as git_mock:
                    git_mock.return_value = SimpleNamespace(stdout="")
                    with patch("bias_core.management.commands.prepare_release.call_command", side_effect=fake_call_command):
                        with self.assertRaisesMessage(CommandError, "contract_snapshot.frontend.routes 移除 forum|alpha"):
                            call_command_quietly(
                                "prepare_release",
                                "--skip-frontend-platform-check",
                                "--set-version",
                                "1.2.3",
                                "--dry-run",
                            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prepare_release_skips_default_contract_baseline_when_file_is_absent(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            (base_dir / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            frontend_dir = base_dir / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=False)
            (frontend_dir / "package.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
            (frontend_dir / "package-lock.json").write_text(json.dumps({
                "version": "1.2.3",
                "packages": {"": {"version": "1.2.3"}},
            }), encoding="utf-8")

            def fake_call_command(name, *args, **kwargs):
                if name == "inspect_extensions":
                    kwargs["stdout"].write(json.dumps({
                        "summary": {
                            "blocking_count": 0,
                            "warning_count": 0,
                            "attention_count": 0,
                            "asset_count": 0,
                            "frontend_bundle_count": 0,
                            "migration_bundle_count": 0,
                            "locale_bundle_count": 0,
                            "signed_extension_count": 0,
                        },
                        "extensions": [
                            {
                                "id": "alpha",
                                "contract_snapshot": build_minimal_contract_snapshot("alpha"),
                            },
                        ],
                    }))
                return None

            with override_settings(BASE_DIR=base_dir, BIAS_FRONTEND_DIR=frontend_dir):
                with patch("bias_core.management.commands.prepare_release.run_git_command") as git_mock:
                    git_mock.return_value = SimpleNamespace(stdout="")
                    with patch("bias_core.management.commands.prepare_release.call_command", side_effect=fake_call_command):
                        call_command_quietly(
                            "prepare_release",
                            "--skip-frontend-platform-check",
                            "--set-version",
                            "1.2.3",
                            "--dry-run",
                        )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prepare_release_dry_run_checks_target_version_without_writing_files(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            (base_dir / "VERSION").write_text("1.2.2\n", encoding="utf-8")
            frontend_dir = base_dir / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=False)
            (frontend_dir / "package.json").write_text(json.dumps({"version": "1.2.1"}), encoding="utf-8")
            (frontend_dir / "package-lock.json").write_text(json.dumps({
                "version": "1.2.1",
                "packages": {"": {"version": "1.2.1"}},
            }), encoding="utf-8")

            def fake_call_command(name, *args, **kwargs):
                if name == "inspect_extensions":
                    kwargs["stdout"].write(json.dumps({
                        "summary": {
                            "blocking_count": 0,
                            "warning_count": 0,
                            "attention_count": 0,
                            "asset_count": 0,
                            "frontend_bundle_count": 0,
                            "migration_bundle_count": 0,
                            "locale_bundle_count": 0,
                            "signed_extension_count": 0,
                        },
                        "extensions": [
                            {
                                "id": "alpha",
                                "contract_snapshot": build_minimal_contract_snapshot("alpha"),
                            },
                        ],
                    }))
                return None

            with override_settings(BASE_DIR=base_dir, BIAS_FRONTEND_DIR=frontend_dir):
                with patch("bias_core.management.commands.prepare_release.run_git_command") as git_mock:
                    git_mock.return_value = SimpleNamespace(stdout="")
                    with patch("bias_core.management.commands.prepare_release.call_command", side_effect=fake_call_command):
                        call_command_quietly(
                            "prepare_release",
                            "--skip-frontend-platform-check",
                            "--set-version",
                            "1.2.3",
                            "--dry-run",
                        )

            self.assertEqual((base_dir / "VERSION").read_text(encoding="utf-8"), "1.2.2\n")
            self.assertEqual(json.loads((frontend_dir / "package.json").read_text(encoding="utf-8"))["version"], "1.2.1")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prepare_release_runs_frontend_platform_check_when_available(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            (base_dir / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            frontend_dir = base_dir / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=False)
            (frontend_dir / "package.json").write_text(json.dumps({
                "version": "1.2.3",
                "scripts": {"check:platform": "node ./scripts/checkPlatform.mjs"},
            }), encoding="utf-8")
            (frontend_dir / "package-lock.json").write_text(json.dumps({
                "version": "1.2.3",
                "packages": {"": {"version": "1.2.3"}},
            }), encoding="utf-8")

            def fake_call_command(name, *args, **kwargs):
                if name == "inspect_extensions":
                    kwargs["stdout"].write(json.dumps({
                        "summary": {
                            "blocking_count": 0,
                            "warning_count": 0,
                            "attention_count": 0,
                            "asset_count": 0,
                            "frontend_bundle_count": 0,
                            "migration_bundle_count": 0,
                            "locale_bundle_count": 0,
                            "signed_extension_count": 0,
                        },
                        "extensions": [
                            {
                                "id": "alpha",
                                "contract_snapshot": build_minimal_contract_snapshot("alpha"),
                            },
                        ],
                    }))
                return None

            with override_settings(BASE_DIR=base_dir, BIAS_FRONTEND_DIR=frontend_dir):
                with patch("bias_core.management.commands.prepare_release.run_git_command") as git_mock:
                    git_mock.return_value = SimpleNamespace(stdout="")
                    with patch("bias_core.management.commands.prepare_release.call_command", side_effect=fake_call_command):
                        with patch("bias_core.management.commands.prepare_release.shutil.which", return_value="npm-bin"):
                            with patch("bias_core.management.commands.prepare_release.subprocess.run") as subprocess_run:
                                call_command_quietly(
                                    "prepare_release",
                                    "--set-version",
                                    "1.2.3",
                                    "--dry-run",
                                )

            subprocess_run.assert_called_once_with(
                ["npm-bin", "run", "check:platform"],
                cwd=str(frontend_dir),
                check=True,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prepare_release_reports_missing_npm_for_frontend_platform_check(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            (base_dir / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            frontend_dir = base_dir / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=False)
            (frontend_dir / "package.json").write_text(json.dumps({
                "version": "1.2.3",
                "scripts": {"check:platform": "node ./scripts/checkPlatform.mjs"},
            }), encoding="utf-8")
            (frontend_dir / "package-lock.json").write_text(json.dumps({
                "version": "1.2.3",
                "packages": {"": {"version": "1.2.3"}},
            }), encoding="utf-8")

            def fake_call_command(name, *args, **kwargs):
                if name == "inspect_extensions":
                    kwargs["stdout"].write(json.dumps({
                        "summary": {
                            "blocking_count": 0,
                            "warning_count": 0,
                            "attention_count": 0,
                            "asset_count": 0,
                            "frontend_bundle_count": 0,
                            "migration_bundle_count": 0,
                            "locale_bundle_count": 0,
                            "signed_extension_count": 0,
                        },
                        "extensions": [
                            {
                                "id": "alpha",
                                "contract_snapshot": build_minimal_contract_snapshot("alpha"),
                            },
                        ],
                    }))
                return None

            with override_settings(BASE_DIR=base_dir, BIAS_FRONTEND_DIR=frontend_dir):
                with patch("bias_core.management.commands.prepare_release.run_git_command") as git_mock:
                    git_mock.return_value = SimpleNamespace(stdout="")
                    with patch("bias_core.management.commands.prepare_release.call_command", side_effect=fake_call_command):
                        with patch("bias_core.management.commands.prepare_release.shutil.which", return_value=None):
                            with self.assertRaisesMessage(CommandError, "无法执行前端平台检查：未找到 npm"):
                                call_command_quietly(
                                    "prepare_release",
                                    "--set-version",
                                    "1.2.3",
                                    "--dry-run",
                                )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prepare_release_stops_when_contract_baseline_loses_public_resource(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            (base_dir / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            frontend_dir = base_dir / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=False)
            (frontend_dir / "package.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
            (frontend_dir / "package-lock.json").write_text(json.dumps({
                "version": "1.2.3",
                "packages": {"": {"version": "1.2.3"}},
            }), encoding="utf-8")
            baseline_snapshot = build_minimal_contract_snapshot("alpha")
            baseline_snapshot["resources"] = {
                "definitions": [{"resource": "discussion", "module_id": "alpha"}],
            }
            current_snapshot = build_minimal_contract_snapshot("alpha")
            current_snapshot["resources"] = {"definitions": []}
            baseline_path = base_dir / "extension-contract-baseline.json"
            baseline_path.write_text(json.dumps({
                "contract_snapshots": {
                    "alpha": baseline_snapshot,
                },
            }, ensure_ascii=False), encoding="utf-8")

            def fake_call_command(name, *args, **kwargs):
                if name == "inspect_extensions":
                    kwargs["stdout"].write(json.dumps({
                        "summary": {
                            "blocking_count": 0,
                            "warning_count": 0,
                            "attention_count": 0,
                            "asset_count": 0,
                            "frontend_bundle_count": 0,
                            "migration_bundle_count": 0,
                            "locale_bundle_count": 0,
                            "signed_extension_count": 0,
                        },
                        "extensions": [
                            {
                                "id": "alpha",
                                "contract_snapshot": current_snapshot,
                            },
                        ],
                    }))
                return None

            with override_settings(BASE_DIR=base_dir, BIAS_FRONTEND_DIR=frontend_dir):
                with patch("bias_core.management.commands.prepare_release.run_git_command") as git_mock:
                    git_mock.return_value = SimpleNamespace(stdout="")
                    with patch("bias_core.management.commands.prepare_release.call_command", side_effect=fake_call_command):
                        with self.assertRaisesMessage(CommandError, "contract_snapshot.resources.definitions 移除 discussion"):
                            call_command_quietly(
                                "prepare_release",
                                "--skip-frontend-platform-check",
                                "--set-version",
                                "1.2.3",
                                "--dry-run",
                                "--contract-baseline",
                                str(baseline_path),
                            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prepare_release_stops_when_contract_snapshot_is_missing(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            (base_dir / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            frontend_dir = base_dir / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=False)
            (frontend_dir / "package.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
            (frontend_dir / "package-lock.json").write_text(json.dumps({
                "version": "1.2.3",
                "packages": {"": {"version": "1.2.3"}},
            }), encoding="utf-8")

            def fake_call_command(name, *args, **kwargs):
                if name == "inspect_extensions":
                    kwargs["stdout"].write(json.dumps({
                        "summary": {
                            "blocking_count": 0,
                            "warning_count": 0,
                            "attention_count": 0,
                            "asset_count": 0,
                            "frontend_bundle_count": 0,
                            "migration_bundle_count": 0,
                            "locale_bundle_count": 0,
                            "signed_extension_count": 0,
                        },
                        "extensions": [{"id": "alpha"}],
                    }))
                return None

            with override_settings(BASE_DIR=base_dir, BIAS_FRONTEND_DIR=frontend_dir):
                with patch("bias_core.management.commands.prepare_release.run_git_command") as git_mock:
                    git_mock.return_value = SimpleNamespace(stdout="")
                    with patch("bias_core.management.commands.prepare_release.call_command", side_effect=fake_call_command):
                        with self.assertRaisesMessage(CommandError, "扩展契约快照不完整"):
                            call_command_quietly(
                                "prepare_release",
                                "--skip-frontend-platform-check",
                                "--set-version",
                                "1.2.3",
                                "--dry-run",
                            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prepare_release_stops_when_extension_validation_finds_no_extensions(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            (base_dir / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            frontend_dir = base_dir / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=False)
            (frontend_dir / "package.json").write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
            (frontend_dir / "package-lock.json").write_text(json.dumps({
                "version": "1.2.3",
                "packages": {"": {"version": "1.2.3"}},
            }), encoding="utf-8")

            def fake_call_command(name, *args, **kwargs):
                if name == "validate_extensions":
                    raise CommandError("扩展校验未发现任何扩展")
                if name == "inspect_extensions":
                    self.fail("prepare_release should not inspect extensions after validation failure")
                return None

            with override_settings(BASE_DIR=base_dir, BIAS_FRONTEND_DIR=frontend_dir):
                with patch("bias_core.management.commands.prepare_release.run_git_command") as git_mock:
                    git_mock.return_value = SimpleNamespace(stdout="")
                    with patch("bias_core.management.commands.prepare_release.call_command", side_effect=fake_call_command):
                        with self.assertRaisesMessage(CommandError, "扩展校验未发现任何扩展"):
                            call_command_quietly(
                                "prepare_release",
                                "--skip-frontend-platform-check",
                                "--set-version",
                                "1.2.3",
                                "--dry-run",
                            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prepare_release_reports_missing_frontend_version_file(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            (base_dir / "VERSION").write_text("1.2.3\n", encoding="utf-8")
            (base_dir / "frontend").mkdir(parents=True, exist_ok=False)

            def fake_call_command(name, *args, **kwargs):
                if name == "inspect_extensions":
                    kwargs["stdout"].write(json.dumps({
                        "summary": {
                            "blocking_count": 0,
                            "warning_count": 0,
                            "attention_count": 0,
                            "asset_count": 0,
                            "frontend_bundle_count": 0,
                            "migration_bundle_count": 0,
                            "locale_bundle_count": 0,
                            "signed_extension_count": 0,
                        },
                        "extensions": [
                            {
                                "id": "alpha",
                                "contract_snapshot": build_minimal_contract_snapshot("alpha"),
                            },
                        ],
                    }))
                return None

            with override_settings(BASE_DIR=base_dir, BIAS_FRONTEND_DIR=base_dir / "frontend"):
                with patch("bias_core.management.commands.prepare_release.run_git_command") as git_mock:
                    git_mock.return_value = SimpleNamespace(stdout="")
                    with patch("bias_core.management.commands.prepare_release.call_command", side_effect=fake_call_command):
                        with self.assertRaisesMessage(CommandError, "前端版本文件不存在"):
                            call_command_quietly(
                                "prepare_release",
                                "--skip-frontend-platform-check",
                                "--set-version",
                                "1.2.3",
                                "--dry-run",
                            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_publish_release_forwards_contract_baseline_and_uses_configured_frontend_dir(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir) / "bias_core"
            frontend_dir = Path(temp_dir) / "bias" / "frontend"
            base_dir.mkdir(parents=True, exist_ok=False)
            frontend_dir.mkdir(parents=True, exist_ok=False)
            calls = []
            git_commands = []

            def fake_call_command(name, *args, **kwargs):
                calls.append((name, args))
                return None

            def fake_run_git_command(base, *args, **kwargs):
                git_commands.append((base, args))
                return SimpleNamespace(stdout="")

            with override_settings(BASE_DIR=base_dir, BIAS_FRONTEND_DIR=frontend_dir):
                with patch("bias_core.management.commands.publish_release.call_command", side_effect=fake_call_command):
                    with patch("bias_core.management.commands.publish_release.run_git_command", side_effect=fake_run_git_command):
                        call_command_quietly(
                            "publish_release",
                            "--set-version",
                            "1.2.3",
                            "--contract-baseline",
                            "extension-contract-baseline.json",
                            "--skip-frontend-platform-check",
                            "--commit-message",
                            "release",
                        )

            prepare_args = next(args for name, args in calls if name == "prepare_release")
            self.assertIn("--contract-baseline", prepare_args)
            self.assertEqual(
                prepare_args[prepare_args.index("--contract-baseline") + 1],
                "extension-contract-baseline.json",
            )
            self.assertIn("--skip-frontend-platform-check", prepare_args)
            git_add_args = next(args for _base, args in git_commands if args and args[0] == "add")
            self.assertIn(str(frontend_dir / "package.json"), git_add_args)
            self.assertIn(str(frontend_dir / "package-lock.json"), git_add_args)
            self.assertIn(("finalize_release", ("--tag", "v1.2.3")), calls)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
