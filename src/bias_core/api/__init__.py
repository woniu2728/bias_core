"""
bias_core.api — API application builders and routers.

Usage:
    from bias_core.api.runtime import build_api_application
"""
from bias_core.api_runtime import build_api_application, _add_router_once  # noqa: F401
from bias_core.api_main import router as core_router  # noqa: F401
