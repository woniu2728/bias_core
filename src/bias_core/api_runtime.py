from __future__ import annotations

from ninja import NinjaAPI, Router

from bias_core.runtime_state import get_runtime_status
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

    _register_core_routes(api)
    _register_admin_routes(api)
    _register_resource_routes(api)
    _register_frontend_manifest_route(api)
    _register_health_route(api)
    _register_extension_routes(api, extension_host=extension_host)
    return api


def _register_core_routes(api: NinjaAPI) -> None:
    from bias_core.api import router as core_router
    _add_router_once(api, "", core_router, tags=["System"])


def _register_admin_routes(api: NinjaAPI) -> None:
    try:
        from bias_core.admin_api import router as admin_router
        _add_router_once(api, "/admin", admin_router, tags=["Admin"])
    except ImportError:
        pass


def _register_resource_routes(api: NinjaAPI) -> None:
    try:
        from bias_core.resource_routes import build_resource_endpoint_router
        from bias_core.resource_registry import get_resource_registry
        registry = get_resource_registry()
        resource_router = build_resource_endpoint_router(registry)
        _add_router_once(api, "", resource_router, tags=["Resources"])
    except ImportError:
        pass


def _register_frontend_manifest_route(api: NinjaAPI) -> None:
    @api.get("/frontend/manifest", tags=["System"], response={200: dict})
    def frontend_manifest(request):
        from bias_core.extensions.frontend_runtime_service import build_frontend_manifest
        manifest = build_frontend_manifest()
        return manifest


def _register_extension_routes(api: NinjaAPI, *, extension_host=None) -> None:
    """Register routes from installed extensions.

    Discovers extensions via entry points when no extension_host is provided.
    """
    host = extension_host
    if host is None:
        try:
            from bias_core.extensions.bootstrap import get_extension_host
            host = get_extension_host()
        except (ImportError, Exception):
            pass

    if host is not None:
        try:
            routes = host.make("routes")
            for mount in routes.get_mounts():
                _add_router_once(api, mount.prefix, mount.router, tags=list(mount.tags))
            return
        except (AttributeError, Exception):
            pass

    # Fallback: discover extension routes directly from entry points
    _discover_extension_routes(api)


def _discover_extension_routes(api: NinjaAPI) -> None:
    """Scan bias.extensions entry points and mount their API routes."""
    import importlib.metadata
    try:
        for ep in importlib.metadata.entry_points(group="bias.extensions"):
            ext_name = ep.name
            try:
                mod = importlib.import_module(f"bias_ext_{ext_name}.backend.api")
                router = getattr(mod, "router", None)
                if router is not None:
                    _add_router_once(api, f"/{ext_name}", router, tags=[ext_name.title()])
            except (ImportError, ModuleNotFoundError, AttributeError, Exception):
                pass
            try:
                mod = importlib.import_module(f"bias_ext_{ext_name}.backend.admin_api")
                router = getattr(mod, "router", None)
                if router is not None:
                    _add_router_once(api, "/admin", router, tags=[ext_name.title()])
            except (ImportError, ModuleNotFoundError, AttributeError, Exception):
                pass
    except Exception:
        pass


def _register_health_route(api: NinjaAPI) -> None:
    @api.get("/health", tags=["System"])
    def health_check(request):
        runtime = get_runtime_status()
        return {
            "status": "ok" if runtime.state in ("ready", "starting") else "degraded",
            "message": "Bias API is running",
            "state": runtime.state,
            "current_version": runtime.current_version,
            "installed_version": runtime.installed_version,
        }


def _add_router_once(api: NinjaAPI, prefix, router, *, tags=None) -> None:
    if getattr(router, "api", None) is api:
        return
    if getattr(router, "api", None) is not None:
        _detach_router_from_api(router)
    api.add_router(prefix, router, tags=tags or [])


def _detach_router_from_api(router) -> None:
    router.api = None
    for path_view in getattr(router, "path_operations", {}).values():
        path_view.api = None
        for operation in getattr(path_view, "operations", ()):
            operation.api = None
    for _prefix, child in getattr(router, "_routers", ()):
        _detach_router_from_api(child)