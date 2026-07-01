from tests.common import *

class ExtensionServiceTests(TestCase):
    def setUp(self):
        self.extension_base_dir = make_extension_test_base_dir()
        self.settings_override = override_settings(BASE_DIR=self.extension_base_dir)
        self.settings_override.enable()
        reset_extension_runtime_state()
        self.addCleanup(self._cleanup_extension_base_dir)

    def _cleanup_extension_base_dir(self):
        reset_extension_runtime_state()
        self.settings_override.disable()
        reset_extension_runtime_state()
        shutil.rmtree(self.extension_base_dir, ignore_errors=True)

    def _record_alpha_tools_django_migration(self):
        from bias_core.extensions.migrations import clear_applied_migration_cache

        MigrationRecorder(connection).record_applied("alpha_tools", "0001_bootstrap")
        clear_applied_migration_cache()

    def _create_beta_tools_dependency_fixture(self):
        beta_dir = self.extension_base_dir / "extensions" / "beta-tools"
        beta_dir.mkdir(parents=True, exist_ok=True)
        (beta_dir / "extension.json").write_text(json.dumps({
            "id": "beta-tools",
            "name": "Beta Tools",
            "version": "0.1.0",
            "dependencies": ["core"],
            "description": "Dependency fixture for lifecycle tests.",
            "extra": {"product_hidden": True},
        }, ensure_ascii=False), encoding="utf-8")
        manifest_path = self.extension_base_dir / "extensions" / "alpha-tools" / "extension.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["dependencies"] = ["core", "beta-tools"]
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        ExtensionInstallation.objects.update_or_create(
            extension_id="beta-tools",
            defaults={
                "version": "0.1.0",
                "source": "filesystem",
                "enabled": False,
                "installed": True,
                "booted": False,
            },
        )
        reset_extension_runtime_state()

    def test_install_and_uninstall_transition_filesystem_extension(self):
        installed = ExtensionService.install_extension("alpha-tools")
        self.assertTrue(installed.runtime.installed)
        self.assertTrue(installed.runtime.enabled)
        self.assertEqual(installed.runtime.backend_hooks["run_install"]["status"], "ok")
        self.assertEqual(installed.runtime.backend_hooks["run_migrations"]["status"], "ok")
        self.assertEqual(installed.runtime.migration_state, "applied")
        self.assertEqual(installed.runtime.migration_label, "最近已执行")
        self.assertEqual(installed.runtime.migration_execution["state"], "applied")
        self.assertIn("0001_bootstrap.py", installed.runtime.migration_execution["details"]["migration_files"])
        self.assertIn("0001_bootstrap", installed.runtime.migration_execution["details"]["applied_steps"])
        installation = ExtensionInstallation.objects.get(extension_id="alpha-tools")
        self.assertIn("0001_bootstrap.py", installation.meta["applied_migration_files"])

        disabled = ExtensionService.set_extension_enabled("alpha-tools", False)
        self.assertFalse(disabled.runtime.enabled)
        self.assertEqual(disabled.runtime.backend_hooks["run_disable"]["status"], "ok")

        enabled = ExtensionService.set_extension_enabled("alpha-tools", True)
        self.assertTrue(enabled.runtime.enabled)
        self.assertEqual(enabled.runtime.backend_hooks["run_enable"]["status"], "ok")

        uninstalled = ExtensionService.uninstall_extension("alpha-tools")
        self.assertFalse(uninstalled.runtime.installed)
        self.assertFalse(uninstalled.runtime.enabled)
        self.assertEqual(uninstalled.runtime.backend_hooks["run_disable"]["status"], "ok")
        self.assertEqual(uninstalled.runtime.backend_hooks["run_uninstall"]["status"], "ok")
        installation = ExtensionInstallation.objects.get(extension_id="alpha-tools")
        self.assertEqual(installation.meta["applied_migration_files"], [])

    def test_run_extension_backend_hook_skips_when_hook_missing(self):
        registry = ExtensionRegistry(extensions_path=Path(settings.BASE_DIR) / "extensions")
        definition = registry.get_extension("alpha-tools")

        result = run_extension_backend_hook(definition, "run_reconcile")

        self.assertEqual(result["status"], "skipped")
        self.assertIn("run_reconcile", result["message"])

    def test_runtime_hook_executes_declared_extension_operation(self):
        installed = ExtensionService.install_extension("alpha-tools")
        self.assertTrue(installed.runtime.enabled)

        updated = ExtensionService.run_extension_runtime_hook("alpha-tools", "run_rebuild_cache")

        self.assertEqual(updated.runtime.backend_hooks["run_rebuild_cache"]["status"], "ok")

    def test_run_extension_migrations_executes_declared_migration_hook(self):
        installed = ExtensionService.install_extension("alpha-tools")
        self.assertTrue(installed.runtime.installed)

        updated = ExtensionService.run_extension_migrations("alpha-tools")

        self.assertEqual(updated.runtime.backend_hooks["run_migrations"]["status"], "ok")
        self.assertEqual(updated.runtime.migration_state, "applied")
        self.assertEqual(updated.runtime.migration_label, "最近已执行")
        self.assertEqual(updated.runtime.migration_execution["status"], "ok")
        self.assertEqual(updated.runtime.migration_execution["details"]["migration_files"], [])
        self.assertIn("0001_bootstrap.py", updated.runtime.migration_execution["details"]["skipped_migration_files"])

    def test_run_extension_migrations_refreshes_auto_installed_extension(self):
        updated = ExtensionService.run_extension_migrations("users")

        self.assertEqual(updated.id, "users")
        self.assertEqual(updated.runtime.backend_hooks["run_migrations"]["status"], "ok")
        self.assertEqual(updated.runtime.migration_state, "applied")

    def test_runtime_reset_keeps_full_extension_catalog_on_reload(self):
        from bias_core.extensions.manager import get_extension_manager

        manager = get_extension_manager()
        manager.load(force=True)
        before_ids = {extension.id for extension in manager.get_extensions()}

        reset_extension_runtime_state()
        manager = get_extension_manager()
        manager.load(force=True)
        after_ids = {extension.id for extension in manager.get_extensions()}

        self.assertIn("approval", before_ids)
        self.assertIn("emoji", after_ids)
        self.assertIn("flags", after_ids)
        self.assertIn("approval", after_ids)

    def test_run_extension_migrations_requires_installation(self):
        with self.assertRaises(ExtensionStateError) as context:
            ExtensionService.run_extension_migrations("alpha-tools")

        self.assertEqual(context.exception.code, "extension_migrations_not_installed")

    def test_migrate_extensions_command_requires_installation(self):
        with self.assertRaisesMessage(CommandError, "尚未安装"):
            call_command("migrate_extensions", "alpha-tools")

    def test_migrate_extensions_command_executes_single_extension(self):
        ExtensionService.install_extension("alpha-tools")
        self._record_alpha_tools_django_migration()

        stdout = StringIO()
        call_command("migrate_extensions", "alpha-tools", "--format", "json", stdout=stdout)
        payload = json.loads(stdout.getvalue())

        self.assertEqual(payload["summary"]["target_count"], 1)
        self.assertEqual(payload["summary"]["error_count"], 0)
        self.assertEqual(payload["extensions"][0]["id"], "alpha-tools")
        self.assertEqual(payload["extensions"][0]["status"], "ok")
        self.assertIn("0001_bootstrap.py", payload["extensions"][0]["details"]["skipped_migration_files"])

    def test_migrate_extensions_command_blocks_when_django_migration_is_unapplied(self):
        ExtensionService.install_extension("alpha-tools")

        with self.assertRaisesMessage(CommandError, "Django 数据库迁移尚未应用"):
            call_command("migrate_extensions", "alpha-tools")

    def test_migrate_extensions_command_dry_run_all_does_not_persist_state(self):
        self._record_alpha_tools_django_migration()
        installation = ExtensionInstallation.objects.create(
            extension_id="alpha-tools",
            version="0.1.0",
            source="filesystem",
            enabled=True,
            installed=True,
            booted=True,
            meta={},
        )

        stdout = StringIO()
        call_command("migrate_extensions", "--all", "--dry-run", "--format", "json", stdout=stdout)
        payload = json.loads(stdout.getvalue())

        self.assertGreaterEqual(payload["summary"]["target_count"], 1)
        sample_extension = next(item for item in payload["extensions"] if item["id"] == "alpha-tools")
        self.assertEqual(sample_extension["status"], "ok")
        self.assertIn("0001_bootstrap.py", sample_extension["django_applied_files"])
        self.assertEqual(sample_extension["django_pending_files"], [])
        installation.refresh_from_db()
        self.assertEqual(installation.meta, {})

    def test_runtime_hook_requires_manifest_declaration(self):
        ExtensionService.install_extension("alpha-tools")

        with self.assertRaises(ExtensionStateError) as context:
            ExtensionService.run_extension_runtime_hook("alpha-tools", "run_unknown")

        self.assertEqual(context.exception.code, "extension_runtime_hook_not_declared")

    def test_enable_ignores_stale_core_installation_dependency_record(self):
        ExtensionService.install_extension("alpha-tools")
        ExtensionInstallation.objects.update_or_create(
            extension_id="core",
            defaults={
                "version": "1.0.0",
                "source": "core-module",
                "enabled": False,
                "installed": True,
                "booted": False,
            },
        )

        enabled = ExtensionService.set_extension_enabled("alpha-tools", True)

        self.assertTrue(enabled.runtime.enabled)

    def test_install_raises_when_required_dependency_is_disabled(self):
        self._create_beta_tools_dependency_fixture()

        with self.assertRaises(ExtensionStateError) as context:
            ExtensionService.install_extension("alpha-tools")

        self.assertEqual(context.exception.code, "extension_install_blocked")
        self.assertEqual(context.exception.details["disabled_dependencies"], ["beta-tools"])
        self.assertFalse(ExtensionInstallation.objects.filter(extension_id="alpha-tools").exists())

    def test_lifecycle_plan_reports_dependency_and_dependent_blockers(self):
        self._create_beta_tools_dependency_fixture()

        plan = ExtensionService.build_extension_lifecycle_plan("alpha-tools")

        self.assertFalse(plan["install"]["can_execute"])
        self.assertEqual(plan["install"]["disabled_dependencies"], ["beta-tools"])
        self.assertIn("disabled_dependencies", plan["install"]["blockers"])
        self.assertFalse(plan["enable"]["dependency_transaction"]["can_execute"])
        self.assertIn("not_installed", plan["enable"]["dependency_transaction"]["blockers"])

        ExtensionInstallation.objects.update_or_create(
            extension_id="alpha-tools",
            defaults={
                "version": "0.1.0",
                "source": "filesystem",
                "enabled": False,
                "installed": True,
                "booted": False,
            },
        )
        reset_extension_runtime_state()
        installed_plan = ExtensionService.build_extension_lifecycle_plan("alpha-tools")
        self.assertTrue(installed_plan["enable"]["dependency_transaction"]["can_execute"])
        self.assertEqual(
            installed_plan["enable"]["dependency_transaction"]["order"],
            ["beta-tools", "alpha-tools"],
        )

        ExtensionInstallation.objects.filter(extension_id="alpha-tools").update(enabled=True, booted=True)
        ExtensionInstallation.objects.filter(extension_id="beta-tools").update(enabled=True, booted=True)
        reset_extension_runtime_state()
        beta_plan = ExtensionService.build_extension_lifecycle_plan("beta-tools")

        self.assertFalse(beta_plan["disable"]["can_execute"])
        self.assertEqual(beta_plan["disable"]["blocking_dependents"], ["alpha-tools"])
        self.assertIn("blocking_dependents", beta_plan["disable"]["blockers"])
        self.assertTrue(beta_plan["disable"]["dependent_transaction"]["can_execute"])
        self.assertEqual(beta_plan["disable"]["dependent_transaction"]["order"], ["alpha-tools", "beta-tools"])
        self.assertFalse(beta_plan["uninstall"]["can_execute"])
        self.assertEqual(beta_plan["uninstall"]["blocking_dependents"], ["alpha-tools"])
        self.assertEqual(beta_plan["uninstall"]["dependent_transaction"]["order"], ["alpha-tools", "beta-tools"])

    def test_runtime_actions_include_lifecycle_transaction_payloads(self):
        self._create_beta_tools_dependency_fixture()
        ExtensionInstallation.objects.update_or_create(
            extension_id="alpha-tools",
            defaults={
                "version": "0.1.0",
                "source": "filesystem",
                "enabled": False,
                "installed": True,
                "booted": False,
            },
        )
        reset_extension_runtime_state()

        alpha = ExtensionService.get_extension("alpha-tools")
        alpha_actions = {action.key: action for action in alpha.runtime.runtime_actions}
        self.assertEqual(alpha_actions["enable-with-dependencies"].action, "enable")
        self.assertEqual(alpha_actions["enable-with-dependencies"].payload, {"include_dependencies": True})

        ExtensionInstallation.objects.filter(extension_id="alpha-tools").update(enabled=True, booted=True)
        ExtensionInstallation.objects.filter(extension_id="beta-tools").update(enabled=True, booted=True)
        reset_extension_runtime_state()
        beta = ExtensionService.get_extension("beta-tools")
        beta_actions = {action.key: action for action in beta.runtime.runtime_actions}
        self.assertEqual(beta_actions["disable-with-dependents"].payload, {"include_dependents": True})

        ExtensionInstallation.objects.filter(extension_id="alpha-tools").update(enabled=False, booted=False)
        ExtensionInstallation.objects.filter(extension_id="beta-tools").update(enabled=False, booted=False)
        reset_extension_runtime_state()
        beta = ExtensionService.get_extension("beta-tools")
        beta_actions = {action.key: action for action in beta.runtime.runtime_actions}
        self.assertEqual(beta_actions["uninstall-with-dependents"].payload, {"include_dependents": True})

    def test_enable_with_dependencies_enables_installed_required_dependencies_first(self):
        self._record_alpha_tools_django_migration()
        self._create_beta_tools_dependency_fixture()
        ExtensionInstallation.objects.update_or_create(
            extension_id="alpha-tools",
            defaults={
                "version": "0.1.0",
                "source": "filesystem",
                "enabled": False,
                "installed": True,
                "booted": False,
            },
        )
        with self.assertRaises(ExtensionStateError) as context:
            ExtensionService.set_extension_enabled("alpha-tools", True)
        self.assertEqual(context.exception.code, "extension_enable_blocked")

        enabled = ExtensionService.set_extension_enabled("alpha-tools", True, include_dependencies=True)

        self.assertTrue(enabled.runtime.enabled)
        beta_installation = ExtensionInstallation.objects.get(extension_id="beta-tools")
        alpha_installation = ExtensionInstallation.objects.get(extension_id="alpha-tools")
        self.assertTrue(beta_installation.enabled)
        self.assertTrue(alpha_installation.enabled)
        self.assertIn("run_enable", beta_installation.meta["backend_hooks"])
        self.assertIn("run_enable", alpha_installation.meta["backend_hooks"])

    def test_enable_with_dependencies_rejects_uninstalled_target_before_enabling_dependencies(self):
        self._record_alpha_tools_django_migration()
        self._create_beta_tools_dependency_fixture()

        with self.assertRaises(ExtensionStateError) as context:
            ExtensionService.set_extension_enabled("alpha-tools", True, include_dependencies=True)

        self.assertEqual(context.exception.code, "extension_enable_not_installed")
        beta_installation = ExtensionInstallation.objects.get(extension_id="beta-tools")
        self.assertFalse(beta_installation.enabled)
        self.assertFalse(beta_installation.booted)

    def test_enable_with_dependencies_rolls_back_when_target_enable_fails(self):
        self._record_alpha_tools_django_migration()
        self._create_beta_tools_dependency_fixture()
        ExtensionInstallation.objects.update_or_create(
            extension_id="alpha-tools",
            defaults={
                "version": "0.1.0",
                "source": "filesystem",
                "enabled": False,
                "installed": True,
                "booted": False,
            },
        )
        backend_path = self.extension_base_dir / "extensions" / "alpha-tools" / "backend" / "ext.py"
        backend_source = backend_path.read_text(encoding="utf-8")
        backend_path.write_text(
            backend_source.replace(
                "def enable(context):\n"
                "    return {'status': 'ok', 'status_label': '已启用'}\n",
                "def enable(context):\n"
                "    return {'status': 'error', 'message': 'enable exploded'}\n",
            ),
            encoding="utf-8",
        )
        reset_extension_runtime_state()

        with self.assertRaises(ExtensionStateError) as context:
            ExtensionService.set_extension_enabled("alpha-tools", True, include_dependencies=True)

        self.assertEqual(context.exception.code, "extension_lifecycle_failed")
        beta_installation = ExtensionInstallation.objects.get(extension_id="beta-tools")
        alpha_installation = ExtensionInstallation.objects.get(extension_id="alpha-tools")
        self.assertFalse(beta_installation.enabled)
        self.assertFalse(beta_installation.booted)
        self.assertFalse(alpha_installation.enabled)
        self.assertFalse(alpha_installation.booted)

    @patch("bias_core.extensions.manager.validate_bias_compatibility")
    def test_manager_enable_validates_bias_compatibility(self, validate_bias_compatibility_mock):
        ExtensionService.install_extension("alpha-tools")
        validate_bias_compatibility_mock.reset_mock()

        from bias_core.extensions.manager import get_extension_manager

        manager = get_extension_manager()
        manager.set_extension_enabled("alpha-tools", False)
        manager.set_extension_enabled("alpha-tools", True)

        checked_extension = validate_bias_compatibility_mock.call_args.kwargs
        self.assertEqual(validate_bias_compatibility_mock.call_args.args[0].id, "alpha-tools")
        self.assertEqual(checked_extension["action"], "enable")

    def test_disable_raises_when_enabled_dependents_exist(self):
        with self.assertRaises(ExtensionStateError) as context:
            ExtensionService.set_extension_enabled("notifications", False)

        self.assertEqual(context.exception.code, "extension_disable_blocked")
        self.assertIn("approval", context.exception.details["blocking_dependents"])

    def test_disable_with_dependents_disables_dependents_before_target(self):
        self._record_alpha_tools_django_migration()
        self._create_beta_tools_dependency_fixture()
        ExtensionInstallation.objects.update_or_create(
            extension_id="alpha-tools",
            defaults={
                "version": "0.1.0",
                "source": "filesystem",
                "enabled": True,
                "installed": True,
                "booted": True,
            },
        )
        ExtensionInstallation.objects.filter(extension_id="beta-tools").update(enabled=True, booted=True)
        reset_extension_runtime_state()

        with self.assertRaises(ExtensionStateError) as context:
            ExtensionService.set_extension_enabled("beta-tools", False)
        self.assertEqual(context.exception.code, "extension_disable_blocked")

        disabled = ExtensionService.set_extension_enabled("beta-tools", False, include_dependents=True)

        self.assertFalse(disabled.runtime.enabled)
        beta_installation = ExtensionInstallation.objects.get(extension_id="beta-tools")
        alpha_installation = ExtensionInstallation.objects.get(extension_id="alpha-tools")
        self.assertFalse(alpha_installation.enabled)
        self.assertFalse(alpha_installation.booted)
        self.assertFalse(beta_installation.enabled)
        self.assertFalse(beta_installation.booted)
        self.assertIn("run_disable", alpha_installation.meta["backend_hooks"])
        self.assertIn("run_disable", beta_installation.meta["backend_hooks"])

    def test_disable_with_dependents_rejects_disabled_target_before_disabling_dependents(self):
        self._record_alpha_tools_django_migration()
        self._create_beta_tools_dependency_fixture()
        ExtensionInstallation.objects.update_or_create(
            extension_id="alpha-tools",
            defaults={
                "version": "0.1.0",
                "source": "filesystem",
                "enabled": True,
                "installed": True,
                "booted": True,
            },
        )
        reset_extension_runtime_state()

        with self.assertRaises(ExtensionStateError) as context:
            ExtensionService.set_extension_enabled("beta-tools", False, include_dependents=True)

        self.assertEqual(context.exception.code, "extension_disable_not_enabled")
        alpha_installation = ExtensionInstallation.objects.get(extension_id="alpha-tools")
        beta_installation = ExtensionInstallation.objects.get(extension_id="beta-tools")
        self.assertTrue(alpha_installation.enabled)
        self.assertTrue(alpha_installation.booted)
        self.assertFalse(beta_installation.enabled)
        self.assertFalse(beta_installation.booted)

    def test_disable_with_dependents_rolls_back_when_target_disable_fails(self):
        self._record_alpha_tools_django_migration()
        self._create_beta_tools_dependency_fixture()
        ExtensionInstallation.objects.update_or_create(
            extension_id="alpha-tools",
            defaults={
                "version": "0.1.0",
                "source": "filesystem",
                "enabled": True,
                "installed": True,
                "booted": True,
            },
        )
        ExtensionInstallation.objects.filter(extension_id="beta-tools").update(enabled=True, booted=True)
        beta_dir = self.extension_base_dir / "extensions" / "beta-tools"
        (beta_dir / "backend").mkdir(parents=True, exist_ok=True)
        (beta_dir / "backend" / "__init__.py").write_text("", encoding="utf-8")
        (beta_dir / "backend" / "ext.py").write_text(
            "from bias_core.extensions import LifecycleExtender\n"
            "\n"
            "def extend():\n"
            "    return [LifecycleExtender(disable=disable)]\n"
            "\n"
            "def disable(context):\n"
            "    return {'status': 'error', 'message': 'disable exploded'}\n",
            encoding="utf-8",
        )
        manifest_path = beta_dir / "extension.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["backend_entry"] = "extensions.beta_tools.backend.ext"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        reset_extension_runtime_state()

        with self.assertRaises(ExtensionStateError) as context:
            ExtensionService.set_extension_enabled("beta-tools", False, include_dependents=True)

        self.assertEqual(context.exception.code, "extension_lifecycle_failed")
        beta_installation = ExtensionInstallation.objects.get(extension_id="beta-tools")
        alpha_installation = ExtensionInstallation.objects.get(extension_id="alpha-tools")
        self.assertTrue(alpha_installation.enabled)
        self.assertTrue(alpha_installation.booted)
        self.assertTrue(beta_installation.enabled)
        self.assertTrue(beta_installation.booted)

    def test_disable_raises_for_protected_extension(self):
        with self.assertRaises(ExtensionStateError) as context:
            ExtensionService.set_extension_enabled("posts", False)

        self.assertEqual(context.exception.code, "extension_disable_protected_blocked")
        self.assertIn("protected_reason", context.exception.details)

    def test_uninstall_raises_for_protected_extension(self):
        with self.assertRaises(ExtensionStateError) as context:
            ExtensionService.uninstall_extension("posts")

        self.assertEqual(context.exception.code, "extension_uninstall_protected_blocked")
        self.assertIn("protected_reason", context.exception.details)

    def test_uninstall_disables_enabled_extension_first(self):
        installed = ExtensionService.install_extension("alpha-tools")
        self.assertTrue(installed.runtime.enabled)

        uninstalled = ExtensionService.uninstall_extension("alpha-tools")

        self.assertFalse(uninstalled.runtime.installed)
        self.assertFalse(uninstalled.runtime.enabled)
        self.assertEqual(uninstalled.runtime.backend_hooks["run_disable"]["status"], "ok")
        self.assertEqual(uninstalled.runtime.backend_hooks["run_uninstall"]["status"], "ok")

    def test_uninstall_blocks_when_installed_disabled_dependents_exist(self):
        self._create_beta_tools_dependency_fixture()
        ExtensionInstallation.objects.update_or_create(
            extension_id="alpha-tools",
            defaults={
                "version": "0.1.0",
                "source": "filesystem",
                "enabled": False,
                "installed": True,
                "booted": False,
            },
        )
        reset_extension_runtime_state()

        with self.assertRaises(ExtensionStateError) as context:
            ExtensionService.uninstall_extension("beta-tools")

        self.assertEqual(context.exception.code, "extension_uninstall_blocked")
        self.assertEqual(context.exception.details["blocking_dependents"], ["alpha-tools"])

    def test_uninstall_with_dependents_uninstalls_dependents_before_target(self):
        self._record_alpha_tools_django_migration()
        self._create_beta_tools_dependency_fixture()
        ExtensionInstallation.objects.update_or_create(
            extension_id="alpha-tools",
            defaults={
                "version": "0.1.0",
                "source": "filesystem",
                "enabled": False,
                "installed": True,
                "booted": False,
            },
        )
        reset_extension_runtime_state()

        uninstalled = ExtensionService.uninstall_extension("beta-tools", include_dependents=True)

        self.assertFalse(uninstalled.runtime.installed)
        beta_installation = ExtensionInstallation.objects.get(extension_id="beta-tools")
        alpha_installation = ExtensionInstallation.objects.get(extension_id="alpha-tools")
        self.assertFalse(alpha_installation.installed)
        self.assertFalse(alpha_installation.enabled)
        self.assertFalse(beta_installation.installed)
        self.assertFalse(beta_installation.enabled)
        self.assertIn("run_uninstall", alpha_installation.meta["backend_hooks"])
        self.assertIn("run_uninstall", beta_installation.meta["backend_hooks"])

    @patch("bias_core.extensions.compatibility_guard.resolve_bias_version_compatibility")
    def test_install_raises_when_bias_version_incompatible(self, resolve_bias_version_compatibility_mock):
        resolve_bias_version_compatibility_mock.return_value = {
            "compatible": False,
            "current_version": "1.0.0",
            "required_range": "^2.0.0",
            "message": "当前 Bias 版本 1.0.0 不满足扩展声明的兼容范围 ^2.0.0。",
        }

        with self.assertRaises(ExtensionStateError) as context:
            ExtensionService.install_extension("alpha-tools")

        self.assertEqual(context.exception.code, "extension_install_incompatible_bias_version")
        self.assertEqual(context.exception.details["required_bias_version"], "^2.0.0")

    @patch("bias_core.extensions.compatibility_guard.resolve_bias_version_compatibility")
    def test_bias_compatibility_guard_normalizes_enable_errors(self, resolve_bias_version_compatibility_mock):
        from bias_core.extensions.compatibility_guard import validate_bias_compatibility

        resolve_bias_version_compatibility_mock.return_value = {
            "compatible": False,
            "current_version": "1.0.0",
            "required_range": "^2.0.0",
            "message": "当前 Bias 版本 1.0.0 不满足扩展声明的兼容范围 ^2.0.0。",
        }
        extension = SimpleNamespace(id="alpha-tools", manifest=SimpleNamespace())

        with self.assertRaises(ExtensionStateError) as context:
            validate_bias_compatibility(extension, action="enable")

        self.assertEqual(context.exception.code, "extension_enable_incompatible_bias_version")
        self.assertEqual(context.exception.details["extension_id"], "alpha-tools")
        self.assertEqual(context.exception.details["current_bias_version"], "1.0.0")
        self.assertEqual(context.exception.details["required_bias_version"], "^2.0.0")

