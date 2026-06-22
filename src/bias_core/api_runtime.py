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
    _register_health_route(api)
    return api


def _register_core_routes(api: NinjaAPI) -> None:
    from bias_core.api import router as core_router
    _add_router_once(api, "", core_router, tags=["System"])


def _register_health_route(api: NinjaAPI) -> None:
    @api.get("/health", tags=["System"])
    def health_check(request):
        runtime = get_runtime_status()
        return {
            "status": "ok" if runtime.state == "ready" else "degraded",
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
