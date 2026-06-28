import json
import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.http import HttpResponse, JsonResponse
from django.test import RequestFactory
from django.test import TestCase, override_settings

from bias_core.extensions.application import ExtensionApplication
from bias_core.extensions.application_types import (
    ApplicationNamedRoute,
    ApplicationRouteMount,
    ApplicationWebSocketRoute,
)
from bias_core.extensions import (
    AdminPageDefinition,
    DiscussionListFilterDefinition,
    DiscussionListQueryDefinition,
    DiscussionSortDefinition,
    ExtensionModelCastDefinition,
    ExtensionModelDefaultDefinition,
    ExtensionModelDefinition,
    ExtensionModelRelationDefinition,
    ExtensionModelSlugDriverDefinition,
    ExtensionResourceDefinition,
    ExtensionResourceEndpointDefinition,
    ExtensionResourceFieldDefinition,
    ExtensionResourceFilterDefinition,
    ExtensionResourceRelationshipDefinition,
    ExtensionResourceSortDefinition,
    ExtensionSearchDriverDefinition,
    ExtensionSearchIndexDefinition,
    LanguagePackDefinition,
    NotificationTypeDefinition,
    PermissionDefinition,
    PostTypeDefinition,
    RuntimeModel,
    SearchFilterDefinition,
    UserPreferenceDefinition,
)
from bias_core.extensions.bootstrap import build_extension_application
from bias_core.extensions.manifest import ExtensionManifestLoader
from bias_core.extensions.registry import ExtensionRegistry
from bias_core.extensions.types import ExtensionFrontendRouteDefinition, ExtensionManifest
from bias_core.extensions.validation import (
    validate_extension_manifests,
    validate_extension_manifests_with_available_ids,
)
from bias_core.middleware import ExtensionRequestMiddleware
from bias_core.models import ExtensionInstallation


def make_workspace_temp_dir():
    return Path(tempfile.mkdtemp(prefix="bias_test_"))

