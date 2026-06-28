from __future__ import annotations

from typing import Any

from bias_core.extensions.notifications import NotificationBlueprint
from bias_core.extensions.runtime_core import (
    RuntimeServiceProxy,
    get_extension_host_service,
    runtime_service_method,
)

_notification = RuntimeServiceProxy("notifications.service")


def get_runtime_notification_service(default: Any = None):
    return get_extension_host_service("notifications.service", default)


# 向后兼容
require_runtime_notification_service = get_runtime_notification_service


def get_runtime_notification_model():
    return _notification.value("model", required_message="notifications.service 未提供通知模型")


def notify_runtime_notification(method_name: str, *args, **kwargs):
    service = get_runtime_notification_service()
    if service is None:
        return None
    return runtime_service_method(service, method_name)(*args, **kwargs)


def create_runtime_notification(
    *,
    blueprint: NotificationBlueprint,
    recipient: Any,
    allow_merge: bool = True,
) -> Any:
    return notify_runtime_notification(
        "create_from_blueprint",
        blueprint=blueprint,
        recipient=recipient,
        allow_merge=allow_merge,
    )


def sync_runtime_notifications(
    *,
    blueprint: NotificationBlueprint,
    recipients: list[Any] | tuple[Any, ...],
) -> Any:
    return notify_runtime_notification(
        "sync_notifications",
        blueprint=blueprint,
        recipients=list(recipients or ()),
    )


def delete_runtime_notifications(*, blueprint: NotificationBlueprint) -> int:
    result = notify_runtime_notification("delete_matching_notifications", blueprint=blueprint)
    return int(result or 0)


def delete_runtime_discussion_reply_notifications_for_post(post_id: int) -> int:
    result = notify_runtime_notification("delete_discussion_reply_for_post", post_id)
    return int(result or 0)

