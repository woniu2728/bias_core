from __future__ import annotations

"""
bias_core.extensions.platform - 平台工具门面（面向扩展开发者）
"""


def _lazy_import(module_name: str, names: list[str]):
    """延迟导入，模块不存在时返回 None 占位"""
    import importlib
    try:
        mod = importlib.import_module(module_name)
        return tuple(getattr(mod, name, None) for name in names)
    except ImportError:
        return tuple(None for _ in names)


(
    AuthorizationDecision,
    AuthorizationPolicy,
    allow,
    assert_can,
    can,
    deny,
    force_allow,
    force_deny,
) = _lazy_import("bias_core.authorization", [
    "AuthorizationDecision", "AuthorizationPolicy",
    "allow", "assert_can", "can", "deny", "force_allow", "force_deny",
])

(api_error,) = _lazy_import("bias_core.api_errors", ["api_error"])

(
    ACCESS_TOKEN_COOKIE_NAME,
    ACCESS_TOKEN_COOKIE_PATH,
    REFRESH_TOKEN_COOKIE_NAME,
    REFRESH_TOKEN_COOKIE_PATH,
    AccessTokenAuth,
    access_token_max_age,
    auth_cookie_secure,
    blacklist_jwt_token,
    clear_access_token_cookie,
    clear_refresh_token_cookie,
    is_jwt_blacklisted,
    refresh_token_max_age,
    set_access_token_cookie,
    set_refresh_token_cookie,
) = _lazy_import("bias_core.jwt_auth", [
    "ACCESS_TOKEN_COOKIE_NAME", "ACCESS_TOKEN_COOKIE_PATH",
    "REFRESH_TOKEN_COOKIE_NAME", "REFRESH_TOKEN_COOKIE_PATH",
    "AccessTokenAuth", "access_token_max_age", "auth_cookie_secure",
    "blacklist_jwt_token", "clear_access_token_cookie", "clear_refresh_token_cookie",
    "is_jwt_blacklisted", "refresh_token_max_age",
    "set_access_token_cookie", "set_refresh_token_cookie",
])

(require_staff,) = _lazy_import("bias_core.admin_auth", ["require_staff"])
(AuthBearer, get_optional_user) = _lazy_import("bias_core.auth", ["AuthBearer", "get_optional_user"])
(PaginationService,) = _lazy_import("bias_core.services", ["PaginationService"])

is_debug_mode = lambda: __import__("django").conf.settings.DEBUG
get_frontend_url = lambda: str(getattr(__import__("django").conf.settings, "FRONTEND_URL", "") or "")


def get_extension_settings(extension_id: str, default: dict | None = None) -> dict:
    """获取扩展设置（占位实现，C6 完善）"""
    return default or {}


def save_extension_settings(extension_id: str, settings_dict: dict) -> None:
    """保存扩展设置（占位实现，C6 完善）"""
    pass


def log_admin_action(user, action: str, **kwargs) -> None:
    """记录管理员操作（占位实现，C6 完善）"""
    pass