class ExtensionMiddlewareIntegrationTests(TestCase):
    def _build_middleware_extension_registry(self) -> tuple[Path, ExtensionRegistry]:
        temp_dir = make_workspace_temp_dir()
        extensions_dir = temp_dir / "extensions"
        manifest_dir = extensions_dir / "alpha-middleware"
        backend_dir = manifest_dir / "backend"
        manifest_dir.mkdir(parents=True, exist_ok=False)
        backend_dir.mkdir(parents=True, exist_ok=False)
        (manifest_dir / "extension.json").write_text(json.dumps({
            "id": "alpha-middleware",
            "name": "Alpha Middleware",
            "version": "1.0.0",
            "backend_entry": "extensions.alpha_middleware.backend.ext",
        }, ensure_ascii=False), encoding="utf-8")
        (backend_dir / "ext.py").write_text(
            "from django.http import JsonResponse\n"
            "from bias_core.extensions import MiddlewareExtender\n"
            "\n"
            "def annotate_request(request, next_handler):\n"
            "    request.alpha_trace = ['global']\n"
            "    response = next_handler(request)\n"
            "    response['X-Alpha-Global'] = '1'\n"
            "    return response\n"
            "\n"
            "def annotate_api_request(request, next_handler):\n"
            "    request.alpha_trace.append('api')\n"
            "    response = next_handler(request)\n"
            "    response['X-Alpha-Api'] = ','.join(request.alpha_trace)\n"
            "    return response\n"
            "\n"
            "def block_admin(request):\n"
            "    return JsonResponse({'blocked': True, 'target': 'admin'}, status=418)\n"
            "\n"
            "def extend():\n"
            "    return [\n"
            "        MiddlewareExtender(mounts=(\n"
            "            ('global', annotate_request, 10),\n"
            "            ('api', annotate_api_request, 20),\n"
            "            ('admin', block_admin, 5),\n"
            "        )),\n"
            "    ]\n",
            encoding="utf-8",
        )
        ExtensionInstallation.objects.create(
            extension_id="alpha-middleware",
            version="1.0.0",
            source="filesystem",
            enabled=True,
            installed=True,
            booted=True,
        )
        return temp_dir, ExtensionRegistry(extensions_path=extensions_dir)

    def test_extension_request_middleware_runs_global_and_api_targets(self):
        temp_dir, registry = self._build_middleware_extension_registry()
        try:
            request = RequestFactory().get("/api/demo")

            def get_response(inner_request):
                trace = list(getattr(inner_request, "alpha_trace", []))
                return JsonResponse({"trace": trace})

            middleware = ExtensionRequestMiddleware(get_response)

            with patch("bias_core.middleware.get_extension_application", return_value=build_extension_application(manager=registry, force=True)):
                response = middleware(request)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(json.loads(response.content), {"trace": ["global", "api"]})
            self.assertEqual(response["X-Alpha-Global"], "1")
            self.assertEqual(response["X-Alpha-Api"], "global,api")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extension_request_middleware_can_short_circuit_admin_target(self):
        temp_dir, registry = self._build_middleware_extension_registry()
        try:
            request = RequestFactory().get("/api/admin/extensions")

            def get_response(_request):
                return HttpResponse("should not execute", status=200)

            middleware = ExtensionRequestMiddleware(get_response)

            with patch("bias_core.middleware.get_extension_application", return_value=build_extension_application(manager=registry, force=True)):
                response = middleware(request)

            self.assertEqual(response.status_code, 418)
            self.assertEqual(json.loads(response.content), {"blocked": True, "target": "admin"})
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_extension_error_handling_middleware_reports_and_reraises(self):
        from bias_core.middleware import ExtensionErrorHandlingMiddleware

        request = RequestFactory().get("/api/fail")
        reported = []

        def get_response(_request):
            raise ValueError("broken")

        middleware = ExtensionErrorHandlingMiddleware(get_response)

        with patch(
            "bias_core.extensions.system_runtime.report_runtime_error",
            side_effect=lambda exc, **kwargs: reported.append((exc, kwargs)),
        ):
            with self.assertRaises(ValueError):
                middleware(request)

        self.assertEqual(reported[0][0].args, ("broken",))
        self.assertEqual(reported[0][1]["request"], request)
        self.assertEqual(reported[0][1]["operation"], "request")

    def test_extension_error_handling_middleware_uses_typed_handler_response(self):
        from bias_core.extensions import ErrorHandlingExtender
        from bias_core.middleware import ExtensionErrorHandlingMiddleware

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")

        def handle_value_error(payload, context):
            return JsonResponse({"handled": payload["message"], "status": payload["http_status"]}, status=409)

        ErrorHandlingExtender() \
            .type(ValueError, "alpha_value_error") \
            .status("alpha_value_error", 409) \
            .handler(ValueError, handle_value_error) \
            .extend(app, extension)
        app.make("error.handling")

        request = RequestFactory().get("/api/fail")

        def get_response(_request):
            raise ValueError("broken")

        middleware = ExtensionErrorHandlingMiddleware(get_response)

        with patch("bias_core.extensions.bootstrap.get_extension_host", return_value=app):
            response = middleware(request)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(response.content), {"handled": "broken", "status": 409})

    def test_extension_csrf_middleware_marks_exempt_runtime_route(self):
        from bias_core.extensions import CsrfExtender
        from bias_core.middleware import ExtensionCsrfMiddleware

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")
        CsrfExtender().exempt_route("alpha-webhook").extend(app, extension)
        app.make("csrf")

        request = RequestFactory().post("/api/webhook")
        request.resolver_match = SimpleNamespace(url_name="alpha-webhook")
        middleware = ExtensionCsrfMiddleware(lambda current_request: HttpResponse("ok"))

        with patch("bias_core.extensions.bootstrap.get_extension_host", return_value=app):
            result = middleware.process_view(request, None, (), {})

        self.assertIsNone(result)
        self.assertTrue(request._dont_enforce_csrf_checks)

    def test_extension_throttle_api_middleware_short_circuits_api_request(self):
        from bias_core.extensions import ThrottleApiExtender
        from bias_core.middleware import ExtensionThrottleApiMiddleware

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")
        ThrottleApiExtender().set("alpha", lambda request: request.path == "/api/demo").extend(app, extension)
        app.make("throttle.api")

        request = RequestFactory().get("/api/demo")
        middleware = ExtensionThrottleApiMiddleware(lambda current_request: HttpResponse("ok"))

        with patch("bias_core.extensions.bootstrap.get_extension_host", return_value=app):
            response = middleware.process_view(request, None, (), {})

        self.assertEqual(response.status_code, 429)
        self.assertEqual(json.loads(response.content), {"error": "请求过于频繁", "code": "rate_limit_exceeded"})


    def test_validate_extension_manifests_reports_missing_dependency_and_missing_admin_entry(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            manifest_path = manifest_dir / "extension.json"
            manifest_path.write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["core", "missing-one"],
                "frontend_admin_entry": "frontend/admin/index.js",
                "settings_pages": ["/admin/extensions/alpha-tools/settings"],
            }, ensure_ascii=False), encoding="utf-8")

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = [item.manifest for item in loader.discover()]
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=Path(temp_dir) / "extensions",
                public_sdk_only=True,
            )

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "missing_dependency" for item in result.issues))
            self.assertTrue(any(item.code == "missing_frontend_admin_entry" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_admin_content_validation_logs_extension_registry_failures(self):
        from bias_core.extension_validation_context import resolve_available_extension_ids_for_validation

        registry = Mock()
        registry.get_extensions.side_effect = RuntimeError("registry unavailable")

        with patch("bias_core.extension_validation_context.get_core_module_ids", return_value=("core",)):
            with patch("bias_core.extension_validation_context.get_extension_registry", return_value=registry):
                with self.assertLogs("bias_core.extension_validation_context", level="WARNING") as logs:
                    extension_ids = resolve_available_extension_ids_for_validation()

        self.assertEqual(extension_ids, {"core"})
        self.assertTrue(any("Failed to resolve installed extension ids" in message for message in logs.output))

    def test_validate_extension_manifests_rejects_optional_dependency_top_level_imports(self):
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
                "from extensions.beta_tools.backend.ext import beta_extenders\n"
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

            manifests = [
                ExtensionManifest(
                    id="alpha-tools",
                    name="Alpha Tools",
                    version="1.0.0",
                    backend_entry="extensions.alpha_tools.backend.ext",
                    optional_dependencies=("beta-tools",),
                    path=str(alpha_dir),
                ),
                ExtensionManifest(
                    id="beta-tools",
                    name="Beta Tools",
                    version="1.0.0",
                    path=str(beta_dir),
                ),
            ]
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=extensions_dir,
            )

            self.assertFalse(result.ok)
            self.assertTrue(any(
                item.code == "optional_dependency_top_level_import"
                and item.extension_id == "alpha-tools"
                and item.field.endswith("extensions/alpha-tools/backend/ext.py")
                for item in result.issues
            ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_rejects_undeclared_cross_extension_imports(self):
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
            }, ensure_ascii=False), encoding="utf-8")
            (alpha_backend_dir / "ext.py").write_text(
                "from extensions.beta_tools.backend.ext import beta_extenders\n"
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

            manifests = [
                ExtensionManifest(
                    id="alpha-tools",
                    name="Alpha Tools",
                    version="1.0.0",
                    backend_entry="extensions.alpha_tools.backend.ext",
                    path=str(alpha_dir),
                ),
                ExtensionManifest(
                    id="beta-tools",
                    name="Beta Tools",
                    version="1.0.0",
                    path=str(beta_dir),
                ),
            ]
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=extensions_dir,
            )

            self.assertFalse(result.ok)
            self.assertTrue(any(
                item.code == "undeclared_cross_extension_import"
                and item.level == "error"
                and item.extension_id == "alpha-tools"
                for item in result.issues
            ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_rejects_declared_dependency_internal_imports(self):
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
                "dependencies": ["beta-tools"],
            }, ensure_ascii=False), encoding="utf-8")
            (alpha_backend_dir / "ext.py").write_text(
                "from extensions.beta_tools.backend.services import BetaService\n"
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

            manifests = [
                ExtensionManifest(
                    id="alpha-tools",
                    name="Alpha Tools",
                    version="1.0.0",
                    backend_entry="extensions.alpha_tools.backend.ext",
                    dependencies=("beta-tools",),
                    path=str(alpha_dir),
                ),
                ExtensionManifest(
                    id="beta-tools",
                    name="Beta Tools",
                    version="1.0.0",
                    path=str(beta_dir),
                ),
            ]
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=extensions_dir,
            )

            self.assertFalse(result.ok)
            self.assertTrue(any(
                item.code == "forbidden_cross_extension_internal_import"
                and item.level == "error"
                and item.extension_id == "alpha-tools"
                for item in result.issues
            ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_rejects_cross_extension_events_and_visibility_imports(self):
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
                "dependencies": ["beta-tools"],
            }, ensure_ascii=False), encoding="utf-8")
            (alpha_backend_dir / "ext.py").write_text(
                "from extensions.beta_tools.backend.events import BetaHappened\n"
                "from extensions.beta_tools.backend.visibility import scope_beta\n"
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

            manifests = [
                ExtensionManifest(
                    id="alpha-tools",
                    name="Alpha Tools",
                    version="1.0.0",
                    backend_entry="extensions.alpha_tools.backend.ext",
                    dependencies=("beta-tools",),
                    path=str(alpha_dir),
                ),
                ExtensionManifest(
                    id="beta-tools",
                    name="Beta Tools",
                    version="1.0.0",
                    path=str(beta_dir),
                ),
            ]
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=extensions_dir,
            )

            issues = [
                item for item in result.issues
                if item.code == "forbidden_cross_extension_internal_import"
                and item.extension_id == "alpha-tools"
            ]
            self.assertFalse(result.ok)
            self.assertEqual(len(issues), 2)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_rejects_delayed_internal_imports(self):
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
                "from bias_core.extensions import ConditionalExtender\n"
                "\n"
                "def beta_extenders():\n"
                "    from extensions.beta_tools.backend.models import BetaThing\n"
                "    return []\n"
                "\n"
                "def extend():\n"
                "    return [ConditionalExtender().when_extension_enabled('beta-tools', beta_extenders)]\n",
                encoding="utf-8",
            )
            (beta_dir / "extension.json").write_text(json.dumps({
                "id": "beta-tools",
                "name": "Beta Tools",
                "version": "1.0.0",
            }, ensure_ascii=False), encoding="utf-8")

            manifests = [
                ExtensionManifest(
                    id="alpha-tools",
                    name="Alpha Tools",
                    version="1.0.0",
                    backend_entry="extensions.alpha_tools.backend.ext",
                    optional_dependencies=("beta-tools",),
                    path=str(alpha_dir),
                ),
                ExtensionManifest(
                    id="beta-tools",
                    name="Beta Tools",
                    version="1.0.0",
                    path=str(beta_dir),
                ),
            ]
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=extensions_dir,
            )

            self.assertFalse(result.ok)
            self.assertTrue(any(
                item.code == "forbidden_cross_extension_internal_import"
                and item.level == "error"
                and item.extension_id == "alpha-tools"
                for item in result.issues
            ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_allows_conditional_optional_dependency_delayed_imports(self):
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
                "from bias_core.extensions import ConditionalExtender\n"
                "\n"
                "def beta_extenders():\n"
                "    from extensions.beta_tools.backend.ext import beta_extenders\n"
                "    return []\n"
                "\n"
                "def extend():\n"
                "    return [ConditionalExtender().when_extension_enabled('beta-tools', beta_extenders)]\n",
                encoding="utf-8",
            )
            (beta_dir / "extension.json").write_text(json.dumps({
                "id": "beta-tools",
                "name": "Beta Tools",
                "version": "1.0.0",
            }, ensure_ascii=False), encoding="utf-8")

            manifests = [
                ExtensionManifest(
                    id="alpha-tools",
                    name="Alpha Tools",
                    version="1.0.0",
                    backend_entry="extensions.alpha_tools.backend.ext",
                    optional_dependencies=("beta-tools",),
                    path=str(alpha_dir),
                ),
                ExtensionManifest(
                    id="beta-tools",
                    name="Beta Tools",
                    version="1.0.0",
                    path=str(beta_dir),
                ),
            ]
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=extensions_dir,
            )

            self.assertTrue(result.ok)
            self.assertFalse(any(item.code == "optional_dependency_top_level_import" for item in result.issues))
            self.assertFalse(any(item.code == "undeclared_cross_extension_import" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_rejects_undeclared_conditional_extension_dependencies(self):
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
            }, ensure_ascii=False), encoding="utf-8")
            (alpha_backend_dir / "ext.py").write_text(
                "from bias_core.extensions import ConditionalExtender\n"
                "\n"
                "def beta_extenders():\n"
                "    return []\n"
                "\n"
                "def extend():\n"
                "    return [ConditionalExtender().when_extension_enabled('beta-tools', beta_extenders)]\n",
                encoding="utf-8",
            )
            (beta_dir / "extension.json").write_text(json.dumps({
                "id": "beta-tools",
                "name": "Beta Tools",
                "version": "1.0.0",
            }, ensure_ascii=False), encoding="utf-8")

            manifests = [
                ExtensionManifest(
                    id="alpha-tools",
                    name="Alpha Tools",
                    version="1.0.0",
                    backend_entry="extensions.alpha_tools.backend.ext",
                    path=str(alpha_dir),
                ),
                ExtensionManifest(
                    id="beta-tools",
                    name="Beta Tools",
                    version="1.0.0",
                    path=str(beta_dir),
                ),
            ]
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=extensions_dir,
            )

            self.assertFalse(result.ok)
            self.assertTrue(any(
                item.code == "undeclared_conditional_extension_dependency"
                and item.extension_id == "alpha-tools"
                and item.field.endswith("extensions/alpha-tools/backend/ext.py")
                for item in result.issues
            ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_rejects_dependency_graph_cycles(self):
        manifests = [
            ExtensionManifest(
                id="alpha-tools",
                name="Alpha Tools",
                version="1.0.0",
                dependencies=("beta-tools",),
            ),
            ExtensionManifest(
                id="beta-tools",
                name="Beta Tools",
                version="1.0.0",
                optional_dependencies=("alpha-tools",),
            ),
        ]

        result = validate_extension_manifests_with_available_ids(
            manifests,
            available_extension_ids={"core"},
        )

        self.assertFalse(result.ok)
        self.assertTrue(any(
            item.code == "dependency_cycle"
            and item.extension_id == "alpha-tools"
            for item in result.issues
        ))
        self.assertTrue(any(
            item.code == "dependency_cycle"
            and item.extension_id == "beta-tools"
            for item in result.issues
        ))

    def test_validate_extension_manifests_allows_missing_optional_dependencies(self):
        manifests = [
            ExtensionManifest(
                id="alpha-tools",
                name="Alpha Tools",
                version="1.0.0",
                optional_dependencies=("missing-tools",),
            ),
        ]

        result = validate_extension_manifests_with_available_ids(
            manifests,
            available_extension_ids={"core"},
        )

        self.assertTrue(result.ok)
        self.assertFalse(any(
            item.field == "optional_dependencies"
            for item in result.issues
        ))

    def test_validate_extension_manifests_rejects_ambiguous_dependency_declarations(self):
        manifests = [
            ExtensionManifest(
                id="alpha-tools",
                name="Alpha Tools",
                version="1.0.0",
                dependencies=("alpha-tools", "beta-tools", "conflict-tools"),
                optional_dependencies=("alpha-tools", "beta-tools", "optional-conflict"),
                conflicts=("conflict-tools", "optional-conflict"),
            ),
            ExtensionManifest(
                id="beta-tools",
                name="Beta Tools",
                version="1.0.0",
            ),
            ExtensionManifest(
                id="conflict-tools",
                name="Conflict Tools",
                version="1.0.0",
            ),
            ExtensionManifest(
                id="optional-conflict",
                name="Optional Conflict",
                version="1.0.0",
            ),
        ]

        result = validate_extension_manifests_with_available_ids(
            manifests,
            available_extension_ids={"core"},
        )
        issue_codes = {item.code for item in result.issues if item.extension_id == "alpha-tools"}

        self.assertFalse(result.ok)
        self.assertIn("self_dependency", issue_codes)
        self.assertIn("self_optional_dependency", issue_codes)
        self.assertIn("dependency_optional_overlap", issue_codes)
        self.assertIn("dependency_conflict_overlap", issue_codes)
        self.assertIn("optional_dependency_conflict_overlap", issue_codes)

    def test_validate_extension_manifests_rejects_frontend_route_conflicts(self):
        manifests = [
            ExtensionManifest(
                id="alpha-tools",
                name="Alpha Tools",
                version="1.0.0",
            ),
            ExtensionManifest(
                id="beta-tools",
                name="Beta Tools",
                version="1.0.0",
            ),
        ]

        result = validate_extension_manifests_with_available_ids(
            manifests,
            available_extension_ids={"core"},
            frontend_routes_by_extension={
                "alpha-tools": (
                    ExtensionFrontendRouteDefinition(
                        path="/alpha",
                        name="alpha",
                        component="./AlphaView.vue",
                        module_id="alpha-tools",
                    ),
                ),
                "beta-tools": (
                    ExtensionFrontendRouteDefinition(
                        path="/alpha",
                        name="alpha",
                        component="./BetaView.vue",
                        module_id="beta-tools",
                    ),
                ),
            },
        )

        self.assertFalse(result.ok)
        self.assertTrue(any(item.code == "duplicate_frontend_route_name" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_frontend_route_path" for item in result.issues))

    def test_validate_extension_manifests_rejects_foreign_frontend_route_owners(self):
        manifests = [
            ExtensionManifest(
                id="alpha-tools",
                name="Alpha Tools",
                version="1.0.0",
            ),
            ExtensionManifest(
                id="beta-tools",
                name="Beta Tools",
                version="1.0.0",
            ),
        ]

        result = validate_extension_manifests_with_available_ids(
            manifests,
            available_extension_ids={"core"},
            frontend_routes_by_extension={
                "alpha-tools": (
                    ExtensionFrontendRouteDefinition(
                        path="alpha",
                        name="alpha",
                        component="./AlphaView.vue",
                        frontend="portal",
                        module_id="beta-tools",
                    ),
                ),
            },
        )

        self.assertFalse(result.ok)
        self.assertTrue(any(item.code == "invalid_frontend_route_target" for item in result.issues))
        self.assertTrue(any(item.code == "invalid_frontend_route_path" for item in result.issues))
        self.assertTrue(any(item.code == "foreign_frontend_route_owner" for item in result.issues))

    def test_validate_extension_manifests_rejects_backend_route_conflicts(self):
        manifests = [
            ExtensionManifest(
                id="alpha-tools",
                name="Alpha Tools",
                version="1.0.0",
            ),
            ExtensionManifest(
                id="beta-tools",
                name="Beta Tools",
                version="1.0.0",
            ),
        ]

        result = validate_extension_manifests_with_available_ids(
            manifests,
            available_extension_ids={"core"},
            route_mounts_by_extension={
                "alpha-tools": (ApplicationRouteMount(prefix="/alpha", router=object()),),
                "beta-tools": (ApplicationRouteMount(prefix="/alpha", router=object()),),
            },
            named_routes_by_extension={
                "alpha-tools": (
                    ApplicationNamedRoute(
                        app_name="api",
                        method="GET",
                        path="/alpha",
                        name="alpha.index",
                        handler=object(),
                        module_id="alpha-tools",
                    ),
                ),
                "beta-tools": (
                    ApplicationNamedRoute(
                        app_name="api",
                        method="GET",
                        path="/alpha",
                        name="alpha.index",
                        handler=object(),
                        module_id="beta-tools",
                    ),
                ),
            },
            websocket_routes_by_extension={
                "alpha-tools": (
                    ApplicationWebSocketRoute(path="ws/alpha/$", name="alpha.socket", consumer=object(), module_id="alpha-tools"),
                ),
                "beta-tools": (
                    ApplicationWebSocketRoute(path="^ws/alpha/$", name="alpha.socket", consumer=object(), module_id="beta-tools"),
                ),
            },
        )

        self.assertFalse(result.ok)
        self.assertTrue(any(item.code == "duplicate_api_route_name" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_api_route_path" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_websocket_route_name" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_websocket_route_path" for item in result.issues))

    def test_validate_extension_manifests_rejects_runtime_capability_conflicts(self):
        manifests = [
            ExtensionManifest(
                id="alpha-tools",
                name="Alpha Tools",
                version="1.0.0",
            ),
            ExtensionManifest(
                id="beta-tools",
                name="Beta Tools",
                version="1.0.0",
            ),
        ]

        def parse_alpha(token):
            return token

        def apply_alpha(queryset, value, context):
            return queryset

        def resolve_alpha(instance, context):
            return True

        def handle_alpha(context):
            return {"ok": True}

        alpha_model = RuntimeModel("alpha-tools.service")
        searcher = object()

        result = validate_extension_manifests_with_available_ids(
            manifests,
            available_extension_ids={"core"},
            permissions_by_extension={
                "alpha-tools": (
                    PermissionDefinition(code="alpha.manage", label="Alpha", section="alpha", section_label="Alpha", module_id="alpha-tools"),
                ),
                "beta-tools": (
                    PermissionDefinition(code="alpha.manage", label="Beta", section="beta", section_label="Beta", module_id="beta-tools"),
                ),
            },
            admin_pages_by_extension={
                "alpha-tools": (
                    AdminPageDefinition(path="/admin/alpha", label="Alpha", icon="alpha", module_id="alpha-tools"),
                ),
                "beta-tools": (
                    AdminPageDefinition(path="/admin/alpha", label="Beta", icon="beta", module_id="beta-tools"),
                ),
            },
            notification_types_by_extension={
                "alpha-tools": (
                    NotificationTypeDefinition(code="alphaPing", label="Alpha", module_id="alpha-tools"),
                ),
                "beta-tools": (
                    NotificationTypeDefinition(code="alphaPing", label="Beta", module_id="beta-tools"),
                ),
            },
            user_preferences_by_extension={
                "alpha-tools": (
                    UserPreferenceDefinition(key="alpha.enabled", label="Alpha", module_id="alpha-tools"),
                ),
                "beta-tools": (
                    UserPreferenceDefinition(key="alpha.enabled", label="Beta", module_id="beta-tools"),
                ),
            },
            language_packs_by_extension={
                "alpha-tools": (
                    LanguagePackDefinition(code="en", label="English", module_id="alpha-tools"),
                ),
                "beta-tools": (
                    LanguagePackDefinition(code="en", label="English", module_id="beta-tools"),
                ),
            },
            post_types_by_extension={
                "alpha-tools": (
                    PostTypeDefinition(code="alpha", label="Alpha", module_id="alpha-tools"),
                ),
                "beta-tools": (
                    PostTypeDefinition(code="alpha", label="Beta", module_id="beta-tools"),
                ),
            },
            search_filters_by_extension={
                "alpha-tools": (
                    SearchFilterDefinition(
                        code="alpha",
                        label="Alpha",
                        module_id="alpha-tools",
                        target="discussion",
                        parser=parse_alpha,
                        applier=apply_alpha,
                    ),
                ),
                "beta-tools": (
                    SearchFilterDefinition(
                        code="alpha",
                        label="Beta",
                        module_id="beta-tools",
                        target="discussion",
                        parser=parse_alpha,
                        applier=apply_alpha,
                    ),
                ),
            },
            discussion_list_queries_by_extension={
                "alpha-tools": (
                    DiscussionListQueryDefinition(key="alpha", module_id="alpha-tools", applier=lambda queryset, context: queryset),
                ),
                "beta-tools": (
                    DiscussionListQueryDefinition(key="alpha", module_id="beta-tools", applier=lambda queryset, context: queryset),
                ),
            },
            discussion_sorts_by_extension={
                "alpha-tools": (
                    DiscussionSortDefinition(code="alpha", label="Alpha", module_id="alpha-tools", applier=lambda queryset, context: queryset),
                ),
                "beta-tools": (
                    DiscussionSortDefinition(code="alpha", label="Beta", module_id="beta-tools", applier=lambda queryset, context: queryset),
                ),
            },
            discussion_list_filters_by_extension={
                "alpha-tools": (
                    DiscussionListFilterDefinition(code="alpha", label="Alpha", module_id="alpha-tools", applier=lambda queryset, context: queryset),
                ),
                "beta-tools": (
                    DiscussionListFilterDefinition(code="alpha", label="Beta", module_id="beta-tools", applier=lambda queryset, context: queryset),
                ),
            },
            resource_definitions_by_extension={
                "alpha-tools": (
                    ExtensionResourceDefinition(resource="alpha", module_id="alpha-tools", resolver=resolve_alpha),
                ),
                "beta-tools": (
                    ExtensionResourceDefinition(resource="alpha", module_id="beta-tools", resolver=resolve_alpha),
                ),
            },
            resource_fields_by_extension={
                "alpha-tools": (
                    ExtensionResourceFieldDefinition(resource="forum", field="alpha", module_id="alpha-tools", resolver=resolve_alpha),
                ),
                "beta-tools": (
                    ExtensionResourceFieldDefinition(resource="forum", field="alpha", module_id="beta-tools", resolver=resolve_alpha),
                ),
            },
            resource_relationships_by_extension={
                "alpha-tools": (
                    ExtensionResourceRelationshipDefinition(resource="discussion", relationship="alpha", module_id="alpha-tools", resolver=resolve_alpha),
                ),
                "beta-tools": (
                    ExtensionResourceRelationshipDefinition(resource="discussion", relationship="alpha", module_id="beta-tools", resolver=resolve_alpha),
                ),
            },
            resource_endpoints_by_extension={
                "alpha-tools": (
                    ExtensionResourceEndpointDefinition(resource="alpha", endpoint="inspect", module_id="alpha-tools", handler=handle_alpha),
                ),
                "beta-tools": (
                    ExtensionResourceEndpointDefinition(resource="alpha", endpoint="inspect", module_id="beta-tools", handler=handle_alpha),
                ),
            },
            resource_sorts_by_extension={
                "alpha-tools": (
                    ExtensionResourceSortDefinition(resource="alpha", sort="recent", module_id="alpha-tools"),
                ),
                "beta-tools": (
                    ExtensionResourceSortDefinition(resource="alpha", sort="recent", module_id="beta-tools"),
                ),
            },
            resource_filters_by_extension={
                "alpha-tools": (
                    ExtensionResourceFilterDefinition(resource="alpha", filter="visible", module_id="alpha-tools", handler=apply_alpha),
                ),
                "beta-tools": (
                    ExtensionResourceFilterDefinition(resource="alpha", filter="visible", module_id="beta-tools", handler=apply_alpha),
                ),
            },
            model_definitions_by_extension={
                "alpha-tools": (
                    ExtensionModelDefinition(model=alpha_model, key="owner", handler=object(), kind="owner"),
                ),
                "beta-tools": (
                    ExtensionModelDefinition(model=alpha_model, key="owner", handler=object(), kind="owner"),
                ),
            },
            model_relations_by_extension={
                "alpha-tools": (
                    ExtensionModelRelationDefinition(model=alpha_model, name="tags", resolver=lambda instance: ()),
                ),
                "beta-tools": (
                    ExtensionModelRelationDefinition(model=alpha_model, name="tags", resolver=lambda instance: ()),
                ),
            },
            model_casts_by_extension={
                "alpha-tools": (
                    ExtensionModelCastDefinition(model=alpha_model, attribute="meta", cast=dict),
                ),
                "beta-tools": (
                    ExtensionModelCastDefinition(model=alpha_model, attribute="meta", cast=dict),
                ),
            },
            model_defaults_by_extension={
                "alpha-tools": (
                    ExtensionModelDefaultDefinition(model=alpha_model, attribute="status", value="new"),
                ),
                "beta-tools": (
                    ExtensionModelDefaultDefinition(model=alpha_model, attribute="status", value="new"),
                ),
            },
            model_slug_drivers_by_extension={
                "alpha-tools": (
                    ExtensionModelSlugDriverDefinition(model=alpha_model, identifier="default", driver=object()),
                ),
                "beta-tools": (
                    ExtensionModelSlugDriverDefinition(model=alpha_model, identifier="default", driver=object()),
                ),
            },
            search_drivers_by_extension={
                "alpha-tools": (
                    ExtensionSearchDriverDefinition(target="alpha", driver="database", model=alpha_model, searcher=searcher),
                ),
                "beta-tools": (
                    ExtensionSearchDriverDefinition(target="alpha", driver="database", model=alpha_model, searcher=searcher),
                ),
            },
            search_indexes_by_extension={
                "alpha-tools": (
                    ExtensionSearchIndexDefinition(name="alpha_index", drop="", create=""),
                ),
                "beta-tools": (
                    ExtensionSearchIndexDefinition(name="alpha_index", drop="", create=""),
                ),
            },
        )

        self.assertFalse(result.ok)
        self.assertTrue(any(item.code == "duplicate_permission" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_admin_page" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_notification_type" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_user_preference" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_language_pack" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_post_type" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_search_filter" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_discussion_list_query" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_discussion_sort" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_discussion_list_filter" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_resource_definition" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_resource_field" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_resource_relationship" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_resource_endpoint" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_resource_sort" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_resource_filter" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_model_definition" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_model_relation" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_model_cast" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_model_default" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_model_slug_driver" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_search_driver" for item in result.issues))
        self.assertTrue(any(item.code == "duplicate_search_index" for item in result.issues))

    def test_validate_extension_manifests_allows_declared_conditional_extension_dependencies(self):
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
                "from bias_core.extensions import ConditionalExtender\n"
                "\n"
                "def beta_extenders():\n"
                "    return []\n"
                "\n"
                "def extend():\n"
                "    return [ConditionalExtender().when_extension_enabled('beta-tools', beta_extenders)]\n",
                encoding="utf-8",
            )
            (beta_dir / "extension.json").write_text(json.dumps({
                "id": "beta-tools",
                "name": "Beta Tools",
                "version": "1.0.0",
            }, ensure_ascii=False), encoding="utf-8")

            manifests = [
                ExtensionManifest(
                    id="alpha-tools",
                    name="Alpha Tools",
                    version="1.0.0",
                    backend_entry="extensions.alpha_tools.backend.ext",
                    optional_dependencies=("beta-tools",),
                    path=str(alpha_dir),
                ),
                ExtensionManifest(
                    id="beta-tools",
                    name="Beta Tools",
                    version="1.0.0",
                    path=str(beta_dir),
                ),
            ]
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=extensions_dir,
            )

            self.assertTrue(result.ok)
            self.assertFalse(any(
                item.code == "undeclared_conditional_extension_dependency"
                for item in result.issues
            ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_rejects_undeclared_public_contract_dependencies(self):
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
            }, ensure_ascii=False), encoding="utf-8")
            (alpha_backend_dir / "ext.py").write_text(
                "from bias_core.extensions import EventListenersExtender, ExtensionEventListenerDefinition, RuntimeModel\n"
                "\n"
                "BETA_MODEL = RuntimeModel('beta-tools.service')\n"
                "\n"
                "def handle_beta(event):\n"
                "    return None\n"
                "\n"
                "def extend():\n"
                "    return [EventListenersExtender(listeners=(ExtensionEventListenerDefinition(\n"
                "        event_type='beta-tools.item.created', handler=handle_beta,\n"
                "    ),))]\n",
                encoding="utf-8",
            )
            (beta_dir / "extension.json").write_text(json.dumps({
                "id": "beta-tools",
                "name": "Beta Tools",
                "version": "1.0.0",
            }, ensure_ascii=False), encoding="utf-8")

            manifests = [
                ExtensionManifest(
                    id="alpha-tools",
                    name="Alpha Tools",
                    version="1.0.0",
                    backend_entry="extensions.alpha_tools.backend.ext",
                    path=str(alpha_dir),
                ),
                ExtensionManifest(
                    id="beta-tools",
                    name="Beta Tools",
                    version="1.0.0",
                    path=str(beta_dir),
                ),
            ]
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=extensions_dir,
            )

            self.assertFalse(result.ok)
            issues = [
                item
                for item in result.issues
                if item.code == "undeclared_public_contract_extension_dependency"
                and item.extension_id == "alpha-tools"
                and item.field.endswith("extensions/alpha-tools/backend/ext.py")
            ]
            self.assertGreaterEqual(len(issues), 2)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_allows_declared_public_contract_dependencies(self):
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
                "dependencies": ["beta-tools"],
            }, ensure_ascii=False), encoding="utf-8")
            (alpha_backend_dir / "ext.py").write_text(
                "from bias_core.extensions import EventListenersExtender, ExtensionEventListenerDefinition, RuntimeModel\n"
                "\n"
                "BETA_MODEL = RuntimeModel('beta-tools.service')\n"
                "\n"
                "def handle_beta(event):\n"
                "    return None\n"
                "\n"
                "def extend():\n"
                "    return [EventListenersExtender(listeners=(ExtensionEventListenerDefinition(\n"
                "        event_type='beta-tools.item.created', handler=handle_beta,\n"
                "    ),))]\n",
                encoding="utf-8",
            )
            (beta_dir / "extension.json").write_text(json.dumps({
                "id": "beta-tools",
                "name": "Beta Tools",
                "version": "1.0.0",
            }, ensure_ascii=False), encoding="utf-8")

            manifests = [
                ExtensionManifest(
                    id="alpha-tools",
                    name="Alpha Tools",
                    version="1.0.0",
                    backend_entry="extensions.alpha_tools.backend.ext",
                    dependencies=("beta-tools",),
                    path=str(alpha_dir),
                ),
                ExtensionManifest(
                    id="beta-tools",
                    name="Beta Tools",
                    version="1.0.0",
                    path=str(beta_dir),
                ),
            ]
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=extensions_dir,
            )

            self.assertTrue(result.ok)
            self.assertFalse(any(
                item.code == "undeclared_public_contract_extension_dependency"
                for item in result.issues
            ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_rejects_internal_event_contract_paths(self):
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
                "dependencies": ["beta-tools"],
            }, ensure_ascii=False), encoding="utf-8")
            (alpha_backend_dir / "ext.py").write_text(
                "from bias_core.extensions import EventListenersExtender, ExtensionEventListenerDefinition, RealtimeExtender\n"
                "\n"
                "def handle_beta(event):\n"
                "    return None\n"
                "\n"
                "def resolve_discussion(event):\n"
                "    return None\n"
                "\n"
                "def extend():\n"
                "    return [\n"
                "        EventListenersExtender(listeners=(ExtensionEventListenerDefinition(\n"
                "            event_type='extensions.beta_tools.backend.events.ItemCreatedEvent', handler=handle_beta,\n"
                "        ),)),\n"
                "        RealtimeExtender().broadcast_discussion_event(\n"
                "            'extensions.beta_tools.backend.events.ItemUpdatedEvent',\n"
                "            'item.updated',\n"
                "            discussion_getter=resolve_discussion,\n"
                "        ),\n"
                "    ]\n",
                encoding="utf-8",
            )
            (beta_dir / "extension.json").write_text(json.dumps({
                "id": "beta-tools",
                "name": "Beta Tools",
                "version": "1.0.0",
            }, ensure_ascii=False), encoding="utf-8")

            manifests = [
                ExtensionManifest(
                    id="alpha-tools",
                    name="Alpha Tools",
                    version="1.0.0",
                    backend_entry="extensions.alpha_tools.backend.ext",
                    dependencies=("beta-tools",),
                    path=str(alpha_dir),
                ),
                ExtensionManifest(
                    id="beta-tools",
                    name="Beta Tools",
                    version="1.0.0",
                    path=str(beta_dir),
                ),
            ]
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=extensions_dir,
            )

            self.assertFalse(result.ok)
            issues = [
                item
                for item in result.issues
                if item.code == "forbidden_internal_event_contract_path"
                and item.extension_id == "alpha-tools"
                and item.field.endswith("extensions/alpha-tools/backend/ext.py")
            ]
            self.assertGreaterEqual(len(issues), 2)
            self.assertTrue(any(
                item.code == "forbidden_internal_event_contract_path"
                and item.extension_id == "alpha-tools"
                and item.field.endswith("extensions/alpha-tools/backend/ext.py")
                for item in result.issues
            ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_does_not_treat_service_provider_keys_as_event_aliases(self):
        temp_dir = make_workspace_temp_dir()
        try:
            extensions_dir = Path(temp_dir) / "extensions"
            alpha_dir = extensions_dir / "alpha-tools"
            search_dir = extensions_dir / "search"
            alpha_backend_dir = alpha_dir / "backend"
            alpha_backend_dir.mkdir(parents=True, exist_ok=False)
            search_dir.mkdir(parents=True, exist_ok=False)
            (alpha_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (alpha_backend_dir / "ext.py").write_text(
                "from bias_core.extensions import ServiceProviderExtender\n"
                "\n"
                "def target_provider():\n"
                "    return {}\n"
                "\n"
                "def extend():\n"
                "    return [ServiceProviderExtender(key='search.target.discussion', provider=target_provider)]\n",
                encoding="utf-8",
            )
            (search_dir / "extension.json").write_text(json.dumps({
                "id": "search",
                "name": "Search",
                "version": "1.0.0",
            }, ensure_ascii=False), encoding="utf-8")

            manifests = [
                ExtensionManifest(
                    id="alpha-tools",
                    name="Alpha Tools",
                    version="1.0.0",
                    backend_entry="extensions.alpha_tools.backend.ext",
                    path=str(alpha_dir),
                ),
                ExtensionManifest(
                    id="search",
                    name="Search",
                    version="1.0.0",
                    path=str(search_dir),
                ),
            ]
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=extensions_dir,
            )

            self.assertTrue(result.ok)
            self.assertFalse(any(
                item.code == "undeclared_public_contract_extension_dependency"
                for item in result.issues
            ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_reports_missing_frontend_admin_exports(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            admin_dir = manifest_dir / "frontend" / "admin"
            admin_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "frontend_admin_entry": "extensions/alpha-tools/frontend/admin/index.js",
                "settings_pages": ["/admin/extensions/alpha-tools/settings"],
                "operations_pages": ["/admin/extensions/alpha-tools/operations"],
            }, ensure_ascii=False), encoding="utf-8")
            (admin_dir / "index.js").write_text(
                "export function resolveSettingsPage() { return null }\n",
                encoding="utf-8",
            )

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = [item.manifest for item in loader.discover()]
            result = validate_extension_manifests(manifests, extensions_base_path=Path(temp_dir) / "extensions")

            self.assertFalse(result.ok)
            self.assertTrue(any(
                item.code == "missing_frontend_admin_export"
                and "resolveOperationsPage" in item.message
                for item in result.issues
            ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_reports_mismatched_frontend_entry_paths(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "frontend_admin_entry": "extensions/other-tools/frontend/admin/index.js",
                "frontend_forum_entry": "extensions/other-tools/frontend/forum/index.js",
            }, ensure_ascii=False), encoding="utf-8")

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = [item.manifest for item in loader.discover()]
            result = validate_extension_manifests(manifests, extensions_base_path=Path(temp_dir) / "extensions")

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "invalid_frontend_admin_entry_path" for item in result.issues))
            self.assertTrue(any(item.code == "invalid_frontend_forum_entry_path" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_rejects_core_owned_frontend_contributions(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            forum_dir = manifest_dir / "frontend" / "forum"
            forum_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "frontend_forum_entry": "frontend/forum/index.js",
            }, ensure_ascii=False), encoding="utf-8")
            (forum_dir / "index.js").write_text(
                "import { registerForumNavItem } from '@/forum/registry'\n"
                "export const extend = [{\n"
                "  extend() {\n"
                "    registerForumNavItem({ key: 'alpha', moduleId: 'core' })\n"
                "  },\n"
                "}]\n",
                encoding="utf-8",
            )

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = loader.discover_manifests()
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=Path(temp_dir) / "extensions",
                public_sdk_only=True,
            )

            self.assertFalse(result.ok)
            self.assertTrue(any(
                item.code == "forbidden_core_module_frontend_contribution"
                and item.field == "extensions/alpha-tools/frontend/forum/index.js"
                for item in result.issues
            ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_allows_generated_settings_surface(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            admin_dir = manifest_dir / "frontend" / "admin"
            admin_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "frontend_admin_entry": "extensions/alpha-tools/frontend/admin/index.js",
                "settings_pages": ["/admin/extensions/alpha-tools/settings"],
                "settings_schema": [
                    {
                        "key": "welcome_message",
                        "label": "欢迎语",
                        "type": "text",
                        "default": "hello",
                    }
                ],
            }, ensure_ascii=False), encoding="utf-8")
            (admin_dir / "index.js").write_text(
                "export function resolveDetailPage() { return null }\n",
                encoding="utf-8",
            )

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = [item.manifest for item in loader.discover()]
            result = validate_extension_manifests(manifests, extensions_base_path=Path(temp_dir) / "extensions")

            self.assertTrue(result.ok)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_allows_generated_permissions_and_operations_surfaces(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            admin_dir = manifest_dir / "frontend" / "admin"
            admin_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
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

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = [item.manifest for item in loader.discover()]
            result = validate_extension_manifests(manifests, extensions_base_path=Path(temp_dir) / "extensions")

            self.assertTrue(result.ok)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_reports_missing_frontend_forum_entry(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "frontend_forum_entry": "frontend/forum/index.js",
            }, ensure_ascii=False), encoding="utf-8")

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = [item.manifest for item in loader.discover()]
            result = validate_extension_manifests(manifests, extensions_base_path=Path(temp_dir) / "extensions")

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "missing_frontend_forum_entry" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_reports_missing_frontend_forum_export(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            forum_dir = manifest_dir / "frontend" / "forum"
            forum_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "frontend_forum_entry": "extensions/alpha-tools/frontend/forum/index.js",
            }, ensure_ascii=False), encoding="utf-8")
            (forum_dir / "index.js").write_text(
                "export const setup = null\n",
                encoding="utf-8",
            )

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = [item.manifest for item in loader.discover()]
            result = validate_extension_manifests(manifests, extensions_base_path=Path(temp_dir) / "extensions")

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "missing_frontend_forum_export" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_reports_mismatched_extension_admin_page(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "frontend_admin_entry": "extensions/alpha-tools/frontend/admin/index.js",
                "settings_pages": ["/admin/extensions/other-tools/settings"],
            }, ensure_ascii=False), encoding="utf-8")

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = [item.manifest for item in loader.discover()]
            result = validate_extension_manifests(manifests, extensions_base_path=Path(temp_dir) / "extensions")

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "invalid_extension_admin_page" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_reports_invalid_admin_actions(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "dependencies": ["core"],
                "admin_actions": [
                    {
                        "key": "broken",
                        "label": "坏动作",
                        "kind": "command",
                        "target": "/admin/extensions/alpha-tools",
                        "tone": "loud",
                    },
                    {
                        "key": "broken-route",
                        "label": "坏路由",
                        "kind": "route",
                        "target": "admin/extensions/alpha-tools",
                        "tone": "default",
                    }
                ],
            }, ensure_ascii=False), encoding="utf-8")

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = [item.manifest for item in loader.discover()]
            result = validate_extension_manifests(manifests, extensions_base_path=Path(temp_dir) / "extensions")

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "invalid_admin_action_kind" for item in result.issues))
            self.assertTrue(any(item.code == "invalid_admin_action_tone" for item in result.issues))
            self.assertTrue(any(item.code == "invalid_admin_action_target" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_reports_invalid_runtime_actions(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "runtime_actions": [
                    {
                        "key": "rebuild-cache",
                        "label": "刷新缓存",
                        "hook": "",
                    },
                    {
                        "key": "rebuild-cache",
                        "label": "",
                        "hook": "run_rebuild_cache",
                        "tone": "loud",
                    }
                ],
            }, ensure_ascii=False), encoding="utf-8")

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = [item.manifest for item in loader.discover()]
            result = validate_extension_manifests(manifests, extensions_base_path=Path(temp_dir) / "extensions")

            self.assertEqual(result.error_count, 5)
            self.assertTrue(any(item.code == "invalid_runtime_action" for item in result.issues))
            self.assertTrue(any(item.code == "duplicate_runtime_action_key" for item in result.issues))
            self.assertTrue(any(item.code == "invalid_runtime_action_tone" for item in result.issues))
            self.assertTrue(any(item.code == "missing_backend_entry_declaration" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_strict_reports_missing_runtime_backend_hook(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
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

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = [item.manifest for item in loader.discover()]
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=Path(temp_dir) / "extensions",
                strict_runtime_hooks=True,
            )

            self.assertFalse(result.ok)
            self.assertTrue(any(
                item.code == "missing_backend_hook" and "run_rebuild_cache" in item.message
                for item in result.issues
            ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_rejects_migration_namespace_field(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
                "migration_namespace": "extensions.alpha_tools.backend.migrations",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "def run_install(context):\n"
                "    return {'status': 'ok'}\n",
                encoding="utf-8",
            )

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = [item.manifest for item in loader.discover()]
            result = validate_extension_manifests(manifests, extensions_base_path=Path(temp_dir) / "extensions")

            self.assertFalse(result.ok)
            self.assertTrue(any(
                item.code == "forbidden_migration_namespace_manifest_field"
                for item in result.issues
            ))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_reports_invalid_backend_and_forbidden_migration_namespace(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            migrations_dir = backend_dir / "migrations"
            migrations_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.other_tools.backend.ext",
                "migration_namespace": "extensions.other_tools.backend.migrations",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "def run_install(context):\n"
                "    return {'status': 'ok'}\n",
                encoding="utf-8",
            )
            (migrations_dir / "0001_initial.py").write_text(
                "def apply():\n"
                "    return 'ok'\n",
                encoding="utf-8",
            )

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = [item.manifest for item in loader.discover()]
            result = validate_extension_manifests(manifests, extensions_base_path=Path(temp_dir) / "extensions")

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "invalid_backend_entry_namespace" for item in result.issues))
            self.assertTrue(any(item.code == "forbidden_migration_namespace_manifest_field" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_reports_invalid_django_app_config_namespace(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "django_app_config": "bias_core.apps.CoreConfig",
            }, ensure_ascii=False), encoding="utf-8")

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = loader.discover_manifests()
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=Path(temp_dir) / "extensions",
                public_sdk_only=True,
            )

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "invalid_django_app_config_namespace" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_rejects_django_migration_module_field(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "django_app_config": "extensions.alpha_tools.backend.apps.AlphaToolsConfig",
                "django_migration_module": "extensions.posts.backend.wrong_migrations",
            }, ensure_ascii=False), encoding="utf-8")

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = loader.discover_manifests()
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=Path(temp_dir) / "extensions",
                public_sdk_only=True,
            )

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "forbidden_django_migration_module_manifest_field" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_reports_invalid_django_app_label_contract(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "django_app_label": "alpha",
            }, ensure_ascii=False), encoding="utf-8")

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = loader.discover_manifests()
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=Path(temp_dir) / "extensions",
                public_sdk_only=True,
            )

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "django_app_label_without_app_config" for item in result.issues))

            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "django_app_config": "extensions.alpha_tools.backend.apps.AlphaToolsConfig",
                "django_app_label": "123-invalid",
            }, ensure_ascii=False), encoding="utf-8")

            manifests = loader.discover_manifests()
            result = validate_extension_manifests(manifests, extensions_base_path=Path(temp_dir) / "extensions")

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "invalid_django_app_label" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_rejects_django_app_entry_imports(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from apps.alpha_tools import signals\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = loader.discover_manifests()
            result = validate_extension_manifests(manifests, extensions_base_path=Path(temp_dir) / "extensions")

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "forbidden_django_app_entry_import" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_rejects_apps_core_root_imports(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core import signals\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = loader.discover_manifests()
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=Path(temp_dir) / "extensions",
                public_sdk_only=True,
            )

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "forbidden_core_internal_import" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_rejects_apps_core_internal_module_imports(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions.policy_runtime_service import PolicyRuntimeService\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = loader.discover_manifests()
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=Path(temp_dir) / "extensions",
                public_sdk_only=True,
            )

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "forbidden_core_internal_import" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_allows_public_sdk_facade_imports(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions.platform import set_access_token_cookie\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = loader.discover_manifests()
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=Path(temp_dir) / "extensions",
                public_sdk_only=True,
            )

            self.assertFalse(any(item.code == "forbidden_core_internal_import" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_rejects_unavailable_public_sdk_submodule_imports(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions.platform.cookies import set_access_token_cookie\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = loader.discover_manifests()
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=Path(temp_dir) / "extensions",
                public_sdk_only=True,
            )

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "forbidden_core_internal_import" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_rejects_extension_application_submodule_imports(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions.application_frontend import ApplicationRouteService\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = loader.discover_manifests()
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=Path(temp_dir) / "extensions",
                public_sdk_only=True,
            )

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "forbidden_core_internal_import" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_rejects_internal_forum_facade_imports(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            backend_dir = manifest_dir / "backend"
            backend_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (backend_dir / "ext.py").write_text(
                "from bias_core.extensions.forum import get_forum_registry\n"
                "\n"
                "def extend():\n"
                "    return []\n",
                encoding="utf-8",
            )

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = loader.discover_manifests()
            result = validate_extension_manifests_with_available_ids(
                manifests,
                available_extension_ids={"core"},
                extensions_base_path=Path(temp_dir) / "extensions",
                public_sdk_only=True,
            )

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "forbidden_core_internal_import" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_reports_legacy_migration_dir_without_files(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            migrations_dir = manifest_dir / "backend" / "migrations"
            migrations_dir.mkdir(parents=True, exist_ok=False)
            (migrations_dir / "__init__.py").write_text("", encoding="utf-8")
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (manifest_dir / "backend" / "ext.py").write_text("def extend():\n    return []\n", encoding="utf-8")

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = [item.manifest for item in loader.discover()]
            result = validate_extension_manifests(manifests, extensions_base_path=Path(temp_dir) / "extensions")

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "legacy_extension_migration_dir" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_reports_legacy_migration_dir_with_invalid_file_contract(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            migrations_dir = manifest_dir / "backend" / "migrations"
            migrations_dir.mkdir(parents=True, exist_ok=False)
            (migrations_dir / "__init__.py").write_text("", encoding="utf-8")
            (migrations_dir / "initial.py").write_text(
                "VALUE = 'missing-entrypoint'\n",
                encoding="utf-8",
            )
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "backend_entry": "extensions.alpha_tools.backend.ext",
            }, ensure_ascii=False), encoding="utf-8")
            (manifest_dir / "backend" / "ext.py").write_text("def extend():\n    return []\n", encoding="utf-8")

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = [item.manifest for item in loader.discover()]
            result = validate_extension_manifests(manifests, extensions_base_path=Path(temp_dir) / "extensions")

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "legacy_extension_migration_dir" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_reports_invalid_settings_schema(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "settings_schema": [
                    {
                        "key": "mode",
                        "label": "",
                        "type": "select",
                        "options": [],
                    },
                    {
                        "key": "mode",
                        "label": "模式",
                        "type": "json",
                    }
                ],
            }, ensure_ascii=False), encoding="utf-8")

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = [item.manifest for item in loader.discover()]
            result = validate_extension_manifests(manifests, extensions_base_path=Path(temp_dir) / "extensions")

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "duplicate_extension_setting_key" for item in result.issues))
            self.assertTrue(any(item.code == "invalid_extension_setting_type" for item in result.issues))
            self.assertTrue(any(item.code == "invalid_extension_setting_options" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_reports_invalid_ecosystem_metadata(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            (manifest_dir / "extension.json").write_text(json.dumps({
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "compatibility": {
                    "bias_version": "latest",
                    "api_version": "v1",
                    "api_stability": "ga",
                },
                "distribution": {
                    "channel": "store",
                    "signature_url": "https://example.com/signature.txt",
                    "replacement": "not a package!",
                },
                "security": {
                    "support_email": "security-at-example.com",
                },
            }, ensure_ascii=False), encoding="utf-8")

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = [item.manifest for item in loader.discover()]
            result = validate_extension_manifests(manifests, extensions_base_path=Path(temp_dir) / "extensions")

            self.assertFalse(result.ok)
            self.assertTrue(any(item.code == "invalid_bias_version_range" for item in result.issues))
            self.assertTrue(any(item.code == "invalid_api_version" for item in result.issues))
            self.assertTrue(any(item.code == "invalid_api_stability" for item in result.issues))
            self.assertTrue(any(item.code == "invalid_distribution_channel" for item in result.issues))
            self.assertTrue(any(item.code == "invalid_distribution_replacement" for item in result.issues))
            self.assertTrue(any(item.code == "invalid_security_support_email" for item in result.issues))
            self.assertTrue(any(item.code == "signature_url_without_key" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_validate_extension_manifests_checks_local_distribution_signature(self):
        temp_dir = make_workspace_temp_dir()
        try:
            manifest_dir = Path(temp_dir) / "extensions" / "alpha-tools"
            manifest_dir.mkdir(parents=True, exist_ok=False)
            manifest = {
                "id": "alpha-tools",
                "name": "Alpha Tools",
                "version": "1.0.0",
                "distribution": {
                    "channel": "private",
                    "signing_key_id": "local-dev",
                    "signature_url": "signature.txt",
                },
                "security": {
                    "capabilities_notice": "测试签名文件校验。",
                },
            }
            (manifest_dir / "extension.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

            loader = ExtensionManifestLoader(Path(temp_dir) / "extensions")
            manifests = [item.manifest for item in loader.discover()]
            result = validate_extension_manifests(manifests, extensions_base_path=Path(temp_dir) / "extensions")

            self.assertTrue(any(item.code == "missing_distribution_signature_file" for item in result.issues))

            (manifest_dir / "signature.txt").write_text("signature", encoding="utf-8")
            result = validate_extension_manifests(manifests, extensions_base_path=Path(temp_dir) / "extensions")

            self.assertFalse(any(item.code == "missing_distribution_signature_file" for item in result.issues))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)



