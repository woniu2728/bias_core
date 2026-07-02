from tests.common import *
import sqlite3


def package_subprocess_env(temp_dir):
    temp_root = Path(temp_dir) / ".tmp-package-subprocess"
    temp_root.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "TEMP": str(temp_root),
        "TMP": str(temp_root),
        "TMPDIR": str(temp_root),
    })
    return env


def package_python_module_command(temp_dir, module_name, *args):
    temp_root = Path(temp_dir) / ".tmp-package-subprocess"
    temp_root.mkdir(parents=True, exist_ok=True)
    script = """
import runpy
import sys
import tempfile
import uuid
from pathlib import Path

temp_root = Path(sys.argv[1])
temp_root.mkdir(parents=True, exist_ok=True)


def _bias_mkdtemp(suffix=None, prefix=None, dir=None):
    base = Path(dir or temp_root)
    base.mkdir(parents=True, exist_ok=True)
    suffix = "" if suffix is None else str(suffix)
    prefix = "tmp" if prefix is None else str(prefix)
    while True:
        path = base / f"{prefix}{uuid.uuid4().hex}{suffix}"
        try:
            path.mkdir()
        except FileExistsError:
            continue
        return str(path.resolve())


tempfile.tempdir = str(temp_root)
tempfile.mkdtemp = _bias_mkdtemp
sys.argv = [sys.argv[2], *sys.argv[3:]]
runpy.run_module(sys.argv[0], run_name="__main__")
"""
    return [
        sys.executable,
        "-c",
        script,
        str(temp_root),
        module_name,
        *args,
    ]



