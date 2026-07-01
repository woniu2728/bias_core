from __future__ import annotations

import os

from ninja import NinjaAPI, Router

from bias_core.version import APP_VERSION


_api_namespace_counter = 0


def next_api_urls_namespace() -> str:
    global _api_namespace_counter
    _api_namespace_counter += 1
    return f"bias-api-{_api_namespace_counter}"


def build_api_application(*, extension_host=None, urls_namespace: str | None = None) -> NinjaAPI:
    api = NinjaAPI(
        title="Bias API",
        version=APP_VERSION,
        description="Bias forum RESTful API",
        docs_url="/docs",
        csrf=True,
        urls_namespace=urls_namespace or next_api_urls_namespace(),
    )

    _register_admin_routes(api)
    _register_extension_routes(api, extension_host=extension_host)
    _register_resource_routes(api, extension_host=extension_host)
    _register_core_routes(api)
    _register_frontend_manifest_route(api)
    _register_health_route(api)
    return api


def _register_core_routes(api: NinjaAPI) -> None:
    from bias_core.api.api import router as core_router
    _add_router_once(api, "", core_router, tags=["System"])


def _register_admin_routes(api: NinjaAPI) -> None:
    try:
        from bias_core.admin_api import router as admin_router
        _add_router_once(api, "/admin", admin_router, tags=["Admin"])
    except Exception:
        pass


def _register_resource_routes(api: NinjaAPI, *, extension_host=None) -> None:
    try:
        from bias_core.resource_routes import build_resource_endpoint_router
        from bias_core.resource_registry import get_resource_registry
        from bias_core.resource_runtime_api import router as legacy_resource_router

        registry = getattr(extension_host, "resources", None) if extension_host is not None else None
        if registry is None:
            registry = get_resource_registry()
        resource_router = build_resource_endpoint_router(registry)
        _add_router_once(api, "", resource_router, tags=["Resources"])
        _add_router_once(api, "", legacy_resource_router, tags=["Resources"])
    except Exception:
        pass


def _register_frontend_manifest_route(api: NinjaAPI) -> None:
    @api.get("/frontend/manifest", tags=["System"], response={200: dict})
    def frontend_manifest(request):
        from bias_core.extensions.frontend_runtime_service import build_frontend_manifest
        manifest = build_frontend_manifest()
        return manifest


def _register_extension_routes(api: NinjaAPI, *, extension_host=None) -> None:
    if extension_host is None:
        return

    try:
        routes = extension_host.make("routes")
        for mount in routes.get_mounts():
            _add_router_once(api, mount.prefix, mount.router, tags=list(mount.tags))
        for route in routes.get_routes(app_name="api"):
            _register_named_route(api, route)
    except (AttributeError, Exception):
        pass


def _register_health_route(api: NinjaAPI) -> None:
    @api.get("/health", tags=["System"], response={200: dict, 503: dict})
    def health_check(request, strict: bool = False):
        from bias_core.health import collect_health_status, health_status_code, strict_health_failed

        payload = collect_health_status()
        app = payload["checks"]["app"]
        strict_enabled = bool(strict) or str(os.getenv("BIAS_HEALTH_STRICT") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        response_payload = {
            **payload,
            "message": "Bias API is running",
            "state": app["state"],
            "current_version": app["current_version"],
            "installed_version": app["installed_version"],
            "strict": strict_enabled,
            "strict_failed": strict_health_failed(payload) if strict_enabled else False,
        }
        return health_status_code(payload, strict=strict_enabled), response_payload


def _add_router_once(api: NinjaAPI, prefix, router, *, tags=None) -> None:
    if getattr(router, "api", None) is api:
        return
    if getattr(router, "api", None) is not None:
        _detach_router_from_api(router)
    api.add_router(prefix, router, tags=tags or [])


def _register_named_route(api: NinjaAPI, route) -> None:
    method = str(getattr(route, "method", "GET") or "GET").strip().upper()
    path = str(getattr(route, "path", "") or "").strip()
    handler = getattr(route, "handler", None)
    if not path or handler is None:
        return
    router = Router()
    tags = list(getattr(route, "tags", ()) or ())
    operation_id = str(getattr(route, "name", "") or "").strip().replace(".", "_").replace("-", "_")

    decorator = {
        "DELETE": router.delete,
        "PATCH": router.patch,
        "POST": router.post,
        "PUT": router.put,
    }.get(method, router.get)
    kwargs = {"tags": tags} if tags else {}
    if operation_id:
        kwargs["operation_id"] = operation_id
    decorator("", **kwargs)(handler)
    _add_router_once(api, path, router, tags=tags)


def _detach_router_from_api(router) -> None:
    router.api = None
    for path_view in getattr(router, "path_operations", {}).values():
        path_view.api = None
        for operation in getattr(path_view, "operations", ()):
            operation.api = None
    for _prefix, child in getattr(router, "_routers", ()):
        _detach_router_from_api(child)

