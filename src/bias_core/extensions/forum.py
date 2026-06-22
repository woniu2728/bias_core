from __future__ import annotations

"""
bias_core.extensions.forum - 论坛宿主能力门面（面向扩展开发者）

提供：
- 论坛注册表访问
- 实时广播
- 在线用户
"""


def get_forum_registry():
    """获取论坛注册表（占位实现，需要 forum_registry 模块完善）"""
    from bias_core.extensions.forum_registry import get_forum_registry as _get
    return _get()


def broadcast_realtime_discussion_event(event_type: str, discussion_id: int, **kwargs) -> None:
    """广播实时讨论事件（占位实现，C7 完善）"""
    pass


__all__ = [
    "get_forum_registry",
    "broadcast_realtime_discussion_event",
]