def build_minimal_package_audit_payload(*, blocking_risk_count=0):
    return {
        "install_plan": {
            "schema": 1,
            "executes_install": False,
            "install_order": ["alpha"],
        },
        "summary": {
            "manifest_count": 1,
            "error_count": 0,
            "risk_count": blocking_risk_count,
            "blocking_risk_count": blocking_risk_count,
            "ok": blocking_risk_count == 0,
        },
        "upgrade_risk": {
            "schema": 1,
            "risk_count": blocking_risk_count,
            "risks": [
                {
                    "extension_id": "alpha",
                    "severity": "blocking",
                    "code": "missing_dependency",
                    "message": "缺少必需依赖: beta",
                }
            ] if blocking_risk_count else [],
            "summary": {
                "risk_count": blocking_risk_count,
                "blocking_risk_count": blocking_risk_count,
                "warning_risk_count": 0,
                "info_risk_count": 0,
                "ok": blocking_risk_count == 0,
            },
        },
    }


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
    def test_inspect_performance_baseline_command_reports_required_contracts(self):
        stdout = StringIO()

        call_command("inspect_performance_baseline", "--format", "json", "--strict", stdout=stdout)

        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"], payload)
        check_names = {item["name"] for item in payload["checks"]}
        self.assertIn("discussion_query_budgets", check_names)
        self.assertIn("tag_stats_refresh", check_names)
        self.assertIn("notification_pagination_indexes", check_names)
        self.assertIn("search_driver_boundary", check_names)
        self.assertIn("queue_worker_metrics", check_names)
        self.assertIn("realtime_metrics", check_names)
        self.assertTrue(payload["p95_load_test_required"])

    def test_inspect_performance_baseline_reads_extension_manifest_contracts(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            contract_payloads = {
                "tags": {
                    "name": "Tags",
                    "contracts": [
                        {
                            "name": "tag_stats_refresh",
                            "message": "tag stats refresh exposes batched implementation and duration metrics.",
                            "metrics": {"batched": True},
                        },
                    ],
                },
                "notifications": {
                    "name": "Notifications",
                    "contracts": [
                        {
                            "name": "notification_pagination_indexes",
                            "message": "notification list has pagination and required indexes.",
                            "required_indexes": [["user"]],
                            "missing_indexes": [],
                        },
                    ],
                },
                "search": {
                    "name": "Search",
                    "contracts": [
                        {
                            "name": "search_driver_boundary",
                            "message": "database search uses PostgreSQL full text only when supported and keeps extension targets behind runtime services.",
                            "database_boundary": "declared in manifest",
                        },
                    ],
                },
                "realtime": {
                    "name": "Realtime",
                    "contracts": [
                        {
                            "name": "realtime_metrics",
                            "message": "realtime metrics include connections, subscriptions and message counters.",
                            "required_fields": ["active_connections"],
                            "missing_fields": [],
                        },
                    ],
                },
            }
            for extension_id, payload in contract_payloads.items():
                manifest_dir = extensions_dir / extension_id
                manifest_dir.mkdir(parents=True, exist_ok=True)
                (manifest_dir / "extension.json").write_text(json.dumps({
                    "id": extension_id,
                    "name": payload["name"],
                    "version": "0.1.0",
                    "dependencies": ["core"],
                    "performance_contracts": payload["contracts"],
                }), encoding="utf-8")

            stdout = StringIO()
            call_command(
                "inspect_performance_baseline",
                "--extensions-path",
                str(extensions_dir),
                "--format",
                "json",
                "--strict",
                stdout=stdout,
            )

            baseline = json.loads(stdout.getvalue())
            self.assertTrue(baseline["ok"], baseline)
            checks = {item["name"]: item for item in baseline["checks"]}
            self.assertEqual(checks["tag_stats_refresh"]["extension_id"], "tags")
            self.assertEqual(checks["notification_pagination_indexes"]["missing_indexes"], [])
            self.assertEqual(checks["search_driver_boundary"]["database_boundary"], "declared in manifest")
            self.assertEqual(checks["realtime_metrics"]["missing_fields"], [])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_performance_baseline_does_not_hardcode_official_extension_modules(self):
        source = (
            Path(settings.BASE_DIR)
            / "src"
            / "bias_core"
            / "management"
            / "commands"
            / "inspect_performance_baseline.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("bias_ext_tags", source)
        self.assertNotIn("bias_ext_notifications", source)
        self.assertNotIn("bias_ext_search", source)
        self.assertNotIn("bias_ext_realtime", source)

    def test_extension_management_commands_skip_django_system_checks(self):
        from bias_core.management.commands.create_extension import Command as CreateExtensionCommand
        from bias_core.management.commands.check_extension_workspace import Command as CheckExtensionWorkspaceCommand
        from bias_core.management.commands.extension_console import Command as ExtensionConsoleCommand
        from bias_core.management.commands.inspect_extensions import Command as InspectExtensionsCommand
        from bias_core.management.commands.inspect_extension_imports import Command as InspectExtensionImportsCommand
        from bias_core.management.commands.inspect_extension_packages import Command as InspectExtensionPackagesCommand
        from bias_core.management.commands.inspect_performance_baseline import Command as InspectPerformanceBaselineCommand
        from bias_core.management.commands.load_test_http import Command as LoadTestHttpCommand
        from bias_core.management.commands.load_test_websocket import Command as LoadTestWebsocketCommand
        from bias_core.management.commands.prepare_load_test_actors import Command as PrepareLoadTestActorsCommand
        from bias_core.management.commands.profile_read_paths import Command as ProfileReadPathsCommand
        from bias_core.management.commands.seed_load_test_data import Command as SeedLoadTestDataCommand
        from bias_core.management.commands.smoke_websocket_realtime import Command as SmokeWebSocketRealtimeCommand
        from bias_core.management.commands.smoke_install_upgrade import Command as SmokeInstallUpgradeCommand
        from bias_core.management.commands.smoke_http_p95 import Command as SmokeHttpP95Command
        from bias_core.management.commands.smoke_queue_worker import Command as SmokeQueueWorkerCommand
        from bias_core.management.commands.sync_extension_package_metadata import Command as SyncPackageMetadataCommand
        from bias_core.management.commands.validate_extensions import Command as ValidateExtensionsCommand

        self.assertEqual(CheckExtensionWorkspaceCommand.requires_system_checks, [])
        self.assertEqual(CreateExtensionCommand.requires_system_checks, [])
        self.assertEqual(ExtensionConsoleCommand.requires_system_checks, [])
        self.assertEqual(InspectExtensionsCommand.requires_system_checks, [])
        self.assertEqual(InspectExtensionImportsCommand.requires_system_checks, [])
        self.assertEqual(InspectExtensionPackagesCommand.requires_system_checks, [])
        self.assertEqual(InspectPerformanceBaselineCommand.requires_system_checks, [])
        self.assertEqual(LoadTestHttpCommand.requires_system_checks, [])
        self.assertEqual(LoadTestWebsocketCommand.requires_system_checks, [])
        self.assertEqual(PrepareLoadTestActorsCommand.requires_system_checks, [])
        self.assertEqual(ProfileReadPathsCommand.requires_system_checks, [])
        self.assertEqual(SeedLoadTestDataCommand.requires_system_checks, [])
        self.assertEqual(SmokeWebSocketRealtimeCommand.requires_system_checks, [])
        self.assertEqual(SmokeHttpP95Command.requires_system_checks, [])
        self.assertEqual(SmokeInstallUpgradeCommand.requires_system_checks, [])
        self.assertEqual(SmokeQueueWorkerCommand.requires_system_checks, [])
        self.assertEqual(SyncPackageMetadataCommand.requires_system_checks, [])
        self.assertEqual(ValidateExtensionsCommand.requires_system_checks, [])

    def test_prepare_load_test_actors_creates_login_users_groups_and_permissions(self):
        stdout = StringIO()

        call_command(
            "prepare_load_test_actors",
            "--username",
            "pytest-auth-user",
            "--password",
            "password123",
            "--moderator-username",
            "pytest-moderator",
            "--moderator-password",
            "password456",
            "--format",
            "json",
            stdout=stdout,
        )

        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["actors"]["auth"]["username"], "pytest-auth-user")
        self.assertEqual(payload["actors"]["moderator"]["username"], "pytest-moderator")
        self.assertEqual(payload["commands"]["forum_main_auth"]["login_username"], "pytest-auth-user")
        self.assertEqual(payload["commands"]["forum_write_moderation"]["login_username"], "pytest-moderator")

        auth_user = User.objects.get(username="pytest-auth-user")
        moderator = User.objects.get(username="pytest-moderator")
        self.assertTrue(auth_user.check_password("password123"))
        self.assertTrue(moderator.check_password("password456"))
        self.assertTrue(auth_user.is_email_confirmed)
        self.assertTrue(moderator.is_email_confirmed)
        self.assertTrue(moderator.is_staff)
        self.assertFalse(moderator.is_superuser)
        self.assertFalse(auth_user.preferences["notify_post_liked"])
        self.assertFalse(moderator.preferences["notify_post_reply"])
        self.assertTrue(auth_user.user_groups.filter(name="Member").exists())
        self.assertTrue(moderator.user_groups.filter(name="Member").exists())
        self.assertTrue(moderator.user_groups.filter(name="Moderator").exists())

        member_group = Group.objects.get(name="Member")
        moderator_group = Group.objects.get(name="Moderator")
        member_permissions = set(Permission.objects.filter(group=member_group).values_list("permission", flat=True))
        moderator_permissions = set(Permission.objects.filter(group=moderator_group).values_list("permission", flat=True))
        self.assertIn("startDiscussion", member_permissions)
        self.assertIn("discussion.reply", member_permissions)
        self.assertIn("post.editOwn", member_permissions)
        self.assertIn("post.edit", moderator_permissions)
        self.assertIn("post.hide", moderator_permissions)
        self.assertIn("post.delete", moderator_permissions)

    def test_prepare_load_test_actors_is_idempotent_and_resets_password(self):
        call_command(
            "prepare_load_test_actors",
            "--username",
            "pytest-idempotent-user",
            "--password",
            "old-password",
            "--moderator-username",
            "pytest-idempotent-moderator",
            "--moderator-password",
            "old-password",
            stdout=StringIO(),
        )

        stdout = StringIO()
        call_command(
            "prepare_load_test_actors",
            "--username",
            "pytest-idempotent-user",
            "--password",
            "new-password",
            "--moderator-username",
            "pytest-idempotent-moderator",
            "--moderator-password",
            "new-moderator-password",
            "--format",
            "json",
            stdout=stdout,
        )

        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(User.objects.filter(username="pytest-idempotent-user").count(), 1)
        self.assertEqual(User.objects.filter(username="pytest-idempotent-moderator").count(), 1)
        self.assertTrue(User.objects.get(username="pytest-idempotent-user").check_password("new-password"))
        self.assertTrue(User.objects.get(username="pytest-idempotent-moderator").check_password("new-moderator-password"))

    def test_seed_load_test_data_creates_minimal_dataset(self):
        stdout = StringIO()

        call_command(
            "seed_load_test_data",
            "--users",
            "2",
            "--discussions",
            "3",
            "--posts",
            "5",
            "--tags",
            "2",
            "--notifications",
            "4",
            "--batch-size",
            "2",
            "--prefix",
            "pytest-load",
            "--format",
            "json",
            stdout=stdout,
        )

        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["summary"]["ok"], payload)
        self.assertEqual(payload["sections"]["users"]["created"], 2)
        self.assertEqual(payload["sections"]["discussions"]["created"], 3)
        self.assertEqual(payload["sections"]["posts"]["created"], 5)
        self.assertEqual(payload["sections"]["tags"]["created"], 2)
        self.assertEqual(payload["sections"]["notifications"]["created"], 4)

        idempotent_stdout = StringIO()
        call_command(
            "seed_load_test_data",
            "--users",
            "2",
            "--discussions",
            "3",
            "--posts",
            "5",
            "--tags",
            "2",
            "--notifications",
            "4",
            "--prefix",
            "pytest-load",
            "--format",
            "json",
            stdout=idempotent_stdout,
        )
        idempotent = json.loads(idempotent_stdout.getvalue())
        self.assertEqual(idempotent["summary"]["created_total"], 0)

    def test_profile_read_paths_reports_external_http_timings(self):
        seen_urls = []

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.headers = kwargs.get("headers") or {}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url):
                seen_urls.append((url, dict(self.headers)))
                return SimpleNamespace(status_code=200)

        ticks = iter(index / 1000 for index in range(0, 200))
        stdout = StringIO()
        with patch("bias_core.management.commands.profile_read_paths.httpx.Client", FakeClient):
            with patch("bias_core.management.commands.profile_read_paths.time.perf_counter", side_effect=lambda: next(ticks)):
                call_command(
                    "profile_read_paths",
                    "--base-url",
                    "http://bias.test",
                    "--path",
                    "/api/forum",
                    "--repeat",
                    "2",
                    "--warmup",
                    "1",
                    "--header",
                    "X-Test: yes",
                    "--format",
                    "json",
                    stdout=stdout,
                )

        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["summary"]["ok"], payload)
        self.assertEqual(payload["mode"], "external-http")
        self.assertEqual(payload["targets"][0]["path"], "/api/forum")
        self.assertEqual(payload["targets"][0]["sample_count"], 2)
        self.assertEqual(payload["targets"][0]["status_code_counts"], {"200": 2})
        self.assertEqual(payload["targets"][0]["query_count_average"], 0.0)
        self.assertEqual(seen_urls[0][0], "http://bias.test/api/forum")
        self.assertEqual(seen_urls[0][1]["X-Test"], "yes")

    def test_profile_read_paths_reports_in_process_query_counts(self):
        stdout = StringIO()

        call_command(
            "profile_read_paths",
            "--in-process",
            "--path",
            "/api/forum",
            "--repeat",
            "1",
            "--warmup",
            "0",
            "--format",
            "json",
            stdout=stdout,
        )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["mode"], "in-process")
        self.assertTrue(payload["summary"]["ok"], payload)
        target = payload["targets"][0]
        self.assertEqual(target["method"], "GET")
        self.assertEqual(target["path"], "/api/forum")
        self.assertEqual(target["sample_count"], 1)
        self.assertIn("query_count_average", target)
        self.assertIn("duplicate_query_count_average", target)
        self.assertIn("db_average_ms", target)
        self.assertIn("serialize_average_ms", target)
        self.assertIn("slow_queries", target)

    def test_profile_read_paths_explain_skips_non_select_and_normalizes_sql(self):
        from bias_core.management.commands import profile_read_paths

        self.assertEqual(
            profile_read_paths.normalize_sql("SELECT * FROM alpha WHERE id = 123 AND name = 'Bob'"),
            "SELECT * FROM alpha WHERE id = ? AND name = ?",
        )
        skipped = profile_read_paths.explain_sql("UPDATE alpha SET name = 'Bob'")
        self.assertEqual(skipped, {"ok": False, "skipped": True, "reason": "not_select"})

    def test_profile_read_paths_requires_base_url_or_in_process(self):
        with self.assertRaisesMessage(CommandError, "缺少 --base-url"):
            call_command_quietly("profile_read_paths", "--path", "/api/forum")

    def test_load_test_http_reports_percentiles_and_error_rate(self):
        from bias_core.management.commands import load_test_http

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def request(self, method, url, json=None):
                return SimpleNamespace(status_code=200)

        ticks = iter(index / 1000 for index in range(0, 200))
        stdout = StringIO()
        with patch("bias_core.management.commands.load_test_http.httpx.Client", FakeClient):
            with patch("bias_core.management.commands.load_test_http.time.perf_counter", side_effect=lambda: next(ticks)):
                call_command(
                    "load_test_http",
                    "--base-url",
                    "http://bias.test",
                    "--path",
                    "/api/forum=10",
                    "--concurrency",
                    "2",
                    "--requests",
                    "4",
                    "--duration",
                    "0",
                    "--format",
                    "json",
                    "--fail-on-threshold",
                    stdout=stdout,
                )

        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["summary"]["ok"], payload)
        self.assertEqual(payload["summary"]["request_count"], 4)
        self.assertEqual(payload["summary"]["error_rate"], 0.0)
        self.assertEqual(payload["targets"][0]["status_code_counts"], {"200": 4})
        self.assertTrue(payload["targets"][0]["covered"])
        self.assertIn("p50_ms", payload["targets"][0])
        self.assertIn("p95_ms", payload["targets"][0])
        self.assertIn("p99_ms", payload["targets"][0])
        self.assertEqual(load_test_http.percentile([1, 2, 3, 4], 99), 3.9699999999999998)

    def test_load_test_http_supports_auth_token_dynamic_path_and_post_profile(self):
        seen_requests = []

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.headers = kwargs.get("headers") or {}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def request(self, method, url, json=None):
                seen_requests.append({
                    "method": method,
                    "url": url,
                    "json": json,
                    "headers": dict(self.headers),
                })
                return SimpleNamespace(status_code=200)

        stdout = StringIO()
        with patch("bias_core.management.commands.load_test_http.httpx.Client", FakeClient):
            call_command(
                "load_test_http",
                "--base-url",
                "http://bias.test",
                "--profile",
                "forum-write",
                "--discussion-id",
                "42",
                "--auth-token",
                "token-123",
                "--concurrency",
                "1",
                "--requests",
                "1",
                "--duration",
                "0",
                "--format",
                "json",
                stdout=stdout,
            )

        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["summary"]["ok"], payload)
        self.assertEqual(payload["dynamic_values"]["discussion_id"], 42)
        self.assertEqual(payload["targets"][0]["method"], "POST")
        self.assertEqual(payload["targets"][0]["path"], "/api/discussions/42/posts")
        self.assertTrue(payload["targets"][0]["has_json_body"])
        self.assertTrue(payload["targets"][0]["covered"])
        self.assertEqual(seen_requests[0]["method"], "POST")
        self.assertEqual(seen_requests[0]["url"], "http://bias.test/api/discussions/42/posts")
        self.assertEqual(seen_requests[0]["json"]["content"].startswith("Load test reply "), True)
        self.assertEqual(seen_requests[0]["headers"]["Authorization"], "Bearer token-123")

    def test_load_test_http_reuses_client_per_worker(self):
        client_count = 0
        seen_requests = []

        class FakeClient:
            def __init__(self, *args, **kwargs):
                nonlocal client_count
                client_count += 1

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def request(self, method, url, **kwargs):
                seen_requests.append((method, url))
                return SimpleNamespace(status_code=200)

        stdout = StringIO()
        with patch("bias_core.management.commands.load_test_http.httpx.Client", FakeClient):
            call_command(
                "load_test_http",
                "--base-url",
                "http://bias.test",
                "--path",
                "/api/forum=300",
                "--concurrency",
                "2",
                "--requests",
                "6",
                "--duration",
                "0",
                "--format",
                "json",
                stdout=stdout,
            )

        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["summary"]["ok"], payload)
        self.assertEqual(payload["summary"]["request_count"], 6)
        self.assertEqual(len(seen_requests), 6)
        self.assertEqual(client_count, 2)

    def test_load_test_http_can_bootstrap_login_session(self):
        seen_requests = []

        class FakeCookies:
            jar = [
                SimpleNamespace(name="csrftoken", value="csrf-cookie"),
                SimpleNamespace(name="bias_access_token", value="cookie-access"),
            ]

        class FakeResponse:
            def __init__(self, status_code=200, payload=None):
                self.status_code = status_code
                self._payload = payload or {}

            def json(self):
                return self._payload

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.headers = kwargs.get("headers") or {}
                self.cookies = FakeCookies()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url):
                seen_requests.append({"method": "GET", "url": url, "headers": dict(self.headers)})
                return FakeResponse(payload={"csrfToken": "csrf-token"})

            def post(self, url, json=None, headers=None):
                seen_requests.append({"method": "POST", "url": url, "json": json, "headers": dict(headers or {})})
                return FakeResponse(payload={"access": "access-token"})

            def request(self, method, url, **kwargs):
                seen_requests.append({
                    "method": method,
                    "url": url,
                    "headers": dict(self.headers),
                    "kwargs": kwargs,
                })
                return SimpleNamespace(status_code=200)

        stdout = StringIO()
        with patch("bias_core.management.commands.load_test_http.httpx.Client", FakeClient):
            call_command(
                "load_test_http",
                "--base-url",
                "http://bias.test",
                "--profile",
                "forum-write",
                "--discussion-id",
                "42",
                "--login-username",
                "load-user",
                "--login-password",
                "load-password",
                "--concurrency",
                "1",
                "--requests",
                "1",
                "--duration",
                "0",
                "--format",
                "json",
                stdout=stdout,
            )

        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["summary"]["ok"], payload)
        self.assertEqual(seen_requests[0]["url"], "http://bias.test/api/csrf")
        self.assertEqual(seen_requests[1]["url"], "http://bias.test/api/users/login")
        self.assertEqual(seen_requests[1]["headers"]["X-CSRFToken"], "csrf-token")
        self.assertEqual(seen_requests[1]["json"], {"identification": "load-user", "password": "load-password"})
        load_request = seen_requests[2]
        self.assertEqual(load_request["headers"]["Authorization"], "Bearer access-token")
        self.assertEqual(load_request["headers"]["X-CSRFToken"], "csrf-token")
        self.assertIn("csrftoken=csrf-cookie", load_request["headers"]["Cookie"])
        self.assertIn("bias_access_token=cookie-access", load_request["headers"]["Cookie"])

    def test_load_test_http_supports_custom_method_body_and_threshold(self):
        from bias_core.management.commands import load_test_http

        targets = load_test_http.parse_targets(
            ['PATCH /api/posts/{post_id} {"content":"Updated {sequence}"}=500'],
            profile="forum-main",
            dynamic_values={"post_id": 7, "sequence": 99},
        )

        self.assertEqual(targets[0].method, "PATCH")
        self.assertEqual(targets[0].path, "/api/posts/7")
        self.assertEqual(targets[0].json_body, {"content": "Updated 99"})
        self.assertEqual(targets[0].threshold_ms, 500.0)

    def test_load_test_http_splits_public_and_authenticated_main_profiles(self):
        from bias_core.management.commands import load_test_http

        public_targets = load_test_http.parse_targets([], profile="forum-main", dynamic_values={})
        auth_targets = load_test_http.parse_targets([], profile="forum-main-auth", dynamic_values={})

        self.assertNotIn("GET /api/notifications", [target.label for target in public_targets])
        self.assertIn("GET /api/notifications", [target.label for target in auth_targets])
        self.assertIn("GET /api/search?q=loadtest-discussion-00000001", [target.label for target in public_targets])
        self.assertNotIn("GET /api/search?q=loadtest", [target.label for target in public_targets])

    def test_load_test_http_supports_mixed_write_profile(self):
        from bias_core.management.commands import load_test_http

        targets = load_test_http.parse_targets(
            [],
            profile="forum-write-mixed",
            dynamic_values={
                "discussion_id": 42,
                "post_id": 77,
                "tag_id": 5,
                "sequence": 99,
            },
        )

        self.assertEqual(
            [target.label for target in targets],
            [
                "POST /api/discussions/",
                "PATCH /api/discussions/42",
                "POST /api/discussions/42/read",
                "POST /api/posts/77/like",
                "DELETE /api/posts/77/like",
                "POST /api/discussions/42/subscribe",
                "DELETE /api/discussions/42/subscribe",
            ],
        )
        create_body = targets[0].json_body
        self.assertEqual(create_body["data"]["attributes"]["title"], "Load test discussion 99")
        self.assertEqual(
            create_body["data"]["relationships"]["tags"]["data"],
            [{"type": "tag", "id": "5"}],
        )
        self.assertEqual(targets[1].json_body["data"]["attributes"]["title"], "Load test update 99")
        self.assertEqual(targets[2].json_body, {"last_read_post_number": 1})
        self.assertEqual(targets[3].threshold_ms, 500.0)

    def test_load_test_http_mixed_profile_supports_distinct_like_targets(self):
        from bias_core.management.commands import load_test_http

        targets = load_test_http.parse_targets(
            [],
            profile="forum-write-mixed",
            dynamic_values={
                "discussion_id": 42,
                "post_id": 77,
                "like_post_id": 78,
                "unlike_post_id": 79,
                "tag_id": 5,
                "sequence": 99,
            },
        )

        self.assertEqual(targets[3].label, "POST /api/posts/78/like")
        self.assertEqual(targets[4].label, "DELETE /api/posts/79/like")

    def test_load_test_http_prepares_mixed_targets_for_actor_owned_updates_and_stable_likes(self):
        from bias_core.management.commands import load_test_http

        actor = User.objects.create_user(
            username="mixed-load-actor",
            email="mixed-load-actor@example.com",
            password="password123",
            is_email_confirmed=True,
        )

        with patch.dict(os.environ, {"BIAS_LOAD_TEST_STATE_POOL_SIZE": "3"}):
            values = load_test_http.resolve_dynamic_values(
                profile="forum-write-mixed",
                prepare_isolated_targets=True,
                actor_user_id=actor.id,
            )

        Discussion = apps.get_model("content", "Discussion")
        PostLike = apps.get_model("likes", "PostLike")
        discussion = Discussion.objects.get(id=values["discussion_id"])
        isolated_user = User.objects.get(id=values["isolated_targets"]["user_id"])
        self.assertEqual(discussion.user_id, actor.id)
        self.assertFalse(isolated_user.preferences["notify_post_liked"])
        self.assertNotEqual(values["like_post_id"], values["unlike_post_id"])
        self.assertFalse(PostLike.objects.filter(post_id=values["like_post_id"], user=actor).exists())
        self.assertTrue(PostLike.objects.filter(post_id=values["unlike_post_id"], user=actor).exists())
        self.assertEqual(values["isolated_targets"]["like_post_pool_size"], 4)
        self.assertEqual(values["isolated_targets"]["unlike_post_pool_size"], 4)

        targets = load_test_http.parse_targets([], profile="forum-write-mixed", dynamic_values=values)
        self.assertIn(f"PATCH /api/discussions/{discussion.id}", [target.label for target in targets])
        self.assertIn(f"POST /api/posts/{values['like_post_id']}/like", [target.label for target in targets])
        self.assertIn(f"DELETE /api/posts/{values['unlike_post_id']}/like", [target.label for target in targets])

        first_like = load_test_http._render_target_for_request(targets[3], sequence=0)
        second_like = load_test_http._render_target_for_request(targets[3], sequence=1)
        first_unlike = load_test_http._render_target_for_request(targets[4], sequence=0)
        second_unlike = load_test_http._render_target_for_request(targets[4], sequence=1)
        self.assertNotEqual(first_like.path, second_like.path)
        self.assertNotEqual(first_unlike.path, second_unlike.path)

    def test_load_test_http_sequence_pools_advance_per_target_field(self):
        from bias_core.management.commands import load_test_http

        values = {
            "discussion_id": 42,
            "post_id": 77,
            "like_post_id": 101,
            "unlike_post_id": 201,
            "tag_id": 5,
            "sequence": 99,
            "_sequence_pools": {
                "like_post_id": [101, 102, 103],
                "unlike_post_id": [201, 202, 203],
            },
        }
        targets = load_test_http.parse_targets([], profile="forum-write-mixed", dynamic_values=values)

        unrelated = load_test_http._render_target_for_request(targets[0], sequence=0)
        first_like = load_test_http._render_target_for_request(targets[3], sequence=7)
        first_unlike = load_test_http._render_target_for_request(targets[4], sequence=8)
        second_like = load_test_http._render_target_for_request(targets[3], sequence=14)
        second_unlike = load_test_http._render_target_for_request(targets[4], sequence=15)

        self.assertEqual(unrelated.path, "/api/discussions/")
        self.assertEqual(first_like.path, "/api/posts/101/like")
        self.assertEqual(second_like.path, "/api/posts/102/like")
        self.assertEqual(first_unlike.path, "/api/posts/201/like")
        self.assertEqual(second_unlike.path, "/api/posts/202/like")

    def test_load_test_http_renders_unique_sequence_per_request(self):
        from bias_core.management.commands import load_test_http

        target = load_test_http.parse_targets(
            ["POST /api/discussions/ {\"title\":\"Load {sequence}\"}=500"],
            profile="forum-main",
            dynamic_values={"sequence": 99},
        )[0]

        first = load_test_http._render_target_for_request(target, sequence=100)
        second = load_test_http._render_target_for_request(target, sequence=101)

        self.assertEqual(first.json_body["title"], "Load 100")
        self.assertEqual(second.json_body["title"], "Load 101")
        self.assertEqual(target.json_body["title"], "Load 99")

    def test_load_test_http_supports_upload_profile_multipart(self):
        seen_requests = []

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def request(self, method, url, **kwargs):
                seen_requests.append({
                    "method": method,
                    "url": url,
                    "kwargs": kwargs,
                })
                return SimpleNamespace(status_code=200)

        stdout = StringIO()
        with patch("bias_core.management.commands.load_test_http.httpx.Client", FakeClient):
            call_command(
                "load_test_http",
                "--base-url",
                "http://bias.test",
                "--profile",
                "forum-upload",
                "--auth-token",
                "token-123",
                "--concurrency",
                "1",
                "--requests",
                "1",
                "--duration",
                "0",
                "--format",
                "json",
                stdout=stdout,
            )

        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["summary"]["ok"], payload)
        self.assertEqual(payload["targets"][0]["method"], "POST")
        self.assertEqual(payload["targets"][0]["path"], "/api/uploads")
        self.assertFalse(payload["targets"][0]["has_json_body"])
        self.assertTrue(payload["targets"][0]["has_multipart_file"])
        files = seen_requests[0]["kwargs"]["files"]
        self.assertIn("file", files)
        filename, content, content_type = files["file"]
        self.assertTrue(filename.startswith("load-test-"))
        self.assertIn(b"load test upload", content)
        self.assertEqual(content_type, "text/plain")

    def test_load_test_http_supports_custom_file_body(self):
        from bias_core.management.commands import load_test_http

        targets = load_test_http.parse_targets(
            ["POST /api/uploads FILE file:guide.txt:text/plain:hello {sequence}=800"],
            profile="forum-main",
            dynamic_values={"sequence": 99},
        )

        self.assertEqual(targets[0].method, "POST")
        self.assertEqual(targets[0].path, "/api/uploads")
        self.assertIsNone(targets[0].json_body)
        self.assertEqual(targets[0].multipart_file["field"], "file")
        self.assertEqual(targets[0].multipart_file["filename"], "guide.txt")
        self.assertEqual(targets[0].multipart_file["content"], "hello 99")
        self.assertEqual(targets[0].threshold_ms, 800.0)

    def test_load_test_http_supports_moderation_write_profile(self):
        from bias_core.management.commands import load_test_http

        targets = load_test_http.parse_targets(
            [],
            profile="forum-write-moderation",
            dynamic_values={
                "discussion_id": 42,
                "post_id": 77,
                "notification_id": 88,
                "sequence": 99,
            },
        )

        self.assertEqual(
            [target.label for target in targets],
            [
                "PATCH /api/posts/77",
                "POST /api/posts/77/report",
                "POST /api/notifications/88/read",
                "POST /api/posts/77/hide",
                "POST /api/posts/77/hide",
                "POST /api/notifications/read-filtered?type=postReply&discussion_id=42",
                "DELETE /api/notifications/read/clear-filtered?type=postReply&discussion_id=42",
                "DELETE /api/notifications/read/clear",
                "DELETE /api/posts/77",
            ],
        )
        self.assertEqual(targets[0].json_body, {"content": "Load test edited post 99"})
        self.assertEqual(targets[1].json_body, {"reason": "spam", "message": "Load test report 99"})
        self.assertEqual(targets[8].threshold_ms, 500.0)
        self.assertIsNone(targets[7].json_body)

    def test_load_test_http_can_prepare_isolated_moderation_targets(self):
        from bias_core.management.commands import load_test_http

        actor = User.objects.create_user(
            username="moderation-load-actor",
            email="moderation-load-actor@example.com",
            password="password123",
            is_email_confirmed=True,
        )
        with patch.dict(os.environ, {"BIAS_LOAD_TEST_STATE_POOL_SIZE": "2"}):
            values = load_test_http.resolve_dynamic_values(
                profile="forum-write-moderation",
                prepare_isolated_targets=True,
                actor_user_id=actor.id,
            )

        self.assertIn("isolated_targets", values)
        self.assertIn("discussion_id", values)
        self.assertIn("post_id", values)
        self.assertIn("notification_id", values)
        self.assertIn("_sequence_pools", values)
        self.assertTrue(values["isolated_targets"]["prefix"].startswith("loadtest-isolated-"))
        self.assertEqual(values["isolated_targets"]["edit_post_pool_size"], 3)
        self.assertEqual(values["isolated_targets"]["notification_read_pool_size"], 3)

        Discussion = apps.get_model("content", "Discussion")
        Post = apps.get_model("content", "Post")
        Notification = apps.get_model("notifications", "Notification")

        discussion = Discussion.objects.get(id=values["discussion_id"])
        post = Post.objects.get(id=values["post_id"])
        notification = Notification.objects.get(id=values["notification_id"])
        self.assertEqual(post.discussion_id, discussion.id)
        self.assertEqual(post.number, 2)
        self.assertEqual(notification.subject_id, post.id)
        self.assertEqual(Discussion.objects.get(id=discussion.id).user_id, actor.id)

        targets = load_test_http.parse_targets([], profile="forum-write-moderation", dynamic_values=values)
        self.assertIn(f"PATCH /api/posts/{values['edit_post_id']}", [target.label for target in targets])
        self.assertIn(f"POST /api/notifications/{values['notification_read_id']}/read", [target.label for target in targets])

        first_delete = load_test_http._render_target_for_request(targets[8], sequence=0)
        second_delete = load_test_http._render_target_for_request(targets[8], sequence=1)
        first_read = load_test_http._render_target_for_request(targets[2], sequence=0)
        second_read = load_test_http._render_target_for_request(targets[2], sequence=1)
        self.assertNotEqual(first_delete.path, second_delete.path)
        self.assertNotEqual(first_read.path, second_read.path)

    def test_load_test_http_can_cleanup_isolated_targets(self):
        from bias_core.management.commands import load_test_http

        values = load_test_http.resolve_dynamic_values(
            profile="forum-write-moderation",
            prepare_isolated_targets=True,
        )
        prefix = values["isolated_targets"]["prefix"]

        cleanup = load_test_http.cleanup_isolated_targets_for_prefix(prefix)

        self.assertTrue(cleanup["ok"], cleanup)
        self.assertEqual(cleanup["prefix"], prefix)
        self.assertGreaterEqual(cleanup["deleted_total"], 4)

        Discussion = apps.get_model("content", "Discussion")
        Post = apps.get_model("content", "Post")
        Notification = apps.get_model("notifications", "Notification")
        self.assertFalse(Discussion.objects.filter(id=values["discussion_id"]).exists())
        self.assertFalse(Post.objects.filter(id=values["post_id"]).exists())
        self.assertFalse(Notification.objects.filter(id=values["notification_id"]).exists())

    def test_load_test_http_rejects_unsafe_cleanup_prefix(self):
        from bias_core.management.commands import load_test_http

        with self.assertRaisesMessage(CommandError, "loadtest-isolated-*"):
            load_test_http.cleanup_isolated_targets_for_prefix("pytest-load")

    def test_load_test_http_cleans_up_prepared_targets_after_run(self):
        from bias_core.management.commands import load_test_http

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def request(self, method, url, **kwargs):
                return SimpleNamespace(status_code=200)

        stdout = StringIO()
        with patch("bias_core.management.commands.load_test_http.httpx.Client", FakeClient):
            call_command(
                "load_test_http",
                "--base-url",
                "http://bias.test",
                "--profile",
                "forum-write-moderation",
                "--prepare-isolated-targets",
                "--cleanup-isolated-targets",
                "--concurrency",
                "1",
                "--requests",
                "9",
                "--duration",
                "0",
                "--format",
                "json",
                stdout=stdout,
            )

        payload = json.loads(stdout.getvalue())
        prefix = payload["isolated_targets"]["prefix"]
        self.assertTrue(payload["summary"]["ok"], payload)
        self.assertEqual(payload["cleanup"]["prefix"], prefix)
        self.assertGreaterEqual(payload["cleanup"]["deleted_total"], 4)

        Discussion = apps.get_model("content", "Discussion")
        self.assertFalse(Discussion.objects.filter(slug=f"{prefix}-discussion").exists())

    def test_smoke_websocket_realtime_reports_connect_subscribe_and_broadcast(self):
        stdout = StringIO()

        call_command(
            "smoke_websocket_realtime",
            "--connections",
            "2",
            "--discussion-id",
            "101",
            "--format",
            "json",
            stdout=stdout,
        )

        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["summary"]["ok"], payload)
        self.assertEqual(payload["mode"], "in_process_channels")
        self.assertIn("workspace_fallback", payload)
        self.assertEqual(payload["summary"]["connection_count"], 2)
        self.assertEqual(payload["timings"]["connect_ms"]["count"], 2)
        self.assertEqual(payload["timings"]["subscribe_ms"]["count"], 2)
        self.assertEqual(payload["timings"]["broadcast_ms"]["count"], 2)
        self.assertEqual(payload["issues"], [])

    def test_smoke_websocket_realtime_prefers_current_extension_host(self):
        from bias_core.management.commands import smoke_websocket_realtime

        route = SimpleNamespace(name="realtime.forum", consumer=SimpleNamespace(__module__="tests.fake"))
        host = SimpleNamespace(get_websocket_routes=lambda: [route])

        with patch("bias_core.management.commands.smoke_websocket_realtime.get_extension_host", return_value=host):
            with patch("bias_core.management.commands.smoke_websocket_realtime.build_extension_test_host") as fallback:
                resolved_route, workspace_fallback = smoke_websocket_realtime.resolve_realtime_forum_route()

        self.assertIs(resolved_route, route)
        self.assertFalse(workspace_fallback)
        fallback.assert_not_called()

    def test_load_test_websocket_resolves_url_and_headers(self):
        from bias_core.management.commands import load_test_websocket

        self.assertEqual(
            load_test_websocket.resolve_websocket_url(base_url="https://forum.example.com", path="/ws/forum/"),
            "wss://forum.example.com/ws/forum/",
        )
        self.assertEqual(
            load_test_websocket.resolve_websocket_url(base_url="http://127.0.0.1:8000/app/", path="ws/forum/"),
            "ws://127.0.0.1:8000/ws/forum/",
        )
        headers = load_test_websocket.parse_headers(["X-Probe: yes"], auth_token="token-123")
        self.assertEqual(headers["X-Probe"], "yes")
        self.assertEqual(headers["Authorization"], "Bearer token-123")

    def test_load_test_websocket_reports_external_connect_subscribe_and_broadcast(self):
        from asgiref.sync import async_to_sync
        from bias_core.management.commands import load_test_websocket

        class FakeWebsocket:
            def __init__(self):
                self.sent = []
                self.messages = [
                    json.dumps({"type": "connection_established"}),
                    json.dumps({"type": "subscribed", "discussion_ids": [101]}),
                    json.dumps({
                        "type": "forum_event",
                        "event": {"event_type": "load.external.websocket"},
                    }),
                ]
                self.closed = False

            async def send(self, message):
                self.sent.append(json.loads(message))

            async def recv(self):
                return self.messages.pop(0)

            async def close(self):
                self.closed = True

        sockets = [FakeWebsocket(), FakeWebsocket()]
        connected_headers = []

        async def fake_connect(url, *, headers, timeout):
            connected_headers.append((url, headers, timeout))
            return sockets[len(connected_headers) - 1]

        broadcasted = []

        async def fake_broadcast(*, discussion_id):
            broadcasted.append(discussion_id)

        with patch("bias_core.management.commands.load_test_websocket._connect_websocket", side_effect=fake_connect):
            with patch("bias_core.management.commands.load_test_websocket._broadcast_forum_event", side_effect=fake_broadcast):
                payload = async_to_sync(load_test_websocket.run_external_websocket_load_test)(
                    url="ws://bias.test/ws/forum/",
                    connections=2,
                    discussion_id=101,
                    timeout=1.0,
                    headers={"Authorization": "Bearer token"},
                    p95_threshold_ms=1000.0,
                    broadcast_p95_threshold_ms=1000.0,
                )

        self.assertTrue(payload["summary"]["ok"], payload)
        self.assertEqual(payload["mode"], "external_websocket")
        self.assertEqual(payload["summary"]["connection_count"], 2)
        self.assertEqual(payload["summary"]["broadcast_count"], 2)
        self.assertEqual(payload["timings"]["connect_ms"]["count"], 2)
        self.assertEqual(payload["timings"]["subscribe_ms"]["count"], 2)
        self.assertEqual(payload["timings"]["broadcast_ms"]["count"], 2)
        self.assertEqual(broadcasted, [101])
        self.assertEqual(connected_headers[0][0], "ws://bias.test/ws/forum/")
        self.assertEqual(connected_headers[0][1]["Authorization"], "Bearer token")
        self.assertEqual(sockets[0].sent[0], {"type": "subscribe_discussions", "discussion_ids": [101]})
        self.assertTrue(all(socket.closed for socket in sockets))

    def test_load_test_websocket_command_outputs_json_without_channel_broadcast(self):
        class FakeWebsocket:
            def __init__(self):
                self.messages = [
                    json.dumps({"type": "connection_established"}),
                    json.dumps({"type": "subscribed", "discussion_ids": [101]}),
                ]

            async def send(self, message):
                return None

            async def recv(self):
                return self.messages.pop(0)

            async def close(self):
                return None

        async def fake_connect(url, *, headers, timeout):
            return FakeWebsocket()

        stdout = StringIO()
        with patch("bias_core.management.commands.load_test_websocket._connect_websocket", side_effect=fake_connect):
            call_command(
                "load_test_websocket",
                "--base-url",
                "https://forum.example.com",
                "--connections",
                "1",
                "--discussion-id",
                "101",
                "--skip-channel-broadcast",
                "--format",
                "json",
                stdout=stdout,
            )

        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["summary"]["ok"], payload)
        self.assertEqual(payload["url"], "wss://forum.example.com/ws/forum/")
        self.assertFalse(payload["channel_broadcast"])
        self.assertEqual(payload["summary"]["expected_broadcast_count"], 0)

    def test_load_test_websocket_reports_exception_class_when_message_is_empty(self):
        from asgiref.sync import async_to_sync
        from bias_core.management.commands import load_test_websocket

        async def fake_connect(url, *, headers, timeout):
            raise TimeoutError()

        with patch("bias_core.management.commands.load_test_websocket._connect_websocket", side_effect=fake_connect):
            payload = async_to_sync(load_test_websocket.run_external_websocket_load_test)(
                url="ws://bias.test/ws/forum/",
                connections=1,
                discussion_id=101,
                timeout=1.0,
                headers={},
                p95_threshold_ms=1000.0,
                broadcast_p95_threshold_ms=1000.0,
                channel_broadcast=False,
            )

        self.assertFalse(payload["summary"]["ok"])
        self.assertEqual(payload["issues"], ["connection 0 failed: TimeoutError"])

    def test_smoke_http_p95_reports_threshold_results(self):
        from bias_core.management.commands import smoke_http_p95

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.calls = []

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url):
                self.calls.append(url)
                return SimpleNamespace(status_code=200)

        ticks = iter([index / 1000 for index in range(0, 40)])
        stdout = StringIO()
        with patch("bias_core.management.commands.smoke_http_p95.httpx.Client", FakeClient):
            with patch("bias_core.management.commands.smoke_http_p95.time.perf_counter", side_effect=lambda: next(ticks)):
                call_command(
                    "smoke_http_p95",
                    "--base-url",
                    "http://bias.test",
                    "--path",
                    "/api/forum=10",
                    "--requests",
                    "3",
                    "--warmup",
                    "1",
                    "--format",
                    "json",
                    "--fail-on-threshold",
                    stdout=stdout,
                )

        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["summary"]["ok"], payload)
        self.assertEqual(payload["targets"][0]["url"], "http://bias.test/api/forum")
        self.assertEqual(payload["targets"][0]["status_code_counts"], {"200": 3})
        self.assertLessEqual(payload["targets"][0]["p95_ms"], 10)
        self.assertEqual(smoke_http_p95.percentile([1, 2, 3, 4], 95), 3.8499999999999996)

    def test_smoke_http_p95_fails_when_threshold_is_exceeded(self):
        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, url):
                return SimpleNamespace(status_code=200)

        ticks = iter([0, 0.1, 0.1, 0.2])
        with patch("bias_core.management.commands.smoke_http_p95.httpx.Client", FakeClient):
            with patch("bias_core.management.commands.smoke_http_p95.time.perf_counter", side_effect=lambda: next(ticks)):
                with self.assertRaises(CommandError):
                    call_command(
                        "smoke_http_p95",
                        "--base-url",
                        "http://bias.test",
                        "--path",
                        "/api/forum=10",
                        "--requests",
                        "2",
                        "--warmup",
                        "0",
                        "--fail-on-threshold",
                        stdout=StringIO(),
                    )

    def test_smoke_runtime_integrations_reports_email_and_storage_dry_run(self):
        stdout = StringIO()
        call_command(
            "smoke_runtime_integrations",
            "--format",
            "json",
            stdout=stdout,
        )

        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["summary"]["ok"], payload)
        self.assertEqual(payload["summary"]["check_count"], 2)
        self.assertEqual(payload["summary"]["error_count"], 0)
        self.assertEqual(payload["summary"]["warning_count"], 2)
        email_check = next(check for check in payload["checks"] if check["key"] == "email")
        storage_check = next(check for check in payload["checks"] if check["key"] == "storage")
        self.assertEqual(email_check["mode"], "config_dry_run")
        self.assertEqual(storage_check["mode"], "backend_init")
        self.assertTrue(storage_check["backend"])

    def test_smoke_runtime_integrations_storage_write_creates_and_deletes_probe(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            media_root = base_dir / "media"
            stdout = StringIO()

            with override_settings(BASE_DIR=base_dir, MEDIA_ROOT=media_root, MEDIA_URL="/media/"):
                call_command(
                    "smoke_runtime_integrations",
                    "--skip-email",
                    "--storage-write",
                    "--storage-prefix",
                    "smoke-test",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"], payload)
            self.assertEqual(payload["summary"]["warning_count"], 0)
            storage_check = payload["checks"][0]
            self.assertEqual(storage_check["key"], "storage")
            self.assertEqual(storage_check["mode"], "write_read_delete")
            self.assertTrue(storage_check["deleted"])
            self.assertFalse((media_root / storage_check["key_written"]).exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_smoke_runtime_integrations_target_gate_requires_smtp_connect(self):
        stdout = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "smoke_runtime_integrations",
                "--skip-storage",
                "--require-smtp-connect",
                "--format",
                "json",
                stdout=stdout,
            )

        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["summary"]["ok"])
        self.assertTrue(payload["summary"]["require_smtp_connect"])
        self.assertIn("SMTP connect was required", payload["errors"][0]["error"])

    def test_smoke_runtime_integrations_target_gate_requires_object_storage(self):
        stdout = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "smoke_runtime_integrations",
                "--skip-email",
                "--storage-write",
                "--require-storage-write",
                "--require-object-storage",
                "--format",
                "json",
                stdout=stdout,
            )

        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["summary"]["ok"])
        self.assertTrue(payload["summary"]["require_storage_write"])
        self.assertTrue(payload["summary"]["require_object_storage"])
        self.assertIn("driver is local", payload["errors"][0]["error"])

    def test_smoke_runtime_integrations_fail_on_warning_blocks_dry_run(self):
        stdout = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "smoke_runtime_integrations",
                "--fail-on-warning",
                "--format",
                "json",
                stdout=stdout,
            )

        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["summary"]["ok"])
        self.assertTrue(payload["summary"]["fail_on_warning"])
        self.assertGreaterEqual(payload["summary"]["warning_count"], 1)
        self.assertTrue(any("not attempted" in item["error"] for item in payload["errors"]))

    def test_smoke_runtime_integrations_smtp_connect_reports_failure(self):
        stdout = StringIO()

        with patch(
            "bias_core.management.commands.smoke_runtime_integrations.get_connection",
            side_effect=OSError("network blocked"),
        ):
            with self.assertRaises(CommandError):
                call_command(
                    "smoke_runtime_integrations",
                    "--skip-storage",
                    "--smtp-connect",
                    "--format",
                    "json",
                    stdout=stdout,
                )

        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["summary"]["ok"])
        self.assertEqual(payload["summary"]["error_count"], 1)
        email_check = payload["checks"][0]
        self.assertEqual(email_check["key"], "email")
        self.assertEqual(email_check["mode"], "smtp_connect")
        self.assertIn("network blocked", email_check["error"])

    def test_validate_target_environment_evidence_rejects_production_smoke_only_evidence(self):
        temp_dir = make_workspace_temp_dir()
        try:
            report_dir = Path(temp_dir) / "reports"
            report_dir.mkdir(parents=True)
            self._write_complete_target_evidence(report_dir)
            self._write_json(report_dir / "smoke-http-p95.json", {
                "base_url": "http://127.0.0.1:8000",
                "summary": {"ok": True},
            })
            self._write_json(report_dir / "post-upgrade-smoke-http-p95.json", {
                "base_url": "http://127.0.0.1:8000",
                "summary": {"ok": True},
            })
            for filename in ("smoke-queue-worker.json", "post-upgrade-smoke-queue-worker.json"):
                self._write_json(report_dir / filename, {
                    "broker_url": "redis://redis:6379/1",
                    "result_backend": "redis://redis:6379/2",
                    "token": "queue-smoke-local",
                    "worker_status": {"available": True, "worker_count": 1},
                    "task_result": {"ok": True, "token": "queue-smoke-local"},
                    "summary": {"ok": True},
                })
            self._write_json(report_dir / "backup-forum.json", {
                "backup_dir": "/app/backups/20260702-p2-smoke",
                "backup_artifacts": [
                    {"key": "site_config", "path": "/app/backups/20260702-p2-smoke/site.json", "required": True, "exists": True},
                    {"key": "database", "path": "/app/backups/20260702-p2-smoke/database.dump", "required": True, "exists": True},
                    {"key": "media", "path": "/app/backups/20260702-p2-smoke/media", "required": True, "exists": True},
                    {"key": "static_frontend", "path": "/app/backups/20260702-p2-smoke/static/frontend", "required": True, "exists": True},
                ],
                "summary": {
                    "ok": True,
                    "dry_run": False,
                    "missing_required_artifact_count": 0,
                },
            })
            self._write_json(report_dir / "verify-forum-backup.json", {
                "backup_dir": "/app/backups/20260702-p2-smoke",
                "checks": [
                    {"key": "site_config", "path": "/app/backups/20260702-p2-smoke/site.json", "exists": True, "ok": True},
                    {"key": "database", "path": "/app/backups/20260702-p2-smoke/database.dump", "exists": True, "ok": True, "database_mode": "postgres", "validated_by": "pg_restore_list"},
                    {"key": "media", "path": "/app/backups/20260702-p2-smoke/media", "exists": True, "ok": True},
                    {"key": "static_frontend", "path": "/app/backups/20260702-p2-smoke/static/frontend", "exists": True, "ok": True},
                ],
                "summary": {
                    "ok": True,
                    "error_count": 0,
                },
            })
            self._write_json(report_dir / "restore-forum-backup-dry-run.json", {
                "backup_dir": "/app/backups/20260702-p2-smoke",
                "backup_artifacts": [
                    {"key": "database", "path": "/app/backups/20260702-p2-smoke/database.dump", "required": True, "exists": True},
                    {"key": "media", "path": "/app/backups/20260702-p2-smoke/media", "required": True, "exists": True},
                    {"key": "static_frontend", "path": "/app/backups/20260702-p2-smoke/static/frontend", "required": True, "exists": True},
                    {"key": "site_config", "path": "/app/backups/20260702-p2-smoke/site.json", "required": True, "exists": True},
                ],
                "restore_steps": [
                    {"artifact_key": "database", "source": "/app/backups/20260702-p2-smoke/database.dump", "destructive": True, "planned_only": True, "ok": True},
                    {"artifact_key": "media", "source": "/app/backups/20260702-p2-smoke/media", "destructive": True, "planned_only": True, "ok": True},
                    {"artifact_key": "static_frontend", "source": "/app/backups/20260702-p2-smoke/static/frontend", "destructive": True, "planned_only": True, "ok": True},
                    {"artifact_key": "site_config", "source": "/app/backups/20260702-p2-smoke/site.json", "destructive": True, "planned_only": True, "ok": True},
                ],
                "summary": {
                    "ok": True,
                    "dry_run": True,
                    "destructive": True,
                    "executes_live_restore": False,
                },
            })
            self._write_json(report_dir / "plan-forum-rollback-with-backups.json", {
                "backup_dir": "/app/backups/20260702-p2-smoke",
                "backup_artifacts": [
                    {"key": "site_config", "path": "/app/backups/20260702-p2-smoke/site.json", "required": True, "exists": True},
                    {"key": "database", "path": "/app/backups/20260702-p2-smoke/database.dump", "required": True, "exists": True},
                    {"key": "media", "path": "/app/backups/20260702-p2-smoke/media", "required": True, "exists": True},
                    {"key": "static_frontend", "path": "/app/backups/20260702-p2-smoke/static/frontend", "required": True, "exists": True},
                ],
                "restore_steps": [
                    {"action": "restore_database", "destructive": True, "artifact_key": "database"},
                    {"action": "restore_media", "destructive": True, "artifact_key": "media"},
                    {"action": "restore_static_frontend", "destructive": True, "artifact_key": "static_frontend"},
                    {"action": "restore_site_config", "destructive": True, "artifact_key": "site_config"},
                ],
                "summary": {
                    "ok": True,
                    "require_existing_backups": True,
                    "missing_required_artifact_count": 0,
                    "executes_restore": False,
                },
            })
            self._write_json(report_dir / "rehearse-forum-restore.json", {
                "backup_dir": "/app/backups/20260702-p2-smoke",
                "database_mode": "postgres",
                "backup_artifacts": [
                    {"key": "site_config", "path": "/app/backups/20260702-p2-smoke/site.json", "required": True, "exists": True},
                    {"key": "database", "path": "/app/backups/20260702-p2-smoke/database.dump", "required": True, "exists": True},
                    {"key": "media", "path": "/app/backups/20260702-p2-smoke/media", "required": True, "exists": True},
                    {"key": "static_frontend", "path": "/app/backups/20260702-p2-smoke/static/frontend", "required": True, "exists": True},
                ],
                "restore_steps": [
                    {"action": "restore_site_config_to_temp_file", "artifact_key": "site_config", "source": "/app/backups/20260702-p2-smoke/site.json", "destructive": False, "ok": True},
                    {"action": "create_temp_database", "destructive": False, "ok": True},
                    {"action": "restore_dump_to_temp_database", "destructive": False, "ok": True},
                    {"action": "verify_temp_database", "destructive": False, "ok": True},
                    {"action": "drop_temp_database", "destructive": False, "ok": True},
                    {"action": "restore_media_to_temp_directory", "artifact_key": "media", "source": "/app/backups/20260702-p2-smoke/media", "destructive": False, "ok": True},
                    {"action": "restore_static_frontend_to_temp_directory", "artifact_key": "static_frontend", "source": "/app/backups/20260702-p2-smoke/static/frontend", "destructive": False, "ok": True},
                ],
                "verification": [
                    {"key": "site_config", "ok": True, "validated_by": "read_site_config"},
                    {"key": "database", "ok": True, "validated_by": "pg_restore_temp_database", "table_count": 31},
                    {"key": "media", "ok": True, "validated_by": "copytree_to_temp_directory"},
                    {"key": "static_frontend", "ok": True, "validated_by": "copytree_to_temp_directory"},
                ],
                "summary": {
                    "ok": True,
                    "executes_live_restore": False,
                    "uses_isolated_restore_targets": True,
                    "keep_temp_database": False,
                    "dropped_temp_database": True,
                },
            })
            self._write_json(report_dir / "load-websocket-external-20.json", {
                "url": "ws://127.0.0.1:8000/ws/forum/",
                "summary": {
                    "ok": True,
                    "connection_count": 20,
                    "expected_connection_count": 20,
                    "broadcast_count": 20,
                    "expected_broadcast_count": 20,
                },
            })
            self._write_json(report_dir / "smoke-runtime-integrations.json", {
                "checks": [
                    {"key": "email", "mode": "config_dry_run", "ok": True},
                    {"key": "storage", "mode": "write_read_delete", "driver": "local", "deleted": True, "ok": True},
                ],
                "summary": {
                    "ok": True,
                    "fail_on_warning": False,
                    "require_smtp_connect": False,
                    "require_storage_write": False,
                    "require_object_storage": False,
                    "warning_count": 1,
                },
            })
            self._write_json(report_dir / "multi-node-topology.json", {
                "roles": {
                    "web": 1,
                    "worker": 1,
                    "scheduler": 1,
                },
                "artifacts": {
                    "image": "local-production-smoke",
                    "version": "0.1.1",
                },
                "shared_services": {
                    "database": "postgres://postgres:5432/bias_smoke",
                    "redis": "redis://redis:6379/0",
                    "load_balancer": "http://127.0.0.1:8000",
                },
                "summary": {
                    "ok": False,
                    "multi_node": False,
                },
            })
            (report_dir / "restore-forum-backup-live.json").unlink()

            stdout = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "validate_target_environment_evidence",
                    "--report-dir",
                    str(report_dir),
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["summary"]["ok"])
            failed = {check["key"]: check for check in payload["checks"] if not check["ok"]}
            self.assertIn("https_http_smoke", failed)
            self.assertIn("external_websocket", failed)
            self.assertIn("queue_worker", failed)
            self.assertIn("backup", failed)
            self.assertIn("backup_verification", failed)
            self.assertIn("post_upgrade_http_smoke", failed)
            self.assertIn("post_upgrade_queue_worker", failed)
            self.assertIn("runtime_integrations", failed)
            self.assertIn("rollback_plan", failed)
            self.assertIn("restore_rehearsal", failed)
            self.assertIn("restore_dry_run", failed)
            self.assertIn("live_restore", failed)
            self.assertIn("multi_node_topology", failed)
            self.assertIn("p0_capacity_suite", failed)
            self.assertIn("p1_capacity_suite", failed)
            self.assertIn("base_url must use https", failed["https_http_smoke"]["errors"][0])
            self.assertIn("base_url must use https", failed["post_upgrade_http_smoke"]["errors"][0])
            self.assertIn("broker_url must not point", failed["queue_worker"]["errors"][0])
            self.assertIn("broker_url must not point", failed["post_upgrade_queue_worker"]["errors"][0])
            self.assertIn("backup_dir must be a durable", failed["backup"]["errors"][0])
            self.assertIn("backup_dir must be a durable", failed["backup_verification"]["errors"][0])
            self.assertIn("backup_dir must be a durable", failed["rollback_plan"]["errors"][0])
            self.assertIn("backup_dir must be a durable", failed["restore_rehearsal"]["errors"][0])
            self.assertIn("backup_dir must be a durable", failed["restore_dry_run"]["errors"][0])
            self.assertFalse(failed["multi_node_topology"].get("missing", False))
            self.assertIn("summary.ok must be true", failed["multi_node_topology"]["errors"])
            self.assertIn("artifacts.image must identify a target release image", failed["multi_node_topology"]["errors"])
            self.assertIn("shared_services.redis must identify a shared target service", failed["multi_node_topology"]["errors"])
            self.assertIn("shared_services.load_balancer must use https", failed["multi_node_topology"]["errors"])
            self.assertTrue(failed["live_restore"]["missing"])
            self.assertTrue(payload["remediation"]["blocked"])
            self.assertIn("restore-forum-backup-live.json", payload["remediation"]["missing_files"])
            remediation_by_key = {item["key"]: item for item in payload["remediation"]["actions"]}
            self.assertTrue(remediation_by_key["live_restore"]["missing"])
            self.assertIn("destructive live restore", remediation_by_key["live_restore"]["hint"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_target_environment_evidence_accepts_complete_target_report(self):
        temp_dir = make_workspace_temp_dir()
        try:
            report_dir = Path(temp_dir) / "reports"
            p0_report_dir = Path(temp_dir) / "p0"
            p1_report_dir = Path(temp_dir) / "p1"
            report_dir.mkdir(parents=True)
            p0_report_dir.mkdir(parents=True)
            p1_report_dir.mkdir(parents=True)
            self._write_complete_target_evidence(report_dir)
            self._write_p0_capacity_evidence(p0_report_dir)
            self._write_p1_capacity_evidence(p1_report_dir)
            plan_path = report_dir / "target-environment-evidence-plan.json"
            self._write_complete_target_evidence_plan(plan_path, report_dir, p0_report_dir, p1_report_dir)

            stdout = StringIO()
            call_command(
                "validate_target_environment_evidence",
                "--report-dir",
                str(report_dir),
                "--p0-report-dir",
                str(p0_report_dir),
                "--p1-report-dir",
                str(p1_report_dir),
                "--plan-file",
                str(plan_path),
                "--require-multi-node",
                "--format",
                "json",
                stdout=stdout,
            )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"], payload)
            self.assertEqual(payload["summary"]["failed_count"], 0)
            self.assertEqual(payload["summary"]["missing_count"], 0)
            self.assertEqual(payload["summary"]["remediation_action_count"], 0)
            self.assertTrue(payload["summary"]["target_environment_ready"])
            self.assertEqual(payload["summary"]["check_count"], 24)
            self.assertEqual(payload["plan_file"], str(plan_path))
            check_keys = {check["key"] for check in payload["checks"]}
            self.assertIn("target_evidence_plan", check_keys)
            self.assertIn("target_dependency_evidence", check_keys)
            self.assertIn("target_plan_evidence_alignment", check_keys)
            self.assertIn("target_archive_integrity", check_keys)
            self.assertFalse(payload["remediation"]["blocked"])
            self.assertEqual(payload["remediation"]["actions"], [])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_target_environment_evidence_rejects_failed_dependency_evidence(self):
        temp_dir = make_workspace_temp_dir()
        try:
            report_dir = Path(temp_dir) / "reports"
            p0_report_dir = Path(temp_dir) / "p0"
            p1_report_dir = Path(temp_dir) / "p1"
            report_dir.mkdir(parents=True)
            p0_report_dir.mkdir(parents=True)
            p1_report_dir.mkdir(parents=True)
            self._write_complete_target_evidence(report_dir)
            self._write_p0_capacity_evidence(p0_report_dir)
            self._write_p1_capacity_evidence(p1_report_dir)
            plan_path = report_dir / "target-environment-evidence-plan.json"
            self._write_complete_target_evidence_plan(plan_path, report_dir, p0_report_dir, p1_report_dir)

            upgrade_payload = json.loads((report_dir / "upgrade-forum-executed.json").read_text(encoding="utf-8"))
            upgrade_payload["summary"]["executed"] = False
            self._write_json(report_dir / "upgrade-forum-executed.json", upgrade_payload)

            backup_verification_payload = json.loads((report_dir / "verify-forum-backup.json").read_text(encoding="utf-8"))
            backup_verification_payload["summary"]["ok"] = False
            backup_verification_payload["summary"]["error_count"] = 1
            self._write_json(report_dir / "verify-forum-backup.json", backup_verification_payload)

            stdout = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "validate_target_environment_evidence",
                    "--report-dir",
                    str(report_dir),
                    "--p0-report-dir",
                    str(p0_report_dir),
                    "--p1-report-dir",
                    str(p1_report_dir),
                    "--plan-file",
                    str(plan_path),
                    "--require-multi-node",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            failed = {check["key"]: check for check in payload["checks"] if not check["ok"]}
            self.assertIn("upgrade_executed", failed)
            self.assertIn("backup_verification", failed)
            self.assertIn("target_dependency_evidence", failed)
            dependency_errors = failed["target_dependency_evidence"]["errors"]
            self.assertTrue(any("dependency upgrade_executed failed" in error for error in dependency_errors))
            self.assertTrue(any("dependency backup_verification failed" in error for error in dependency_errors))
            self.assertEqual(
                failed["target_dependency_evidence"]["details"]["failed_dependency_keys"],
                ["upgrade_executed", "backup_verification"],
            )
            self.assertEqual(
                failed["target_dependency_evidence"]["details"]["blocked_command_keys"],
                [
                    "post_upgrade_strict_health",
                    "post_upgrade_http_smoke",
                    "post_upgrade_queue_worker",
                    "restore_rehearsal",
                    "restore_dry_run",
                    "live_restore",
                ],
            )
            actions = {item["key"]: item for item in payload["remediation"]["actions"]}
            planned_keys = [
                command["key"]
                for command in actions["target_dependency_evidence"]["planned_commands"]
            ]
            self.assertEqual(
                planned_keys,
                [
                    "upgrade_executed",
                    "backup_verification",
                    "post_upgrade_strict_health",
                    "post_upgrade_http_smoke",
                    "post_upgrade_queue_worker",
                    "restore_rehearsal",
                    "restore_dry_run",
                    "live_restore",
                ],
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_target_environment_evidence_rejects_weak_capacity_dependency_evidence(self):
        temp_dir = make_workspace_temp_dir()
        try:
            report_dir = Path(temp_dir) / "reports"
            p0_report_dir = Path(temp_dir) / "p0"
            p1_report_dir = Path(temp_dir) / "p1"
            report_dir.mkdir(parents=True)
            p0_report_dir.mkdir(parents=True)
            p1_report_dir.mkdir(parents=True)
            self._write_complete_target_evidence(report_dir)
            self._write_p0_capacity_evidence(p0_report_dir)
            self._write_p1_capacity_evidence(p1_report_dir)
            plan_path = report_dir / "target-environment-evidence-plan.json"
            self._write_complete_target_evidence_plan(plan_path, report_dir, p0_report_dir, p1_report_dir)

            p1_write_payload = json.loads((p1_report_dir / "forum-write-120s.json").read_text(encoding="utf-8"))
            p1_write_payload["base_url"] = "http://127.0.0.1:8000"
            p1_write_payload["profile"] = "forum-main"
            p1_write_payload["concurrency"] = 1
            p1_write_payload["duration_seconds"] = 30
            p1_write_payload["summary"]["ok"] = True
            self._write_json(p1_report_dir / "forum-write-120s.json", p1_write_payload)

            stdout = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "validate_target_environment_evidence",
                    "--report-dir",
                    str(report_dir),
                    "--p0-report-dir",
                    str(p0_report_dir),
                    "--p1-report-dir",
                    str(p1_report_dir),
                    "--plan-file",
                    str(plan_path),
                    "--require-multi-node",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            failed = {check["key"]: check for check in payload["checks"] if not check["ok"]}
            self.assertIn("p1_capacity_suite", failed)
            self.assertIn("target_dependency_evidence", failed)
            dependency_errors = failed["target_dependency_evidence"]["errors"]
            self.assertTrue(any("dependency p1_forum_write failed" in error for error in dependency_errors))
            self.assertTrue(any("profile must be forum-write" in error for error in dependency_errors))
            self.assertEqual(
                failed["target_dependency_evidence"]["details"]["failed_dependency_keys"],
                ["p1_forum_write"],
            )
            self.assertEqual(
                failed["target_dependency_evidence"]["details"]["blocked_command_keys"],
                ["p1_forum_write_mixed"],
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_target_environment_evidence_rejects_misaligned_dependency_evidence(self):
        temp_dir = make_workspace_temp_dir()
        try:
            report_dir = Path(temp_dir) / "reports"
            p0_report_dir = Path(temp_dir) / "p0"
            p1_report_dir = Path(temp_dir) / "p1"
            report_dir.mkdir(parents=True)
            p0_report_dir.mkdir(parents=True)
            p1_report_dir.mkdir(parents=True)
            self._write_complete_target_evidence(report_dir)
            self._write_p0_capacity_evidence(p0_report_dir)
            self._write_p1_capacity_evidence(p1_report_dir)
            plan_path = report_dir / "target-environment-evidence-plan.json"
            self._write_complete_target_evidence_plan(plan_path, report_dir, p0_report_dir, p1_report_dir)

            p1_write_payload = json.loads((p1_report_dir / "forum-write-120s.json").read_text(encoding="utf-8"))
            p1_write_payload["login_username"] = "stale-load-user"
            self._write_json(p1_report_dir / "forum-write-120s.json", p1_write_payload)

            stdout = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "validate_target_environment_evidence",
                    "--report-dir",
                    str(report_dir),
                    "--p0-report-dir",
                    str(p0_report_dir),
                    "--p1-report-dir",
                    str(p1_report_dir),
                    "--plan-file",
                    str(plan_path),
                    "--require-multi-node",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            failed = {check["key"]: check for check in payload["checks"] if not check["ok"]}
            self.assertNotIn("p1_capacity_suite", failed)
            self.assertIn("target_plan_evidence_alignment", failed)
            self.assertIn("target_dependency_evidence", failed)
            dependency_errors = failed["target_dependency_evidence"]["errors"]
            self.assertTrue(any("dependency p1_forum_write failed" in error for error in dependency_errors))
            self.assertTrue(any("login_username must match capacity_profile" in error for error in dependency_errors))
            self.assertEqual(
                failed["target_dependency_evidence"]["details"]["failed_dependency_keys"],
                ["p1_forum_write"],
            )
            self.assertEqual(
                failed["target_dependency_evidence"]["details"]["blocked_command_keys"],
                ["p1_forum_write_mixed"],
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_target_environment_evidence_rejects_plan_evidence_mismatch(self):
        temp_dir = make_workspace_temp_dir()
        try:
            report_dir = Path(temp_dir) / "reports"
            p0_report_dir = Path(temp_dir) / "p0"
            p1_report_dir = Path(temp_dir) / "p1"
            report_dir.mkdir(parents=True)
            p0_report_dir.mkdir(parents=True)
            p1_report_dir.mkdir(parents=True)
            self._write_complete_target_evidence(report_dir)
            self._write_p0_capacity_evidence(p0_report_dir)
            self._write_p1_capacity_evidence(p1_report_dir)
            plan_path = report_dir / "target-environment-evidence-plan.json"
            self._write_complete_target_evidence_plan(plan_path, report_dir, p0_report_dir, p1_report_dir)

            websocket_payload = json.loads((report_dir / "load-websocket-external-20.json").read_text(encoding="utf-8"))
            websocket_payload["discussion_id"] = 7
            websocket_payload["summary"]["expected_connection_count"] = 10
            websocket_payload["summary"]["p95_threshold_ms"] = 500
            self._write_json(report_dir / "load-websocket-external-20.json", websocket_payload)

            queue_payload = json.loads((report_dir / "smoke-queue-worker.json").read_text(encoding="utf-8"))
            queue_payload["broker_url"] = "redis://other.target.example:6379/1"
            self._write_json(report_dir / "smoke-queue-worker.json", queue_payload)

            backup_payload = json.loads((report_dir / "backup-forum.json").read_text(encoding="utf-8"))
            backup_payload["backup_dir"] = "s3://bias-target-backups/stale-release"
            self._write_json(report_dir / "backup-forum.json", backup_payload)

            topology_payload = json.loads((report_dir / "multi-node-topology.json").read_text(encoding="utf-8"))
            topology_payload["shared_services"]["load_balancer"] = "https://other.example.test"
            self._write_json(report_dir / "multi-node-topology.json", topology_payload)

            p0_payload = json.loads((p0_report_dir / "forum-main-300s.json").read_text(encoding="utf-8"))
            p0_payload["base_url"] = "https://other.example.test"
            p0_payload["concurrency"] = 10
            self._write_json(p0_report_dir / "forum-main-300s.json", p0_payload)

            p1_mixed_payload = json.loads((p1_report_dir / "forum-write-mixed-120s.json").read_text(encoding="utf-8"))
            p1_mixed_payload["login_username"] = "stale-load-user"
            p1_mixed_payload["prepare_isolated_targets"] = False
            self._write_json(p1_report_dir / "forum-write-mixed-120s.json", p1_mixed_payload)

            p1_moderation_payload = json.loads((p1_report_dir / "forum-write-moderation-60s.json").read_text(encoding="utf-8"))
            p1_moderation_payload["cleanup_isolated_targets"] = False
            self._write_json(p1_report_dir / "forum-write-moderation-60s.json", p1_moderation_payload)

            runtime_payload = json.loads((report_dir / "smoke-runtime-integrations.json").read_text(encoding="utf-8"))
            runtime_payload["checks"][0]["mode"] = "config_dry_run"
            runtime_payload["summary"]["fail_on_warning"] = False
            self._write_json(report_dir / "smoke-runtime-integrations.json", runtime_payload)

            stdout = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "validate_target_environment_evidence",
                    "--report-dir",
                    str(report_dir),
                    "--p0-report-dir",
                    str(p0_report_dir),
                    "--p1-report-dir",
                    str(p1_report_dir),
                    "--plan-file",
                    str(plan_path),
                    "--require-multi-node",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            failed = {check["key"]: check for check in payload["checks"] if not check["ok"]}
            self.assertIn("target_plan_evidence_alignment", failed)
            errors = failed["target_plan_evidence_alignment"]["errors"]
            self.assertIn("commands.external_websocket.evidence discussion_id must match websocket_profile", errors)
            self.assertIn("commands.external_websocket.evidence expected_connection_count must match websocket_profile", errors)
            self.assertIn("commands.queue_worker.evidence broker_url must match plan redis_broker_url", errors)
            self.assertIn("commands.backup.evidence backup_dir must match plan backup_dir", errors)
            self.assertIn("commands.multi_node_topology.evidence topology.load_balancer must match plan", errors)
            self.assertIn("commands.p0_forum_main.evidence base_url must match plan base_url", errors)
            self.assertIn("commands.p0_forum_main.evidence concurrency must match capacity_profile", errors)
            self.assertIn("commands.p1_forum_write_mixed.evidence login_username must match capacity_profile", errors)
            self.assertIn("commands.p1_forum_write_mixed.evidence prepare_isolated_targets must match capacity_profile", errors)
            self.assertIn("commands.p1_forum_moderation.evidence cleanup_isolated_targets must match capacity_profile", errors)
            self.assertIn("commands.runtime_integrations.evidence email mode must match runtime_integration_profile.smtp_connect", errors)
            self.assertIn("commands.runtime_integrations.evidence summary.fail_on_warning must match runtime_integration_profile", errors)
            self.assertEqual(
                failed["target_plan_evidence_alignment"]["details"]["mismatched_command_keys"],
                [
                    "external_websocket",
                    "queue_worker",
                    "backup",
                    "runtime_integrations",
                    "multi_node_topology",
                    "p0_forum_main",
                    "p1_forum_write_mixed",
                    "p1_forum_moderation",
                ],
            )
            actions = {item["key"]: item for item in payload["remediation"]["actions"]}
            planned_keys = [
                command["key"]
                for command in actions["target_plan_evidence_alignment"]["planned_commands"]
            ]
            self.assertEqual(planned_keys, failed["target_plan_evidence_alignment"]["details"]["mismatched_command_keys"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_target_environment_evidence_rejects_plan_archive_stderr_output(self):
        temp_dir = make_workspace_temp_dir()
        try:
            report_dir = Path(temp_dir) / "reports"
            p0_report_dir = Path(temp_dir) / "p0"
            p1_report_dir = Path(temp_dir) / "p1"
            report_dir.mkdir(parents=True)
            p0_report_dir.mkdir(parents=True)
            p1_report_dir.mkdir(parents=True)
            self._write_complete_target_evidence(report_dir)
            self._write_p0_capacity_evidence(p0_report_dir)
            self._write_p1_capacity_evidence(p1_report_dir)
            plan_path = report_dir / "target-environment-evidence-plan.json"
            self._write_complete_target_evidence_plan(plan_path, report_dir, p0_report_dir, p1_report_dir)
            (report_dir / "smoke-http-p95.stderr.txt").write_text("warning: proxy fallback\n", encoding="utf-8")

            stdout = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "validate_target_environment_evidence",
                    "--report-dir",
                    str(report_dir),
                    "--p0-report-dir",
                    str(p0_report_dir),
                    "--p1-report-dir",
                    str(p1_report_dir),
                    "--plan-file",
                    str(plan_path),
                    "--require-multi-node",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            failed = {check["key"]: check for check in payload["checks"] if not check["ok"]}
            self.assertEqual(set(failed), {"target_archive_integrity"})
            self.assertIn(
                "commands.https_http_smoke.stderr_file must be empty",
                failed["target_archive_integrity"]["errors"][0],
            )
            self.assertEqual(
                failed["target_archive_integrity"]["details"]["non_empty_stderr_keys"],
                ["https_http_smoke"],
            )
            self.assertIn("target_archive_integrity", payload["remediation"]["failed_keys"])
            actions = {item["key"]: item for item in payload["remediation"]["actions"]}
            self.assertIn("target_archive_integrity", actions)
            planned_keys = [
                command["key"]
                for command in actions["target_archive_integrity"]["planned_commands"]
            ]
            self.assertEqual(planned_keys, ["https_http_smoke"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_target_environment_evidence_remediation_targets_missing_stderr_archive(self):
        temp_dir = make_workspace_temp_dir()
        try:
            report_dir = Path(temp_dir) / "reports"
            p0_report_dir = Path(temp_dir) / "p0"
            p1_report_dir = Path(temp_dir) / "p1"
            report_dir.mkdir(parents=True)
            p0_report_dir.mkdir(parents=True)
            p1_report_dir.mkdir(parents=True)
            self._write_complete_target_evidence(report_dir)
            self._write_p0_capacity_evidence(p0_report_dir)
            self._write_p1_capacity_evidence(p1_report_dir)
            plan_path = report_dir / "target-environment-evidence-plan.json"
            self._write_complete_target_evidence_plan(plan_path, report_dir, p0_report_dir, p1_report_dir)
            (report_dir / "load-websocket-external-20.stderr.txt").unlink()

            stdout = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "validate_target_environment_evidence",
                    "--report-dir",
                    str(report_dir),
                    "--p0-report-dir",
                    str(p0_report_dir),
                    "--p1-report-dir",
                    str(p1_report_dir),
                    "--plan-file",
                    str(plan_path),
                    "--require-multi-node",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            failed = {check["key"]: check for check in payload["checks"] if not check["ok"]}
            self.assertEqual(set(failed), {"target_archive_integrity"})
            self.assertEqual(
                failed["target_archive_integrity"]["details"]["missing_stderr_keys"],
                ["external_websocket"],
            )
            actions = {item["key"]: item for item in payload["remediation"]["actions"]}
            planned_keys = [
                command["key"]
                for command in actions["target_archive_integrity"]["planned_commands"]
            ]
            self.assertEqual(planned_keys, ["external_websocket"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_target_environment_evidence_remediation_targets_invalid_stderr_archive(self):
        temp_dir = make_workspace_temp_dir()
        try:
            report_dir = Path(temp_dir) / "reports"
            p0_report_dir = Path(temp_dir) / "p0"
            p1_report_dir = Path(temp_dir) / "p1"
            report_dir.mkdir(parents=True)
            p0_report_dir.mkdir(parents=True)
            p1_report_dir.mkdir(parents=True)
            self._write_complete_target_evidence(report_dir)
            self._write_p0_capacity_evidence(p0_report_dir)
            self._write_p1_capacity_evidence(p1_report_dir)
            plan_path = report_dir / "target-environment-evidence-plan.json"
            self._write_complete_target_evidence_plan(plan_path, report_dir, p0_report_dir, p1_report_dir)
            stderr_path = report_dir / "load-websocket-external-20.stderr.txt"
            stderr_path.unlink()
            stderr_path.mkdir()

            stdout = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "validate_target_environment_evidence",
                    "--report-dir",
                    str(report_dir),
                    "--p0-report-dir",
                    str(p0_report_dir),
                    "--p1-report-dir",
                    str(p1_report_dir),
                    "--plan-file",
                    str(plan_path),
                    "--require-multi-node",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            failed = {check["key"]: check for check in payload["checks"] if not check["ok"]}
            self.assertEqual(set(failed), {"target_archive_integrity"})
            self.assertIn(
                "commands.external_websocket.stderr_file is not a file",
                failed["target_archive_integrity"]["errors"][0],
            )
            self.assertEqual(
                failed["target_archive_integrity"]["details"]["missing_stderr_keys"],
                ["external_websocket"],
            )
            actions = {item["key"]: item for item in payload["remediation"]["actions"]}
            planned_keys = [
                command["key"]
                for command in actions["target_archive_integrity"]["planned_commands"]
            ]
            self.assertEqual(planned_keys, ["external_websocket"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_target_environment_evidence_remediation_targets_missing_output_archive(self):
        temp_dir = make_workspace_temp_dir()
        try:
            report_dir = Path(temp_dir) / "reports"
            p0_report_dir = Path(temp_dir) / "p0"
            p1_report_dir = Path(temp_dir) / "p1"
            report_dir.mkdir(parents=True)
            p0_report_dir.mkdir(parents=True)
            p1_report_dir.mkdir(parents=True)
            self._write_complete_target_evidence(report_dir)
            self._write_p0_capacity_evidence(p0_report_dir)
            self._write_p1_capacity_evidence(p1_report_dir)
            plan_path = report_dir / "target-environment-evidence-plan.json"
            self._write_complete_target_evidence_plan(plan_path, report_dir, p0_report_dir, p1_report_dir)
            (report_dir / "load-websocket-external-20.json").unlink()

            stdout = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "validate_target_environment_evidence",
                    "--report-dir",
                    str(report_dir),
                    "--p0-report-dir",
                    str(p0_report_dir),
                    "--p1-report-dir",
                    str(p1_report_dir),
                    "--plan-file",
                    str(plan_path),
                    "--require-multi-node",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            failed = {check["key"]: check for check in payload["checks"] if not check["ok"]}
            self.assertEqual(set(failed), {"external_websocket", "target_archive_integrity"})
            self.assertEqual(
                failed["target_archive_integrity"]["details"]["missing_output_keys"],
                ["external_websocket"],
            )
            actions = {item["key"]: item for item in payload["remediation"]["actions"]}
            planned_keys = [
                command["key"]
                for command in actions["target_archive_integrity"]["planned_commands"]
            ]
            self.assertEqual(planned_keys, ["external_websocket"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_target_environment_evidence_remediation_targets_empty_output_archive(self):
        temp_dir = make_workspace_temp_dir()
        try:
            report_dir = Path(temp_dir) / "reports"
            p0_report_dir = Path(temp_dir) / "p0"
            p1_report_dir = Path(temp_dir) / "p1"
            report_dir.mkdir(parents=True)
            p0_report_dir.mkdir(parents=True)
            p1_report_dir.mkdir(parents=True)
            self._write_complete_target_evidence(report_dir)
            self._write_p0_capacity_evidence(p0_report_dir)
            self._write_p1_capacity_evidence(p1_report_dir)
            plan_path = report_dir / "target-environment-evidence-plan.json"
            self._write_complete_target_evidence_plan(plan_path, report_dir, p0_report_dir, p1_report_dir)
            (report_dir / "load-websocket-external-20.json").write_text("", encoding="utf-8")

            stdout = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "validate_target_environment_evidence",
                    "--report-dir",
                    str(report_dir),
                    "--p0-report-dir",
                    str(p0_report_dir),
                    "--p1-report-dir",
                    str(p1_report_dir),
                    "--plan-file",
                    str(plan_path),
                    "--require-multi-node",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            failed = {check["key"]: check for check in payload["checks"] if not check["ok"]}
            self.assertEqual(set(failed), {"external_websocket", "target_archive_integrity"})
            self.assertIn(
                "commands.external_websocket.output_file is empty",
                failed["target_archive_integrity"]["errors"][0],
            )
            self.assertEqual(
                failed["target_archive_integrity"]["details"]["missing_output_keys"],
                ["external_websocket"],
            )
            actions = {item["key"]: item for item in payload["remediation"]["actions"]}
            planned_keys = [
                command["key"]
                for command in actions["target_archive_integrity"]["planned_commands"]
            ]
            self.assertEqual(planned_keys, ["external_websocket"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_target_environment_evidence_checklist_identifies_stderr_archive_keys(self):
        temp_dir = make_workspace_temp_dir()
        try:
            report_dir = Path(temp_dir) / "reports"
            p0_report_dir = Path(temp_dir) / "p0"
            p1_report_dir = Path(temp_dir) / "p1"
            checklist_path = Path(temp_dir) / "follow-up" / "target-remediation.md"
            report_dir.mkdir(parents=True)
            p0_report_dir.mkdir(parents=True)
            p1_report_dir.mkdir(parents=True)
            self._write_complete_target_evidence(report_dir)
            self._write_p0_capacity_evidence(p0_report_dir)
            self._write_p1_capacity_evidence(p1_report_dir)
            plan_path = report_dir / "target-environment-evidence-plan.json"
            self._write_complete_target_evidence_plan(plan_path, report_dir, p0_report_dir, p1_report_dir)
            (report_dir / "health-strict.json").unlink()
            (report_dir / "smoke-http-p95.stderr.txt").write_text("warning: proxy fallback\n", encoding="utf-8")
            (report_dir / "load-websocket-external-20.stderr.txt").unlink()

            stdout = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "validate_target_environment_evidence",
                    "--report-dir",
                    str(report_dir),
                    "--p0-report-dir",
                    str(p0_report_dir),
                    "--p1-report-dir",
                    str(p1_report_dir),
                    "--plan-file",
                    str(plan_path),
                    "--write-remediation-checklist",
                    str(checklist_path),
                    "--require-multi-node",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            actions = {item["key"]: item for item in payload["remediation"]["actions"]}
            self.assertEqual(
                actions["target_archive_integrity"]["details"]["missing_output_keys"],
                ["strict_health"],
            )
            self.assertEqual(
                actions["target_archive_integrity"]["details"]["missing_stderr_keys"],
                ["external_websocket"],
            )
            self.assertEqual(
                actions["target_archive_integrity"]["details"]["non_empty_stderr_keys"],
                ["https_http_smoke"],
            )
            checklist = checklist_path.read_text(encoding="utf-8")
            self.assertIn("missing_output_keys: `strict_health`", checklist)
            self.assertIn("missing_stderr_keys: `external_websocket`", checklist)
            self.assertIn("non_empty_stderr_keys: `https_http_smoke`", checklist)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_target_environment_evidence_rejects_stale_or_template_plan_file(self):
        temp_dir = make_workspace_temp_dir()
        try:
            report_dir = Path(temp_dir) / "reports"
            p0_report_dir = Path(temp_dir) / "p0"
            p1_report_dir = Path(temp_dir) / "p1"
            report_dir.mkdir(parents=True)
            p0_report_dir.mkdir(parents=True)
            p1_report_dir.mkdir(parents=True)
            self._write_complete_target_evidence(report_dir)
            self._write_p0_capacity_evidence(p0_report_dir)
            self._write_p1_capacity_evidence(p1_report_dir)
            plan_path = report_dir / "target-environment-evidence-plan.json"
            self._write_complete_target_evidence_plan(plan_path, report_dir, p0_report_dir, p1_report_dir)
            plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
            plan_payload["schema_version"] = 2
            plan_payload["base_url"] = "http://127.0.0.1:8000"
            plan_payload["backup_dir"] = "<durable-backup-uri>"
            plan_payload["remediation_checklist"] = str(report_dir / "stale-remediation-checklist.md")
            plan_payload["errors"] = ["stale plan error", ""]
            plan_payload["warnings"] = ["stale plan warning", 7]
            plan_payload["commands"][1]["requires_substitution"] = True
            plan_payload["commands"][1]["substitution_tokens"] = ["<target-token>", ""]
            plan_payload["commands"][1]["safe_to_run_unattended"] = "true"
            plan_payload["commands"][1]["exists"] = "true"
            queue_worker = next(
                item for item in plan_payload["commands"]
                if item["key"] == "queue_worker"
            )
            queue_worker["command"] = queue_worker["command"].replace(
                "python manage.py smoke_queue_worker",
                "python manage.py stale_queue_worker",
            )
            queue_worker["output_file"] = str(report_dir / "wrong-smoke-queue-worker.json")
            queue_worker["archive_command"] = queue_worker["archive_command"].replace(
                "smoke-queue-worker.json",
                "wrong-smoke-queue-worker.json",
            ) + " # stale redirect"
            queue_worker["redis_broker_url"] = "redis://stale.example.test:6379/1"
            queue_worker["redis_result_backend"] = "redis://stale.example.test:6379/2"
            backup = next(
                item for item in plan_payload["commands"]
                if item["key"] == "backup"
            )
            backup["command"] = backup["command"].replace(
                "s3://bias-target-backups/release-001",
                "s3://bias-target-backups/stale-release",
            )
            backup["archive_command"] = backup["archive_command"].replace(
                "s3://bias-target-backups/release-001",
                "s3://bias-target-backups/stale-release",
            )
            backup["backup_dir"] = "s3://bias-target-backups/stale-release"
            install_dry_run = next(
                item for item in plan_payload["commands"]
                if item["key"] == "install_dry_run"
            )
            install_dry_run["command"] = install_dry_run["command"].replace(
                "--dry-run",
                "--skip-dry-run",
            )
            strict_health = next(
                item for item in plan_payload["commands"]
                if item["key"] == "strict_health"
            )
            strict_health["archive_command"] = strict_health["archive_command"].replace(
                "python manage.py smoke_runtime_integrations",
                "python manage.py stale_runtime_integrations",
                1,
            )
            strict_health["command"] = ""
            https_smoke = next(
                item for item in plan_payload["commands"]
                if item["key"] == "https_http_smoke"
            )
            https_smoke["phase"] = ""
            https_smoke["command"] = https_smoke["command"].replace(
                "https://forum.example.test",
                "https://stale.example.test",
            )
            https_smoke["archive_command"] = https_smoke["archive_command"].replace(
                "https://forum.example.test",
                "https://stale.example.test",
            )
            https_smoke["base_url"] = "https://stale.example.test"
            install_dry_run["base_url"] = "https://stale.example.test"
            install_dry_run["backup_dir"] = "s3://bias-target-backups/stale-release"
            install_dry_run["redis_broker_url"] = "redis://stale.example.test:6379/1"
            install_dry_run["redis_result_backend"] = "redis://stale.example.test:6379/2"
            install_dry_run["topology"] = {"image": "registry.example.test/stale:1"}
            install_dry_run["capacity_profile"] = {"profile": "stale-profile"}
            multi_node_topology = next(
                item for item in plan_payload["commands"]
                if item["key"] == "multi_node_topology"
            )
            multi_node_topology["topology"] = {
                "web_nodes": "3",
                "worker_nodes": "3",
                "scheduler_nodes": "2",
                "image": "registry.example.test/stale:1",
                "app_version": "stale",
                "database_endpoint": "postgres.stale.example:5432/bias",
                "redis_endpoint": "redis.stale.example:6379",
                "load_balancer": "https://stale.example.test",
            }
            final_validation = next(
                item for item in plan_payload["commands"]
                if item["key"] == "validate_target_environment_evidence"
            )
            final_validation["command"] = final_validation["command"].replace(
                f" --plan-file {plan_path}",
                "",
            )
            final_validation["archive_command"] = final_validation["archive_command"].replace(
                f" --plan-file {plan_path}",
                "",
            )
            checklist_path = report_dir / "target-environment-remediation-checklist.md"
            final_validation["command"] = final_validation["command"].replace(
                f" --write-remediation-checklist {checklist_path}",
                "",
            )
            final_validation["archive_command"] = final_validation["archive_command"].replace(
                f" --write-remediation-checklist {checklist_path}",
                "",
            )
            final_validation["validation_profile"] = {
                "plan_file": str(report_dir / "stale-plan.json"),
                "remediation_checklist": str(report_dir / "stale-checklist.md"),
                "require_multi_node": "false",
            }
            final_validation["manual_approval_required"] = True
            final_validation["destructive"] = True
            final_validation["safe_archive_ready"] = True
            plan_payload["safe_archive_commands"].extend(["", 7])
            plan_payload["safe_archive_manifest"][0]["archive_command"] = "python manage.py stale-safe-command"
            plan_payload["safe_archive_manifest"][0]["safe_archive_ready"] = "true"
            plan_payload["safe_archive_manifest"][0]["exists"] = not plan_payload["commands"][0]["exists"]
            plan_payload["safe_archive_manifest"][3], plan_payload["safe_archive_manifest"][4] = (
                plan_payload["safe_archive_manifest"][4],
                plan_payload["safe_archive_manifest"][3],
            )
            plan_payload["excluded_from_safe_archive"][1], plan_payload["excluded_from_safe_archive"][2] = (
                plan_payload["excluded_from_safe_archive"][2],
                plan_payload["excluded_from_safe_archive"][1],
            )
            plan_payload["command_groups"]["safe_unattended"]["command_count"] = 99
            plan_payload["command_groups"]["safe_unattended"]["command_keys"] = ["strict_health"]
            plan_payload["command_groups"]["safe_unattended"]["command_keys"].append("")
            plan_payload["command_groups"]["safe_unattended"]["commands"][0] = "python manage.py stale-group-command"
            plan_payload["command_groups"]["safe_unattended"]["output_files"][0] = str(report_dir / "stale-group-output.json")
            plan_payload["command_groups"]["safe_unattended"]["archive_commands"].append(7)
            plan_payload["command_groups"]["safe_unattended"]["requires_substitution"] = False
            plan_payload["command_groups"]["safe_unattended"]["safe_to_run_unattended"] = "true"
            plan_payload["execution_sequence"][0]["step"] = 2
            plan_payload["execution_sequence"][0]["command_keys"] = ["strict_health"]
            plan_payload["execution_sequence"][-1]["groups"] = ["safe_unattended"]
            plan_payload["execution_sequence"].append("not-a-sequence-object")
            plan_payload["execution_queues"]["safe_unattended"]["command_count"] = 99
            plan_payload["execution_queues"]["safe_unattended"]["command_keys"] = ["strict_health"]
            plan_payload["execution_queues"]["safe_unattended"]["command_keys"].append("")
            plan_payload["execution_queues"]["safe_unattended"]["commands"][0]["command"] = "python manage.py stale-queue-command"
            plan_payload["execution_queues"]["safe_unattended"]["commands"].append("not-a-queue-command")
            plan_payload["execution_queues"]["safe_unattended"]["archive_commands"][0] = "python manage.py stale-queue-archive"
            plan_payload["execution_queues"]["safe_unattended"]["archive_commands"].append(7)
            plan_payload["dependency_execution_waves"][0]["command_keys"] = ["stale_dependency_wave"]
            plan_payload["dependency_execution_waves"].append("not-a-wave-object")
            plan_payload["manual_approval_commands"] = []
            plan_payload["final_validation_commands"] = []
            plan_payload["substitution_required_commands"] = []
            plan_payload["dependency_blocked_commands"] = []
            plan_payload["target_value_required_commands"] = [{
                "key": "stale_target_value",
                "execution_group": "target_value_required",
            }]
            plan_payload["manual_approval_commands"].append("not-a-manual-command")
            plan_payload["final_validation_commands"].append("not-a-final-command")
            plan_payload["substitution_required_commands"].append("not-a-substitution-command")
            plan_payload["target_value_required_commands"].append("not-a-target-value-command")
            plan_payload["dependency_blocked_commands"].append("not-a-dependency-command")
            plan_payload["summary"]["manual_approval_command_count"] = 0
            plan_payload["summary"]["final_validation_command_count"] = 0
            plan_payload["summary"]["substitution_required_command_count"] = 0
            plan_payload["summary"]["target_value_required_command_count"] = 99
            plan_payload["summary"]["dependency_blocked_command_count"] = 0
            plan_payload["summary"]["dependency_execution_wave_count"] = 99
            plan_payload["summary"]["execution_queue_counts"]["safe_unattended"] = 99
            plan_payload["summary"]["destructive_command_count"] = 0
            plan_payload["summary"]["missing_output_count"] = 99
            plan_payload["summary"]["safe_archive_ready_command_count"] = 99
            plan_payload["summary"]["excluded_from_safe_archive_count"] = 99
            excluded_live_restore = next(
                item for item in plan_payload["excluded_from_safe_archive"]
                if item["key"] == "live_restore"
            )
            excluded_live_restore["target_value_errors"] = ["stale target error", 7]
            excluded_live_restore["safe_to_run_unattended"] = "false"
            excluded_live_restore["exclude_reasons"].append("")
            excluded_live_restore["exclude_reasons"].append("not_safe_to_run_unattended")
            live_restore_command = next(
                item for item in plan_payload["commands"]
                if item["key"] == "live_restore"
            )
            live_restore_command["execution_group"] = "safe_unattended"
            live_restore_command["destructive"] = False
            live_restore_command["manual_approval_required"] = False
            live_restore_command["safe_to_run_unattended"] = True
            live_restore_command["safe_archive_ready"] = True
            upgrade_executed = next(
                item for item in plan_payload["commands"]
                if item["key"] == "upgrade_executed"
            )
            upgrade_executed["manual_approval_required"] = False
            upgrade_executed["safe_to_run_unattended"] = True
            upgrade_executed["safe_archive_ready"] = True
            p0_forum_main = next(
                item for item in plan_payload["commands"]
                if item["key"] == "p0_forum_main"
            )
            p0_forum_main["phase"] = "ops"
            p0_forum_main["command"] = p0_forum_main["command"].replace(
                "--profile forum-main",
                "--profile forum-main-auth",
            )
            p0_forum_main["capacity_profile"] = {
                "profile": "forum-stale",
                "concurrency": "1",
                "duration": "30",
            }
            external_websocket = next(
                item for item in plan_payload["commands"]
                if item["key"] == "external_websocket"
            )
            external_websocket["websocket_profile"] = {
                "connections": "1",
                "discussion_id": "",
                "p95_threshold_ms": "250",
                "broadcast_p95_threshold_ms": "250",
                "fail_on_threshold": "false",
            }
            runtime_integrations = next(
                item for item in plan_payload["commands"]
                if item["key"] == "runtime_integrations"
            )
            runtime_integrations["runtime_integration_profile"] = {
                "smtp_connect": "false",
                "storage_write": "true",
                "require_smtp_connect": "true",
                "require_storage_write": "true",
                "require_object_storage": "true",
                "fail_on_warning": "true",
            }
            post_upgrade_http = next(
                item for item in plan_payload["commands"]
                if item["key"] == "post_upgrade_http_smoke"
            )
            post_upgrade_http["requires_completed_commands"] = ["missing_dependency", ""]
            post_upgrade_http["safe_archive_ready"] = True
            restore_dry_run = next(
                item for item in plan_payload["commands"]
                if item["key"] == "restore_dry_run"
            )
            restore_dry_run["requires_completed_commands"] = ["backup_verification"]
            live_restore_dependencies = next(
                item for item in plan_payload["commands"]
                if item["key"] == "live_restore"
            )
            live_restore_dependencies["requires_completed_commands"] = ["backup_verification"]
            excluded_post_upgrade_strict = next(
                item for item in plan_payload["excluded_from_safe_archive"]
                if item["key"] == "post_upgrade_strict_health"
            )
            excluded_post_upgrade_strict["target_value_errors"] = ["stale target error"]
            excluded_post_upgrade_strict["exclude_reasons"].append("not_safe_to_run_unattended")
            post_upgrade_strict = next(
                item for item in plan_payload["commands"]
                if item["key"] == "post_upgrade_strict_health"
            )
            post_upgrade_strict["requires_completed_commands"] = ["post_upgrade_strict_health"]
            p1_write = next(
                item for item in plan_payload["commands"]
                if item["key"] == "p1_forum_write"
            )
            p1_write["requires_completed_commands"] = ["p1_forum_moderation"]
            plan_payload["commands"].append("not-a-command-object")
            duplicate_command = dict(plan_payload["commands"][0])
            duplicate_command["output_file"] = plan_payload["commands"][1]["output_file"]
            duplicate_command["stderr_file"] = plan_payload["commands"][1]["stderr_file"]
            plan_payload["commands"].append(duplicate_command)
            unexpected_command = dict(plan_payload["commands"][0])
            unexpected_command["key"] = "unexpected_target_command"
            unexpected_command["output_file"] = str(report_dir / "unexpected-target-command.json")
            unexpected_command["stderr_file"] = str(report_dir / "unexpected-target-command.stderr.txt")
            unexpected_command["archive_command"] = (
                f"{unexpected_command['command']} > {unexpected_command['output_file']} "
                f"2> {unexpected_command['stderr_file']}"
            )
            plan_payload["commands"].append(unexpected_command)
            plan_payload["safe_archive_manifest"].insert(1, dict(plan_payload["safe_archive_manifest"][0]))
            plan_payload["safe_archive_manifest"].insert(2, "not-a-manifest-object")
            plan_payload["excluded_from_safe_archive"].append(dict(plan_payload["excluded_from_safe_archive"][0]))
            plan_payload["excluded_from_safe_archive"].append("not-an-excluded-object")
            empty_key_command = dict(plan_payload["commands"][0])
            empty_key_command["key"] = ""
            empty_key_command["output_file"] = str(report_dir / "empty-key-output.json")
            empty_key_command["stderr_file"] = str(report_dir / "empty-key-output.stderr.txt")
            empty_key_command["archive_command"] = (
                f"{empty_key_command['command']} > {empty_key_command['output_file']} "
                f"2> {empty_key_command['stderr_file']}"
            )
            plan_payload["commands"].append(empty_key_command)
            empty_key_manifest = dict(plan_payload["safe_archive_manifest"][0])
            empty_key_manifest["key"] = ""
            plan_payload["safe_archive_manifest"].insert(2, empty_key_manifest)
            empty_key_excluded = dict(plan_payload["excluded_from_safe_archive"][0])
            empty_key_excluded["key"] = ""
            plan_payload["excluded_from_safe_archive"].append(empty_key_excluded)
            plan_payload["plan_file_path"] = str(plan_path)
            plan_payload["safe_script_path"] = str(report_dir / "target-safe.ps1")
            plan_payload["safe_shell_script_path"] = str(report_dir / "target-safe.sh")
            plan_payload["safe_archive_manifest"].pop()
            plan_payload["summary"]["safe_unattended_command_count"] = 20
            self._write_json(plan_path, plan_payload)

            stdout = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "validate_target_environment_evidence",
                    "--report-dir",
                    str(report_dir),
                    "--p0-report-dir",
                    str(p0_report_dir),
                    "--p1-report-dir",
                    str(p1_report_dir),
                    "--plan-file",
                    str(plan_path),
                    "--require-multi-node",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            failed = {check["key"]: check for check in payload["checks"] if not check["ok"]}
            self.assertEqual(set(failed), {"target_evidence_plan"})
            errors = failed["target_evidence_plan"]["errors"]
            self.assertIn("schema_version must be 1", errors)
            self.assertIn("errors items must be non-empty strings", errors)
            self.assertIn("errors must be empty", errors)
            self.assertIn("warnings items must be non-empty strings", errors)
            self.assertIn("summary.error_count must match errors", errors)
            self.assertIn("summary.warning_count must match warnings", errors)
            self.assertIn("summary.destructive_command_count must match commands", errors)
            self.assertIn("summary.missing_output_count must match commands.exists", errors)
            self.assertIn("summary.safe_unattended_command_count must match commands", errors)
            self.assertIn("summary.safe_archive_ready_command_count must match commands", errors)
            self.assertIn("summary.excluded_from_safe_archive_count must match commands", errors)
            self.assertIn("plan base_url must use https", errors)
            self.assertIn("plan backup_dir must be a durable target-environment backup location", errors)
            self.assertIn("plan remediation_checklist must match --report-dir", errors)
            self.assertIn("commands items must be objects", errors)
            self.assertIn("safe_archive_manifest items must be objects", errors)
            self.assertIn("excluded_from_safe_archive items must be objects", errors)
            self.assertIn("execution_sequence items must be objects", errors)
            self.assertIn("dependency_execution_waves items must be objects", errors)
            self.assertIn("manual_approval_commands items must be objects", errors)
            self.assertIn("final_validation_commands items must be objects", errors)
            self.assertIn("substitution_required_commands items must be objects", errors)
            self.assertIn("target_value_required_commands items must be objects", errors)
            self.assertIn("dependency_blocked_commands items must be objects", errors)
            self.assertIn("commands.key must be non-empty", errors)
            self.assertIn("safe_archive_manifest.key must be non-empty", errors)
            self.assertIn("excluded_from_safe_archive.key must be non-empty", errors)
            self.assertIn("commands.strict_health.command must be non-empty", errors)
            self.assertIn("commands.https_http_smoke.phase must be non-empty", errors)
            self.assertIn("commands.https_http_smoke.exists must be a boolean", errors)
            self.assertIn("commands.https_http_smoke.safe_to_run_unattended must be a boolean", errors)
            self.assertIn("commands.https_http_smoke.substitution_tokens items must be non-empty strings", errors)
            self.assertIn("safe_archive_commands items must be non-empty strings", errors)
            self.assertIn("safe_archive_manifest.strict_health.safe_archive_ready must be a boolean", errors)
            self.assertIn("excluded_from_safe_archive.live_restore.safe_to_run_unattended must be a boolean", errors)
            self.assertIn("excluded_from_safe_archive.live_restore.target_value_errors items must be non-empty strings", errors)
            self.assertIn("excluded_from_safe_archive.live_restore.exclude_reasons items must be non-empty strings", errors)
            self.assertIn("excluded_from_safe_archive.post_upgrade_strict_health.exclude_reasons must match commands", errors)
            self.assertIn("commands.post_upgrade_http_smoke.requires_completed_commands items must be non-empty strings", errors)
            self.assertIn("commands.key values must be unique: strict_health", errors)
            self.assertIn("safe_archive_manifest.key values must be unique: strict_health", errors)
            self.assertIn("excluded_from_safe_archive.key values must be unique: upgrade_executed", errors)
            self.assertIn("safe_archive_manifest key order must match commands", errors)
            self.assertIn("excluded_from_safe_archive key order must match commands", errors)
            self.assertIn("safe_archive_commands must match commands order", errors)
            self.assertIn(f"commands.output_file values must be unique: {report_dir / 'smoke-http-p95.json'}", errors)
            self.assertIn(f"commands.stderr_file values must be unique: {report_dir / 'smoke-http-p95.stderr.txt'}", errors)
            self.assertIn("safe_archive_manifest.strict_health.archive_command must match commands.strict_health.archive_command", errors)
            self.assertIn("safe_archive_manifest.strict_health.exists must match commands.strict_health.exists", errors)
            self.assertIn("command_groups.safe_unattended.command_count must match grouped commands", errors)
            self.assertIn("command_groups.safe_unattended.command_keys items must be non-empty strings", errors)
            self.assertIn("command_groups.safe_unattended.command_keys must match grouped commands", errors)
            self.assertIn("command_groups.safe_unattended.commands must match grouped commands", errors)
            self.assertIn("command_groups.safe_unattended.output_files must match grouped commands", errors)
            self.assertIn("command_groups.safe_unattended.archive_commands items must be non-empty strings", errors)
            self.assertIn("command_groups.safe_unattended.safe_to_run_unattended must be a boolean", errors)
            self.assertIn("command_groups.safe_unattended.requires_substitution must match grouped commands", errors)
            self.assertIn("execution_sequence steps must be consecutive starting at 1", errors)
            self.assertIn("execution_sequence groups must cover command_groups exactly", errors)
            self.assertIn("execution_queues.safe_unattended.command_count must match commands", errors)
            self.assertIn("execution_queues.safe_unattended.command_keys items must be non-empty strings", errors)
            self.assertIn("execution_queues.safe_unattended.command_keys must match commands", errors)
            self.assertIn("execution_queues.safe_unattended.archive_commands items must be non-empty strings", errors)
            self.assertIn("execution_queues.safe_unattended.archive_commands must match commands", errors)
            self.assertIn("execution_queues.safe_unattended.commands items must be objects", errors)
            self.assertIn("execution_queues.safe_unattended.commands must match commands", errors)
            self.assertIn("summary.execution_queue_counts must match execution_queues", errors)
            self.assertIn("manual_approval_commands must match commands", errors)
            self.assertIn("final_validation_commands must match commands", errors)
            self.assertIn("substitution_required_commands must match commands", errors)
            self.assertIn("target_value_required_commands must match commands", errors)
            self.assertIn("dependency_blocked_commands must match commands", errors)
            self.assertIn("summary.manual_approval_command_count must match manual_approval_commands", errors)
            self.assertIn("summary.final_validation_command_count must match final_validation_commands", errors)
            self.assertIn("summary.substitution_required_command_count must match substitution_required_commands", errors)
            self.assertIn("summary.target_value_required_command_count must match target_value_required_commands", errors)
            self.assertIn("summary.dependency_blocked_command_count must match dependency_blocked_commands", errors)
            self.assertIn("dependency_execution_waves must match commands.requires_completed_commands", errors)
            self.assertIn("summary.dependency_execution_wave_count must match dependency_execution_waves", errors)
            self.assertIn("excluded_from_safe_archive.post_upgrade_strict_health.target_value_errors must match commands.post_upgrade_strict_health.target_value_errors", errors)
            self.assertIn("commands.backup.backup_dir must match plan backup_dir", errors)
            self.assertIn("commands.backup.command must include plan backup_dir", errors)
            self.assertIn("commands.backup.archive_command must include plan backup_dir", errors)
            self.assertTrue(any(
                error.startswith("commands.key contains unexpected values:")
                and "unexpected_target_command" in error
                for error in errors
            ))
            self.assertIn("commands.live_restore.manual_approval_required must be true", errors)
            self.assertIn("commands.live_restore.destructive must be true", errors)
            self.assertIn("commands.live_restore.safe_to_run_unattended must be false", errors)
            self.assertIn("commands.live_restore.safe_archive_ready must be false", errors)
            self.assertIn("commands.upgrade_executed.manual_approval_required must be true", errors)
            self.assertIn("commands.upgrade_executed.safe_to_run_unattended must be false", errors)
            self.assertIn("commands.upgrade_executed.safe_archive_ready must be false", errors)
            self.assertIn("commands.post_upgrade_http_smoke.safe_archive_ready must match safe_to_run_unattended and dependencies", errors)
            self.assertIn("commands.validate_target_environment_evidence.manual_approval_required must be false", errors)
            self.assertIn("commands.validate_target_environment_evidence.destructive must be false", errors)
            self.assertIn("commands.validate_target_environment_evidence.safe_archive_ready must be false", errors)
            self.assertIn("commands.p0_forum_main.phase must be p0_capacity", errors)
            self.assertIn("commands.p0_forum_main.command must include capacity_profile.profile", errors)
            self.assertIn("commands.p0_forum_main.archive_command must include capacity_profile.profile", errors)
            self.assertIn("commands.p0_forum_main.command must include capacity_profile.concurrency", errors)
            self.assertIn("commands.external_websocket.command must include websocket_profile.connections", errors)
            self.assertIn("commands.external_websocket.websocket_profile.discussion_id must be non-empty", errors)
            self.assertIn("commands.external_websocket.websocket_profile.fail_on_threshold must be true", errors)
            self.assertIn("commands.runtime_integrations.runtime_integration_profile.smtp_connect must be true", errors)
            self.assertIn("commands.validate_target_environment_evidence.validation_profile.plan_file must match target validation command", errors)
            self.assertIn("commands.validate_target_environment_evidence.validation_profile.remediation_checklist must match target validation command", errors)
            self.assertIn("commands.validate_target_environment_evidence.validation_profile.require_multi_node must match target validation command", errors)
            self.assertIn("commands.p0_forum_main.command must include --profile forum-main", errors)
            self.assertIn(f"commands.queue_worker.output_file must be {report_dir / 'smoke-queue-worker.json'}", errors)
            self.assertIn("commands.queue_worker.command must include python manage.py smoke_queue_worker", errors)
            self.assertIn("commands.install_dry_run.command must include --dry-run", errors)
            self.assertIn("commands.queue_worker.command must include redis_broker_url", errors)
            self.assertIn("commands.queue_worker.archive_command must include redis_broker_url", errors)
            self.assertIn("commands.queue_worker.command must include redis_result_backend", errors)
            self.assertIn("commands.queue_worker.archive_command must include redis_result_backend", errors)
            self.assertIn("commands.queue_worker.archive_command must redirect to output_file and stderr_file", errors)
            self.assertIn("commands.queue_worker.archive_command must match command, output_file, and stderr_file", errors)
            self.assertIn("commands.https_http_smoke.base_url must match plan base_url", errors)
            self.assertIn("commands.https_http_smoke.command must include plan base_url", errors)
            self.assertIn("commands.https_http_smoke.archive_command must include plan base_url", errors)
            self.assertIn("commands.install_dry_run.base_url must be empty", errors)
            self.assertIn("commands.install_dry_run.backup_dir must be empty", errors)
            self.assertIn("commands.install_dry_run.redis_broker_url must be empty", errors)
            self.assertIn("commands.install_dry_run.redis_result_backend must be empty", errors)
            self.assertIn("commands.install_dry_run.topology must be empty", errors)
            self.assertIn("commands.install_dry_run.capacity_profile must be empty", errors)
            self.assertIn("commands.multi_node_topology.topology.load_balancer must match plan base_url", errors)
            self.assertIn("commands.multi_node_topology.command must include topology.web_nodes", errors)
            self.assertIn("commands.multi_node_topology.archive_command must include topology.image", errors)
            self.assertIn("commands.https_http_smoke safe command must not require substitution", errors)
            self.assertIn("commands.https_http_smoke safe command must not contain substitution tokens", errors)
            self.assertIn("commands.validate_target_environment_evidence.command must include --plan-file for this plan", errors)
            self.assertIn("commands.validate_target_environment_evidence.archive_command must include --plan-file for this plan", errors)
            self.assertIn("commands.validate_target_environment_evidence.command must include --write-remediation-checklist for this report", errors)
            self.assertIn("commands.validate_target_environment_evidence.archive_command must include --write-remediation-checklist for this report", errors)
            self.assertIn("commands.post_upgrade_http_smoke.requires_completed_commands must be upgrade_executed", errors)
            self.assertIn("commands.post_upgrade_strict_health.requires_completed_commands must be upgrade_executed", errors)
            self.assertIn("commands.restore_dry_run.requires_completed_commands must be backup_verification, restore_rehearsal", errors)
            self.assertIn("commands.live_restore.requires_completed_commands must be backup_verification, restore_dry_run", errors)
            self.assertIn("commands.p1_forum_write.requires_completed_commands must be empty", errors)
            self.assertIn("commands.post_upgrade_http_smoke.requires_completed_commands references unknown command missing_dependency", errors)
            self.assertIn("commands.post_upgrade_strict_health.requires_completed_commands must not reference itself", errors)
            self.assertIn("commands.requires_completed_commands contains cycle: p1_forum_write -> p1_forum_moderation -> p1_forum_write_mixed -> p1_forum_write", errors)
            self.assertIn("plan commands must not contain unresolved substitution tokens", errors)
            self.assertIn("plan_file_path must not be persisted in plan file", errors)
            self.assertIn("safe_script_path must not be persisted in plan file", errors)
            self.assertIn("safe_shell_script_path must not be persisted in plan file", errors)
            self.assertTrue(payload["remediation"]["blocked"])
            self.assertEqual(payload["remediation"]["failed_keys"], ["target_evidence_plan"])
            self.assertEqual(payload["remediation"]["actions"][0]["key"], "target_evidence_plan")
            self.assertIn("Regenerate the target run plan", payload["remediation"]["actions"][0]["hint"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_target_environment_evidence_remediation_includes_plan_command_metadata(self):
        temp_dir = make_workspace_temp_dir()
        try:
            report_dir = Path(temp_dir) / "reports"
            p0_report_dir = Path(temp_dir) / "p0"
            p1_report_dir = Path(temp_dir) / "p1"
            report_dir.mkdir(parents=True)
            p0_report_dir.mkdir(parents=True)
            p1_report_dir.mkdir(parents=True)
            self._write_complete_target_evidence(report_dir)
            self._write_p0_capacity_evidence(p0_report_dir)
            self._write_p1_capacity_evidence(p1_report_dir)
            plan_path = report_dir / "target-environment-evidence-plan.json"
            self._write_complete_target_evidence_plan(plan_path, report_dir, p0_report_dir, p1_report_dir)
            self._write_json(report_dir / "smoke-http-p95.json", {
                "base_url": "http://127.0.0.1:8000",
                "summary": {"ok": True},
            })
            (report_dir / "restore-forum-backup-live.json").unlink()

            stdout = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "validate_target_environment_evidence",
                    "--report-dir",
                    str(report_dir),
                    "--p0-report-dir",
                    str(p0_report_dir),
                    "--p1-report-dir",
                    str(p1_report_dir),
                    "--plan-file",
                    str(plan_path),
                    "--require-multi-node",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            actions = {item["key"]: item for item in payload["remediation"]["actions"]}
            self.assertEqual(set(actions), {"target_archive_integrity", "https_http_smoke", "live_restore"})
            self.assertEqual(
                actions["target_archive_integrity"]["details"]["missing_output_keys"],
                ["live_restore"],
            )
            self.assertEqual(
                actions["target_archive_integrity"]["planned_commands"][0]["key"],
                "live_restore",
            )
            http_command = actions["https_http_smoke"]["planned_commands"][0]
            self.assertEqual(http_command["key"], "https_http_smoke")
            self.assertEqual(http_command["execution_group"], "safe_unattended")
            self.assertTrue(http_command["safe_to_run_unattended"])
            self.assertFalse(http_command["manual_approval_required"])
            self.assertFalse(http_command["destructive"])
            self.assertIn("smoke_http_p95", http_command["command"])
            self.assertTrue(http_command["output_file"].endswith("smoke-http-p95.json"))
            self.assertTrue(http_command["stderr_file"].endswith("smoke-http-p95.stderr.txt"))
            self.assertIn("smoke-http-p95.json", http_command["archive_command"])
            self.assertEqual(http_command["substitution_tokens"], [])
            self.assertEqual(http_command["target_value_errors"], [])
            self.assertEqual(http_command["base_url"], "https://forum.example.test")
            live_restore_command = actions["live_restore"]["planned_commands"][0]
            self.assertEqual(live_restore_command["key"], "live_restore")
            self.assertEqual(live_restore_command["execution_group"], "destructive_approval")
            self.assertTrue(live_restore_command["manual_approval_required"])
            self.assertTrue(live_restore_command["destructive"])
            self.assertFalse(live_restore_command["safe_to_run_unattended"])
            self.assertIn("restore_forum_backup", live_restore_command["command"])
            self.assertTrue(live_restore_command["output_file"].endswith("restore-forum-backup-live.json"))
            self.assertTrue(live_restore_command["stderr_file"].endswith("restore-forum-backup-live.stderr.txt"))
            self.assertIn("restore-forum-backup-live.json", live_restore_command["archive_command"])
            self.assertIn("restore live forum data", live_restore_command["archive_command"])
            self.assertEqual(live_restore_command["backup_dir"], "s3://bias-target-backups/release-001")
            command_groups = payload["remediation"]["command_groups"]
            self.assertEqual(set(command_groups), {"destructive_approval", "safe_unattended"})
            self.assertEqual(command_groups["safe_unattended"]["command_count"], 1)
            self.assertEqual(command_groups["safe_unattended"]["action_keys"], ["https_http_smoke"])
            self.assertEqual(command_groups["safe_unattended"]["command_keys"], ["https_http_smoke"])
            self.assertEqual(len(command_groups["safe_unattended"]["commands"]), 1)
            self.assertEqual(command_groups["safe_unattended"]["output_files"], [str(report_dir / "smoke-http-p95.json")])
            self.assertEqual(command_groups["safe_unattended"]["stderr_files"], [str(report_dir / "smoke-http-p95.stderr.txt")])
            self.assertTrue(command_groups["safe_unattended"]["safe_to_run_unattended"])
            self.assertFalse(command_groups["safe_unattended"]["manual_approval_required"])
            self.assertFalse(command_groups["safe_unattended"]["destructive"])
            self.assertEqual(command_groups["destructive_approval"]["command_count"], 1)
            self.assertEqual(command_groups["destructive_approval"]["action_keys"], ["target_archive_integrity"])
            self.assertEqual(command_groups["destructive_approval"]["command_keys"], ["live_restore"])
            self.assertEqual(len(command_groups["destructive_approval"]["commands"]), 1)
            self.assertEqual(command_groups["destructive_approval"]["output_files"], [str(report_dir / "restore-forum-backup-live.json")])
            self.assertEqual(command_groups["destructive_approval"]["stderr_files"], [str(report_dir / "restore-forum-backup-live.stderr.txt")])
            self.assertFalse(command_groups["destructive_approval"]["safe_to_run_unattended"])
            self.assertTrue(command_groups["destructive_approval"]["manual_approval_required"])
            self.assertTrue(command_groups["destructive_approval"]["destructive"])
            self.assertIn("restore-forum-backup-live.json", command_groups["destructive_approval"]["archive_commands"][0])
            execution_sequence = payload["remediation"]["execution_sequence"]
            self.assertEqual([item["groups"][0] for item in execution_sequence], ["safe_unattended", "destructive_approval"])
            self.assertEqual(execution_sequence[0]["action_keys"], ["https_http_smoke"])
            self.assertEqual(execution_sequence[0]["command_keys"], ["https_http_smoke"])
            self.assertTrue(execution_sequence[0]["safe_to_run_unattended"])
            self.assertEqual(execution_sequence[1]["action_keys"], ["target_archive_integrity"])
            self.assertTrue(execution_sequence[1]["manual_approval_required"])
            self.assertTrue(execution_sequence[1]["destructive"])
            execution_queues = payload["remediation"]["execution_queues"]
            self.assertEqual(payload["remediation"]["execution_queue_counts"], {
                "safe_unattended": 1,
                "requires_substitution": 0,
                "target_value_required": 0,
                "dependency_blocked": 1,
                "maintenance_approval": 0,
                "destructive_approval": 1,
                "final_validation": 0,
            })
            self.assertEqual(execution_queues["safe_unattended"]["command_count"], 1)
            self.assertEqual(execution_queues["safe_unattended"]["command_keys"], ["https_http_smoke"])
            self.assertIn("smoke-http-p95.json", execution_queues["safe_unattended"]["archive_commands"][0])
            self.assertEqual(execution_queues["destructive_approval"]["command_count"], 1)
            self.assertEqual(execution_queues["destructive_approval"]["command_keys"], ["live_restore"])
            self.assertIn("restore-forum-backup-live.json", execution_queues["destructive_approval"]["archive_commands"][0])
            self.assertEqual(execution_queues["requires_substitution"]["command_count"], 0)
            self.assertEqual(execution_queues["target_value_required"]["command_count"], 0)
            self.assertEqual(execution_queues["dependency_blocked"]["command_count"], 1)
            self.assertEqual(execution_queues["dependency_blocked"]["command_keys"], ["live_restore"])
            self.assertEqual(
                execution_queues["dependency_blocked"]["commands"][0]["requires_completed_commands"],
                ["backup_verification", "restore_dry_run"],
            )
            self.assertEqual(execution_queues["final_validation"]["command_count"], 0)
            remediation_waves = payload["remediation"]["dependency_execution_waves"]
            self.assertEqual(payload["remediation"]["dependency_execution_wave_count"], 1)
            self.assertEqual(remediation_waves[0]["command_keys"], ["live_restore"])
            self.assertEqual(remediation_waves[0]["requires_completed_commands"], ["backup_verification", "restore_dry_run"])
            self.assertEqual(remediation_waves[0]["commands"][0]["key"], "live_restore")
            self.assertEqual(remediation_waves[0]["commands"][0]["action_key"], "target_archive_integrity")
            self.assertFalse(any(
                command["key"] == "live_restore"
                for command in execution_queues["safe_unattended"]["commands"]
            ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_target_environment_evidence_can_write_remediation_checklist(self):
        temp_dir = make_workspace_temp_dir()
        try:
            report_dir = Path(temp_dir) / "reports"
            p0_report_dir = Path(temp_dir) / "p0"
            p1_report_dir = Path(temp_dir) / "p1"
            checklist_path = Path(temp_dir) / "follow-up" / "target-remediation.md"
            report_dir.mkdir(parents=True)
            p0_report_dir.mkdir(parents=True)
            p1_report_dir.mkdir(parents=True)
            self._write_complete_target_evidence(report_dir)
            self._write_p0_capacity_evidence(p0_report_dir)
            self._write_p1_capacity_evidence(p1_report_dir)
            plan_path = report_dir / "target-environment-evidence-plan.json"
            self._write_complete_target_evidence_plan(plan_path, report_dir, p0_report_dir, p1_report_dir)
            self._write_json(report_dir / "smoke-http-p95.json", {
                "base_url": "http://127.0.0.1:8000",
                "summary": {"ok": True},
            })
            websocket_payload = json.loads((report_dir / "load-websocket-external-20.json").read_text(encoding="utf-8"))
            websocket_payload["discussion_id"] = 7
            self._write_json(report_dir / "load-websocket-external-20.json", websocket_payload)
            upgrade_payload = json.loads((report_dir / "upgrade-forum-executed.json").read_text(encoding="utf-8"))
            upgrade_payload["summary"]["executed"] = False
            self._write_json(report_dir / "upgrade-forum-executed.json", upgrade_payload)
            (report_dir / "smoke-queue-worker.json").unlink()
            (report_dir / "multi-node-topology.json").unlink()
            (report_dir / "restore-forum-backup-live.json").unlink()
            (p0_report_dir / "forum-main-300s.json").unlink()

            stdout = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "validate_target_environment_evidence",
                    "--report-dir",
                    str(report_dir),
                    "--p0-report-dir",
                    str(p0_report_dir),
                    "--p1-report-dir",
                    str(p1_report_dir),
                    "--plan-file",
                    str(plan_path),
                    "--write-remediation-checklist",
                    str(checklist_path),
                    "--require-multi-node",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["remediation"]["checklist_path"], str(checklist_path))
            checklist = checklist_path.read_text(encoding="utf-8")
            self.assertIn("# Target Environment Remediation Checklist", checklist)
            self.assertIn("## Guardrails", checklist)
            self.assertIn("Do not treat this checklist as P2 approval", checklist)
            self.assertIn("Replace every `<...>` token", checklist)
            self.assertIn("## Execution Sequence", checklist)
            self.assertIn("### Step 1: safe_unattended", checklist)
            self.assertIn("### Step 2: maintenance_approval", checklist)
            self.assertIn("### Step 3: destructive_approval", checklist)
            self.assertIn("action_keys: `target_archive_integrity, https_http_smoke, target_dependency_evidence, target_plan_evidence_alignment`", checklist)
            self.assertIn("action_keys: `target_archive_integrity`", checklist)
            self.assertIn("command_keys: `live_restore`", checklist)
            self.assertIn("## Execution Queues", checklist)
            self.assertIn("### safe_unattended", checklist)
            self.assertIn("### final_validation", checklist)
            self.assertIn("command_count: `0`", checklist)
            self.assertIn("## Dependency Execution Waves", checklist)
            self.assertIn("### Wave 1", checklist)
            self.assertIn("requires_completed_commands: `backup_verification, restore_dry_run`", checklist)
            self.assertIn("### safe_unattended", checklist)
            self.assertIn("### destructive_approval", checklist)
            self.assertIn("execution_policy: eligible for unattended execution", checklist)
            self.assertIn("execution_policy: maintenance approval required", checklist)
            self.assertIn("- [ ] `", checklist)
            self.assertIn("command: `python manage.py smoke_http_p95", checklist)
            self.assertIn("base_url: `https://forum.example.test`", checklist)
            self.assertIn("backup_dir: `s3://bias-target-backups/release-001`", checklist)
            self.assertIn("redis_broker_url: `redis://redis.target.example:6379/1`", checklist)
            self.assertIn("redis_result_backend: `redis://redis.target.example:6379/2`", checklist)
            self.assertIn("  - topology:", checklist)
            self.assertIn("    - web_nodes: `2`", checklist)
            self.assertIn("    - image: `registry.example.test/bias:20260702`", checklist)
            self.assertIn("    - load_balancer: `https://forum.example.test`", checklist)
            self.assertIn("  - capacity_profile:", checklist)
            self.assertIn("    - profile: `forum-main`", checklist)
            self.assertIn("    - concurrency: `20`", checklist)
            self.assertIn("    - duration: `300`", checklist)
            self.assertIn("output_file: `", checklist)
            self.assertIn("stderr_file: `", checklist)
            self.assertIn("- errors:", checklist)
            self.assertIn("`base_url must use https for target-environment evidence`", checklist)
            self.assertIn("`dependency upgrade_executed failed", checklist)
            self.assertIn("`commands.external_websocket.evidence discussion_id must match websocket_profile`", checklist)
            self.assertIn("missing_output_keys: `queue_worker, live_restore, multi_node_topology, p0_forum_main`", checklist)
            self.assertIn("mismatched_command_keys: `external_websocket`", checklist)
            self.assertIn("failed_dependency_keys: `upgrade_executed`", checklist)
            self.assertIn("blocked_command_keys: `post_upgrade_strict_health, post_upgrade_http_smoke, post_upgrade_queue_worker`", checklist)
            self.assertIn("smoke-http-p95.json", checklist)
            self.assertIn("smoke-queue-worker.json", checklist)
            self.assertIn("multi-node-topology.json", checklist)
            self.assertIn("forum-main-300s.json", checklist)
            self.assertIn("restore-forum-backup-live.json", checklist)
            self.assertIn("destructive=true", checklist)
            self.assertIn("manual=true", checklist)
            self.assertIn("s3://bias-target-backups/release-001", checklist)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_target_environment_evidence_requires_live_restore_verification(self):
        temp_dir = make_workspace_temp_dir()
        try:
            report_dir = Path(temp_dir) / "reports"
            p0_report_dir = Path(temp_dir) / "p0"
            p1_report_dir = Path(temp_dir) / "p1"
            report_dir.mkdir(parents=True)
            p0_report_dir.mkdir(parents=True)
            p1_report_dir.mkdir(parents=True)
            self._write_complete_target_evidence(report_dir)
            self._write_p0_capacity_evidence(p0_report_dir)
            self._write_p1_capacity_evidence(p1_report_dir)
            live_restore_path = report_dir / "restore-forum-backup-live.json"
            live_restore_payload = json.loads(live_restore_path.read_text(encoding="utf-8"))
            live_restore_payload.pop("verification")
            self._write_json(live_restore_path, live_restore_payload)

            stdout = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "validate_target_environment_evidence",
                    "--report-dir",
                    str(report_dir),
                    "--p0-report-dir",
                    str(p0_report_dir),
                    "--p1-report-dir",
                    str(p1_report_dir),
                    "--require-multi-node",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            failed = {check["key"]: check for check in payload["checks"] if not check["ok"]}
            self.assertEqual(set(failed), {"live_restore"})
            self.assertIn("verification must include site_config", failed["live_restore"]["errors"])
            self.assertIn("verification.database.table_count must be at least 1", failed["live_restore"]["errors"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_target_topology_outputs_multi_node_evidence(self):
        stdout = StringIO()
        call_command(
            "inspect_target_topology",
            "--web-nodes",
            "2",
            "--worker-nodes",
            "2",
            "--scheduler-nodes",
            "1",
            "--image",
            "registry.example.test/bias:20260702",
            "--app-version",
            "2026.07.02",
            "--database",
            "postgres://db.example.test:5432/bias",
            "--redis",
            "redis://redis.example.test:6379/0",
            "--load-balancer",
            "https://forum.example.test",
            "--require-multi-node",
            "--format",
            "json",
            stdout=stdout,
        )

        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["summary"]["ok"], payload)
        self.assertTrue(payload["summary"]["multi_node"])
        self.assertEqual(payload["roles"]["web"], 2)
        self.assertEqual(payload["roles"]["worker"], 2)
        self.assertEqual(payload["roles"]["scheduler"], 1)
        self.assertEqual(payload["artifacts"]["image"], "registry.example.test/bias:20260702")
        self.assertEqual(payload["shared_services"]["load_balancer"], "https://forum.example.test")

    def test_inspect_target_topology_requires_shared_target_details(self):
        stdout = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "inspect_target_topology",
                "--web-nodes",
                "1",
                "--worker-nodes",
                "0",
                "--scheduler-nodes",
                "0",
                "--require-multi-node",
                "--format",
                "json",
                stdout=stdout,
            )

        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["summary"]["ok"])
        self.assertFalse(payload["summary"]["multi_node"])
        self.assertIn("worker nodes must be at least 1", payload["errors"])
        self.assertIn("multi-node target evidence requires at least 2 web nodes", payload["errors"])
        self.assertIn("artifacts.image is required", payload["errors"])

    def test_inspect_target_topology_rejects_local_smoke_details(self):
        stdout = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "inspect_target_topology",
                "--web-nodes",
                "1",
                "--worker-nodes",
                "1",
                "--scheduler-nodes",
                "1",
                "--image",
                "local-production-smoke",
                "--app-version",
                "0.1.1",
                "--database",
                "postgres://postgres:5432/bias_smoke",
                "--redis",
                "redis://redis:6379/0",
                "--load-balancer",
                "http://127.0.0.1:8000",
                "--require-multi-node",
                "--format",
                "json",
                stdout=stdout,
            )

        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["summary"]["ok"])
        self.assertFalse(payload["summary"]["multi_node"])
        self.assertIn("multi-node target evidence requires at least 2 web nodes", payload["errors"])
        self.assertIn("artifacts.image must identify a target release image", payload["errors"])
        self.assertIn("shared_services.database must identify a shared target service", payload["errors"])
        self.assertIn("shared_services.redis must identify a shared target service", payload["errors"])
        self.assertIn("shared_services.load_balancer must use https", payload["errors"])

    def test_plan_target_environment_evidence_outputs_complete_archive_plan(self):
        temp_dir = make_workspace_temp_dir()
        try:
            report_dir = Path(temp_dir) / "ops"
            p0_report_dir = Path(temp_dir) / "p0"
            p1_report_dir = Path(temp_dir) / "p1"
            report_dir.mkdir(parents=True)
            p0_report_dir.mkdir(parents=True)
            p1_report_dir.mkdir(parents=True)
            (report_dir / "health-strict.json").write_text("{}", encoding="utf-8")

            stdout = StringIO()
            call_command(
                "plan_target_environment_evidence",
                "--base-url",
                "https://forum.example.test",
                "--report-dir",
                str(report_dir),
                "--p0-report-dir",
                str(p0_report_dir),
                "--p1-report-dir",
                str(p1_report_dir),
                "--backup-dir",
                "s3://bias-backups/release-001",
                "--discussion-id",
                "42",
                "--load-username",
                "load-user",
                "--load-password",
                "load-password",
                "--moderator-username",
                "mod-user",
                "--moderator-password",
                "mod-password",
                "--format",
                "json",
                stdout=stdout,
            )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["schema_version"], 1)
            self.assertTrue(payload["summary"]["ok"], payload)
            self.assertFalse(payload["summary"]["executes_commands"])
            self.assertEqual(payload["summary"]["command_count"], 25)
            self.assertEqual(payload["summary"]["destructive_command_count"], 1)
            self.assertEqual(payload["summary"]["manual_approval_command_count"], 2)
            self.assertEqual(payload["summary"]["safe_unattended_command_count"], 19)
            self.assertEqual(payload["summary"]["safe_archive_ready_command_count"], 13)
            self.assertEqual(payload["summary"]["excluded_from_safe_archive_count"], 12)
            self.assertEqual(payload["summary"]["substitution_required_command_count"], 3)
            self.assertEqual(payload["summary"]["target_value_required_command_count"], 0)
            self.assertEqual(payload["summary"]["dependency_blocked_command_count"], 8)
            self.assertEqual(payload["summary"]["dependency_execution_wave_count"], 3)
            self.assertEqual(payload["summary"]["final_validation_command_count"], 1)
            self.assertEqual(len(payload["safe_archive_commands"]), 13)
            self.assertEqual(len(payload["safe_archive_manifest"]), 13)
            self.assertEqual(len(payload["excluded_from_safe_archive"]), 12)
            commands = {item["key"]: item for item in payload["commands"]}
            command_groups = payload["command_groups"]
            self.assertEqual(set(command_groups), {
                "destructive_approval",
                "final_validation",
                "maintenance_approval",
                "requires_substitution",
                "safe_unattended",
            })
            self.assertEqual(command_groups["safe_unattended"]["command_count"], 19)
            self.assertEqual(command_groups["safe_unattended"]["command_keys"][0], "strict_health")
            self.assertIn("p1_forum_moderation", command_groups["safe_unattended"]["command_keys"])
            self.assertEqual(len(command_groups["safe_unattended"]["commands"]), 19)
            self.assertIn(str(p0_report_dir / "forum-main-300s.json"), command_groups["safe_unattended"]["output_files"])
            self.assertIn(str(p1_report_dir / "forum-upload-120s.stderr.txt"), command_groups["safe_unattended"]["stderr_files"])
            self.assertTrue(command_groups["safe_unattended"]["safe_to_run_unattended"])
            self.assertFalse(command_groups["safe_unattended"]["safe_archive_ready"])
            self.assertTrue(command_groups["safe_unattended"]["dependency_blocked"])
            self.assertIn("upgrade_executed", command_groups["safe_unattended"]["requires_completed_commands"])
            self.assertFalse(command_groups["safe_unattended"]["manual_approval_required"])
            self.assertEqual(command_groups["requires_substitution"]["command_count"], 3)
            self.assertEqual(command_groups["requires_substitution"]["command_keys"], ["queue_worker", "post_upgrade_queue_worker", "multi_node_topology"])
            self.assertTrue(command_groups["requires_substitution"]["requires_substitution"])
            self.assertFalse(command_groups["requires_substitution"]["target_value_required"])
            self.assertEqual(command_groups["maintenance_approval"]["command_keys"], ["upgrade_executed"])
            self.assertTrue(command_groups["maintenance_approval"]["manual_approval_required"])
            self.assertEqual(command_groups["destructive_approval"]["command_keys"], ["live_restore"])
            self.assertTrue(command_groups["destructive_approval"]["destructive"])
            self.assertTrue(command_groups["destructive_approval"]["manual_approval_required"])
            self.assertEqual(command_groups["final_validation"]["command_keys"], ["validate_target_environment_evidence"])
            self.assertFalse(command_groups["final_validation"]["safe_to_run_unattended"])
            execution_sequence = payload["execution_sequence"]
            self.assertEqual([item["groups"][0] for item in execution_sequence], [
                "safe_unattended",
                "requires_substitution",
                "maintenance_approval",
                "destructive_approval",
                "final_validation",
            ])
            self.assertEqual([item["step"] for item in execution_sequence], [1, 2, 3, 4, 5])
            self.assertEqual(execution_sequence[0]["command_count"], 19)
            self.assertTrue(execution_sequence[0]["safe_to_run_unattended"])
            self.assertFalse(execution_sequence[0]["manual_approval_required"])
            self.assertTrue(execution_sequence[1]["requires_substitution"])
            self.assertTrue(execution_sequence[2]["manual_approval_required"])
            self.assertTrue(execution_sequence[3]["destructive"])
            self.assertEqual(execution_sequence[-1]["command_keys"], ["validate_target_environment_evidence"])
            self.assertIn("after all evidence", execution_sequence[-1]["policy"])
            execution_queues = payload["execution_queues"]
            self.assertEqual(payload["summary"]["execution_queue_counts"], {
                "safe_unattended": 19,
                "requires_substitution": 3,
                "target_value_required": 0,
                "dependency_blocked": 8,
                "maintenance_approval": 1,
                "destructive_approval": 1,
                "final_validation": 1,
            })
            self.assertEqual(set(execution_queues), {
                "destructive_approval",
                "final_validation",
                "dependency_blocked",
                "maintenance_approval",
                "requires_substitution",
                "safe_unattended",
                "target_value_required",
            })
            self.assertEqual(execution_queues["safe_unattended"]["command_count"], 19)
            self.assertEqual(execution_queues["safe_unattended"]["command_keys"][0], "strict_health")
            self.assertIn("p1_forum_moderation", execution_queues["safe_unattended"]["command_keys"])
            self.assertEqual(execution_queues["requires_substitution"]["command_count"], 3)
            self.assertEqual(execution_queues["requires_substitution"]["command_keys"], ["queue_worker", "post_upgrade_queue_worker", "multi_node_topology"])
            self.assertEqual(execution_queues["dependency_blocked"]["command_count"], 8)
            self.assertEqual(execution_queues["dependency_blocked"]["command_keys"], [
                "post_upgrade_strict_health",
                "post_upgrade_http_smoke",
                "post_upgrade_queue_worker",
                "restore_rehearsal",
                "restore_dry_run",
                "live_restore",
                "p1_forum_write_mixed",
                "p1_forum_moderation",
            ])
            self.assertEqual(execution_queues["maintenance_approval"]["command_keys"], ["upgrade_executed"])
            self.assertEqual(execution_queues["destructive_approval"]["command_keys"], ["live_restore"])
            self.assertEqual(execution_queues["final_validation"]["command_keys"], ["validate_target_environment_evidence"])
            self.assertEqual(execution_queues["target_value_required"]["command_count"], 0)
            self.assertIn("restore-forum-backup-live.json", execution_queues["destructive_approval"]["archive_commands"][0])
            self.assertFalse(any(
                command["key"] == "live_restore"
                for command in execution_queues["safe_unattended"]["commands"]
            ))
            dependency_waves = payload["dependency_execution_waves"]
            self.assertEqual([wave["command_keys"] for wave in dependency_waves], [
                [
                    "post_upgrade_strict_health",
                    "post_upgrade_http_smoke",
                    "post_upgrade_queue_worker",
                    "restore_rehearsal",
                    "p1_forum_write_mixed",
                ],
                ["restore_dry_run", "p1_forum_moderation"],
                ["live_restore"],
            ])
            self.assertEqual([wave["dependency_depth"] for wave in dependency_waves], [1, 2, 3])
            self.assertEqual(dependency_waves[0]["commands"][0]["key"], "post_upgrade_strict_health")
            self.assertEqual(dependency_waves[0]["commands"][0]["requires_completed_commands"], ["upgrade_executed"])
            self.assertNotIn("phase", dependency_waves[0]["commands"][0])
            self.assertEqual(
                [item["archive_command"] for item in payload["safe_archive_manifest"]],
                payload["safe_archive_commands"],
            )
            strict_health_manifest = next(item for item in payload["safe_archive_manifest"] if item["key"] == "strict_health")
            self.assertEqual(strict_health_manifest["command"], commands["strict_health"]["command"])
            manual_by_key = {item["key"]: item for item in payload["manual_approval_commands"]}
            self.assertEqual(set(manual_by_key), {"upgrade_executed", "live_restore"})
            self.assertEqual(manual_by_key["upgrade_executed"]["execution_group"], "maintenance_approval")
            self.assertIn("upgrade_forum", manual_by_key["upgrade_executed"]["command"])
            self.assertTrue(manual_by_key["upgrade_executed"]["output_file"].endswith("upgrade-forum-executed.json"))
            self.assertTrue(manual_by_key["upgrade_executed"]["stderr_file"].endswith("upgrade-forum-executed.stderr.txt"))
            self.assertEqual(manual_by_key["live_restore"]["execution_group"], "destructive_approval")
            self.assertTrue(manual_by_key["live_restore"]["destructive"])
            self.assertFalse(manual_by_key["live_restore"]["requires_substitution"])
            self.assertEqual(manual_by_key["live_restore"]["substitution_tokens"], [])
            self.assertEqual(manual_by_key["live_restore"]["target_value_errors"], [])
            self.assertEqual(payload["final_validation_commands"][0]["key"], "validate_target_environment_evidence")
            self.assertFalse(payload["final_validation_commands"][0]["requires_substitution"])
            self.assertEqual(payload["final_validation_commands"][0]["target_value_errors"], [])
            substitution_by_key = {item["key"]: item for item in payload["substitution_required_commands"]}
            self.assertEqual(set(substitution_by_key), {
                "queue_worker",
                "post_upgrade_queue_worker",
                "multi_node_topology",
            })
            self.assertEqual(substitution_by_key["queue_worker"]["execution_group"], "requires_substitution")
            self.assertEqual(substitution_by_key["queue_worker"]["substitution_tokens"], ["<redis-broker-url>", "<redis-result-backend>"])
            self.assertIn("<web-count>", substitution_by_key["multi_node_topology"]["substitution_tokens"])
            self.assertFalse(payload["target_value_required_commands"])
            self.assertTrue(commands["strict_health"]["exists"])
            self.assertFalse(commands["live_restore"]["exists"])
            self.assertTrue(commands["live_restore"]["destructive"])
            self.assertTrue(commands["live_restore"]["manual_approval_required"])
            self.assertFalse(commands["live_restore"]["safe_to_run_unattended"])
            self.assertEqual(commands["live_restore"]["execution_group"], "destructive_approval")
            self.assertFalse(commands["upgrade_executed"]["destructive"])
            self.assertTrue(commands["upgrade_executed"]["manual_approval_required"])
            self.assertFalse(commands["upgrade_executed"]["safe_to_run_unattended"])
            self.assertEqual(commands["upgrade_executed"]["execution_group"], "maintenance_approval")
            self.assertFalse(commands["p0_forum_main"]["manual_approval_required"])
            self.assertTrue(commands["p0_forum_main"]["safe_to_run_unattended"])
            self.assertEqual(commands["p0_forum_main"]["execution_group"], "safe_unattended")
            self.assertFalse(commands["p1_forum_write"]["requires_substitution"])
            self.assertTrue(commands["p1_forum_write"]["safe_to_run_unattended"])
            self.assertTrue(commands["p1_forum_write"]["safe_archive_ready"])
            self.assertEqual(commands["p1_forum_write"]["requires_completed_commands"], [])
            self.assertTrue(commands["p1_forum_write_mixed"]["safe_to_run_unattended"])
            self.assertFalse(commands["p1_forum_write_mixed"]["safe_archive_ready"])
            self.assertEqual(commands["p1_forum_write_mixed"]["requires_completed_commands"], ["p1_forum_write"])
            self.assertTrue(commands["queue_worker"]["requires_substitution"])
            self.assertFalse(commands["queue_worker"]["safe_to_run_unattended"])
            self.assertEqual(commands["queue_worker"]["execution_group"], "requires_substitution")
            self.assertEqual(commands["queue_worker"]["redis_broker_url"], "<redis-broker-url>")
            self.assertEqual(commands["queue_worker"]["redis_result_backend"], "<redis-result-backend>")
            self.assertEqual(commands["post_upgrade_queue_worker"]["redis_broker_url"], "<redis-broker-url>")
            self.assertEqual(commands["strict_health"]["redis_broker_url"], "")
            self.assertEqual(execution_queues["requires_substitution"]["commands"][0]["redis_broker_url"], "<redis-broker-url>")
            self.assertEqual(dependency_waves[0]["commands"][2]["redis_result_backend"], "<redis-result-backend>")
            self.assertEqual(commands["multi_node_topology"]["topology"]["web_nodes"], "<web-count>")
            self.assertEqual(commands["multi_node_topology"]["topology"]["load_balancer"], "https://forum.example.test")
            self.assertEqual(commands["strict_health"]["topology"], {})
            self.assertEqual(execution_queues["requires_substitution"]["commands"][2]["topology"]["image"], "<image-or-release>")
            self.assertEqual(commands["p0_forum_main"]["capacity_profile"]["profile"], "forum-main")
            self.assertEqual(commands["p0_forum_main"]["capacity_profile"]["concurrency"], "20")
            self.assertEqual(commands["p1_forum_write"]["capacity_profile"]["discussion_id"], "42")
            self.assertEqual(commands["p1_forum_moderation"]["capacity_profile"]["login_username"], "mod-user")
            self.assertEqual(commands["strict_health"]["capacity_profile"], {})
            self.assertEqual(commands["external_websocket"]["websocket_profile"]["discussion_id"], "42")
            self.assertEqual(commands["external_websocket"]["websocket_profile"]["connections"], "20")
            self.assertEqual(commands["runtime_integrations"]["runtime_integration_profile"]["require_object_storage"], "true")
            self.assertEqual(commands["validate_target_environment_evidence"]["validation_profile"]["require_multi_node"], "true")
            self.assertEqual(
                commands["validate_target_environment_evidence"]["validation_profile"]["remediation_checklist"],
                str(report_dir / "target-environment-remediation-checklist.md"),
            )
            self.assertEqual(commands["strict_health"]["websocket_profile"], {})
            self.assertEqual(commands["strict_health"]["runtime_integration_profile"], {})
            self.assertEqual(commands["strict_health"]["validation_profile"], {})
            safe_queue_by_key = {
                command["key"]: command
                for command in execution_queues["safe_unattended"]["commands"]
            }
            self.assertEqual(safe_queue_by_key["p1_forum_upload"]["capacity_profile"]["profile"], "forum-upload")
            self.assertEqual(safe_queue_by_key["runtime_integrations"]["runtime_integration_profile"]["smtp_connect"], "true")
            self.assertEqual(commands["backup"]["backup_dir"], "s3://bias-backups/release-001")
            self.assertEqual(commands["restore_dry_run"]["backup_dir"], "s3://bias-backups/release-001")
            self.assertEqual(commands["strict_health"]["backup_dir"], "")
            self.assertEqual(execution_queues["safe_unattended"]["commands"][6]["backup_dir"], "s3://bias-backups/release-001")
            self.assertEqual(dependency_waves[0]["commands"][3]["backup_dir"], "s3://bias-backups/release-001")
            self.assertIn("restore live forum data", commands["live_restore"]["command"])
            self.assertIn("restore-forum-backup-live.json", commands["live_restore"]["archive_command"])
            self.assertIn("2>", commands["live_restore"]["archive_command"])
            self.assertIn("--base-url https://forum.example.test", commands["p0_forum_main"]["command"])
            self.assertEqual(commands["p0_forum_main"]["output_file"], str(p0_report_dir / "forum-main-300s.json"))
            self.assertEqual(commands["p1_forum_upload"]["output_file"], str(p1_report_dir / "forum-upload-120s.json"))
            self.assertIn("--require-multi-node", commands["validate_target_environment_evidence"]["command"])
            self.assertIn("--plan-file", commands["validate_target_environment_evidence"]["command"])
            self.assertIn("--write-remediation-checklist", commands["validate_target_environment_evidence"]["command"])
            self.assertIn("target-environment-evidence-plan.json", commands["validate_target_environment_evidence"]["command"])
            self.assertIn("target-environment-remediation-checklist.md", commands["validate_target_environment_evidence"]["command"])
            self.assertIn("target-environment-evidence-validation.json", commands["validate_target_environment_evidence"]["archive_command"])
            self.assertIn("target-environment-evidence-plan.json", commands["validate_target_environment_evidence"]["archive_command"])
            self.assertIn("target-environment-remediation-checklist.md", commands["validate_target_environment_evidence"]["archive_command"])
            self.assertEqual(commands["validate_target_environment_evidence"]["execution_group"], "final_validation")
            self.assertFalse(commands["validate_target_environment_evidence"]["safe_to_run_unattended"])
            self.assertNotIn(commands["queue_worker"]["archive_command"], payload["safe_archive_commands"])
            excluded_by_key = {item["key"]: item for item in payload["excluded_from_safe_archive"]}
            self.assertIn("requires_substitution", excluded_by_key["queue_worker"]["exclude_reasons"])
            self.assertEqual(excluded_by_key["queue_worker"]["redis_broker_url"], "<redis-broker-url>")
            self.assertEqual(excluded_by_key["queue_worker"]["redis_result_backend"], "<redis-result-backend>")
            self.assertEqual(excluded_by_key["multi_node_topology"]["topology"]["database_endpoint"], "<db-endpoint>")
            self.assertEqual(excluded_by_key["validate_target_environment_evidence"]["validation_profile"]["plan_file"], str(report_dir / "target-environment-evidence-plan.json"))
            self.assertIn("requires_completed_commands", excluded_by_key["post_upgrade_http_smoke"]["exclude_reasons"])
            self.assertTrue(excluded_by_key["post_upgrade_http_smoke"]["safe_to_run_unattended"])
            self.assertFalse(excluded_by_key["post_upgrade_http_smoke"]["safe_archive_ready"])
            self.assertEqual(excluded_by_key["post_upgrade_http_smoke"]["requires_completed_commands"], ["upgrade_executed"])
            self.assertEqual(excluded_by_key["restore_dry_run"]["backup_dir"], "s3://bias-backups/release-001")
            self.assertIn("requires_completed_commands", excluded_by_key["p1_forum_write_mixed"]["exclude_reasons"])
            self.assertIn("manual_approval_required", excluded_by_key["upgrade_executed"]["exclude_reasons"])
            self.assertIn("destructive", excluded_by_key["live_restore"]["exclude_reasons"])
            self.assertIn("manual_approval_required", excluded_by_key["live_restore"]["exclude_reasons"])
            self.assertIn("final_validation", excluded_by_key["validate_target_environment_evidence"]["exclude_reasons"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_plan_target_environment_evidence_rejects_non_https_base_url(self):
        temp_dir = make_workspace_temp_dir()
        try:
            stdout = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "plan_target_environment_evidence",
                    "--base-url",
                    "http://127.0.0.1:8000",
                    "--report-dir",
                    str(Path(temp_dir) / "ops"),
                    "--p0-report-dir",
                    str(Path(temp_dir) / "p0"),
                    "--p1-report-dir",
                    str(Path(temp_dir) / "p1"),
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["summary"]["ok"])
            self.assertIn("base_url must start with https://", payload["errors"][0])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_plan_target_environment_evidence_writes_safe_script_only(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            script_path = base_dir / "target-safe.ps1"
            shell_script_path = base_dir / "target-safe.sh"
            plan_path = base_dir / "nested" / "target-environment-evidence-plan.json"

            stdout = StringIO()
            call_command(
                "plan_target_environment_evidence",
                "--base-url",
                "https://forum.example.test",
                "--report-dir",
                str(base_dir / "ops"),
                "--p0-report-dir",
                str(base_dir / "p0"),
                "--p1-report-dir",
                str(base_dir / "p1"),
                "--write-plan-file",
                str(plan_path),
                "--write-safe-script",
                str(script_path),
                "--write-safe-shell-script",
                str(shell_script_path),
                "--format",
                "json",
                stdout=stdout,
            )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["plan_file_path"], str(plan_path))
            self.assertEqual(payload["safe_script_path"], str(script_path))
            self.assertEqual(payload["safe_shell_script_path"], str(shell_script_path))
            self.assertEqual(payload["remediation_checklist"], str(base_dir / "ops" / "target-environment-remediation-checklist.md"))
            self.assertEqual(payload["summary"]["safe_unattended_command_count"], 8)
            self.assertEqual(payload["summary"]["safe_archive_ready_command_count"], 6)
            self.assertEqual(payload["summary"]["excluded_from_safe_archive_count"], 19)
            self.assertEqual(payload["summary"]["substitution_required_command_count"], 15)
            self.assertEqual(payload["summary"]["target_value_required_command_count"], 0)
            self.assertEqual(payload["summary"]["dependency_blocked_command_count"], 8)
            self.assertEqual(payload["summary"]["dependency_execution_wave_count"], 3)
            self.assertEqual(payload["summary"]["execution_queue_counts"], {
                "safe_unattended": 8,
                "requires_substitution": 15,
                "target_value_required": 0,
                "dependency_blocked": 8,
                "maintenance_approval": 1,
                "destructive_approval": 1,
                "final_validation": 1,
            })
            self.assertEqual(len(payload["safe_archive_manifest"]), 6)
            self.assertEqual(len(payload["excluded_from_safe_archive"]), 19)
            command_groups = payload["command_groups"]
            self.assertEqual(command_groups["safe_unattended"]["command_count"], 8)
            self.assertEqual(command_groups["requires_substitution"]["command_count"], 14)
            self.assertEqual(command_groups["destructive_approval"]["command_count"], 1)
            self.assertEqual(command_groups["final_validation"]["command_count"], 1)
            execution_queues = payload["execution_queues"]
            self.assertEqual(execution_queues["safe_unattended"]["command_count"], 8)
            self.assertEqual(execution_queues["requires_substitution"]["command_count"], 15)
            self.assertEqual(execution_queues["target_value_required"]["command_count"], 0)
            self.assertEqual(execution_queues["dependency_blocked"]["command_count"], 8)
            self.assertIn("post_upgrade_strict_health", execution_queues["dependency_blocked"]["command_keys"])
            self.assertIn("live_restore", execution_queues["dependency_blocked"]["command_keys"])
            self.assertIn("p1_forum_moderation", execution_queues["dependency_blocked"]["command_keys"])
            self.assertEqual(payload["dependency_execution_waves"][-1]["command_keys"], ["live_restore"])
            self.assertEqual(execution_queues["maintenance_approval"]["command_count"], 1)
            self.assertEqual(execution_queues["maintenance_approval"]["command_keys"], ["upgrade_executed"])
            self.assertEqual(execution_queues["destructive_approval"]["command_count"], 1)
            self.assertEqual(execution_queues["final_validation"]["command_count"], 1)
            self.assertIn("live_restore", execution_queues["requires_substitution"]["command_keys"])
            self.assertIn("live_restore", execution_queues["destructive_approval"]["command_keys"])
            self.assertNotIn("live_restore", execution_queues["safe_unattended"]["command_keys"])
            self.assertEqual([item["groups"][0] for item in payload["execution_sequence"]], [
                "safe_unattended",
                "requires_substitution",
                "maintenance_approval",
                "destructive_approval",
                "final_validation",
            ])
            self.assertTrue(any("smoke_runtime_integrations" in command for command in command_groups["safe_unattended"]["commands"]))
            self.assertIn(str(base_dir / "ops" / "smoke-runtime-integrations.json"), command_groups["safe_unattended"]["output_files"])
            self.assertFalse(command_groups["safe_unattended"]["safe_archive_ready"])
            self.assertTrue(command_groups["safe_unattended"]["dependency_blocked"])
            self.assertTrue(command_groups["requires_substitution"]["requires_substitution"])
            self.assertFalse(command_groups["requires_substitution"]["target_value_required"])
            self.assertTrue(command_groups["destructive_approval"]["requires_substitution"])
            self.assertTrue(plan_path.exists())
            file_payload = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(file_payload["summary"], payload["summary"])
            self.assertEqual(file_payload["commands"], payload["commands"])
            self.assertNotIn("plan_file_path", file_payload)
            self.assertNotIn("safe_script_path", file_payload)
            self.assertNotIn("safe_shell_script_path", file_payload)
            commands = {item["key"]: item for item in payload["commands"]}
            self.assertIn(f"--plan-file {plan_path}", commands["validate_target_environment_evidence"]["command"])
            self.assertIn(f"--plan-file {plan_path}", commands["validate_target_environment_evidence"]["archive_command"])
            self.assertIn(f"--write-remediation-checklist {base_dir / 'ops' / 'target-environment-remediation-checklist.md'}", commands["validate_target_environment_evidence"]["command"])
            self.assertTrue(script_path.exists())
            script = script_path.read_text(encoding="utf-8")
            self.assertIn("Output directories are created before command redirection.", script)
            self.assertIn("New-Item -ItemType Directory -Force -Path", script)
            self.assertIn(str(base_dir / "ops"), script)
            self.assertIn(str(base_dir / "p0"), script)
            self.assertIn("safe_to_run_unattended=true", script)
            self.assertIn("forum-main-300s.json", script)
            self.assertIn("$global:LASTEXITCODE = 0", script)
            self.assertIn("if (-not $? -or $LASTEXITCODE -ne 0)", script)
            self.assertIn("archive command failed: strict_health exit code $LASTEXITCODE", script)
            self.assertIn("output archive is missing or empty", script)
            self.assertIn(f"Test-Path -LiteralPath '{base_dir / 'ops' / 'health-strict.json'}", script)
            self.assertIn(f"Get-Item -LiteralPath '{base_dir / 'ops' / 'health-strict.json'}", script)
            self.assertIn(".Length -eq 0", script)
            self.assertIn("stderr archive is missing or not empty", script)
            self.assertIn(f"Test-Path -LiteralPath '{base_dir / 'ops' / 'health-strict.stderr.txt'}", script)
            self.assertIn(f"Get-Item -LiteralPath '{base_dir / 'ops' / 'health-strict.stderr.txt'}", script)
            self.assertNotIn("backup-forum.json", script)
            self.assertNotIn("restore-forum-backup-dry-run.json", script)
            self.assertNotIn("smoke-queue-worker.json", script)
            self.assertNotIn("post-upgrade-health-strict.json", script)
            self.assertNotIn("forum-write-120s.json", script)
            self.assertNotRegex(script, r"<[^<>]+>")
            self.assertNotIn("upgrade-forum-executed.json", script)
            self.assertNotIn("restore-forum-backup-live.json", script)
            self.assertNotIn("validate_target_environment_evidence", script)
            self.assertNotIn("restore live forum data", script)
            self.assertTrue(shell_script_path.exists())
            shell_script = shell_script_path.read_text(encoding="utf-8")
            self.assertIn("#!/usr/bin/env sh", shell_script)
            self.assertIn("set -eu", shell_script)
            self.assertIn("mkdir -p", shell_script)
            self.assertIn(str(base_dir / "ops"), shell_script)
            self.assertIn(str(base_dir / "p0"), shell_script)
            self.assertIn("forum-main-300s.json", shell_script)
            self.assertIn(f"> '{base_dir / 'ops' / 'health-strict.json'}'", shell_script)
            self.assertIn(f"2> '{base_dir / 'ops' / 'health-strict.stderr.txt'}'", shell_script)
            self.assertIn("output archive is missing or empty", shell_script)
            self.assertIn(f"test -s '{base_dir / 'ops' / 'health-strict.json'}'", shell_script)
            self.assertIn("stderr archive is missing or not empty", shell_script)
            self.assertIn(
                f"test -f '{base_dir / 'ops' / 'health-strict.stderr.txt'}' && test ! -s '{base_dir / 'ops' / 'health-strict.stderr.txt'}'",
                shell_script,
            )
            self.assertNotIn(f"> {base_dir / 'ops' / 'health-strict.json'}", shell_script)
            self.assertNotRegex(shell_script, r"<[^<>]+>")
            self.assertNotIn("backup-forum.json", shell_script)
            self.assertNotIn("restore-forum-backup-dry-run.json", shell_script)
            self.assertNotIn("smoke-queue-worker.json", shell_script)
            self.assertNotIn("post-upgrade-health-strict.json", shell_script)
            self.assertNotIn("forum-write-120s.json", shell_script)
            self.assertNotIn("upgrade-forum-executed.json", shell_script)
            self.assertNotIn("restore-forum-backup-live.json", shell_script)
            self.assertNotIn("validate_target_environment_evidence", shell_script)
            self.assertNotIn("restore live forum data", shell_script)
            substitution_by_key = {item["key"]: item for item in payload["substitution_required_commands"]}
            self.assertIn("backup", substitution_by_key)
            self.assertIn("<durable-backup-uri>", substitution_by_key["backup"]["substitution_tokens"])
            self.assertIn("live_restore", substitution_by_key)
            self.assertTrue(substitution_by_key["live_restore"]["destructive"])
            self.assertTrue(substitution_by_key["live_restore"]["manual_approval_required"])
            self.assertEqual(substitution_by_key["live_restore"]["execution_group"], "destructive_approval")
            self.assertIn("<durable-backup-uri>", substitution_by_key["live_restore"]["substitution_tokens"])
            excluded_by_key = {item["key"]: item for item in payload["excluded_from_safe_archive"]}
            self.assertIn("requires_substitution", excluded_by_key["backup"]["exclude_reasons"])
            self.assertIn("requires_completed_commands", excluded_by_key["post_upgrade_strict_health"]["exclude_reasons"])
            self.assertTrue(excluded_by_key["post_upgrade_strict_health"]["safe_to_run_unattended"])
            self.assertFalse(excluded_by_key["post_upgrade_strict_health"]["safe_archive_ready"])
            self.assertEqual(excluded_by_key["post_upgrade_strict_health"]["requires_completed_commands"], ["upgrade_executed"])
            self.assertIn("destructive", excluded_by_key["live_restore"]["exclude_reasons"])
            self.assertIn("requires_substitution", excluded_by_key["live_restore"]["exclude_reasons"])
            self.assertIn("final_validation", excluded_by_key["validate_target_environment_evidence"]["exclude_reasons"])
            self.assertFalse(payload["target_value_required_commands"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_plan_target_environment_evidence_allows_supplied_target_values_in_safe_script(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            script_path = base_dir / "target-safe.ps1"

            stdout = StringIO()
            call_command(
                "plan_target_environment_evidence",
                "--base-url",
                "https://forum.example.test",
                "--report-dir",
                str(base_dir / "ops"),
                "--p0-report-dir",
                str(base_dir / "p0"),
                "--p1-report-dir",
                str(base_dir / "p1"),
                "--backup-dir",
                "s3://bias-target-backups/release-001",
                "--discussion-id",
                "42",
                "--load-username",
                "load-user",
                "--load-password",
                "load-password",
                "--moderator-username",
                "mod-user",
                "--moderator-password",
                "mod-password",
                "--redis-broker-url",
                "redis://redis.example.test:6379/1",
                "--redis-result-backend",
                "redis://redis.example.test:6379/2",
                "--web-nodes",
                "2",
                "--worker-nodes",
                "2",
                "--scheduler-nodes",
                "1",
                "--image",
                "registry.example.test/bias:20260702",
                "--app-version",
                "20260702",
                "--database-endpoint",
                "postgres.example.test:5432/bias",
                "--redis-endpoint",
                "redis.example.test:6379",
                "--write-safe-script",
                str(script_path),
                "--format",
                "json",
                stdout=stdout,
            )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["summary"]["safe_unattended_command_count"], 22)
            self.assertEqual(payload["summary"]["safe_archive_ready_command_count"], 15)
            self.assertEqual(payload["summary"]["excluded_from_safe_archive_count"], 10)
            self.assertEqual(payload["summary"]["substitution_required_command_count"], 0)
            self.assertEqual(payload["summary"]["target_value_required_command_count"], 0)
            self.assertEqual(payload["summary"]["dependency_blocked_command_count"], 8)
            self.assertEqual(payload["summary"]["dependency_execution_wave_count"], 3)
            self.assertEqual(payload["summary"]["execution_queue_counts"], {
                "safe_unattended": 22,
                "requires_substitution": 0,
                "target_value_required": 0,
                "dependency_blocked": 8,
                "maintenance_approval": 1,
                "destructive_approval": 1,
                "final_validation": 1,
            })
            self.assertFalse(payload["substitution_required_commands"])
            self.assertFalse(payload["target_value_required_commands"])
            self.assertEqual(len(payload["safe_archive_manifest"]), 15)
            self.assertEqual(len(payload["excluded_from_safe_archive"]), 10)
            commands = {item["key"]: item for item in payload["commands"]}
            self.assertTrue(commands["queue_worker"]["safe_to_run_unattended"])
            self.assertTrue(commands["queue_worker"]["safe_archive_ready"])
            self.assertTrue(commands["post_upgrade_queue_worker"]["safe_to_run_unattended"])
            self.assertFalse(commands["post_upgrade_queue_worker"]["safe_archive_ready"])
            self.assertEqual(commands["post_upgrade_queue_worker"]["requires_completed_commands"], ["upgrade_executed"])
            self.assertTrue(commands["multi_node_topology"]["safe_to_run_unattended"])
            self.assertTrue(commands["multi_node_topology"]["safe_archive_ready"])
            execution_queues = payload["execution_queues"]
            self.assertEqual(execution_queues["dependency_blocked"]["command_count"], 8)
            self.assertIn("post_upgrade_queue_worker", execution_queues["dependency_blocked"]["command_keys"])
            self.assertIn("p1_forum_moderation", execution_queues["dependency_blocked"]["command_keys"])
            self.assertEqual(payload["dependency_execution_waves"][1]["command_keys"], ["restore_dry_run", "p1_forum_moderation"])
            script = script_path.read_text(encoding="utf-8")
            self.assertIn("New-Item -ItemType Directory -Force -Path", script)
            self.assertIn(str(base_dir / "ops"), script)
            self.assertIn(str(base_dir / "p0"), script)
            self.assertIn(str(base_dir / "p1"), script)
            self.assertIn("smoke-queue-worker.json", script)
            self.assertNotIn("post-upgrade-smoke-queue-worker.json", script)
            self.assertIn("multi-node-topology.json", script)
            self.assertIn("redis://redis.example.test:6379/1", script)
            self.assertIn("registry.example.test/bias:20260702", script)
            self.assertNotRegex(script, r"<[^<>]+>")
            self.assertNotIn("upgrade-forum-executed.json", script)
            self.assertNotIn("restore-forum-backup-live.json", script)
            self.assertNotIn("validate_target_environment_evidence", script)
            excluded_by_key = {item["key"]: item for item in payload["excluded_from_safe_archive"]}
            self.assertIn("requires_completed_commands", excluded_by_key["post_upgrade_queue_worker"]["exclude_reasons"])
            self.assertIn("requires_completed_commands", excluded_by_key["p1_forum_write_mixed"]["exclude_reasons"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_plan_target_environment_evidence_blocks_local_target_values_from_safe_script(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            script_path = base_dir / "target-safe.ps1"

            stdout = StringIO()
            call_command(
                "plan_target_environment_evidence",
                "--base-url",
                "https://forum.example.test",
                "--report-dir",
                str(base_dir / "ops"),
                "--p0-report-dir",
                str(base_dir / "p0"),
                "--p1-report-dir",
                str(base_dir / "p1"),
                "--backup-dir",
                "backups/target-p2",
                "--discussion-id",
                "42",
                "--load-username",
                "load-user",
                "--load-password",
                "load-password",
                "--moderator-username",
                "mod-user",
                "--moderator-password",
                "mod-password",
                "--redis-broker-url",
                "redis://redis:6379/1",
                "--redis-result-backend",
                "redis://redis:6379/2",
                "--web-nodes",
                "1",
                "--worker-nodes",
                "1",
                "--scheduler-nodes",
                "1",
                "--image",
                "local-production-smoke",
                "--app-version",
                "0.1.1",
                "--database-endpoint",
                "postgres://postgres:5432/bias_smoke",
                "--redis-endpoint",
                "redis://redis:6379/0",
                "--write-safe-script",
                str(script_path),
                "--format",
                "json",
                stdout=stdout,
            )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"], payload)
            self.assertEqual(payload["summary"]["substitution_required_command_count"], 0)
            target_value_by_key = {item["key"]: item for item in payload["target_value_required_commands"]}
            self.assertIn("queue_worker", target_value_by_key)
            self.assertIn("post_upgrade_queue_worker", target_value_by_key)
            self.assertIn("backup", target_value_by_key)
            self.assertIn("multi_node_topology", target_value_by_key)
            self.assertIn("redis_broker_url must identify", target_value_by_key["queue_worker"]["target_value_errors"][0])
            self.assertIn("backup_dir must be a durable", target_value_by_key["backup"]["target_value_errors"][0])
            self.assertIn("web_nodes must be at least 2", target_value_by_key["multi_node_topology"]["target_value_errors"])
            self.assertIn("image must identify a target release image", target_value_by_key["multi_node_topology"]["target_value_errors"])
            commands = {item["key"]: item for item in payload["commands"]}
            self.assertEqual(commands["queue_worker"]["execution_group"], "target_value_required")
            self.assertFalse(commands["queue_worker"]["safe_to_run_unattended"])
            self.assertEqual(commands["multi_node_topology"]["execution_group"], "target_value_required")
            self.assertFalse(commands["multi_node_topology"]["safe_to_run_unattended"])
            excluded_by_key = {item["key"]: item for item in payload["excluded_from_safe_archive"]}
            self.assertIn("target_value_required", excluded_by_key["queue_worker"]["exclude_reasons"])
            self.assertIn("target_value_required", excluded_by_key["backup"]["exclude_reasons"])
            self.assertIn("target_value_required", excluded_by_key["multi_node_topology"]["exclude_reasons"])
            script = script_path.read_text(encoding="utf-8")
            self.assertNotIn("smoke-queue-worker.json", script)
            self.assertNotIn("backup-forum.json", script)
            self.assertNotIn("multi-node-topology.json", script)
            self.assertNotIn("redis://redis:6379/1", script)
            self.assertNotIn("local-production-smoke", script)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_plan_target_environment_evidence_preserves_final_validation_group_with_template_paths(self):
        stdout = StringIO()
        call_command(
            "plan_target_environment_evidence",
            "--base-url",
            "https://forum.example.test",
            "--report-dir",
            "reports/capacity/<target-run-id>",
            "--p0-report-dir",
            "reports/capacity/<target-p0-run-id>",
            "--p1-report-dir",
            "reports/capacity/<target-p1-run-id>",
            "--format",
            "json",
            stdout=stdout,
        )

        payload = json.loads(stdout.getvalue())
        commands = {item["key"]: item for item in payload["commands"]}
        final_validation = commands["validate_target_environment_evidence"]
        self.assertTrue(final_validation["requires_substitution"])
        self.assertFalse(final_validation["safe_to_run_unattended"])
        self.assertEqual(final_validation["execution_group"], "final_validation")
        self.assertEqual(payload["final_validation_commands"][0]["key"], "validate_target_environment_evidence")
        self.assertTrue(payload["final_validation_commands"][0]["requires_substitution"])
        self.assertIn("<target-run-id>", payload["final_validation_commands"][0]["substitution_tokens"])
        self.assertIn("<target-run-id>", final_validation["substitution_tokens"])
        self.assertIn("--plan-file", final_validation["command"])
        self.assertIn("target-environment-evidence-plan.json", final_validation["command"])
        self.assertNotIn(final_validation["archive_command"], payload["safe_archive_commands"])

    def _write_complete_target_evidence_plan(self, plan_path, report_dir, p0_report_dir, p1_report_dir):
        stdout = StringIO()
        call_command(
            "plan_target_environment_evidence",
            "--base-url",
            "https://forum.example.test",
            "--report-dir",
            str(report_dir),
            "--p0-report-dir",
            str(p0_report_dir),
            "--p1-report-dir",
            str(p1_report_dir),
            "--backup-dir",
            "s3://bias-target-backups/release-001",
            "--discussion-id",
            "42",
            "--load-username",
            "load-user",
            "--load-password",
            "load-password",
            "--moderator-username",
            "mod-user",
            "--moderator-password",
            "mod-password",
            "--redis-broker-url",
            "redis://redis.target.example:6379/1",
            "--redis-result-backend",
            "redis://redis.target.example:6379/2",
            "--web-nodes",
            "2",
            "--worker-nodes",
            "2",
            "--scheduler-nodes",
            "1",
            "--image",
            "registry.example.test/bias:20260702",
            "--app-version",
            "20260702",
            "--database-endpoint",
            "postgres.target.example:5432/bias",
            "--redis-endpoint",
            "redis.target.example:6379",
            "--format",
            "json",
            stdout=stdout,
        )
        payload = json.loads(stdout.getvalue())
        self._write_json(plan_path, payload)
        self._write_plan_stderr_files(payload)

    def _write_complete_target_evidence(self, report_dir):
        self._write_json(report_dir / "health-strict.json", {
            "status": "ok",
            "strict": True,
            "strict_failed": False,
        })
        self._write_json(report_dir / "smoke-http-p95.json", {
            "base_url": "https://forum.example.test",
            "summary": {"ok": True},
        })
        self._write_json(report_dir / "load-websocket-external-20.json", {
            "url": "wss://forum.example.test/ws/forum/",
            "discussion_id": 42,
            "summary": {
                "ok": True,
                "connection_count": 20,
                "expected_connection_count": 20,
                "p95_threshold_ms": 1000.0,
                "broadcast_count": 20,
                "expected_broadcast_count": 20,
                "broadcast_threshold_ms": 1000.0,
            },
        })
        self._write_json(report_dir / "backup-forum.json", {
            "backup_dir": "s3://bias-target-backups/release-001",
            "backup_artifacts": [
                {"key": "site_config", "path": "s3://bias-target-backups/release-001/site.json", "required": True, "exists": True},
                {"key": "database", "path": "s3://bias-target-backups/release-001/database.dump", "required": True, "exists": True},
                {"key": "media", "path": "s3://bias-target-backups/release-001/media", "required": True, "exists": True},
                {"key": "static_frontend", "path": "s3://bias-target-backups/release-001/static/frontend", "required": True, "exists": True},
            ],
            "summary": {
                "ok": True,
                "dry_run": False,
                "missing_required_artifact_count": 0,
            },
        })
        self._write_json(report_dir / "verify-forum-backup.json", {
            "backup_dir": "s3://bias-target-backups/release-001",
            "checks": [
                {"key": "site_config", "path": "s3://bias-target-backups/release-001/site.json", "exists": True, "ok": True},
                {"key": "database", "path": "s3://bias-target-backups/release-001/database.dump", "exists": True, "ok": True, "database_mode": "postgres", "validated_by": "pg_restore_list"},
                {"key": "media", "path": "s3://bias-target-backups/release-001/media", "exists": True, "ok": True},
                {"key": "static_frontend", "path": "s3://bias-target-backups/release-001/static/frontend", "exists": True, "ok": True},
            ],
            "summary": {
                "ok": True,
                "error_count": 0,
            },
        })
        for filename in ("smoke-queue-worker.json", "post-upgrade-smoke-queue-worker.json"):
            self._write_json(report_dir / filename, {
                "broker_url": "redis://redis.target.example:6379/1",
                "result_backend": "redis://redis.target.example:6379/2",
                "token": "queue-smoke-target",
                "worker_status": {"available": True, "worker_count": 2},
                "task_result": {"ok": True, "token": "queue-smoke-target"},
                "summary": {"ok": True},
            })
        self._write_json(report_dir / "post-upgrade-smoke-http-p95.json", {
            "base_url": "https://forum.example.test",
            "summary": {"ok": True},
        })
        self._write_json(report_dir / "install-forum-dry-run.json", {
            "summary": {"ok": True, "dry_run": True},
        })
        self._write_json(report_dir / "upgrade-forum-dry-run.json", {
            "summary": {"ok": True, "dry_run": True, "executed": False},
        })
        self._write_json(report_dir / "upgrade-forum-executed.json", {
            "summary": {"ok": True, "dry_run": False, "executed": True},
        })
        self._write_json(report_dir / "post-upgrade-health-strict.json", {
            "status": "ok",
            "strict": True,
            "strict_failed": False,
        })
        self._write_json(report_dir / "plan-forum-rollback-with-backups.json", {
            "backup_dir": "s3://bias-target-backups/release-001",
            "backup_artifacts": [
                {"key": "site_config", "path": "s3://bias-target-backups/release-001/site.json", "required": True, "exists": True},
                {"key": "database", "path": "s3://bias-target-backups/release-001/database.dump", "required": True, "exists": True},
                {"key": "media", "path": "s3://bias-target-backups/release-001/media", "required": True, "exists": True},
                {"key": "static_frontend", "path": "s3://bias-target-backups/release-001/static/frontend", "required": True, "exists": True},
            ],
            "restore_steps": [
                {"action": "restore_database", "destructive": True, "artifact_key": "database"},
                {"action": "restore_media", "destructive": True, "artifact_key": "media"},
                {"action": "restore_static_frontend", "destructive": True, "artifact_key": "static_frontend"},
                {"action": "restore_site_config", "destructive": True, "artifact_key": "site_config"},
            ],
            "summary": {
                "ok": True,
                "require_existing_backups": True,
                "missing_required_artifact_count": 0,
                "executes_restore": False,
            },
        })
        self._write_json(report_dir / "rehearse-forum-restore.json", {
            "backup_dir": "s3://bias-target-backups/release-001",
            "database_mode": "postgres",
            "backup_artifacts": [
                {"key": "site_config", "path": "s3://bias-target-backups/release-001/site.json", "required": True, "exists": True},
                {"key": "database", "path": "s3://bias-target-backups/release-001/database.dump", "required": True, "exists": True},
                {"key": "media", "path": "s3://bias-target-backups/release-001/media", "required": True, "exists": True},
                {"key": "static_frontend", "path": "s3://bias-target-backups/release-001/static/frontend", "required": True, "exists": True},
            ],
            "restore_steps": [
                {"action": "restore_site_config_to_temp_file", "artifact_key": "site_config", "source": "s3://bias-target-backups/release-001/site.json", "destructive": False, "ok": True},
                {"action": "create_temp_database", "destructive": False, "ok": True},
                {"action": "restore_dump_to_temp_database", "destructive": False, "ok": True},
                {"action": "verify_temp_database", "destructive": False, "ok": True},
                {"action": "drop_temp_database", "destructive": False, "ok": True},
                {"action": "restore_media_to_temp_directory", "artifact_key": "media", "source": "s3://bias-target-backups/release-001/media", "destructive": False, "ok": True},
                {"action": "restore_static_frontend_to_temp_directory", "artifact_key": "static_frontend", "source": "s3://bias-target-backups/release-001/static/frontend", "destructive": False, "ok": True},
            ],
            "verification": [
                {"key": "site_config", "ok": True, "validated_by": "read_site_config"},
                {"key": "database", "ok": True, "validated_by": "pg_restore_temp_database", "table_count": 31},
                {"key": "media", "ok": True, "validated_by": "copytree_to_temp_directory"},
                {"key": "static_frontend", "ok": True, "validated_by": "copytree_to_temp_directory"},
            ],
            "summary": {
                "ok": True,
                "executes_live_restore": False,
                "uses_isolated_restore_targets": True,
                "keep_temp_database": False,
                "dropped_temp_database": True,
            },
        })
        self._write_json(report_dir / "restore-forum-backup-dry-run.json", {
            "backup_dir": "s3://bias-target-backups/release-001",
            "backup_artifacts": [
                {"key": "database", "path": "s3://bias-target-backups/release-001/database.dump", "required": True, "exists": True},
                {"key": "media", "path": "s3://bias-target-backups/release-001/media", "required": True, "exists": True},
                {"key": "static_frontend", "path": "s3://bias-target-backups/release-001/static/frontend", "required": True, "exists": True},
                {"key": "site_config", "path": "s3://bias-target-backups/release-001/site.json", "required": True, "exists": True},
            ],
            "restore_steps": [
                {"artifact_key": "database", "source": "s3://bias-target-backups/release-001/database.dump", "destructive": True, "planned_only": True, "ok": True},
                {"artifact_key": "media", "source": "s3://bias-target-backups/release-001/media", "destructive": True, "planned_only": True, "ok": True},
                {"artifact_key": "static_frontend", "source": "s3://bias-target-backups/release-001/static/frontend", "destructive": True, "planned_only": True, "ok": True},
                {"artifact_key": "site_config", "source": "s3://bias-target-backups/release-001/site.json", "destructive": True, "planned_only": True, "ok": True},
            ],
            "summary": {
                "ok": True,
                "dry_run": True,
                "destructive": True,
                "executes_live_restore": False,
            },
        })
        self._write_json(report_dir / "restore-forum-backup-live.json", {
            "backup_dir": "s3://bias-target-backups/release-001",
            "backup_artifacts": [
                {"key": "database", "path": "s3://bias-target-backups/release-001/database.dump", "required": True, "exists": True},
                {"key": "media", "path": "s3://bias-target-backups/release-001/media", "required": True, "exists": True},
                {"key": "static_frontend", "path": "s3://bias-target-backups/release-001/static/frontend", "required": True, "exists": True},
                {"key": "site_config", "path": "s3://bias-target-backups/release-001/site.json", "required": True, "exists": True},
            ],
            "restore_steps": [
                {"artifact_key": "database", "source": "s3://bias-target-backups/release-001/database.dump", "destructive": True, "planned_only": False, "ok": True},
                {"artifact_key": "media", "source": "s3://bias-target-backups/release-001/media", "destructive": True, "planned_only": False, "ok": True},
                {"artifact_key": "static_frontend", "source": "s3://bias-target-backups/release-001/static/frontend", "destructive": True, "planned_only": False, "ok": True},
                {"artifact_key": "site_config", "source": "s3://bias-target-backups/release-001/site.json", "destructive": True, "planned_only": False, "ok": True},
            ],
            "verification": [
                {"key": "site_config", "ok": True, "validated_by": "read_site_config"},
                {"key": "database", "ok": True, "validated_by": "psql_live_database", "table_count": 31},
                {"key": "media", "ok": True, "validated_by": "directory_scan", "file_count": 12},
                {"key": "static_frontend", "ok": True, "validated_by": "directory_scan", "file_count": 8},
            ],
            "summary": {
                "ok": True,
                "dry_run": False,
                "confirmed_overwrites_live_data": True,
                "executes_live_restore": True,
                "verification_count": 4,
            },
        })
        self._write_json(report_dir / "smoke-runtime-integrations.json", {
            "checks": [
                {"key": "email", "mode": "smtp_connect", "connected": True, "ok": True},
                {"key": "storage", "mode": "write_read_delete", "driver": "s3", "deleted": True, "ok": True},
            ],
            "summary": {
                "ok": True,
                "fail_on_warning": True,
                "require_smtp_connect": True,
                "require_storage_write": True,
                "require_object_storage": True,
                "warning_count": 0,
            },
        })
        self._write_json(report_dir / "multi-node-topology.json", {
            "roles": {
                "web": 2,
                "worker": 2,
                "scheduler": 1,
            },
            "artifacts": {
                "image": "registry.example.test/bias:20260702",
                "version": "20260702",
            },
            "shared_services": {
                "database": "postgres.target.example:5432/bias",
                "redis": "redis.target.example:6379",
                "load_balancer": "https://forum.example.test",
            },
            "summary": {
                "ok": True,
                "multi_node": True,
            },
        })

    def _write_p0_capacity_evidence(self, report_dir):
        self._write_capacity_profile(
            report_dir / "forum-main-300s.json",
            profile="forum-main",
            concurrency=20,
            duration_seconds=300.1,
        )

    def _write_p1_capacity_evidence(self, report_dir):
        self._write_capacity_profile(
            report_dir / "forum-main-auth-300s.json",
            profile="forum-main-auth",
            concurrency=20,
            duration_seconds=300.1,
            login_username="load-user",
        )
        self._write_capacity_profile(
            report_dir / "forum-write-120s.json",
            profile="forum-write",
            concurrency=5,
            duration_seconds=120.1,
            discussion_id=42,
            login_username="load-user",
        )
        self._write_capacity_profile(
            report_dir / "forum-write-mixed-120s.json",
            profile="forum-write-mixed",
            concurrency=5,
            duration_seconds=120.1,
            login_username="load-user",
            prepare_isolated_targets=True,
            cleanup_isolated_targets=True,
        )
        self._write_capacity_profile(
            report_dir / "forum-upload-120s.json",
            profile="forum-upload",
            concurrency=5,
            duration_seconds=120.1,
            login_username="load-user",
        )
        self._write_capacity_profile(
            report_dir / "forum-write-moderation-60s.json",
            profile="forum-write-moderation",
            concurrency=2,
            duration_seconds=60.1,
            login_username="mod-user",
            prepare_isolated_targets=True,
            cleanup_isolated_targets=True,
        )

    def _write_capacity_profile(
        self,
        path,
        *,
        profile,
        concurrency,
        duration_seconds,
        discussion_id=None,
        login_username=None,
        prepare_isolated_targets=False,
        cleanup_isolated_targets=False,
    ):
        payload = {
            "base_url": "https://forum.example.test",
            "profile": profile,
            "login_username": login_username or "",
            "prepare_isolated_targets": prepare_isolated_targets,
            "cleanup_isolated_targets": cleanup_isolated_targets,
            "concurrency": concurrency,
            "duration_seconds": duration_seconds,
            "targets": [],
            "summary": {
                "ok": True,
                "error_count": 0,
                "failed_threshold_count": 0,
            },
        }
        if discussion_id is not None:
            payload["dynamic_values"] = {"discussion_id": discussion_id}
        self._write_json(path, payload)

    def _write_json(self, path, payload):
        Path(path).write_text(json.dumps(payload), encoding="utf-8")

    def _write_plan_stderr_files(self, plan_payload):
        for command in plan_payload.get("commands", []):
            if not isinstance(command, dict):
                continue
            if command.get("execution_group") == "final_validation":
                continue
            stderr_file = command.get("stderr_file")
            if stderr_file:
                Path(stderr_file).write_text("", encoding="utf-8")

    def test_ci_runs_extension_workspace_gate_when_split_workspace_is_available(self):
        workflow_path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
        workflow = workflow_path.read_text(encoding="utf-8")

        self.assertIn("Check extension workspace gate", workflow)
        self.assertIn("python -m django check_extension_workspace", workflow)
        self.assertNotIn("python -m django inspect_extension_imports", workflow)
        self.assertIn("python -m django inspect_extension_packages", workflow)
        self.assertIn("--require-extensions", workflow)
        self.assertIn("--migration-smoke", workflow)

    def test_content_foundation_migration_state_is_current(self):
        stdout = StringIO()

        call_command(
            "makemigrations",
            "content",
            "discussions",
            "posts",
            "--check",
            "--dry-run",
            stdout=stdout,
            stderr=StringIO(),
        )

        self.assertIn("No changes detected", stdout.getvalue())

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
                self.assertEqual(manifest["schema_version"], 1)
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
                self.assertEqual(
                    pyproject["tool"]["pytest"]["ini_options"]["DJANGO_SETTINGS_MODULE"],
                    "bias_core.extension_test_settings",
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
                self.assertIn("from .resources import resource_extender", backend_source)
                self.assertIn("from .runtime import service_contract_extender, service_provider_extender", backend_source)
                self.assertIn("frontend_extender()", backend_source)
                self.assertIn("service_provider_extender()", backend_source)
                self.assertIn("service_contract_extender()", backend_source)
                self.assertIn("resource_extender()", backend_source)
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
                self.assertIn("from bias_core.extensions import ApiResourceExtender, ExtensionResourceEndpointDefinition", resources_source)
                self.assertIn("def status_endpoint(context):", resources_source)
                self.assertIn("    from bias_core.extensions.runtime import call_runtime_service", resources_source)
                self.assertIn('return call_runtime_service(f"{EXTENSION_ID}.status", "status_payload")', resources_source)
                self.assertIn("def resource_extender():", resources_source)
                self.assertIn('ApiResourceExtender("forum").endpoint(', resources_source)
                self.assertIn("ExtensionResourceEndpointDefinition(", resources_source)
                self.assertIn('endpoint=f"{EXTENSION_ID}.status"', resources_source)
                self.assertIn('path=f"{EXTENSION_ID}/status"', resources_source)
                self.assertIn("handler=status_endpoint", resources_source)
                self.assertNotIn("from bias_core.", resources_source.replace("from bias_core.extensions", ""))
                self.assertIn("def policy_definitions():", policies_source)
                self.assertIn("def event_listener_definitions():", listeners_source)
                self.assertIn("from bias_core.extensions import RuntimeServiceContractExtender, ServiceProviderExtender", runtime_source)
                self.assertIn("class StatusService:", runtime_source)
                self.assertIn("def status_payload(self):", runtime_source)
                self.assertIn("def status_service_provider():", runtime_source)
                self.assertIn("def service_provider_extender():", runtime_source)
                self.assertIn("def service_contract_extender():", runtime_source)
                self.assertIn('key=f"{EXTENSION_ID}.status"', runtime_source)
                self.assertIn('version="1.0"', runtime_source)
                self.assertIn('required_methods=("status_payload",)', runtime_source)
                self.assertIn('required_values=("model",)', runtime_source)
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
                self.assertNotIn("RuntimeActionsExtender", backend_source)
                self.assertNotIn("AdminNavigationExtender", backend_source)
                admin_source = (extension_dir / "frontend" / "admin" / "index.js").read_text(encoding="utf-8")
                forum_source = (extension_dir / "frontend" / "forum" / "index.js").read_text(encoding="utf-8")
                self.assertIn("from '@bias/core/admin'", admin_source)
                self.assertIn("export const extend", admin_source)
                self.assertIn("extendAdmin(admin => admin", admin_source)
                self.assertIn(".page({", admin_source)
                self.assertIn("name: 'alpha-tools.getting-started'", admin_source)
                self.assertIn("path: '/admin/extensions/alpha-tools/getting-started'", admin_source)
                self.assertIn("export function resolveDetailPage()", admin_source)
                self.assertIn("return null", admin_source)
                self.assertIn("from '@bias/core/forum'", forum_source)
                self.assertIn("extendForum(forum => forum", forum_source)
                self.assertIn(".navItem({", forum_source)
                self.assertIn("key: 'alpha-tools'", forum_source)
                self.assertIn("href: '/alpha-tools'", forum_source)
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
                self.assertIn("admin page", readme_source)
                self.assertIn("forum nav item", readme_source)
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

                from bias_core.extensions.bootstrap import build_extension_application
                from bias_core.extensions.manager import ExtensionManager
                from bias_core.models import ExtensionInstallation

                manager_extensions_dir = Path(temp_dir) / "runtime-extensions"
                manager_extension_dir = manager_extensions_dir / "alpha-tools"
                shutil.copytree(extension_dir, manager_extension_dir)
                ExtensionInstallation.objects.create(
                    extension_id="alpha-tools",
                    version="0.1.0",
                    source="filesystem",
                    enabled=True,
                    installed=True,
                    booted=True,
                )
                application = build_extension_application(
                    manager=ExtensionManager(extensions_path=manager_extensions_dir),
                    force=True,
                )
                runtime_view = application.get_runtime_view("alpha-tools")
                self.assertIsNotNone(runtime_view)
                self.assertEqual(runtime_view.frontend_admin_entry, "frontend/admin/index.js")
                self.assertEqual(runtime_view.frontend_forum_entry, "frontend/forum/index.js")
                self.assertEqual(len(runtime_view.resource_endpoints), 1)
                self.assertEqual(runtime_view.resource_endpoints[0].resource, "forum")
                self.assertEqual(runtime_view.resource_endpoints[0].endpoint, "alpha-tools.status")
                self.assertEqual(runtime_view.resource_endpoints[0].path, "alpha-tools/status")
                self.assertEqual(runtime_view.resource_endpoints[0].methods, ("GET",))

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

    def test_create_extension_command_accepts_explicit_target_workspace(self):
        temp_dir = make_workspace_temp_dir()
        try:
            target = Path(temp_dir) / "generated-extensions"
            with override_settings(BASE_DIR=Path(temp_dir) / "bias"):
                call_command_quietly(
                    "create_extension",
                    "alpha-tools",
                    "--target",
                    str(target),
                )

            self.assertTrue((target / "bias-ext-alpha-tools" / "extension.json").exists())
            self.assertTrue((target / "bias-ext-alpha-tools" / "pyproject.toml").exists())
            self.assertFalse((Path(temp_dir) / "bias-ext-alpha-tools").exists())
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
                self.assertIn(".page({", entry_source)
                self.assertIn("path: '/admin/extensions/alpha-tools/getting-started'", entry_source)
                forum_entry_source = (Path(temp_dir) / "bias-ext-alpha-tools" / "frontend" / "forum" / "index.js").read_text(encoding="utf-8")
                self.assertIn("export const extend", forum_entry_source)
                self.assertIn("extendForum(forum => forum", forum_entry_source)
                self.assertIn(".navItem({", forum_entry_source)
                self.assertIn("key: 'alpha-tools'", forum_entry_source)
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

    def test_validate_extensions_command_rejects_unsupported_manifest_schema_version(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")
                manifest_path = Path(temp_dir) / "bias-ext-alpha-tools" / "extension.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["schema_version"] = 99
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
            self.assertEqual(payload["manifests"][0]["schema_version"], 99)
            self.assertTrue(any(
                issue["code"] == "unsupported_manifest_schema_version"
                and issue["field"] == "schema_version"
                for issue in payload["issues"]
            ))
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

    def test_validate_extensions_command_rejects_manifest_dependencies_without_package_dependencies(self):
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
                self.assertFalse(payload["summary"]["ok"])
                self.assertTrue(any(
                    item["code"] == "extension_package_metadata_invalid"
                    and item["extension_id"] == "beta-tools"
                    and "bias-ext-alpha-tools" in item["message"]
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
        import zipfile
        from bias_core.extensions.packaging import inspect_extension_package_wheel

        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")

            extension_dir = Path(temp_dir) / "bias-ext-alpha-tools"
            output_dir = Path(temp_dir) / "wheel-output"
            result = inspect_extension_package_wheel(
                extension_dir,
                extension_id="alpha-tools",
                extension_version="0.1.0",
                backend_entry="bias_ext_alpha_tools.backend.ext",
                build=True,
                build_output_dir=output_dir,
                timeout=60,
            )
            self.assertEqual(result.errors, ())
            self.assertIsNotNone(result.wheel_path)

            wheels = sorted(output_dir.glob("*.whl"))
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
                self.assertIn(
                    "bias_ext_alpha_tools-0.1.0.data/data/bias_extensions/alpha-tools/frontend/admin/index.js",
                    names,
                )
                self.assertIn("bias_ext_alpha_tools/backend/ext.py", names)
                self.assertIn("bias_ext_alpha_tools/backend/resources.py", names)
                self.assertIn("bias_ext_alpha_tools/backend/apps.py", names)
                self.assertIn("bias_ext_alpha_tools/backend/django_migrations/__init__.py", names)
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

    def test_inspect_extension_packages_outputs_install_plan_and_upgrade_risk(self):
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
            self.assertTrue(payload["summary"]["ok"])
            self.assertEqual(payload["install_plan"]["schema"], 1)
            self.assertFalse(payload["install_plan"]["executes_install"])
            self.assertEqual(payload["install_plan"]["install_order"], ["alpha-tools"])
            self.assertIn("build_wheel", [step["action"] for step in payload["install_plan"]["steps"]])
            self.assertIn("install_smoke", [step["action"] for step in payload["install_plan"]["steps"]])
            self.assertEqual(payload["install_plan"]["missing_dependencies"], {})
            self.assertEqual(payload["summary"]["risk_count"], payload["upgrade_risk"]["summary"]["risk_count"])
            self.assertEqual(payload["summary"]["blocking_risk_count"], 0)
            self.assertTrue(any(
                risk["extension_id"] == "alpha-tools"
                and risk["code"] == "unstable_api"
                and risk["severity"] == "warning"
                for risk in payload["upgrade_risk"]["risks"]
            ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_packages_upgrade_risk_blocks_missing_dependency_and_incompatible_bias(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")
                manifest_path = Path(temp_dir) / "bias-ext-alpha-tools" / "extension.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["dependencies"] = ["core", "missing-tools"]
                manifest.setdefault("compatibility", {})
                manifest["compatibility"]["bias_version"] = ">=99.0.0"
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

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
            self.assertEqual(payload["install_plan"]["missing_dependencies"], {"alpha-tools": ["missing-tools"]})
            blocking_codes = {
                risk["code"]
                for risk in payload["upgrade_risk"]["risks"]
                if risk["severity"] == "blocking"
            }
            self.assertEqual(blocking_codes, {"missing_dependency", "bias_version_incompatible"})
            self.assertEqual(payload["upgrade_risk"]["summary"]["blocking_risk_count"], 2)
            self.assertEqual(payload["summary"]["blocking_risk_count"], 2)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_packages_counts_resources_under_hidden_temp_parent(self):
        temp_dir = make_workspace_temp_dir()
        try:
            target = Path(temp_dir) / ".tmp-extension-dx"
            with override_settings(BASE_DIR=Path(temp_dir) / "bias"):
                call_command_quietly(
                    "create_extension",
                    "alpha-tools",
                    "--target",
                    str(target),
                )

                output = StringIO()
                call_command(
                    "inspect_extension_packages",
                    "--extensions-path",
                    str(target),
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
            self.assertGreaterEqual(result["source_file_count"], 3)
            self.assertEqual(result["discovered_extension_id"], "alpha-tools")
            self.assertEqual(result["discovered_source"], "python-package")
            self.assertEqual(result["errors"], [])
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

    def test_inspect_extension_packages_command_smokes_installed_wheel_lifecycle(self):
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
                    "--install-set-smoke",
                    "--lifecycle-smoke",
                    "--format",
                    "json",
                    stdout=output,
                )

            payload = json.loads(output.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            install_set = payload["install_set"]
            self.assertTrue(install_set["lifecycle_smoke"])
            self.assertEqual(install_set["discovered_sources"]["alpha-tools"], "python-package")
            self.assertEqual(
                install_set["lifecycle_states"]["alpha-tools"],
                {"installed": True, "enabled": True, "booted": True},
            )
            hooks = install_set["lifecycle_backend_hooks"]["alpha-tools"]
            self.assertIn(hooks["install"], {"ok", "skipped"})
            self.assertIn(hooks["install_enable"], {"ok", "skipped"})
            self.assertIn(hooks["disable"], {"ok", "skipped"})
            self.assertIn(hooks["enable"], {"ok", "skipped"})
            self.assertEqual(install_set["errors"], [])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_packages_lifecycle_smoke_allows_auto_installed_extension(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")
                manifest_path = Path(temp_dir) / "bias-ext-alpha-tools" / "extension.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest.setdefault("extra", {})
                manifest["extra"]["auto_install"] = True
                manifest["extra"]["auto_enable"] = True
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

                output = StringIO()
                call_command(
                    "inspect_extension_packages",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--extension-id",
                    "alpha-tools",
                    "--build",
                    "--install-set-smoke",
                    "--lifecycle-smoke",
                    "--format",
                    "json",
                    stdout=output,
                )

            payload = json.loads(output.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            install_set = payload["install_set"]
            self.assertTrue(install_set["lifecycle_states"]["alpha-tools"]["installed"])
            self.assertTrue(install_set["lifecycle_states"]["alpha-tools"]["enabled"])
            self.assertEqual(install_set["errors"], [])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_packages_lifecycle_smoke_allows_protected_extension(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command_quietly("create_extension", "alpha-tools")
                manifest_path = Path(temp_dir) / "bias-ext-alpha-tools" / "extension.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest.setdefault("extra", {})
                manifest["extra"]["auto_install"] = True
                manifest["extra"]["auto_enable"] = True
                manifest["extra"]["protected"] = True
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

                output = StringIO()
                call_command(
                    "inspect_extension_packages",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--extension-id",
                    "alpha-tools",
                    "--build",
                    "--install-set-smoke",
                    "--lifecycle-smoke",
                    "--format",
                    "json",
                    stdout=output,
                )

            payload = json.loads(output.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            hooks = payload["install_set"]["lifecycle_backend_hooks"]["alpha-tools"]
            self.assertEqual(hooks["disable"], "protected")
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

    def test_inspect_extension_packages_lifecycle_smoke_requires_install_set_smoke(self):
        with self.assertRaisesMessage(CommandError, "--lifecycle-smoke 必须配合 --install-set-smoke 使用"):
            call_command(
                "inspect_extension_packages",
                "--extensions-path",
                str(Path(settings.BASE_DIR) / "extensions"),
                "--lifecycle-smoke",
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
                package_python_module_command(temp_dir, "build", "--wheel", "--no-isolation"),
                cwd=extension_dir,
                text=True,
                capture_output=True,
                timeout=60,
                env=package_subprocess_env(temp_dir),
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
                env=package_subprocess_env(temp_dir),
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
            self.assertTrue(any("wheel 缺少后端入口模块" in error for error in errors), errors)
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
                "from bias_core.extensions.runtime import get_runtime_resource_registry\n"
                "from bias_core.extensions.platform import api_error, get_forum_registry\n"
                "from bias_core.extensions.contracts import PermissionDefinition\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            call_command_quietly("validate_extensions", "--extensions-path", str(Path(temp_dir) / "extensions"))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_imports_command_can_reject_undeclared_runtime_facade_dependencies(self):
        temp_dir = make_workspace_temp_dir()
        try:
            users_dir = Path(temp_dir) / "extensions" / "users"
            users_dir.mkdir(parents=True, exist_ok=False)
            (users_dir / "extension.json").write_text(json.dumps({
                "id": "users",
                "name": "Users",
                "version": "1.0.0",
                "dependencies": ["core"],
            }, ensure_ascii=False), encoding="utf-8")
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
                "from bias_core.extensions.runtime import get_runtime_user_by_id\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            with self.assertRaisesMessage(CommandError, "扩展 import 边界审计失败"):
                stdout = StringIO()
                call_command(
                    "inspect_extension_imports",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--check-runtime-facades",
                    stdout=stdout,
                )
            self.assertIn("undeclared_runtime_facade_dependency", stdout.getvalue())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_check_extension_workspace_reports_missing_shared_test_settings(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "bias-ext-alpha"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha",
                "name": "Alpha",
                "version": "1.0.0",
            }, ensure_ascii=False), encoding="utf-8")
            (manifest_dir / "pyproject.toml").write_text(
                "[project]\nname = \"bias-ext-alpha\"\nversion = \"1.0.0\"\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with self.assertRaisesMessage(CommandError, "扩展 workspace 门禁失败"):
                call_command(
                    "check_extension_workspace",
                    "--extensions-path",
                    str(temp_dir),
                    "--skip-inspect-extensions",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["summary"]["ok"])
            self.assertEqual(payload["summary"]["manifest_count"], 1)
            self.assertTrue(any(
                issue["code"] == "missing_shared_test_settings"
                and issue["extension_id"] == "alpha"
                for issue in payload["issues"]
            ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_check_extension_workspace_passes_static_checks_with_shared_test_settings(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "bias-ext-alpha"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha",
                "name": "Alpha",
                "version": "1.0.0",
            }, ensure_ascii=False), encoding="utf-8")
            (manifest_dir / "pyproject.toml").write_text(
                "\n".join([
                    "[project]",
                    'name = "bias-ext-alpha"',
                    'version = "1.0.0"',
                    "",
                    "[tool.pytest.ini_options]",
                    'DJANGO_SETTINGS_MODULE = "bias_core.extension_test_settings"',
                    "",
                ]),
                encoding="utf-8",
            )

            stdout = StringIO()
            call_command(
                "check_extension_workspace",
                "--extensions-path",
                str(temp_dir),
                "--skip-inspect-extensions",
                "--format",
                "json",
                stdout=stdout,
            )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertEqual(payload["summary"]["manifest_count"], 1)
            self.assertEqual(payload["issues"], [])
            self.assertTrue(payload["checks"]["pyproject_test_settings"]["ok"])
            self.assertTrue(payload["checks"]["import_boundaries"]["ok"])
            self.assertFalse(payload["summary"]["full_runtime_checks"])
            self.assertFalse(payload["summary"]["runtime_service_contracts_checked"])
            self.assertFalse(payload["summary"]["foundation_boundaries_checked"])
            self.assertTrue(payload["summary"]["static_only"])
            self.assertEqual(
                payload["summary"]["skipped_checks"],
                ["foundation_boundaries", "runtime_service_contracts"],
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_check_extension_workspace_runs_runtime_service_contract_gate(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "bias-ext-alpha"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha",
                "name": "Alpha",
                "version": "1.0.0",
            }, ensure_ascii=False), encoding="utf-8")
            (manifest_dir / "pyproject.toml").write_text(
                "\n".join([
                    "[project]",
                    'name = "bias-ext-alpha"',
                    'version = "1.0.0"',
                    "",
                    "[tool.pytest.ini_options]",
                    'DJANGO_SETTINGS_MODULE = "bias_core.extension_test_settings"',
                    "",
                ]),
                encoding="utf-8",
            )
            calls = []

            def fake_call_command(name, *args, **kwargs):
                calls.append((name, args))
                stdout = kwargs.get("stdout")
                if name == "inspect_extension_imports":
                    stdout.write(json.dumps({
                        "summary": {"ok": True, "manifest_count": 1, "error_count": 0, "warning_count": 0},
                        "issues": [],
                    }))
                    return None
                return call_command(name, *args, **kwargs)

            stdout = StringIO()
            with patch("bias_core.management.commands.check_extension_workspace.call_command", side_effect=fake_call_command):
                with patch(
                    "bias_core.management.commands.check_extension_workspace.build_extension_test_host",
                    return_value=object(),
                ) as build_host_mock:
                    with patch(
                        "bias_core.management.commands.check_extension_workspace.inspect_runtime_service_contracts",
                        return_value=[{
                            "code": "missing_service",
                            "provider_extension": "alpha",
                            "service_key": "alpha.service",
                        }],
                    ):
                        with patch(
                            "bias_core.management.commands.check_extension_workspace.inspect_runtime_service_contract_sources",
                            return_value=[],
                        ):
                            with patch(
                                "bias_core.management.commands.check_extension_workspace.snapshot_runtime_service_contracts",
                                return_value=[],
                            ):
                                with self.assertRaisesMessage(CommandError, "扩展 workspace 门禁失败"):
                                    call_command(
                                        "check_extension_workspace",
                                        "--extensions-path",
                                        str(temp_dir),
                                        "--format",
                                        "json",
                                        stdout=stdout,
                                    )

            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["summary"]["ok"])
            self.assertTrue(any(issue["code"] == "missing_service" for issue in payload["issues"]))
            self.assertIn(("alpha",), [call.args for call in build_host_mock.call_args_list])
            import_call = next(args for name, args in calls if name == "inspect_extension_imports")
            self.assertIn("--check-runtime-facades", import_call)
            self.assertIn("--fail-on-warnings", import_call)
            self.assertTrue(payload["summary"]["full_runtime_checks"])
            self.assertTrue(payload["summary"]["runtime_service_contracts_checked"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_check_extension_workspace_full_gate_requires_foundation_extensions(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "bias-ext-alpha"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha",
                "name": "Alpha",
                "version": "1.0.0",
            }, ensure_ascii=False), encoding="utf-8")
            (manifest_dir / "pyproject.toml").write_text(
                "\n".join([
                    "[project]",
                    'name = "bias-ext-alpha"',
                    'version = "1.0.0"',
                    "",
                    "[tool.pytest.ini_options]",
                    'DJANGO_SETTINGS_MODULE = "bias_core.extension_test_settings"',
                    "",
                ]),
                encoding="utf-8",
            )

            stdout = StringIO()
            with self.assertRaisesMessage(CommandError, "扩展 workspace 门禁失败"):
                call_command(
                    "check_extension_workspace",
                    "--extensions-path",
                    str(temp_dir),
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["summary"]["ok"])
            self.assertTrue(payload["summary"]["full_runtime_checks"])
            self.assertTrue(payload["summary"]["foundation_boundaries_checked"])
            self.assertFalse(payload["summary"]["static_only"])
            missing_foundations = {
                issue["extension_id"]
                for issue in payload["issues"]
                if issue["code"] == "missing_foundation_extension"
            }
            self.assertEqual(missing_foundations, {"content", "users"})
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_check_extension_workspace_runs_foundation_boundary_gate(self):
        temp_dir = make_workspace_temp_dir()
        try:
            for extension_id, extra in {
                "content": {"auto_install": True, "auto_enable": True, "protected": True},
                "users": {"auto_install": True, "auto_enable": True, "protected": True},
                "discussions": {},
                "posts": {},
            }.items():
                manifest_dir = Path(temp_dir) / f"bias-ext-{extension_id}"
                if extension_id == "content":
                    manifest_dir = Path(temp_dir) / "bias-content"
                manifest_dir.mkdir(parents=True, exist_ok=False)
                (manifest_dir / "extension.json").write_text(json.dumps({
                    "id": extension_id,
                    "name": extension_id,
                    "version": "1.0.0",
                    "extra": extra,
                }, ensure_ascii=False), encoding="utf-8")
                (manifest_dir / "pyproject.toml").write_text(
                    "\n".join([
                        "[project]",
                        f'name = "bias-ext-{extension_id}"',
                        'version = "1.0.0"',
                        "",
                        "[tool.pytest.ini_options]",
                        'DJANGO_SETTINGS_MODULE = "bias_core.extension_test_settings"',
                        "",
                    ]),
                    encoding="utf-8",
                )

            class Meta:
                def __init__(self, label):
                    self.label = label

            class Model:
                def __init__(self, label):
                    self._meta = Meta(label)

            class Definition:
                def __init__(self, label):
                    self.model = Model(label)

            class Models:
                def get_owned_models(self, *, extension_id=None):
                    if extension_id == "content":
                        return [
                            Definition("content.Discussion"),
                            Definition("content.DiscussionUser"),
                            Definition("content.Post"),
                        ]
                    return []

            host = SimpleNamespace(models=Models())

            stdout = StringIO()
            with patch("bias_core.management.commands.check_extension_workspace.build_extension_test_host", return_value=host):
                call_command(
                    "check_extension_workspace",
                    "--extensions-path",
                    str(temp_dir),
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["checks"]["foundation_boundaries"]["ok"])
            self.assertEqual(
                payload["checks"]["foundation_boundaries"]["owned_by_extension"]["content"],
                ["content.Discussion", "content.DiscussionUser", "content.Post"],
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_imports_command_rejects_runtime_facade_wildcard_imports(self):
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
                "from bias_core.extensions.runtime import *\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            with self.assertRaisesMessage(CommandError, "扩展 import 边界审计失败"):
                stdout = StringIO()
                call_command(
                    "inspect_extension_imports",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--check-runtime-facades",
                    stdout=stdout,
                )
            self.assertIn("forbidden_runtime_facade_wildcard_import", stdout.getvalue())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_imports_command_allows_declared_runtime_facade_dependencies(self):
        temp_dir = make_workspace_temp_dir()
        try:
            users_dir = Path(temp_dir) / "extensions" / "users"
            users_dir.mkdir(parents=True, exist_ok=False)
            (users_dir / "extension.json").write_text(json.dumps({
                "id": "users",
                "name": "Users",
                "version": "1.0.0",
                "dependencies": ["core"],
            }, ensure_ascii=False), encoding="utf-8")
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["core", "users"],
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions.runtime import get_runtime_user_by_id\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            call_command(
                "inspect_extension_imports",
                "--extensions-path",
                str(Path(temp_dir) / "extensions"),
                "--check-runtime-facades",
                "--format",
                "json",
                stdout=stdout,
            )
            payload = json.loads(stdout.getvalue())
            graph = payload["runtime_facade_dependency_graph"]
            self.assertIn("users", graph["dependencies"]["alpha-tools"])
            self.assertEqual(
                graph["runtime_edges"],
                [{
                    "source": "alpha-tools",
                    "target": "users",
                    "references": [{
                        "field": "extensions/alpha-tools/backend/ext.py",
                        "facade": "get_runtime_user_by_id",
                    }],
                }],
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_imports_command_warns_on_top_level_runtime_facade_imports(self):
        temp_dir = make_workspace_temp_dir()
        try:
            users_dir = Path(temp_dir) / "extensions" / "users"
            users_dir.mkdir(parents=True, exist_ok=False)
            (users_dir / "extension.json").write_text(json.dumps({
                "id": "users",
                "name": "Users",
                "version": "1.0.0",
                "dependencies": ["core"],
            }, ensure_ascii=False), encoding="utf-8")
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["core", "users"],
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions.runtime import get_runtime_user_by_id\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            call_command(
                "inspect_extension_imports",
                "--extensions-path",
                str(Path(temp_dir) / "extensions"),
                "--extension-id",
                "alpha-tools",
                "--check-runtime-facades",
                stdout=stdout,
            )

            output = stdout.getvalue()
            self.assertIn("runtime_facade_top_level_import", output)
            self.assertIn("get_runtime_user_by_id", output)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_imports_command_can_fail_on_warnings(self):
        temp_dir = make_workspace_temp_dir()
        try:
            users_dir = Path(temp_dir) / "extensions" / "users"
            users_dir.mkdir(parents=True, exist_ok=False)
            (users_dir / "extension.json").write_text(json.dumps({
                "id": "users",
                "name": "Users",
                "version": "1.0.0",
                "dependencies": ["core"],
            }, ensure_ascii=False), encoding="utf-8")
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["core", "users"],
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions.runtime import get_runtime_user_by_id\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            with self.assertRaisesMessage(CommandError, "扩展 import 边界审计失败，共 1 个警告"):
                call_command(
                    "inspect_extension_imports",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--extension-id",
                    "alpha-tools",
                    "--check-runtime-facades",
                    "--fail-on-warnings",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["summary"]["ok"])
            self.assertEqual(payload["summary"]["warning_count"], 1)
            self.assertEqual(payload["issues"][0]["code"], "runtime_facade_top_level_import")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_imports_command_allows_lazy_runtime_facade_imports_without_warning(self):
        temp_dir = make_workspace_temp_dir()
        try:
            users_dir = Path(temp_dir) / "extensions" / "users"
            users_dir.mkdir(parents=True, exist_ok=False)
            (users_dir / "extension.json").write_text(json.dumps({
                "id": "users",
                "name": "Users",
                "version": "1.0.0",
                "dependencies": ["core"],
            }, ensure_ascii=False), encoding="utf-8")
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["core", "users"],
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "def resolve_user(user_id):\n"
                "    from bias_core.extensions.runtime import get_runtime_user_by_id\n"
                "    return get_runtime_user_by_id(user_id)\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            call_command(
                "inspect_extension_imports",
                "--extensions-path",
                str(Path(temp_dir) / "extensions"),
                "--extension-id",
                "alpha-tools",
                "--check-runtime-facades",
                stdout=stdout,
            )

            self.assertNotIn("runtime_facade_top_level_import", stdout.getvalue())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_imports_command_warns_on_lazy_legacy_runtime_facade_imports(self):
        temp_dir = make_workspace_temp_dir()
        try:
            users_dir = Path(temp_dir) / "extensions" / "users"
            users_dir.mkdir(parents=True, exist_ok=False)
            (users_dir / "extension.json").write_text(json.dumps({
                "id": "users",
                "name": "Users",
                "version": "1.0.0",
                "dependencies": ["core"],
            }, ensure_ascii=False), encoding="utf-8")
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["core", "users"],
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "def resolve_user(user_id):\n"
                "    from bias_core.extensions.runtime import get_runtime_user_by_id\n"
                "    return get_runtime_user_by_id(user_id)\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            call_command(
                "inspect_extension_imports",
                "--extensions-path",
                str(Path(temp_dir) / "extensions"),
                "--extension-id",
                "alpha-tools",
                "--check-runtime-facades",
                "--format",
                "json",
                stdout=stdout,
            )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertEqual(payload["summary"]["warning_count"], 1)
            self.assertEqual(payload["issues"][0]["code"], "legacy_runtime_facade_import")
            self.assertIn("get_runtime_user_by_id", payload["issues"][0]["message"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_imports_command_allows_lazy_runtime_service_contract_access(self):
        temp_dir = make_workspace_temp_dir()
        try:
            users_dir = Path(temp_dir) / "extensions" / "users"
            users_dir.mkdir(parents=True, exist_ok=False)
            (users_dir / "extension.json").write_text(json.dumps({
                "id": "users",
                "name": "Users",
                "version": "1.0.0",
                "dependencies": ["core"],
            }, ensure_ascii=False), encoding="utf-8")
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["core", "users"],
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "def resolve_user(user_id):\n"
                "    from bias_core.extensions.runtime import get_runtime_service\n"
                "    return get_runtime_service('users.service').get_by_id(user_id)\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            stdout = StringIO()
            call_command(
                "inspect_extension_imports",
                "--extensions-path",
                str(Path(temp_dir) / "extensions"),
                "--extension-id",
                "alpha-tools",
                "--check-runtime-facades",
                "--format",
                "json",
                stdout=stdout,
            )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertEqual(payload["summary"]["warning_count"], 0)
            self.assertEqual(payload["runtime_facade_dependency_graph"]["runtime_edges"], [])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_imports_command_resolves_runtime_facade_capability_provider(self):
        temp_dir = make_workspace_temp_dir()
        try:
            content_dir = Path(temp_dir) / "extensions" / "content"
            content_dir.mkdir(parents=True, exist_ok=False)
            (content_dir / "extension.json").write_text(json.dumps({
                "id": "content",
                "name": "Content Foundation",
                "version": "1.0.0",
                "dependencies": ["core"],
                "provides": ["discussions", "posts"],
            }, ensure_ascii=False), encoding="utf-8")
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["core", "content"],
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions.runtime import get_runtime_post_by_id\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            call_command_quietly(
                "inspect_extension_imports",
                "--extensions-path",
                str(Path(temp_dir) / "extensions"),
                "--check-runtime-facades",
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_imports_command_reports_runtime_facade_dependency_cycles(self):
        temp_dir = make_workspace_temp_dir()
        try:
            alpha_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            alpha_backend_dir = alpha_dir / "backend"
            alpha_backend_dir.mkdir(parents=True, exist_ok=False)
            (alpha_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["core"],
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (alpha_backend_dir / "ext.py").write_text(
                "from bias_core.extensions.runtime import get_runtime_user_by_id\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            users_dir = Path(temp_dir) / "extensions" / "users"
            users_dir.mkdir(parents=True, exist_ok=False)
            (users_dir / "extension.json").write_text(json.dumps({
                "id": "users",
                "name": "Users",
                "version": "1.0.0",
                "dependencies": ["core", "alpha-tools"],
            }, ensure_ascii=False), encoding="utf-8")

            with self.assertRaisesMessage(CommandError, "扩展 import 边界审计失败"):
                stdout = StringIO()
                call_command(
                    "inspect_extension_imports",
                    "--extensions-path",
                    str(Path(temp_dir) / "extensions"),
                    "--check-runtime-facades",
                    stdout=stdout,
                )
            output = stdout.getvalue()
            self.assertIn("runtime_facade_dependency_cycle", output)
            self.assertIn("alpha-tools -> users", output)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extensions_command_rejects_testing_facade_by_default(self):
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
                "from bias_core.extensions.testing import ExtensionRuntimeTestMixin\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            with self.assertRaisesMessage(CommandError, "扩展校验失败"):
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
        self.assertIn("compatibility_matrix", payload)
        self.assertEqual(payload["compatibility_matrix"]["schema"], 1)
        self.assertIn("compatibility_blocking_count", payload["summary"])
        self.assertIn("bias_version_incompatible_count", payload["summary"])
        self.assertTrue(any(item["id"] == "core" for item in payload["extensions"]))
        self.assertTrue(any(item["id"] == "tags" for item in payload["extensions"]))
        core_extension = next(item for item in payload["extensions"] if item["id"] == "core")
        self.assertEqual(core_extension["source"], "core-module")
        self.assertFalse(core_extension["lifecycle_plan"]["disable"]["can_execute"])
        self.assertIn("core_module", core_extension["lifecycle_plan"]["disable"]["blockers"])
        alpha_extension = next((item for item in payload["extensions"] if item["id"] == "alpha-tools"), None)
        if alpha_extension is not None:
            self.assertFalse(alpha_extension["product_visible"])

    def test_inspect_extensions_command_reports_compatibility_matrix(self):
        stdout = StringIO()
        call_command(
            "inspect_extensions",
            "--extension-id",
            "tags",
            stdout=stdout,
        )
        payload = json.loads(stdout.getvalue())
        matrix = payload["compatibility_matrix"]
        row = matrix["rows"][0]

        self.assertEqual(matrix["schema"], 1)
        self.assertEqual(matrix["summary"]["extension_count"], 1)
        self.assertEqual(payload["summary"]["compatibility_blocking_count"], matrix["summary"]["blocking_count"])
        self.assertEqual(payload["summary"]["bias_version_incompatible_count"], matrix["summary"]["bias_version_incompatible_count"])
        self.assertEqual(row["extension_id"], "tags")
        self.assertEqual(row["schema_version"], payload["extensions"][0]["schema_version"])
        self.assertIn("core", row["dependencies"])
        self.assertEqual(row["compatibility"]["api_version"], payload["extensions"][0]["compatibility"]["api_version"])
        self.assertIn("prepare_release --contract-baseline", row["release_policy"]["contract_baseline_gate"])
        self.assertTrue(row["release_policy"]["contract_snapshot_required"])

    def test_inspect_extensions_command_matrix_flags_upgrade_policy_risks(self):
        fallback_payload = {
            "extensions": [{
                "id": "alpha",
                "name": "Alpha",
                "version": "1.0.0",
                "schema_version": 1,
                "source": "filesystem",
                "enabled": True,
                "healthy": True,
                "dependencies": ["core"],
                "optional_dependencies": [],
                "conflicts": [],
                "provides": [],
                "compatibility": {
                    "bias_version": ">=99.0.0",
                    "api_version": "1.0",
                    "api_stability": "experimental",
                    "breaking_change_policy": "Document breaking changes.",
                },
                "distribution": {
                    "channel": "public",
                    "signing_key_id": "",
                    "signature_url": "",
                    "abandoned": True,
                    "replacement": "beta-tools",
                },
                "diagnostics": {"blocking": False, "warning_reasons": [], "blocking_reasons": []},
            }],
            "summary": {
                "extension_count": 1,
                "enabled_count": 1,
                "healthy_count": 1,
                "filesystem_count": 1,
            },
        }

        with patch(
            "bias_core.management.commands.inspect_extensions.serialize_admin_extensions_payload",
            return_value=fallback_payload,
        ):
            stdout = StringIO()
            call_command("inspect_extensions", stdout=stdout)

        payload = json.loads(stdout.getvalue())
        matrix = payload["compatibility_matrix"]
        row = matrix["rows"][0]
        self.assertFalse(row["compatibility"]["bias_version_compatible"])
        self.assertTrue(row["status"]["blocking"])
        self.assertTrue(row["status"]["warning"])
        self.assertEqual(matrix["summary"]["bias_version_incompatible_count"], 1)
        self.assertEqual(matrix["summary"]["unstable_api_count"], 1)
        self.assertEqual(matrix["summary"]["abandoned_distribution_count"], 1)
        self.assertEqual(payload["summary"]["compatibility_blocking_count"], 1)
        self.assertEqual(payload["summary"]["abandoned_distribution_count"], 1)

    def test_inspect_extensions_stdout_encoding_helper_escapes_gbk_unsafe_json(self):
        from bias_core.management.commands.inspect_extensions import _encode_stdout_safe

        value = '{"status": "ok", "marker": "✓"}'
        encoded = _encode_stdout_safe(value, "gbk")

        self.assertIn("\\u2713", encoded)
        encoded.encode("gbk")

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

    def test_extension_diagnostics_report_runtime_service_contract_issues_as_blocking(self):
        from bias_core.extension_diagnostics import classify_extension_diagnostics

        diagnostics = classify_extension_diagnostics({
            "healthy": True,
            "runtime_service_contract_issues": [{
                "code": "missing_method",
                "service_key": "users.service",
                "provider_extension": "users",
                "member": "get_by_id",
            }],
            "dependency_state": "healthy",
        })

        self.assertTrue(diagnostics["blocking"])
        self.assertIn("运行时服务契约不完整", diagnostics["blocking_reasons"])

    def test_extension_diagnostics_report_runtime_service_contract_fallback_as_warning(self):
        from bias_core.extension_diagnostics import classify_extension_diagnostics

        diagnostics = classify_extension_diagnostics({
            "healthy": True,
            "runtime_service_contract_warnings": [{
                "code": "runtime_service_contract_uses_core_fallback",
                "service_key": "users.service",
                "provider_extension": "users",
                "member": "users.service",
                "severity": "warning",
            }],
            "dependency_state": "healthy",
        })

        self.assertFalse(diagnostics["blocking"])
        self.assertTrue(diagnostics["warning"])
        self.assertIn("运行时服务契约仍依赖 core fallback", diagnostics["warning_reasons"])

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
        self.assertTrue(all(isinstance(item, dict) for item in snapshot["resources"]["definitions"]))
        self.assertTrue(any(
            item.get("resource") == "discussion" and item.get("field") == "tags"
            for item in snapshot["resources"]["fields"]
            if isinstance(item, dict)
        ))
        self.assertTrue(any(item.get("resource") == "tag" for item in snapshot["resources"]["endpoints"] if isinstance(item, dict)))
        self.assertTrue(any(item.get("target") == "discussion" for item in snapshot["forum"]["search_filters"] if isinstance(item, dict)))
        self.assertEqual(snapshot["summary"]["resource_definition_count"], len(snapshot["resources"]["definitions"]))
        self.assertEqual(snapshot["summary"]["resource_field_count"], len(snapshot["resources"]["fields"]))
        self.assertEqual(snapshot["summary"]["resource_endpoint_count"], len(snapshot["resources"]["endpoints"]))
        self.assertEqual(
            snapshot["resources"]["definitions"],
            sorted(snapshot["resources"]["definitions"], key=lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True)),
        )
        self.assertIn("hooks", snapshot["lifecycle"])
        self.assertEqual(snapshot["lifecycle"]["hooks"], sorted(snapshot["lifecycle"]["hooks"]))

    def test_inspect_extensions_command_reports_runtime_facade_contracts(self):
        stdout = StringIO()
        call_command(
            "inspect_extensions",
            "--extension-id",
            "tags",
            stdout=stdout,
        )
        payload = json.loads(stdout.getvalue())
        snapshot = payload["extensions"][0]["contract_snapshot"]
        facades = snapshot["runtime"]["facades"]

        self.assertEqual(snapshot["summary"]["runtime_facade_count"], len(facades))
        self.assertEqual(facades, sorted(facades, key=lambda item: item["name"]))
        self.assertTrue(all("missing_service" in item for item in facades))
        self.assertIn({
            "name": "get_runtime_user_by_id",
            "domain": "users",
            "provider_extension": "users",
            "stability": "public",
            "missing_service": "raises_runtime_error",
        }, facades)
        self.assertIn({
            "name": "has_runtime_model_visibility",
            "domain": "models",
            "provider_extension": "",
            "stability": "public",
            "missing_service": "returns_false",
        }, facades)

    def test_inspect_extensions_command_reports_runtime_service_contracts(self):
        stdout = StringIO()
        call_command(
            "inspect_extensions",
            "--extension-id",
            "users",
            stdout=stdout,
        )
        payload = json.loads(stdout.getvalue())
        extension = payload["extensions"][0]
        snapshot = extension["contract_snapshot"]
        service_contracts = snapshot["runtime"]["service_contracts"]

        self.assertEqual(extension["runtime_service_contract_issues"], [])
        self.assertEqual(extension["runtime_service_contract_warnings"], [])
        self.assertEqual(snapshot["summary"]["runtime_service_contract_count"], len(service_contracts))
        self.assertTrue(any(
            item["service_key"] == "users.service"
            and item["provider_extension"] == "users"
            and item["source"] == "declared"
            and "get_by_id" in item["required_methods"]
            and "model" in item["required_values"]
            for item in service_contracts
        ))

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

    def test_inspect_extensions_command_can_fail_on_runtime_service_contract_fallback(self):
        fallback_payload = {
            "extensions": [{
                "id": "alpha",
                "runtime_service_contract_warnings": [{
                    "code": "runtime_service_contract_uses_core_fallback",
                    "service_key": "alpha.service",
                }],
                "contract_snapshot": {
                    "runtime": {
                        "service_contracts": [{
                            "service_key": "alpha.service",
                            "source": "core_fallback",
                        }],
                    },
                },
                "diagnostics": {},
                "enabled": True,
                "healthy": True,
                "source": "filesystem",
            }],
            "summary": {
                "extension_count": 1,
                "enabled_count": 1,
                "healthy_count": 1,
                "filesystem_count": 1,
            },
        }

        with patch(
            "bias_core.management.commands.inspect_extensions.serialize_admin_extensions_payload",
            return_value=fallback_payload,
        ):
            with self.assertRaisesMessage(
                CommandError,
                "runtime service contract 仍依赖 core fallback: alpha:alpha.service",
            ):
                call_command(
                    "inspect_extensions",
                    "--fail-on-runtime-service-fallback",
                    stdout=StringIO(),
                )

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
            discover_auth_user_model,
            discover_extension_django_configuration,
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
                    "auth_user_model": "users.User",
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
                self.assertEqual(
                    discover_auth_user_model(temp_dir / "empty"),
                    "users.User",
                )
                self.assertEqual(
                    discover_extension_django_configuration(temp_dir / "empty")["auth_user_model"],
                    "users.User",
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
        module_name = "bias_ext_packaged_demo"
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
                    "entry": "bias_ext_packaged_demo.backend.ext",
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
            self.assertEqual(inspection["resolved_path"], "bias_ext_packaged_demo.backend.ext")
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

    def test_validate_extensions_command_discovers_split_workspace_from_bias_site_host(self):
        temp_dir = make_workspace_temp_dir()
        try:
            workspace_root = Path(temp_dir)
            site_host = workspace_root / "bias"
            extensions_dir = site_host / "extensions"
            generated_dir = extensions_dir / "alpha"
            generated_dir.mkdir(parents=True, exist_ok=False)
            (generated_dir / ".bias-generated-extension-source").write_text("bias-ext-alpha\n", encoding="utf-8")
            (generated_dir / "extension.json").write_text(json.dumps({
                "id": "alpha",
                "name": "Alpha Generated Copy",
                "version": "1.0.0",
                "backend": {"entry": "bias_ext_alpha.backend.ext:extend"},
            }, ensure_ascii=False), encoding="utf-8")

            workspace_manifest_dir = workspace_root / "bias-ext-alpha"
            backend_dir = workspace_manifest_dir / "bias_ext_alpha" / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (backend_dir / "__init__.py").write_text("", encoding="utf-8")
            (backend_dir / "ext.py").write_text("def extend(app):\n    return None\n", encoding="utf-8")
            (workspace_manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha",
                "name": "Alpha Workspace Source",
                "version": "1.0.0",
                "backend": {"entry": "bias_ext_alpha.backend.ext:extend"},
                "security": {"capabilities_notice": "Test extension fixture."},
            }, ensure_ascii=False), encoding="utf-8")

            stdout = StringIO()
            with override_settings(BASE_DIR=site_host, BIAS_EXTENSION_WORKSPACE_ROOT=workspace_root):
                call_command(
                    "validate_extensions",
                    "--extensions-path",
                    str(extensions_dir),
                    "--format",
                    "json",
                    "--strict",
                    "--require-extensions",
                    stdout=stdout,
                    stderr=StringIO(),
                )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertEqual(payload["summary"]["manifest_count"], 1)
            self.assertEqual(payload["manifests"][0]["id"], "alpha")
            self.assertEqual(payload["manifests"][0]["name"], "Alpha Workspace Source")
            self.assertEqual(payload["manifests"][0]["path"], str(workspace_manifest_dir))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_inspect_extension_imports_command_discovers_split_workspace_from_bias_site_host(self):
        temp_dir = make_workspace_temp_dir()
        try:
            workspace_root = Path(temp_dir)
            site_host = workspace_root / "bias"
            extensions_dir = site_host / "extensions"
            generated_dir = extensions_dir / "alpha"
            generated_dir.mkdir(parents=True, exist_ok=False)
            (generated_dir / ".bias-generated-extension-source").write_text("bias-ext-alpha\n", encoding="utf-8")
            (generated_dir / "extension.json").write_text(json.dumps({
                "id": "alpha",
                "name": "Alpha Generated Copy",
                "version": "1.0.0",
            }, ensure_ascii=False), encoding="utf-8")

            workspace_manifest_dir = workspace_root / "bias-ext-alpha"
            backend_dir = workspace_manifest_dir / "bias_ext_alpha" / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (backend_dir / "__init__.py").write_text("", encoding="utf-8")
            (backend_dir / "ext.py").write_text("from bias_core.extensions.runtime import users\n", encoding="utf-8")
            (workspace_manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha",
                "name": "Alpha Workspace Source",
                "version": "1.0.0",
                "dependencies": ["users"],
            }, ensure_ascii=False), encoding="utf-8")

            stdout = StringIO()
            with override_settings(BASE_DIR=site_host, BIAS_EXTENSION_WORKSPACE_ROOT=workspace_root):
                call_command(
                    "inspect_extension_imports",
                    "--extensions-path",
                    str(extensions_dir),
                    "--format",
                    "json",
                    "--internal",
                    "--require-extensions",
                    stdout=stdout,
                    stderr=StringIO(),
                )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertEqual(payload["summary"]["manifest_count"], 1)
            self.assertEqual(payload["manifests"][0]["id"], "alpha")
            self.assertEqual(payload["manifests"][0]["name"], "Alpha Workspace Source")
            self.assertEqual(payload["manifests"][0]["path"], str(workspace_manifest_dir))
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
                if name == "inspect_extension_packages":
                    kwargs["stdout"].write(json.dumps(build_minimal_package_audit_payload()))
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
            workspace_gate_call = next((args for name, args in calls if name == "check_extension_workspace"), None)
            package_call = next((args for name, args in calls if name == "inspect_extension_packages"), None)
            self.assertIsNotNone(sync_call)
            self.assertIn("--extensions-path", sync_call)
            self.assertIsNotNone(workspace_gate_call)
            self.assertIn("--extensions-path", workspace_gate_call)
            self.assertIsNotNone(package_call)
            self.assertIn("--install-set-smoke", package_call)
            self.assertIn("--migration-smoke", package_call)
            self.assertIn("--lifecycle-smoke", package_call)
            self.assertIn("--format", package_call)
            self.assertIn("json", package_call)
            self.assertIsNotNone(validate_call)
            self.assertIn("--strict", validate_call)
            self.assertIn("--internal", validate_call)
            self.assertIn("--require-extensions", validate_call)
            self.assertIn("--extensions-path", validate_call)
            inspect_call = next((args for name, args in calls if name == "inspect_extensions"), None)
            self.assertIsNotNone(inspect_call)
            self.assertIn("--fail-on-runtime-service-fallback", inspect_call)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prepare_release_can_run_capacity_smoke_gate(self):
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
                if name == "inspect_extension_packages":
                    kwargs["stdout"].write(json.dumps(build_minimal_package_audit_payload()))
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
                            "--run-capacity-smoke",
                            "--websocket-smoke-connections",
                            "2",
                            "--websocket-smoke-discussion-id",
                            "321",
                            "--websocket-smoke-p95-threshold-ms",
                            "750",
                        )

            baseline_call = next((args for name, args in calls if name == "inspect_performance_baseline"), None)
            websocket_call = next((args for name, args in calls if name == "smoke_websocket_realtime"), None)
            self.assertIsNotNone(baseline_call)
            self.assertIn("--format", baseline_call)
            self.assertIn("json", baseline_call)
            self.assertIn("--strict", baseline_call)
            self.assertIn("--extensions-path", baseline_call)
            self.assertIsNotNone(websocket_call)
            self.assertIn("--connections", websocket_call)
            self.assertEqual(websocket_call[websocket_call.index("--connections") + 1], "2")
            self.assertIn("--discussion-id", websocket_call)
            self.assertEqual(websocket_call[websocket_call.index("--discussion-id") + 1], "321")
            self.assertIn("--p95-threshold-ms", websocket_call)
            self.assertEqual(websocket_call[websocket_call.index("--p95-threshold-ms") + 1], "750.0")
            self.assertIn("--format", websocket_call)
            self.assertIn("json", websocket_call)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_smoke_install_upgrade_runs_install_and_upgrade_and_validates_state(self):
        temp_dir = make_workspace_temp_dir()
        calls = []
        state_payloads = [
            {
                "admin_exists": True,
                "admin_username": "smoke-admin",
                "admin_email": "smoke-admin@example.com",
                "installed_extensions": ["users", "discussions"],
                "enabled_extensions": ["users", "discussions"],
                "settings": {"system.version": "\"1.2.3\""},
            },
            {
                "admin_exists": True,
                "admin_username": "smoke-admin",
                "admin_email": "smoke-admin@example.com",
                "installed_extensions": ["users", "discussions"],
                "enabled_extensions": ["users", "discussions"],
                "settings": {"system.version": "\"1.2.3\""},
            },
        ]
        static_payload = {
            "static_root_exists": False,
            "frontend_root_exists": False,
            "frontend_file_count": 0,
            "build_manifest_exists": False,
            "output_manifest_exists": False,
        }

        def fake_run_manage_py(args, env):
            calls.append((list(args), dict(env)))
            if args[:2] == ["shell", "-c"]:
                if "static_root = Path(settings.STATIC_ROOT)" in args[2]:
                    return SimpleNamespace(stdout=json.dumps(static_payload), stderr="", returncode=0)
                payload = state_payloads.pop(0)
                return SimpleNamespace(stdout=json.dumps(payload), stderr="", returncode=0)
            return SimpleNamespace(stdout="", stderr="", returncode=0)

        try:
            stdout = StringIO()
            with patch("bias_core.management.commands.smoke_install_upgrade.run_manage_py", side_effect=fake_run_manage_py):
                call_command(
                    "smoke_install_upgrade",
                    "--workdir",
                    str(temp_dir),
                    "--skip-collectstatic",
                    "--skip-extension-frontend",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertEqual(payload["install"]["enabled_extensions"], ["users", "discussions"])
            self.assertEqual(payload["upgrade"]["enabled_extensions"], ["users", "discussions"])

            install_args = calls[0][0]
            self.assertEqual(install_args[0], "install_forum")
            self.assertIn("--database", install_args)
            self.assertEqual(install_args[install_args.index("--database") + 1], "sqlite")
            self.assertIn("--non-interactive", install_args)
            self.assertIn("--skip-collectstatic", install_args)
            self.assertIn("--skip-extension-frontend", install_args)

            install_env = calls[0][1]
            config_path = temp_dir / "instance" / "site.json"
            self.assertEqual(install_env["BIAS_SITE_CONFIG"], str(config_path))
            self.assertEqual(install_env["BIAS_STATIC_ROOT"], str(temp_dir / "staticfiles"))

            upgrade_args = calls[2][0]
            self.assertEqual(upgrade_args[0], "upgrade_forum")
            self.assertIn("--non-interactive", upgrade_args)
            self.assertIn("--skip-collectstatic", upgrade_args)
            self.assertIn("--skip-extension-frontend", upgrade_args)
            self.assertEqual(calls[1][0][:2], ["shell", "-c"])
            self.assertEqual(calls[3][0][:2], ["shell", "-c"])
            self.assertEqual(calls[4][0][:2], ["shell", "-c"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_smoke_install_upgrade_can_run_from_built_wheel_target(self):
        temp_dir = make_workspace_temp_dir()
        source_root = Path(temp_dir) / "workspace"
        wheel_target = Path(temp_dir) / "site" / "site-packages"
        for package_name in ("bias_core", "bias-content", "bias-ext-users"):
            package_root = source_root / package_name
            package_root.mkdir(parents=True, exist_ok=True)
            (package_root / "pyproject.toml").write_text("[project]\nname = 'fixture'\nversion = '0.1.0'\n", encoding="utf-8")
        calls = []
        state_payloads = [
            {
                "admin_exists": True,
                "admin_username": "smoke-admin",
                "admin_email": "smoke-admin@example.com",
                "installed_extensions": ["users"],
                "enabled_extensions": ["users"],
                "settings": {"system.version": "\"1.2.3\""},
                "bias_core_file": str(wheel_target / "bias_core" / "__init__.py"),
                "wheel_target": str(wheel_target),
            },
            {
                "admin_exists": True,
                "admin_username": "smoke-admin",
                "admin_email": "smoke-admin@example.com",
                "installed_extensions": ["users"],
                "enabled_extensions": ["users"],
                "settings": {"system.version": "\"1.2.3\""},
                "bias_core_file": str(wheel_target / "bias_core" / "__init__.py"),
                "wheel_target": str(wheel_target),
            },
        ]
        static_payload = {
            "static_root_exists": False,
            "frontend_root_exists": False,
            "frontend_file_count": 0,
            "build_manifest_exists": False,
            "output_manifest_exists": False,
        }

        def fake_build_and_install_wheels(workdir, *, source_root, timeout):
            return {
                "source_root": str(source_root),
                "target": str(wheel_target),
                "wheelhouse": str(Path(workdir) / "wheelhouse"),
                "package_roots": [],
                "wheels": [],
            }

        def fake_run_manage_py(args, env):
            calls.append((list(args), dict(env)))
            if args[:2] == ["shell", "-c"]:
                if "static_root = Path(settings.STATIC_ROOT)" in args[2]:
                    return SimpleNamespace(stdout=json.dumps(static_payload), stderr="", returncode=0)
                return SimpleNamespace(stdout=json.dumps(state_payloads.pop(0)), stderr="", returncode=0)
            return SimpleNamespace(stdout="", stderr="", returncode=0)

        try:
            stdout = StringIO()
            with patch(
                "bias_core.management.commands.smoke_install_upgrade.Command._build_and_install_wheels",
                side_effect=fake_build_and_install_wheels,
            ):
                with patch("bias_core.management.commands.smoke_install_upgrade.run_manage_py", side_effect=fake_run_manage_py):
                    call_command(
                        "smoke_install_upgrade",
                        "--workdir",
                        str(Path(temp_dir) / "site"),
                        "--from-wheels",
                        "--wheel-source-root",
                        str(source_root),
                        "--skip-collectstatic",
                        "--skip-extension-frontend",
                        "--format",
                        "json",
                        stdout=stdout,
                    )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertEqual(payload["wheel_install"]["target"], str(wheel_target))
            self.assertEqual(calls[0][1]["BIAS_SMOKE_WHEEL_TARGET"], str(wheel_target))
            self.assertTrue(calls[0][1]["PYTHONPATH"].startswith(str(wheel_target)))
            self.assertEqual(payload["install"]["bias_core_file"], str(wheel_target / "bias_core" / "__init__.py"))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_smoke_install_upgrade_rebuild_publish_requires_collected_frontend_dist(self):
        temp_dir = make_workspace_temp_dir()
        calls = []
        state_payloads = [
            {
                "admin_exists": True,
                "admin_username": "smoke-admin",
                "admin_email": "smoke-admin@example.com",
                "installed_extensions": ["users"],
                "enabled_extensions": ["users"],
                "settings": {"system.version": "\"1.2.3\""},
            },
            {
                "admin_exists": True,
                "admin_username": "smoke-admin",
                "admin_email": "smoke-admin@example.com",
                "installed_extensions": ["users"],
                "enabled_extensions": ["users"],
                "settings": {"system.version": "\"1.2.3\""},
            },
        ]
        static_payload = {
            "static_root_exists": True,
            "frontend_root_exists": False,
            "frontend_file_count": 0,
            "build_manifest_exists": True,
            "output_manifest_exists": True,
        }

        def fake_run_manage_py(args, env):
            calls.append((list(args), dict(env)))
            if args[:2] == ["shell", "-c"]:
                if "static_root = Path(settings.STATIC_ROOT)" in args[2]:
                    return SimpleNamespace(stdout=json.dumps(static_payload), stderr="", returncode=0)
                return SimpleNamespace(stdout=json.dumps(state_payloads.pop(0)), stderr="", returncode=0)
            return SimpleNamespace(stdout="", stderr="", returncode=0)

        try:
            with patch("bias_core.management.commands.smoke_install_upgrade.run_manage_py", side_effect=fake_run_manage_py):
                with self.assertRaisesMessage(CommandError, "collectstatic 后未发现已发布 frontend dist"):
                    call_command_quietly(
                        "smoke_install_upgrade",
                        "--workdir",
                        str(temp_dir),
                        "--publish-frontend-dist",
                    )

            install_args = calls[0][0]
            self.assertIn("--publish-frontend-dist", install_args)
            self.assertIn("--rebuild-extension-frontend", install_args)
            upgrade_args = calls[2][0]
            self.assertIn("--publish-frontend-dist", upgrade_args)
            self.assertIn("--rebuild-extension-frontend", upgrade_args)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_smoke_install_upgrade_can_run_against_postgres_database(self):
        temp_dir = make_workspace_temp_dir()
        calls = []
        lifecycle = []
        state_payloads = [
            {
                "admin_exists": True,
                "admin_username": "smoke-admin",
                "admin_email": "smoke-admin@example.com",
                "installed_extensions": ["users"],
                "enabled_extensions": ["users"],
                "settings": {
                    "system.version": "\"1.2.3\"",
                    "advanced.queue_enabled": "false",
                },
            },
            {
                "admin_exists": True,
                "admin_username": "smoke-admin",
                "admin_email": "smoke-admin@example.com",
                "installed_extensions": ["users"],
                "enabled_extensions": ["users"],
                "settings": {
                    "system.version": "\"1.2.3\"",
                    "advanced.queue_enabled": "false",
                },
            },
        ]
        static_payload = {
            "static_root_exists": False,
            "frontend_root_exists": False,
            "frontend_file_count": 0,
            "build_manifest_exists": False,
            "output_manifest_exists": False,
        }

        def fake_run_manage_py(args, env):
            calls.append((list(args), dict(env)))
            if args[:2] == ["shell", "-c"]:
                if "static_root = Path(settings.STATIC_ROOT)" in args[2]:
                    return SimpleNamespace(stdout=json.dumps(static_payload), stderr="", returncode=0)
                return SimpleNamespace(stdout=json.dumps(state_payloads.pop(0)), stderr="", returncode=0)
            return SimpleNamespace(stdout="", stderr="", returncode=0)

        def fake_create(self, database):
            lifecycle.append(("create", dict(database)))
            return True

        def fake_drop(self, database):
            lifecycle.append(("drop", dict(database)))
            return True

        try:
            stdout = StringIO()
            with patch("bias_core.management.commands.smoke_install_upgrade.Command._create_postgres_database", fake_create):
                with patch("bias_core.management.commands.smoke_install_upgrade.Command._drop_postgres_database", fake_drop):
                    with patch("bias_core.management.commands.smoke_install_upgrade.run_manage_py", side_effect=fake_run_manage_py):
                        call_command(
                            "smoke_install_upgrade",
                            "--workdir",
                            str(temp_dir),
                            "--database",
                            "postgres",
                            "--db-name",
                            "bias_smoke_test",
                            "--db-user",
                            "bias",
                            "--db-password",
                            "biaspass",
                            "--db-host",
                            "db",
                            "--db-port",
                            "5432",
                            "--postgres-create-db",
                            "--postgres-drop-db",
                            "--skip-collectstatic",
                            "--skip-extension-frontend",
                            "--format",
                            "json",
                            stdout=stdout,
                        )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertEqual(payload["database"], "postgres")
            self.assertEqual(payload["postgres"]["name"], "bias_smoke_test")
            self.assertTrue(payload["postgres"]["created"])
            self.assertTrue(payload["postgres"]["dropped"])
            self.assertEqual([item[0] for item in lifecycle], ["create", "drop"])

            install_args = calls[0][0]
            self.assertEqual(install_args[0], "install_forum")
            self.assertEqual(install_args[install_args.index("--database") + 1], "postgres")
            self.assertEqual(install_args[install_args.index("--db-name") + 1], "bias_smoke_test")
            self.assertEqual(install_args[install_args.index("--db-user") + 1], "bias")
            self.assertEqual(install_args[install_args.index("--db-password") + 1], "biaspass")
            self.assertEqual(install_args[install_args.index("--db-host") + 1], "db")
            self.assertEqual(install_args[install_args.index("--db-port") + 1], "5432")
            self.assertEqual(install_args[install_args.index("--redis") + 1], "auto")
            self.assertEqual(install_args[install_args.index("--frontend-url") + 1], "http://localhost:5173")
            self.assertEqual(
                install_args[install_args.index("--email-backend") + 1],
                "django.core.mail.backends.smtp.EmailBackend",
            )
            self.assertNotIn("--sqlite-name", install_args)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_smoke_install_upgrade_postgres_requires_database_config(self):
        temp_dir = make_workspace_temp_dir()
        try:
            with patch.dict(os.environ, {
                "DB_NAME": "",
                "DB_USER": "",
                "DB_PASSWORD": "",
                "DB_HOST": "",
                "DB_PORT": "",
            }, clear=False):
                with self.assertRaisesMessage(CommandError, "PostgreSQL 冒烟缺少必要配置"):
                    call_command_quietly(
                        "smoke_install_upgrade",
                        "--workdir",
                        str(temp_dir),
                        "--database",
                        "postgres",
                    )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_smoke_install_upgrade_from_wheels_rejects_source_import(self):
        temp_dir = make_workspace_temp_dir()
        wheel_target = Path(temp_dir) / "site-packages"
        state_payloads = [
            {
                "admin_exists": True,
                "admin_username": "smoke-admin",
                "admin_email": "smoke-admin@example.com",
                "installed_extensions": ["users"],
                "enabled_extensions": ["users"],
                "settings": {"system.version": "\"1.2.3\""},
                "bias_core_file": str(Path(temp_dir) / "bias_core" / "src" / "bias_core" / "__init__.py"),
                "wheel_target": str(wheel_target),
            },
            {
                "admin_exists": True,
                "admin_username": "smoke-admin",
                "admin_email": "smoke-admin@example.com",
                "installed_extensions": ["users"],
                "enabled_extensions": ["users"],
                "settings": {"system.version": "\"1.2.3\""},
                "bias_core_file": str(Path(temp_dir) / "bias_core" / "src" / "bias_core" / "__init__.py"),
                "wheel_target": str(wheel_target),
            },
        ]
        static_payload = {
            "static_root_exists": False,
            "frontend_root_exists": False,
            "frontend_file_count": 0,
            "build_manifest_exists": False,
            "output_manifest_exists": False,
        }

        def fake_build_and_install_wheels(workdir, *, source_root, timeout):
            return {
                "source_root": str(source_root),
                "target": str(wheel_target),
                "wheelhouse": str(Path(workdir) / "wheelhouse"),
                "package_roots": [],
                "wheels": [],
            }

        def fake_run_manage_py(args, env):
            if args[:2] == ["shell", "-c"]:
                if "static_root = Path(settings.STATIC_ROOT)" in args[2]:
                    return SimpleNamespace(stdout=json.dumps(static_payload), stderr="", returncode=0)
                return SimpleNamespace(stdout=json.dumps(state_payloads.pop(0)), stderr="", returncode=0)
            return SimpleNamespace(stdout="", stderr="", returncode=0)

        try:
            with patch(
                "bias_core.management.commands.smoke_install_upgrade.Command._build_and_install_wheels",
                side_effect=fake_build_and_install_wheels,
            ):
                with patch("bias_core.management.commands.smoke_install_upgrade.run_manage_py", side_effect=fake_run_manage_py):
                    with self.assertRaisesMessage(CommandError, "未从 wheel target 导入 bias_core"):
                        call_command_quietly(
                            "smoke_install_upgrade",
                            "--workdir",
                            str(Path(temp_dir) / "site"),
                            "--from-wheels",
                            "--skip-collectstatic",
                        )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_smoke_install_upgrade_blocks_when_upgrade_drops_enabled_extensions(self):
        temp_dir = make_workspace_temp_dir()
        state_payloads = [
            {
                "admin_exists": True,
                "admin_username": "smoke-admin",
                "admin_email": "smoke-admin@example.com",
                "installed_extensions": ["users", "discussions"],
                "enabled_extensions": ["users", "discussions"],
                "settings": {"system.version": "\"1.2.3\""},
            },
            {
                "admin_exists": True,
                "admin_username": "smoke-admin",
                "admin_email": "smoke-admin@example.com",
                "installed_extensions": ["users", "discussions"],
                "enabled_extensions": ["users"],
                "settings": {"system.version": "\"1.2.3\""},
            },
        ]
        static_payload = {
            "static_root_exists": True,
            "frontend_root_exists": True,
            "frontend_file_count": 1,
            "build_manifest_exists": True,
            "output_manifest_exists": True,
        }

        def fake_run_manage_py(args, env):
            if args[:2] == ["shell", "-c"]:
                if "static_root = Path(settings.STATIC_ROOT)" in args[2]:
                    return SimpleNamespace(stdout=json.dumps(static_payload), stderr="", returncode=0)
                return SimpleNamespace(stdout=json.dumps(state_payloads.pop(0)), stderr="", returncode=0)
            return SimpleNamespace(stdout="", stderr="", returncode=0)

        try:
            with patch("bias_core.management.commands.smoke_install_upgrade.run_manage_py", side_effect=fake_run_manage_py):
                with self.assertRaisesMessage(CommandError, "upgrade 后已启用扩展状态未保持"):
                    call_command_quietly(
                        "smoke_install_upgrade",
                        "--workdir",
                        str(temp_dir),
                    )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_smoke_queue_worker_enables_runtime_queue_and_dispatches_probe(self):
        from bias_core.models import Setting
        from bias_core.queue_service import QueueService
        from bias_core.settings_service import clear_runtime_setting_caches
        from bias_core.tasks import queue_worker_probe

        class DummyWorker:
            def __init__(self):
                self.terminated = False
                self.killed = False

            def poll(self):
                return None

            def terminate(self):
                self.terminated = True

            def wait(self, timeout=None):
                return 0

            def kill(self):
                self.killed = True

        class DummyAsyncResult:
            def get(self, timeout=None, propagate=True):
                return {
                    "ok": True,
                    "token": dispatched_tokens[-1],
                    "worker_pid": 123,
                }

        dispatched_tokens = []
        worker = DummyWorker()
        Setting.objects.update_or_create(
            key="advanced.queue_enabled",
            defaults={"value": json.dumps(False)},
        )
        Setting.objects.update_or_create(
            key="advanced.queue_driver",
            defaults={"value": json.dumps("sync")},
        )
        clear_runtime_setting_caches()

        def fake_dispatch(task, token):
            self.assertIs(task, queue_worker_probe)
            self.assertEqual(
                QueueService.get_runtime_config(),
                {"enabled": True, "driver": "redis"},
            )
            dispatched_tokens.append(token)
            return DummyAsyncResult()

        stdout = StringIO()
        with override_settings(CELERY_BROKER_URL="redis://localhost:6379/5", CELERY_RESULT_BACKEND="redis://localhost:6379/5"):
            with patch("bias_core.management.commands.smoke_queue_worker.Command._start_worker", return_value=worker) as start_worker:
                with patch("bias_core.management.commands.smoke_queue_worker.Command._wait_for_worker", return_value={
                    "status": "available",
                    "label": "1 个 worker 在线",
                    "available": True,
                    "worker_count": 1,
                    "message": "Celery worker 可用。",
                }) as wait_for_worker:
                    with patch("bias_core.management.commands.smoke_queue_worker.QueueService.dispatch_celery_task", side_effect=fake_dispatch):
                        call_command(
                            "smoke_queue_worker",
                            "--format",
                            "json",
                            stdout=stdout,
                        )

        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["summary"]["ok"])
        self.assertEqual(payload["task_result"]["token"], dispatched_tokens[-1])
        self.assertEqual(payload["worker_status"]["worker_count"], 1)
        self.assertTrue(worker.terminated)
        self.assertFalse(worker.killed)
        self.assertTrue(start_worker.called)
        self.assertTrue(wait_for_worker.called)
        self.assertEqual(
            json.loads(Setting.objects.get(key="advanced.queue_enabled").value),
            False,
        )
        self.assertEqual(
            json.loads(Setting.objects.get(key="advanced.queue_driver").value),
            "sync",
        )

    def test_smoke_queue_worker_cli_broker_updates_current_process_runtime_config(self):
        from bias_core.queue_service import QueueService

        class DummyWorker:
            def poll(self):
                return None

            def terminate(self):
                return None

            def wait(self, timeout=None):
                return 0

            def kill(self):
                return None

        class DummyAsyncResult:
            def get(self, timeout=None, propagate=True):
                return {
                    "ok": True,
                    "token": dispatched_tokens[-1],
                    "worker_pid": 123,
                }

        dispatched_tokens = []

        def fake_dispatch(_task, token):
            self.assertEqual(
                QueueService.get_runtime_config(),
                {"enabled": True, "driver": "redis"},
            )
            dispatched_tokens.append(token)
            return DummyAsyncResult()

        with override_settings(CELERY_BROKER_URL="", CELERY_RESULT_BACKEND=""):
            with patch("bias_core.management.commands.smoke_queue_worker.Command._start_worker", return_value=DummyWorker()):
                with patch("bias_core.management.commands.smoke_queue_worker.Command._wait_for_worker", return_value={
                    "status": "available",
                    "label": "1 个 worker 在线",
                    "available": True,
                    "worker_count": 1,
                    "message": "Celery worker 可用。",
                }):
                    with patch("bias_core.management.commands.smoke_queue_worker.QueueService.dispatch_celery_task", side_effect=fake_dispatch):
                        call_command_quietly(
                            "smoke_queue_worker",
                            "--broker-url",
                            "redis://localhost:6379/5",
                            "--result-backend",
                            "redis://localhost:6379/5",
                        )

        self.assertTrue(dispatched_tokens)

    def test_smoke_queue_worker_requires_broker_url(self):
        with override_settings(CELERY_BROKER_URL="", CELERY_RESULT_BACKEND=""):
            with self.assertRaisesMessage(CommandError, "缺少 Celery broker URL"):
                call_command_quietly("smoke_queue_worker")

    def test_install_forum_publish_frontend_dist_runs_rebuild_before_collectstatic(self):
        temp_dir = make_workspace_temp_dir()
        try:
            config_path = Path(temp_dir) / "instance" / "site.json"
            calls = []

            def fake_run_manage_py(args, env):
                calls.append(list(args))
                return SimpleNamespace(stdout="", stderr="", returncode=0)

            with override_settings(BASE_DIR=Path(temp_dir)):
                with patch("bias_core.management.commands.install_forum.assert_database_connection"):
                    with patch("bias_core.management.commands.install_forum.run_manage_py", side_effect=fake_run_manage_py):
                        call_command_quietly(
                            "install_forum",
                            "--database",
                            "postgres",
                            "--config",
                            str(config_path),
                            "--overwrite",
                            "--non-interactive",
                            "--admin-username",
                            "smoke-admin",
                            "--admin-email",
                            "smoke-admin@example.com",
                            "--admin-password",
                            "smoke-admin-password",
                            "--db-name",
                            "bias_smoke_test",
                            "--db-user",
                            "bias",
                            "--db-password",
                            "biaspass",
                            "--db-host",
                            "127.0.0.1",
                            "--db-port",
                            "5432",
                            "--redis",
                            "auto",
                            "--site-domains",
                            "forum.example.com",
                            "--frontend-url",
                            "https://forum.example.com",
                            "--email-backend",
                            "django.core.mail.backends.smtp.EmailBackend",
                            "--email-host",
                            "smtp.example.com",
                            "--default-from-email",
                            "noreply@example.com",
                            "--publish-frontend-dist",
                        )

            frontend_call = next(args for args in calls if args and args[0] == "build_extension_frontend")
            settings_call = next(args for args in calls if args[:2] == ["shell", "-c"] and "advanced.queue_enabled" in args[2])
            migrate_index = calls.index(["migrate", "--noinput"])
            sync_index = calls.index(["sync_extensions"])
            collectstatic_index = calls.index(["collectstatic", "--noinput"])
            self.assertLess(migrate_index, calls.index(settings_call))
            self.assertLess(calls.index(settings_call), sync_index)
            self.assertLess(calls.index(frontend_call), collectstatic_index)
            self.assertIn("--rebuild", frontend_call)
            self.assertIn("--publish", frontend_call)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_install_forum_dry_run_outputs_plan_without_writing_config(self):
        temp_dir = make_workspace_temp_dir()
        try:
            config_path = Path(temp_dir) / "instance" / "site.json"
            stdout = StringIO()

            with override_settings(BASE_DIR=Path(temp_dir)):
                with patch("bias_core.management.commands.install_forum.assert_database_connection"):
                    with patch("bias_core.management.commands.install_forum.run_manage_py") as run_manage_py:
                        call_command(
                            "install_forum",
                            "--database",
                            "sqlite",
                            "--config",
                            str(config_path),
                            "--overwrite",
                            "--non-interactive",
                            "--admin-username",
                            "dry-admin",
                            "--admin-email",
                            "dry-admin@example.com",
                            "--admin-password",
                            "dry-admin-password",
                            "--dry-run",
                            stdout=stdout,
                        )

            self.assertFalse(config_path.exists())
            run_manage_py.assert_not_called()
            output = stdout.getvalue()
            self.assertIn("安装计划", output)
            self.assertIn("python manage.py migrate --noinput", output)
            self.assertIn("[DRY-RUN]", output)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_install_forum_postgres_dry_run_reports_production_findings_without_database_connection(self):
        temp_dir = make_workspace_temp_dir()
        try:
            config_path = Path(temp_dir) / "instance" / "site.example.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps({
                "installed": False,
                "source": "example",
                "debug": False,
                "secret_key": "replace-with-django-secret-key",
                "jwt_secret_key": "replace-with-jwt-secret-key",
                "site_domains": ["forum.example.com"],
                "site_scheme": "https",
                "frontend_url": "https://forum.example.com",
                "database_mode": "postgres",
                "db_name": "replace-with-db-name",
                "db_user": "replace-with-db-user",
                "db_password": "replace-with-db-password",
                "db_host": "db",
                "db_port": "5432",
                "use_redis": True,
                "redis_host": "redis",
                "redis_port": "6379",
                "redis_db": "0",
                "email_backend": "django.core.mail.backends.smtp.EmailBackend",
                "email_host": "smtp.example.com",
                "email_port": 587,
                "email_use_tls": True,
                "default_from_email": "noreply@example.com",
            }), encoding="utf-8")
            stdout = StringIO()

            with override_settings(BASE_DIR=Path(temp_dir)):
                with patch("bias_core.management.commands.install_forum.assert_database_connection") as assert_db:
                    with patch("bias_core.management.commands.install_forum.run_manage_py") as run_manage_py:
                        call_command(
                            "install_forum",
                            "--database",
                            "postgres",
                            "--config",
                            str(config_path),
                            "--non-interactive",
                            "--skip-admin",
                            "--dry-run",
                            stdout=stdout,
                        )

            assert_db.assert_not_called()
            run_manage_py.assert_not_called()
            output = stdout.getvalue()
            self.assertIn("生产配置检查", output)
            self.assertIn("secret_key_placeholder", output)
            self.assertIn("jwt_secret_key_placeholder", output)
            self.assertIn("db_name_placeholder", output)
            self.assertIn("[DRY-RUN]", output)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_install_forum_postgres_dry_run_json_reports_findings_for_ci(self):
        temp_dir = make_workspace_temp_dir()
        try:
            config_path = Path(temp_dir) / "instance" / "site.example.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps({
                "installed": False,
                "source": "example",
                "debug": False,
                "secret_key": "replace-with-django-secret-key",
                "jwt_secret_key": "replace-with-jwt-secret-key",
                "site_domains": ["forum.example.com"],
                "site_scheme": "https",
                "frontend_url": "https://forum.example.com",
                "database_mode": "postgres",
                "db_name": "replace-with-db-name",
                "db_user": "replace-with-db-user",
                "db_password": "replace-with-db-password",
                "db_host": "replace-with-db-host",
                "db_port": "5432",
                "use_redis": True,
                "redis_host": "replace-with-redis-host",
                "redis_port": "6379",
                "redis_db": "0",
                "email_backend": "django.core.mail.backends.smtp.EmailBackend",
                "email_host": "replace-with-email-host",
                "email_port": 587,
                "email_use_tls": True,
                "default_from_email": "noreply@example.com",
            }), encoding="utf-8")
            stdout = StringIO()

            with override_settings(BASE_DIR=Path(temp_dir)):
                with patch("bias_core.management.commands.install_forum.assert_database_connection") as assert_db:
                    with patch("bias_core.management.commands.install_forum.run_manage_py") as run_manage_py:
                        call_command(
                            "install_forum",
                            "--database",
                            "postgres",
                            "--config",
                            str(config_path),
                            "--non-interactive",
                            "--skip-admin",
                            "--dry-run",
                            "--format",
                            "json",
                            stdout=stdout,
                        )

            assert_db.assert_not_called()
            run_manage_py.assert_not_called()
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["config_path"], str(config_path))
            self.assertEqual(payload["database_mode"], "postgres")
            self.assertTrue(payload["redis_enabled"])
            self.assertEqual(payload["site_domains"], ["forum.example.com"])
            self.assertFalse(payload["summary"]["ok"])
            self.assertGreater(payload["summary"]["error_count"], 0)
            self.assertTrue(payload["summary"]["dry_run"])
            self.assertTrue(payload["install_steps"])
            codes = {item["code"] for item in payload["production_config_findings"]}
            self.assertIn("secret_key_placeholder", codes)
            self.assertIn("jwt_secret_key_placeholder", codes)
            self.assertIn("db_name_placeholder", codes)
            self.assertIn("db_user_placeholder", codes)
            self.assertIn("db_password_placeholder", codes)
            self.assertIn("db_host_placeholder", codes)
            self.assertIn("redis_host_placeholder", codes)
            self.assertIn("email_host_placeholder", codes)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_install_forum_rejects_placeholder_production_config_before_database_connection(self):
        temp_dir = make_workspace_temp_dir()
        try:
            config_path = Path(temp_dir) / "instance" / "site.json"

            with override_settings(BASE_DIR=Path(temp_dir)):
                with patch("bias_core.management.commands.install_forum.assert_database_connection") as assert_db:
                    with self.assertRaisesMessage(CommandError, "生产配置缺少必需项"):
                        call_command_quietly(
                            "install_forum",
                            "--database",
                            "postgres",
                            "--config",
                            str(config_path),
                            "--overwrite",
                            "--non-interactive",
                            "--skip-admin",
                            "--db-name",
                            "replace-with-db-name",
                            "--db-user",
                            "replace-with-db-user",
                            "--db-password",
                            "replace-with-db-password",
                            "--db-host",
                            "db",
                            "--db-port",
                            "5432",
                            "--redis",
                            "on",
                            "--site-domains",
                            "forum.example.com",
                            "--frontend-url",
                            "https://forum.example.com",
                            "--email-backend",
                            "django.core.mail.backends.smtp.EmailBackend",
                            "--email-host",
                            "smtp.example.com",
                        )

            assert_db.assert_not_called()
            self.assertFalse(config_path.exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_upgrade_forum_allows_split_site_without_version_file(self):
        temp_dir = make_workspace_temp_dir()
        try:
            config_path = Path(temp_dir) / "instance" / "site.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps({
                "installed": True,
                "source": "file",
                "debug": True,
                "secret_key": "x" * 50,
                "jwt_secret_key": "y" * 50,
                "site_scheme": "http",
                "frontend_url": "http://localhost:5173",
                "database_mode": "sqlite",
                "sqlite_name": str(Path(temp_dir) / "db.sqlite3"),
                "use_redis": False,
            }), encoding="utf-8")
            calls = []

            def fake_run_manage_py(args, env):
                calls.append(list(args))
                return SimpleNamespace(stdout="", stderr="", returncode=0)

            with override_settings(BASE_DIR=Path(temp_dir)):
                with patch("bias_core.management.commands.upgrade_forum.run_manage_py", side_effect=fake_run_manage_py):
                    call_command_quietly(
                        "upgrade_forum",
                        "--config",
                        str(config_path),
                        "--non-interactive",
                        "--skip-collectstatic",
                        "--skip-extension-frontend",
                    )

            self.assertFalse((Path(temp_dir) / "VERSION").exists())
            self.assertIn(["check"], calls)
            self.assertIn(["sync_forum_version"], calls)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_upgrade_forum_dry_run_json_outputs_machine_readable_plan(self):
        temp_dir = make_workspace_temp_dir()
        try:
            config_path = Path(temp_dir) / "instance" / "site.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps({
                "installed": True,
                "source": "file",
                "debug": True,
                "secret_key": "x" * 50,
                "jwt_secret_key": "y" * 50,
                "site_scheme": "http",
                "frontend_url": "http://localhost:5173",
                "database_mode": "sqlite",
                "sqlite_name": str(Path(temp_dir) / "db.sqlite3"),
                "use_redis": False,
            }), encoding="utf-8")
            stdout = StringIO()

            with override_settings(BASE_DIR=Path(temp_dir)):
                with patch("bias_core.management.commands.upgrade_forum.run_manage_py") as run_manage:
                    call_command(
                        "upgrade_forum",
                        "--config",
                        str(config_path),
                        "--dry-run",
                        "--non-interactive",
                        "--skip-collectstatic",
                        "--skip-extension-frontend",
                        "--format",
                        "json",
                        stdout=stdout,
                    )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertTrue(payload["summary"]["dry_run"])
            self.assertFalse(payload["summary"]["executed"])
            self.assertEqual(payload["config_path"], str(config_path))
            self.assertEqual(payload["database_mode"], "sqlite")
            self.assertEqual(payload["upgrade_steps"][0]["args"], ["check"])
            self.assertTrue(any(step["args"] == ["sync_forum_version"] for step in payload["upgrade_steps"]))
            self.assertFalse(payload["backup_required"])
            run_manage.assert_not_called()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_upgrade_forum_execute_json_outputs_machine_readable_summary_only(self):
        temp_dir = make_workspace_temp_dir()
        try:
            config_path = Path(temp_dir) / "instance" / "site.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps({
                "installed": True,
                "source": "file",
                "debug": True,
                "secret_key": "x" * 50,
                "jwt_secret_key": "y" * 50,
                "site_scheme": "http",
                "frontend_url": "http://localhost:5173",
                "database_mode": "sqlite",
                "sqlite_name": str(Path(temp_dir) / "db.sqlite3"),
                "use_redis": False,
            }), encoding="utf-8")
            stdout = StringIO()
            calls = []

            def fake_run_manage_py(args, env):
                calls.append(list(args))
                return SimpleNamespace(stdout=f"ran {' '.join(args)}", stderr="", returncode=0)

            with override_settings(BASE_DIR=Path(temp_dir)):
                with patch("bias_core.management.commands.upgrade_forum.run_manage_py", side_effect=fake_run_manage_py):
                    call_command(
                        "upgrade_forum",
                        "--config",
                        str(config_path),
                        "--non-interactive",
                        "--skip-collectstatic",
                        "--skip-extension-frontend",
                        "--format",
                        "json",
                        stdout=stdout,
                    )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertFalse(payload["summary"]["dry_run"])
            self.assertTrue(payload["summary"]["executed"])
            self.assertEqual(payload["summary"]["executed_step_count"], len(calls))
            self.assertEqual(payload["executed_steps"][0]["args"], ["check"])
            self.assertEqual(payload["executed_steps"][0]["stdout"], "ran check")
            self.assertNotIn("开始升级 Bias", stdout.getvalue())
            self.assertTrue(any(step["args"] == ["sync_forum_version"] for step in payload["executed_steps"]))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_plan_forum_rollback_json_outputs_backup_and_restore_plan(self):
        temp_dir = make_workspace_temp_dir()
        try:
            config_path = Path(temp_dir) / "instance" / "site.json"
            backup_dir = Path(temp_dir) / "backups" / "upgrade-001"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps({
                "installed": True,
                "source": "file",
                "debug": True,
                "secret_key": "x" * 50,
                "jwt_secret_key": "y" * 50,
                "site_scheme": "http",
                "frontend_url": "http://localhost:5173",
                "database_mode": "sqlite",
                "sqlite_name": str(Path(temp_dir) / "db.sqlite3"),
                "use_redis": False,
            }), encoding="utf-8")
            stdout = StringIO()

            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command(
                    "plan_forum_rollback",
                    "--config",
                    str(config_path),
                    "--backup-dir",
                    str(backup_dir),
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertFalse(payload["summary"]["executes_restore"])
            self.assertEqual(payload["summary"]["warning_count"], 4)
            self.assertEqual(payload["database_mode"], "sqlite")
            self.assertEqual({item["key"] for item in payload["backup_artifacts"]}, {
                "site_config",
                "database",
                "media",
                "static_frontend",
            })
            self.assertTrue(any(step["action"] == "restore_database" for step in payload["restore_steps"]))
            self.assertTrue(any("smoke_http_p95" in step["command"] for step in payload["verification_steps"]))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_plan_forum_rollback_require_existing_backups_fails_missing_artifacts(self):
        temp_dir = make_workspace_temp_dir()
        try:
            config_path = Path(temp_dir) / "instance" / "site.json"
            backup_dir = Path(temp_dir) / "backups" / "upgrade-001"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps({
                "installed": True,
                "source": "file",
                "debug": True,
                "secret_key": "x" * 50,
                "jwt_secret_key": "y" * 50,
                "site_scheme": "https",
                "frontend_url": "https://forum.example.test",
                "database_mode": "postgres",
                "db_name": "bias",
                "db_user": "bias",
                "db_password": "secret",
                "db_host": "db",
                "db_port": "5432",
                "use_redis": True,
                "redis_host": "redis",
                "redis_port": "6379",
            }), encoding="utf-8")
            stdout = StringIO()

            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command(
                    "plan_forum_rollback",
                    "--config",
                    str(config_path),
                    "--backup-dir",
                    str(backup_dir),
                    "--require-existing-backups",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["summary"]["ok"])
            self.assertEqual(payload["summary"]["error_count"], 4)
            self.assertEqual(payload["summary"]["warning_count"], 0)
            self.assertEqual(payload["database_mode"], "postgres")
            database_artifact = next(item for item in payload["backup_artifacts"] if item["key"] == "database")
            self.assertTrue(database_artifact["path"].endswith("database.dump"))
            self.assertIn("pg_restore", database_artifact["restore_hint"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_backup_forum_dry_run_json_outputs_backup_plan_without_writes(self):
        temp_dir = make_workspace_temp_dir()
        try:
            config_path = Path(temp_dir) / "instance" / "site.json"
            backup_dir = Path(temp_dir) / "backups" / "upgrade-001"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps({
                "installed": True,
                "source": "file",
                "debug": True,
                "secret_key": "x" * 50,
                "jwt_secret_key": "y" * 50,
                "site_scheme": "http",
                "frontend_url": "http://localhost:5173",
                "database_mode": "sqlite",
                "sqlite_name": str(Path(temp_dir) / "db.sqlite3"),
                "use_redis": False,
            }), encoding="utf-8")
            stdout = StringIO()

            with override_settings(BASE_DIR=Path(temp_dir)):
                call_command(
                    "backup_forum",
                    "--config",
                    str(config_path),
                    "--backup-dir",
                    str(backup_dir),
                    "--dry-run",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertTrue(payload["summary"]["dry_run"])
            self.assertEqual(payload["summary"]["warning_count"], 4)
            self.assertFalse(backup_dir.exists())
            self.assertEqual({item["key"] for item in payload["backup_artifacts"]}, {
                "site_config",
                "database",
                "media",
                "static_frontend",
            })
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_backup_forum_sqlite_creates_required_backup_artifacts(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            config_path = base_dir / "instance" / "site.json"
            backup_dir = base_dir / "backups" / "upgrade-001"
            sqlite_path = base_dir / "db.sqlite3"
            media_file = base_dir / "media" / "uploads" / "hello.txt"
            static_file = base_dir / "static" / "frontend" / "manifest.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            media_file.parent.mkdir(parents=True, exist_ok=True)
            static_file.parent.mkdir(parents=True, exist_ok=True)
            sqlite_path.write_text("sqlite-db", encoding="utf-8")
            media_file.write_text("media", encoding="utf-8")
            static_file.write_text("{}", encoding="utf-8")
            config_path.write_text(json.dumps({
                "installed": True,
                "source": "file",
                "debug": True,
                "secret_key": "x" * 50,
                "jwt_secret_key": "y" * 50,
                "site_scheme": "http",
                "frontend_url": "http://localhost:5173",
                "database_mode": "sqlite",
                "sqlite_name": str(sqlite_path),
                "use_redis": False,
            }), encoding="utf-8")
            stdout = StringIO()

            with override_settings(BASE_DIR=base_dir):
                call_command(
                    "backup_forum",
                    "--config",
                    str(config_path),
                    "--backup-dir",
                    str(backup_dir),
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertFalse(payload["summary"]["dry_run"])
            self.assertEqual(payload["summary"]["missing_required_artifact_count"], 0)
            self.assertTrue((backup_dir / "site.json").exists())
            self.assertEqual((backup_dir / "db.sqlite3").read_text(encoding="utf-8"), "sqlite-db")
            self.assertEqual((backup_dir / "media" / "uploads" / "hello.txt").read_text(encoding="utf-8"), "media")
            self.assertTrue((backup_dir / "static" / "frontend" / "manifest.json").exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_backup_forum_postgres_uses_pg_dump_with_password_env(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            config_path = base_dir / "instance" / "site.json"
            backup_dir = base_dir / "backups" / "upgrade-001"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps({
                "installed": True,
                "source": "file",
                "debug": False,
                "secret_key": "x" * 50,
                "jwt_secret_key": "y" * 50,
                "site_scheme": "https",
                "frontend_url": "https://forum.example.test",
                "database_mode": "postgres",
                "db_name": "bias",
                "db_user": "bias",
                "db_password": "secret",
                "db_host": "db",
                "db_port": "5432",
                "use_redis": True,
                "redis_host": "redis",
                "redis_port": "6379",
            }), encoding="utf-8")
            calls = []

            def fake_run(command, env, capture_output, text, check):
                calls.append((command, env, capture_output, text, check))
                Path(command[command.index("--file") + 1]).write_text("dump", encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            stdout = StringIO()
            with override_settings(BASE_DIR=base_dir):
                with patch("bias_core.management.commands.backup_forum.subprocess.run", side_effect=fake_run):
                    call_command(
                        "backup_forum",
                        "--config",
                        str(config_path),
                        "--backup-dir",
                        str(backup_dir),
                        "--skip-media",
                        "--skip-static-frontend",
                        "--format",
                        "json",
                        stdout=stdout,
                    )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertEqual(payload["summary"]["artifact_count"], 2)
            command, env, capture_output, text, check = calls[0]
            self.assertEqual(command[0], "pg_dump")
            self.assertIn("--format=custom", command)
            self.assertIn("bias", command)
            self.assertEqual(env["PGPASSWORD"], "secret")
            self.assertTrue(capture_output)
            self.assertTrue(text)
            self.assertFalse(check)
            self.assertEqual((backup_dir / "database.dump").read_text(encoding="utf-8"), "dump")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_verify_forum_backup_sqlite_validates_backup_artifacts(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            config_path = base_dir / "instance" / "site.json"
            backup_dir = base_dir / "backups" / "upgrade-001"
            sqlite_path = base_dir / "db.sqlite3"
            media_file = base_dir / "media" / "uploads" / "hello.txt"
            static_file = base_dir / "static" / "frontend" / "manifest.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            media_file.parent.mkdir(parents=True, exist_ok=True)
            static_file.parent.mkdir(parents=True, exist_ok=True)
            media_file.write_text("media", encoding="utf-8")
            static_file.write_text("{}", encoding="utf-8")
            sqlite3.connect(sqlite_path).close()
            config_path.write_text(json.dumps({
                "installed": True,
                "source": "file",
                "debug": True,
                "secret_key": "x" * 50,
                "jwt_secret_key": "y" * 50,
                "site_scheme": "http",
                "frontend_url": "http://localhost:5173",
                "database_mode": "sqlite",
                "sqlite_name": str(sqlite_path),
                "use_redis": False,
            }), encoding="utf-8")

            with override_settings(BASE_DIR=base_dir):
                call_command_quietly(
                    "backup_forum",
                    "--config",
                    str(config_path),
                    "--backup-dir",
                    str(backup_dir),
                    "--format",
                    "json",
                )
                stdout = StringIO()
                call_command(
                    "verify_forum_backup",
                    "--config",
                    str(config_path),
                    "--backup-dir",
                    str(backup_dir),
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertEqual(payload["summary"]["check_count"], 4)
            database_check = next(item for item in payload["checks"] if item["key"] == "database")
            self.assertEqual(database_check["validated_by"], "sqlite_open")
            media_check = next(item for item in payload["checks"] if item["key"] == "media")
            self.assertEqual(media_check["file_count"], 1)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_verify_forum_backup_postgres_uses_pg_restore_list(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            config_path = base_dir / "instance" / "site.json"
            backup_dir = base_dir / "backups" / "upgrade-001"
            (backup_dir / "media").mkdir(parents=True, exist_ok=True)
            (backup_dir / "static" / "frontend").mkdir(parents=True, exist_ok=True)
            (backup_dir / "database.dump").write_text("dump", encoding="utf-8")
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_payload = {
                "installed": True,
                "source": "file",
                "debug": False,
                "secret_key": "x" * 50,
                "jwt_secret_key": "y" * 50,
                "site_scheme": "https",
                "frontend_url": "https://forum.example.test",
                "database_mode": "postgres",
                "db_name": "bias",
                "db_user": "bias",
                "db_password": "secret",
                "db_host": "db",
                "db_port": "5432",
                "use_redis": True,
                "redis_host": "redis",
                "redis_port": "6379",
            }
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")
            (backup_dir / "site.json").write_text(json.dumps(config_payload), encoding="utf-8")

            def fake_run(command, capture_output, text, check):
                self.assertEqual(command[:2], ["pg_restore", "--list"])
                self.assertTrue(capture_output)
                self.assertTrue(text)
                self.assertFalse(check)
                return SimpleNamespace(returncode=0, stdout="1; table public.bias_core_setting\n", stderr="")

            stdout = StringIO()
            with override_settings(BASE_DIR=base_dir):
                with patch("bias_core.management.commands.verify_forum_backup.subprocess.run", side_effect=fake_run):
                    call_command(
                        "verify_forum_backup",
                        "--config",
                        str(config_path),
                        "--backup-dir",
                        str(backup_dir),
                        "--format",
                        "json",
                        stdout=stdout,
                    )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            database_check = next(item for item in payload["checks"] if item["key"] == "database")
            self.assertEqual(database_check["validated_by"], "pg_restore_list")
            self.assertEqual(database_check["entry_count"], 1)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_verify_forum_backup_reports_missing_required_artifacts(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            config_path = base_dir / "instance" / "site.json"
            backup_dir = base_dir / "backups" / "upgrade-001"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps({
                "installed": True,
                "source": "file",
                "debug": True,
                "secret_key": "x" * 50,
                "jwt_secret_key": "y" * 50,
                "site_scheme": "http",
                "frontend_url": "http://localhost:5173",
                "database_mode": "sqlite",
                "sqlite_name": str(base_dir / "db.sqlite3"),
                "use_redis": False,
            }), encoding="utf-8")
            stdout = StringIO()

            with override_settings(BASE_DIR=base_dir):
                call_command(
                    "verify_forum_backup",
                    "--config",
                    str(config_path),
                    "--backup-dir",
                    str(backup_dir),
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["summary"]["ok"])
            self.assertEqual(payload["summary"]["error_count"], 4)
            self.assertTrue(all(not item["exists"] for item in payload["checks"]))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_restore_forum_backup_dry_run_json_outputs_destructive_plan_without_writes(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            config_path = base_dir / "instance" / "site.json"
            backup_dir = base_dir / "backups" / "upgrade-001"
            sqlite_path = base_dir / "db.sqlite3"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            sqlite3.connect(sqlite_path).close()
            config_path.write_text(json.dumps({
                "installed": True,
                "source": "file",
                "debug": True,
                "secret_key": "x" * 50,
                "jwt_secret_key": "y" * 50,
                "site_scheme": "http",
                "frontend_url": "http://localhost:5173",
                "database_mode": "sqlite",
                "sqlite_name": str(sqlite_path),
                "use_redis": False,
            }), encoding="utf-8")

            with override_settings(BASE_DIR=base_dir):
                call_command_quietly(
                    "backup_forum",
                    "--config",
                    str(config_path),
                    "--backup-dir",
                    str(backup_dir),
                    "--format",
                    "json",
                )
                stdout = StringIO()
                call_command(
                    "restore_forum_backup",
                    "--config",
                    str(config_path),
                    "--backup-dir",
                    str(backup_dir),
                    "--dry-run",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"], payload)
            self.assertTrue(payload["summary"]["dry_run"])
            self.assertFalse(payload["summary"]["executes_live_restore"])
            self.assertTrue(payload["summary"]["destructive"])
            self.assertEqual(payload["summary"]["restore_step_count"], 4)
            self.assertTrue(all(step["planned_only"] for step in payload["restore_steps"]))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_restore_forum_backup_requires_double_confirmation_for_live_restore(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            config_path = base_dir / "instance" / "site.json"
            backup_dir = base_dir / "backups" / "upgrade-001"
            sqlite_path = base_dir / "db.sqlite3"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            sqlite3.connect(sqlite_path).close()
            config_path.write_text(json.dumps({
                "installed": True,
                "source": "file",
                "debug": True,
                "secret_key": "x" * 50,
                "jwt_secret_key": "y" * 50,
                "site_scheme": "http",
                "frontend_url": "http://localhost:5173",
                "database_mode": "sqlite",
                "sqlite_name": str(sqlite_path),
                "use_redis": False,
            }), encoding="utf-8")

            with override_settings(BASE_DIR=base_dir):
                call_command_quietly(
                    "backup_forum",
                    "--config",
                    str(config_path),
                    "--backup-dir",
                    str(backup_dir),
                    "--format",
                    "json",
                )
                with self.assertRaisesMessage(CommandError, "--i-understand-this-overwrites-live-data"):
                    call_command_quietly(
                        "restore_forum_backup",
                        "--config",
                        str(config_path),
                        "--backup-dir",
                        str(backup_dir),
                        "--format",
                        "json",
                    )
                with self.assertRaisesMessage(CommandError, "--confirm-phrase"):
                    call_command_quietly(
                        "restore_forum_backup",
                        "--config",
                        str(config_path),
                        "--backup-dir",
                        str(backup_dir),
                        "--i-understand-this-overwrites-live-data",
                        "--format",
                        "json",
                    )

            self.assertTrue(sqlite_path.exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_restore_forum_backup_sqlite_executes_confirmed_live_restore(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            config_path = base_dir / "instance" / "site.json"
            backup_dir = base_dir / "backups" / "upgrade-001"
            sqlite_path = base_dir / "db.sqlite3"
            media_file = base_dir / "media" / "uploads" / "hello.txt"
            static_file = base_dir / "static" / "frontend" / "manifest.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            media_file.parent.mkdir(parents=True, exist_ok=True)
            static_file.parent.mkdir(parents=True, exist_ok=True)
            media_file.write_text("media-before", encoding="utf-8")
            static_file.write_text("static-before", encoding="utf-8")
            connection = sqlite3.connect(sqlite_path)
            try:
                connection.execute("CREATE TABLE probe (id integer primary key, value text)")
                connection.execute("INSERT INTO probe (value) VALUES ('backup')")
                connection.commit()
            finally:
                connection.close()
            config_path.write_text(json.dumps({
                "installed": True,
                "source": "file",
                "debug": True,
                "secret_key": "x" * 50,
                "jwt_secret_key": "y" * 50,
                "site_scheme": "http",
                "frontend_url": "http://localhost:5173",
                "database_mode": "sqlite",
                "sqlite_name": str(sqlite_path),
                "use_redis": False,
            }), encoding="utf-8")

            with override_settings(BASE_DIR=base_dir):
                call_command_quietly(
                    "backup_forum",
                    "--config",
                    str(config_path),
                    "--backup-dir",
                    str(backup_dir),
                    "--format",
                    "json",
                )

                connection = sqlite3.connect(sqlite_path)
                try:
                    connection.execute("DELETE FROM probe")
                    connection.execute("INSERT INTO probe (value) VALUES ('live-mutated')")
                    connection.commit()
                finally:
                    connection.close()
                media_file.write_text("media-mutated", encoding="utf-8")
                static_file.write_text("static-mutated", encoding="utf-8")

                stdout = StringIO()
                call_command(
                    "restore_forum_backup",
                    "--config",
                    str(config_path),
                    "--backup-dir",
                    str(backup_dir),
                    "--i-understand-this-overwrites-live-data",
                    "--confirm-phrase",
                    "restore live forum data",
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"], payload)
            self.assertFalse(payload["summary"]["dry_run"])
            self.assertTrue(payload["summary"]["executes_live_restore"])
            self.assertTrue(payload["summary"]["confirmed_overwrites_live_data"])
            self.assertEqual(payload["summary"]["verification_count"], 4)
            verification_by_key = {item["key"]: item for item in payload["verification"]}
            self.assertEqual(verification_by_key["database"]["validated_by"], "sqlite_live_database")
            self.assertGreaterEqual(verification_by_key["database"]["table_count"], 1)
            self.assertTrue(verification_by_key["media"]["ok"])
            self.assertTrue(verification_by_key["static_frontend"]["ok"])
            self.assertTrue(verification_by_key["site_config"]["ok"])
            connection = sqlite3.connect(sqlite_path)
            try:
                value = connection.execute("SELECT value FROM probe").fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(value, "backup")
            self.assertEqual(media_file.read_text(encoding="utf-8"), "media-before")
            self.assertEqual(static_file.read_text(encoding="utf-8"), "static-before")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_restore_forum_backup_postgres_executes_live_pg_restore_when_confirmed(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            config_path = base_dir / "instance" / "site.json"
            backup_dir = base_dir / "backups" / "upgrade-001"
            (backup_dir / "media").mkdir(parents=True, exist_ok=True)
            (backup_dir / "static" / "frontend").mkdir(parents=True, exist_ok=True)
            (backup_dir / "database.dump").write_text("dump", encoding="utf-8")
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_payload = {
                "installed": True,
                "source": "file",
                "debug": False,
                "secret_key": "x" * 50,
                "jwt_secret_key": "y" * 50,
                "site_scheme": "https",
                "frontend_url": "https://forum.example.test",
                "database_mode": "postgres",
                "db_name": "bias",
                "db_user": "bias_user",
                "db_password": "secret",
                "db_host": "db",
                "db_port": "5432",
                "use_redis": True,
            }
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")
            (backup_dir / "site.json").write_text(json.dumps(config_payload), encoding="utf-8")
            calls = []

            def fake_run(command, env, capture_output, text, check):
                calls.append((command, env, capture_output, text, check))
                if command[0] == "psql":
                    return SimpleNamespace(returncode=0, stdout="7\n", stderr="")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            stdout = StringIO()
            with override_settings(BASE_DIR=base_dir):
                with patch("bias_core.management.commands.restore_forum_backup.subprocess.run", side_effect=fake_run):
                    call_command(
                        "restore_forum_backup",
                        "--config",
                        str(config_path),
                        "--backup-dir",
                        str(backup_dir),
                        "--skip-media",
                        "--skip-static-frontend",
                        "--skip-site-config",
                        "--i-understand-this-overwrites-live-data",
                        "--confirm-phrase",
                        "restore live forum data",
                        "--format",
                        "json",
                        stdout=stdout,
                    )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"], payload)
            self.assertTrue(payload["summary"]["executes_live_restore"])
            self.assertEqual(payload["summary"]["restore_step_count"], 1)
            self.assertEqual(payload["summary"]["verification_count"], 1)
            database_check = payload["verification"][0]
            self.assertEqual(database_check["key"], "database")
            self.assertEqual(database_check["validated_by"], "psql_live_database")
            self.assertEqual(database_check["table_count"], 7)
            command, env, capture_output, text, check = calls[0]
            self.assertEqual(command[0], "pg_restore")
            self.assertIn("--clean", command)
            self.assertIn("--if-exists", command)
            self.assertEqual(command[command.index("--dbname") + 1], "bias")
            self.assertEqual(env["PGPASSWORD"], "secret")
            self.assertTrue(capture_output)
            self.assertTrue(text)
            self.assertFalse(check)
            verify_command, verify_env, verify_capture_output, verify_text, verify_check = calls[1]
            self.assertEqual(verify_command[0], "psql")
            self.assertEqual(verify_command[verify_command.index("--dbname") + 1], "bias")
            self.assertEqual(verify_env["PGPASSWORD"], "secret")
            self.assertTrue(verify_capture_output)
            self.assertTrue(verify_text)
            self.assertFalse(verify_check)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_rehearse_forum_restore_sqlite_uses_isolated_restore_targets(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            config_path = base_dir / "instance" / "site.json"
            backup_dir = base_dir / "backups" / "upgrade-001"
            sqlite_path = base_dir / "db.sqlite3"
            media_file = base_dir / "media" / "uploads" / "hello.txt"
            static_file = base_dir / "static" / "frontend" / "manifest.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            media_file.parent.mkdir(parents=True, exist_ok=True)
            static_file.parent.mkdir(parents=True, exist_ok=True)
            media_file.write_text("media", encoding="utf-8")
            static_file.write_text("{}", encoding="utf-8")
            connection = sqlite3.connect(sqlite_path)
            try:
                connection.execute("CREATE TABLE probe (id integer primary key, value text)")
                connection.execute("INSERT INTO probe (value) VALUES ('live')")
                connection.commit()
            finally:
                connection.close()
            config_path.write_text(json.dumps({
                "installed": True,
                "source": "file",
                "debug": True,
                "secret_key": "x" * 50,
                "jwt_secret_key": "y" * 50,
                "site_scheme": "http",
                "frontend_url": "http://localhost:5173",
                "database_mode": "sqlite",
                "sqlite_name": str(sqlite_path),
                "use_redis": False,
            }), encoding="utf-8")

            with override_settings(BASE_DIR=base_dir):
                call_command_quietly(
                    "backup_forum",
                    "--config",
                    str(config_path),
                    "--backup-dir",
                    str(backup_dir),
                    "--format",
                    "json",
                )
                stdout = StringIO()
                call_command(
                    "rehearse_forum_restore",
                    "--config",
                    str(config_path),
                    "--backup-dir",
                    str(backup_dir),
                    "--format",
                    "json",
                    stdout=stdout,
                )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertEqual(payload["summary"]["warning_count"], 0)
            self.assertFalse(payload["summary"]["executes_live_restore"])
            self.assertTrue(payload["summary"]["uses_isolated_restore_targets"])
            self.assertEqual(payload["database_mode"], "sqlite")
            self.assertEqual(payload["summary"]["verification_count"], 4)
            self.assertTrue(all(step["destructive"] is False for step in payload["restore_steps"]))
            database_check = next(item for item in payload["verification"] if item["key"] == "database")
            self.assertEqual(database_check["validated_by"], "sqlite_temp_copy")
            self.assertEqual(database_check["table_count"], 1)
            self.assertTrue(sqlite_path.exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_rehearse_forum_restore_postgres_restores_dump_to_temp_database_and_drops_it(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            config_path = base_dir / "instance" / "site.json"
            backup_dir = base_dir / "backups" / "upgrade-001"
            (backup_dir / "media").mkdir(parents=True, exist_ok=True)
            (backup_dir / "static" / "frontend").mkdir(parents=True, exist_ok=True)
            (backup_dir / "database.dump").write_text("dump", encoding="utf-8")
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_payload = {
                "installed": True,
                "source": "file",
                "debug": False,
                "secret_key": "x" * 50,
                "jwt_secret_key": "y" * 50,
                "site_scheme": "https",
                "frontend_url": "https://forum.example.test",
                "database_mode": "postgres",
                "db_name": "bias",
                "db_user": "bias_user",
                "db_password": "secret",
                "db_host": "db",
                "db_port": "5432",
                "use_redis": True,
                "redis_host": "redis",
                "redis_port": "6379",
            }
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")
            (backup_dir / "site.json").write_text(json.dumps(config_payload), encoding="utf-8")
            commands = []

            def fake_run(command, env, capture_output, text, check):
                commands.append((command, env, capture_output, text, check))
                self.assertEqual(env["PGPASSWORD"], "secret")
                self.assertTrue(capture_output)
                self.assertTrue(text)
                self.assertFalse(check)
                if command[0] == "psql":
                    return SimpleNamespace(returncode=0, stdout="7\n", stderr="")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            stdout = StringIO()
            with override_settings(BASE_DIR=base_dir):
                with patch("bias_core.management.commands.rehearse_forum_restore.subprocess.run", side_effect=fake_run):
                    call_command(
                        "rehearse_forum_restore",
                        "--config",
                        str(config_path),
                        "--backup-dir",
                        str(backup_dir),
                        "--database-name-suffix",
                        "unit-test",
                        "--format",
                        "json",
                        stdout=stdout,
                    )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertEqual(payload["summary"]["warning_count"], 0)
            self.assertEqual(payload["database_mode"], "postgres")
            self.assertEqual(payload["temp_database"], "bias_restore_smoke_unit_test")
            self.assertTrue(payload["summary"]["dropped_temp_database"])
            self.assertFalse(payload["summary"]["executes_live_restore"])
            database_check = next(item for item in payload["verification"] if item["key"] == "database")
            self.assertEqual(database_check["table_count"], 7)
            command_names = [command[0][0] for command in commands]
            self.assertEqual(command_names, ["createdb", "pg_restore", "psql", "dropdb"])
            restore_command = commands[1][0]
            self.assertIn("--dbname", restore_command)
            self.assertIn("bias_restore_smoke_unit_test", restore_command)
            self.assertNotIn(" --dbname bias ", " ".join(restore_command))
            self.assertIn("--if-exists", commands[3][0])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_rehearse_forum_restore_postgres_reports_createdb_permission_blocker(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            config_path = base_dir / "instance" / "site.json"
            backup_dir = base_dir / "backups" / "upgrade-001"
            (backup_dir / "media").mkdir(parents=True, exist_ok=True)
            (backup_dir / "static" / "frontend").mkdir(parents=True, exist_ok=True)
            (backup_dir / "database.dump").write_text("dump", encoding="utf-8")
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_payload = {
                "installed": True,
                "source": "file",
                "debug": False,
                "secret_key": "x" * 50,
                "jwt_secret_key": "y" * 50,
                "site_scheme": "https",
                "frontend_url": "https://forum.example.test",
                "database_mode": "postgres",
                "db_name": "bias",
                "db_user": "bias_user",
                "db_password": "secret",
                "db_host": "db",
                "db_port": "5432",
                "use_redis": True,
                "redis_host": "redis",
                "redis_port": "6379",
            }
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")
            (backup_dir / "site.json").write_text(json.dumps(config_payload), encoding="utf-8")

            def fake_run(command, env, capture_output, text, check):
                self.assertEqual(command[0], "createdb")
                return SimpleNamespace(returncode=1, stdout="", stderr="permission denied to create database")

            stdout = StringIO()
            with override_settings(BASE_DIR=base_dir):
                with patch("bias_core.management.commands.rehearse_forum_restore.subprocess.run", side_effect=fake_run):
                    call_command(
                        "rehearse_forum_restore",
                        "--config",
                        str(config_path),
                        "--backup-dir",
                        str(backup_dir),
                        "--database-name-suffix",
                        "no-createdb",
                        "--format",
                        "json",
                        stdout=stdout,
                    )

            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["summary"]["ok"])
            self.assertEqual(payload["summary"]["error_count"], 1)
            self.assertEqual(payload["summary"]["warning_count"], 0)
            self.assertIn("permission denied", payload["errors"][0])
            self.assertFalse(payload["summary"]["dropped_temp_database"])
            self.assertFalse(payload["summary"]["executes_live_restore"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_rehearse_forum_restore_postgres_tolerates_transaction_timeout_dump_warning(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            config_path = base_dir / "instance" / "site.json"
            backup_dir = base_dir / "backups" / "upgrade-001"
            (backup_dir / "media").mkdir(parents=True, exist_ok=True)
            (backup_dir / "static" / "frontend").mkdir(parents=True, exist_ok=True)
            (backup_dir / "database.dump").write_text("dump", encoding="utf-8")
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_payload = {
                "installed": True,
                "source": "file",
                "debug": False,
                "secret_key": "x" * 50,
                "jwt_secret_key": "y" * 50,
                "site_scheme": "https",
                "frontend_url": "https://forum.example.test",
                "database_mode": "postgres",
                "db_name": "bias",
                "db_user": "bias_user",
                "db_password": "secret",
                "db_host": "db",
                "db_port": "5432",
                "use_redis": True,
            }
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")
            (backup_dir / "site.json").write_text(json.dumps(config_payload), encoding="utf-8")

            def fake_run(command, env, capture_output, text, check):
                if command[0] == "pg_restore":
                    return SimpleNamespace(
                        returncode=1,
                        stdout="",
                        stderr=(
                            'pg_restore: error: could not execute query: ERROR:  '
                            'unrecognized configuration parameter "transaction_timeout"\n'
                            'Command was: SET transaction_timeout = 0;\n'
                            "pg_restore: warning: errors ignored on restore: 1"
                        ),
                    )
                if command[0] == "psql":
                    return SimpleNamespace(returncode=0, stdout="7\n", stderr="")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            stdout = StringIO()
            with override_settings(BASE_DIR=base_dir):
                with patch("bias_core.management.commands.rehearse_forum_restore.subprocess.run", side_effect=fake_run):
                    call_command(
                        "rehearse_forum_restore",
                        "--config",
                        str(config_path),
                        "--backup-dir",
                        str(backup_dir),
                        "--database-name-suffix",
                        "pg16-to-pg15",
                        "--format",
                        "json",
                        stdout=stdout,
                    )

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["summary"]["ok"])
            self.assertEqual(payload["summary"]["error_count"], 0)
            self.assertEqual(payload["summary"]["warning_count"], 1)
            self.assertIn("transaction_timeout", payload["warnings"][0])
            restore_step = next(step for step in payload["restore_steps"] if step["action"] == "restore_dump_to_temp_database")
            self.assertTrue(restore_step["ok"])
            self.assertTrue(restore_step["tolerated"])
            database_check = next(item for item in payload["verification"] if item["key"] == "database")
            self.assertTrue(database_check["ok"])
            self.assertEqual(database_check["table_count"], 7)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_upgrade_forum_publish_frontend_dist_runs_rebuild_before_collectstatic(self):
        temp_dir = make_workspace_temp_dir()
        try:
            config_path = Path(temp_dir) / "instance" / "site.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps({
                "installed": True,
                "source": "file",
                "debug": True,
                "secret_key": "x" * 50,
                "jwt_secret_key": "y" * 50,
                "site_scheme": "http",
                "frontend_url": "http://localhost:5173",
                "database_mode": "sqlite",
                "sqlite_name": str(Path(temp_dir) / "db.sqlite3"),
                "use_redis": False,
            }), encoding="utf-8")
            calls = []

            def fake_run_manage_py(args, env):
                calls.append(list(args))
                return SimpleNamespace(stdout="", stderr="", returncode=0)

            with override_settings(BASE_DIR=Path(temp_dir)):
                with patch("bias_core.management.commands.upgrade_forum.run_manage_py", side_effect=fake_run_manage_py):
                    call_command_quietly(
                        "upgrade_forum",
                        "--config",
                        str(config_path),
                        "--non-interactive",
                        "--publish-frontend-dist",
                    )

            frontend_call = next(args for args in calls if args and args[0] == "build_extension_frontend")
            collectstatic_index = calls.index(["collectstatic", "--noinput"])
            self.assertLess(calls.index(frontend_call), collectstatic_index)
            self.assertIn("--rebuild", frontend_call)
            self.assertIn("--publish", frontend_call)
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
                if name == "inspect_extension_packages":
                    kwargs["stdout"].write(json.dumps(build_minimal_package_audit_payload()))
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
            workspace_gate_call = next(args for name, args in calls if name == "check_extension_workspace")
            sync_extensions_path = sync_call[sync_call.index("--extensions-path") + 1]
            workspace_gate_extensions_path = workspace_gate_call[workspace_gate_call.index("--extensions-path") + 1]
            extensions_path = validate_call[validate_call.index("--extensions-path") + 1]
            self.assertEqual(sync_extensions_path, str(workspace_root / "extensions"))
            self.assertEqual(workspace_gate_extensions_path, str(workspace_root / "extensions"))
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
                if name == "check_extension_workspace":
                    raise CommandError("扩展 workspace 门禁失败")
                if name in {"validate_extensions", "inspect_extensions"}:
                    self.fail("prepare_release should stop before extension validation when workspace gate fails")
                return None

            with override_settings(BASE_DIR=base_dir, BIAS_FRONTEND_DIR=frontend_dir):
                with patch("bias_core.management.commands.prepare_release.run_git_command") as git_mock:
                    git_mock.return_value = SimpleNamespace(stdout="")
                    with patch("bias_core.management.commands.prepare_release.call_command", side_effect=fake_call_command):
                        with self.assertRaisesMessage(CommandError, "扩展 workspace 门禁失败"):
                            call_command_quietly(
                                "prepare_release",
                                "--skip-frontend-platform-check",
                                "--set-version",
                                "1.2.3",
                                "--dry-run",
                            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_prepare_release_stops_when_extension_package_upgrade_risk_blocks_release(self):
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
                if name == "inspect_extension_packages":
                    kwargs["stdout"].write(json.dumps(
                        build_minimal_package_audit_payload(blocking_risk_count=1)
                    ))
                if name == "validate_extensions":
                    self.fail("prepare_release should stop before extension validation when package upgrade risk blocks")
                return None

            with override_settings(BASE_DIR=base_dir, BIAS_FRONTEND_DIR=frontend_dir):
                with patch("bias_core.management.commands.prepare_release.run_git_command") as git_mock:
                    git_mock.return_value = SimpleNamespace(stdout="")
                    with patch("bias_core.management.commands.prepare_release.call_command", side_effect=fake_call_command):
                        with self.assertRaisesMessage(CommandError, "扩展包升级风险存在 1 个阻断项"):
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

    def test_prepare_release_extension_report_includes_package_audit_gate_payload(self):
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
            report_path = base_dir / "reports" / "extension-release-report.json"

            def fake_call_command(name, *args, **kwargs):
                if name == "inspect_extension_packages":
                    kwargs["stdout"].write(json.dumps(build_minimal_package_audit_payload()))
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
                            "--extension-report",
                            str(report_path),
                        )

            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["blocking_count"], 0)
            self.assertEqual(payload["extensions"][0]["id"], "alpha")
            self.assertEqual(payload["release_gate"]["source"], "prepare_release")
            self.assertTrue(payload["release_gate"]["package_audit_included"])
            self.assertIn("package_audit", payload)
            self.assertEqual(payload["package_audit"]["install_plan"]["install_order"], ["alpha"])
            self.assertEqual(payload["package_audit"]["upgrade_risk"]["summary"]["blocking_risk_count"], 0)
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
                if name == "inspect_extension_packages":
                    kwargs["stdout"].write(json.dumps(build_minimal_package_audit_payload()))
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

    def test_prepare_release_stops_when_compatibility_matrix_blocks_release(self):
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
                if name == "inspect_extension_packages":
                    kwargs["stdout"].write(json.dumps(build_minimal_package_audit_payload()))
                if name == "inspect_extensions":
                    kwargs["stdout"].write(json.dumps({
                        "summary": {
                            "blocking_count": 0,
                            "warning_count": 0,
                            "attention_count": 0,
                            "compatibility_blocking_count": 1,
                            "compatibility_warning_count": 0,
                            "bias_version_incompatible_count": 1,
                            "unstable_api_count": 0,
                            "abandoned_distribution_count": 0,
                            "asset_count": 0,
                            "frontend_bundle_count": 0,
                            "migration_bundle_count": 0,
                            "locale_bundle_count": 0,
                            "signed_extension_count": 0,
                        },
                        "compatibility_matrix": {
                            "schema": 1,
                            "summary": {
                                "extension_count": 1,
                                "blocking_count": 1,
                                "warning_count": 0,
                                "bias_version_incompatible_count": 1,
                                "unstable_api_count": 0,
                                "abandoned_distribution_count": 0,
                                "ok": False,
                            },
                            "rows": [{
                                "extension_id": "alpha",
                                "status": {"blocking": True},
                            }],
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
                        with self.assertRaisesMessage(CommandError, "扩展兼容矩阵存在 1 个阻断项"):
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
                if name == "inspect_extension_packages":
                    kwargs["stdout"].write(json.dumps(build_minimal_package_audit_payload()))
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
                if name == "inspect_extension_packages":
                    kwargs["stdout"].write(json.dumps(build_minimal_package_audit_payload()))
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
                if name == "inspect_extension_packages":
                    kwargs["stdout"].write(json.dumps(build_minimal_package_audit_payload()))
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
                if name == "inspect_extension_packages":
                    kwargs["stdout"].write(json.dumps(build_minimal_package_audit_payload()))
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
                if name == "inspect_extension_packages":
                    kwargs["stdout"].write(json.dumps(build_minimal_package_audit_payload()))
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

    def test_prepare_release_dry_run_allows_split_site_without_version_file(self):
        temp_dir = make_workspace_temp_dir()
        try:
            base_dir = Path(temp_dir)
            frontend_dir = base_dir / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=False)
            (frontend_dir / "package.json").write_text(json.dumps({"version": "1.2.1"}), encoding="utf-8")
            (frontend_dir / "package-lock.json").write_text(json.dumps({
                "version": "1.2.1",
                "packages": {"": {"version": "1.2.1"}},
            }), encoding="utf-8")

            def fake_call_command(name, *args, **kwargs):
                if name == "inspect_extension_packages":
                    kwargs["stdout"].write(json.dumps(build_minimal_package_audit_payload()))
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

            self.assertFalse((base_dir / "VERSION").exists())
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
                if name == "inspect_extension_packages":
                    kwargs["stdout"].write(json.dumps(build_minimal_package_audit_payload()))
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
                if name == "inspect_extension_packages":
                    kwargs["stdout"].write(json.dumps(build_minimal_package_audit_payload()))
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
                if name == "inspect_extension_packages":
                    kwargs["stdout"].write(json.dumps(build_minimal_package_audit_payload()))
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

    def test_prepare_release_stops_when_contract_baseline_loses_runtime_facade(self):
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
            baseline_snapshot["runtime"] = {
                "facades": [{
                    "name": "get_runtime_user_by_id",
                    "domain": "users",
                    "provider_extension": "users",
                    "stability": "public",
                    "missing_service": "raises_runtime_error",
                }],
            }
            current_snapshot = build_minimal_contract_snapshot("alpha")
            current_snapshot["runtime"] = {"facades": []}
            baseline_path = base_dir / "extension-contract-baseline.json"
            baseline_path.write_text(json.dumps({
                "contract_snapshots": {
                    "alpha": baseline_snapshot,
                },
            }, ensure_ascii=False), encoding="utf-8")

            def fake_call_command(name, *args, **kwargs):
                if name == "inspect_extension_packages":
                    kwargs["stdout"].write(json.dumps(build_minimal_package_audit_payload()))
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
                        with self.assertRaisesMessage(CommandError, "contract_snapshot.runtime.facades 移除 get_runtime_user_by_id"):
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
                if name == "inspect_extension_packages":
                    kwargs["stdout"].write(json.dumps(build_minimal_package_audit_payload()))
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
                if name == "inspect_extension_packages":
                    kwargs["stdout"].write(json.dumps(build_minimal_package_audit_payload()))
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
                if name == "inspect_extension_packages":
                    kwargs["stdout"].write(json.dumps(build_minimal_package_audit_payload()))
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
                            "--run-capacity-smoke",
                            "--websocket-smoke-connections",
                            "3",
                            "--websocket-smoke-discussion-id",
                            "456",
                            "--websocket-smoke-p95-threshold-ms",
                            "800",
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
            self.assertIn("--run-capacity-smoke", prepare_args)
            self.assertEqual(prepare_args[prepare_args.index("--websocket-smoke-connections") + 1], "3")
            self.assertEqual(prepare_args[prepare_args.index("--websocket-smoke-discussion-id") + 1], "456")
            self.assertEqual(prepare_args[prepare_args.index("--websocket-smoke-p95-threshold-ms") + 1], "800.0")
            git_add_args = next(args for _base, args in git_commands if args and args[0] == "add")
            self.assertIn(str(frontend_dir / "package.json"), git_add_args)
            self.assertIn(str(frontend_dir / "package-lock.json"), git_add_args)
            self.assertIn(("finalize_release", ("--tag", "v1.2.3")), calls)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
