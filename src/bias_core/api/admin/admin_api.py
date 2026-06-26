"""管理后台 API 路由聚合。"""
from ninja import Router


router = Router()


def _add_optional_router(import_path: str) -> None:
    module_name, attr_name = import_path.rsplit(".", 1)
    try:
        module = __import__(module_name, fromlist=[attr_name])
        child_router = getattr(module, attr_name)
    except Exception:
        return
    router.add_router("", child_router)


_add_optional_router("bias_core.api.admin.admin_audit_api.router")
_add_optional_router("bias_core.api.admin.admin_content_api.router")
_add_optional_router("bias_core.api.admin.admin_extension_recovery_api.router")
_add_optional_router("bias_core.api.admin.admin_settings_api.router")
_add_optional_router("bias_core.api.admin.admin_stats_api.router")


