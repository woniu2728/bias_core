from __future__ import annotations

"""
bias_core.extensions.runtime - 运行时领域能力（面向扩展开发者）

提供：
- 用户、帖子、讨论、标签、通知等运行时模型访问
- 搜索、审核等运行时操作
"""


def get_runtime_user_by_id(user_id: int):
    """获取运行时用户（占位实现，需要 users 扩展可用后完善）"""
    from django.contrib.auth import get_user_model
    try:
        return get_user_model().objects.get(id=user_id)
    except Exception:
        return None


def get_runtime_user_model():
    """获取运行时用户模型（占位实现）"""
    from django.contrib.auth import get_user_model
    return get_user_model()


def get_runtime_resource_registry():
    """获取运行时资源注册表"""
    from bias_core.resources.registry import get_resource_registry
    return get_resource_registry()


def get_runtime_formatter_service():
    """获取运行时格式化服务"""
    return None


def get_runtime_locale_service():
    """获取运行时本地化服务"""
    return None


def notify_runtime_notification(user, notification_type: str, **kwargs) -> None:
    """发送运行时通知（占位实现）"""
    pass


__all__ = [
    "get_runtime_user_by_id",
    "get_runtime_user_model",
    "get_runtime_resource_registry",
    "notify_runtime_notification",
]
