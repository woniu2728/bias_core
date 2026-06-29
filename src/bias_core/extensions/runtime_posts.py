from __future__ import annotations

from typing import Any

from bias_core.extensions.runtime_core import (
    RuntimeServiceProxy,
    get_extension_host_service,
    require_extension_host_service,
    runtime_service_method,
)

_post_service = RuntimeServiceProxy("posts.service")
_content_post_service = RuntimeServiceProxy("content.posts")
_discussion_posts_service = RuntimeServiceProxy("discussion.posts")
_realtime_post_payload_service = RuntimeServiceProxy("realtime.post_payload")


def _default_post_type() -> str:
    from bias_core.extensions.platform import get_forum_registry

    return str(get_forum_registry().get_default_post_type_code() or "comment")


def _discussion_counted_post_types() -> tuple[str, ...]:
    from bias_core.extensions.platform import get_forum_registry

    return tuple(get_forum_registry().get_discussion_counted_post_type_codes() or ())


def _user_counted_post_types() -> tuple[str, ...]:
    from bias_core.extensions.platform import get_forum_registry

    return tuple(get_forum_registry().get_user_counted_post_type_codes() or ())


def get_runtime_content_posts_service(default: Any = None):
    return get_extension_host_service("content.posts", default)


def get_runtime_post_service(default: Any = None):
    return get_extension_host_service("posts.service", default)


def require_runtime_post_service():
    content_posts = get_runtime_content_posts_service(None)
    if content_posts is not None:
        return content_posts
    return require_extension_host_service("posts.service")


def get_runtime_discussion_posts_service():
    service = get_runtime_content_posts_service(None)
    if service is not None:
        return service
    return require_extension_host_service("discussion.posts")


def _discussion_posts_method(name: str):
    content_posts = get_runtime_content_posts_service(None)
    if content_posts is not None:
        return runtime_service_method(content_posts, name)
    return _discussion_posts_service.method(name)


def get_runtime_post_model():
    content_posts = get_runtime_content_posts_service(None)
    if content_posts is not None:
        if isinstance(content_posts, dict):
            model = content_posts.get("model")
        else:
            model = getattr(content_posts, "model", None)
        if model is not None:
            return model
    return _post_service.value("model", required_message="posts.service 未提供帖子模型")


def get_runtime_post_model_or_none():
    content_posts = get_runtime_content_posts_service(None)
    if isinstance(content_posts, dict):
        model = content_posts.get("model")
        if model is not None:
            return model
    elif content_posts is not None:
        model = getattr(content_posts, "model", None)
        if model is not None:
            return model
    service = get_extension_host_service("posts.service", None)
    if isinstance(service, dict):
        return service.get("model")
    return getattr(service, "model", None)


def get_runtime_post_by_id(
    post_id: int,
    *,
    user: Any = None,
    preload=None,
    require_visible: bool = False,
    select_related: tuple[str, ...] = (),
):
    if require_visible and not select_related:
        content_posts = get_runtime_content_posts_service(None)
        if content_posts is not None:
            return runtime_service_method(content_posts, "get_by_id")(
                post_id,
                user=user,
                preload=preload,
                require_visible=True,
            )
        return _post_service.get_by_id(post_id, user, preload=preload)
    model = get_runtime_post_model()
    queryset = model.objects
    if select_related:
        queryset = queryset.select_related(*select_related)
    post = queryset.get(id=post_id)
    if require_visible and not can_runtime_view_post(post, user):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied("没有权限查看此帖子")
    return post


def can_runtime_view_post(post: Any, user: Any = None) -> bool:
    content_posts = get_runtime_content_posts_service(None)
    if content_posts is not None:
        return bool(runtime_service_method(content_posts, "can_view")(post, user))
    return bool(_post_service.can_view(post, user))


def get_runtime_visible_post_ids(user: Any = None, *, context: dict | None = None):
    content_posts = get_runtime_content_posts_service(None)
    if content_posts is not None:
        return runtime_service_method(content_posts, "get_visible_ids")(user=user, context=context or {})
    return _post_service.get_visible_ids(user=user, context=context or {})


def get_runtime_post_action_context(post_id: int, user: Any = None, *, require_visible: bool = True) -> dict | None:
    content_posts = get_runtime_content_posts_service(None)
    if content_posts is not None:
        return runtime_service_method(content_posts, "get_action_context")(
            post_id,
            user=user,
            require_visible=require_visible,
        )
    return _post_service.get_action_context(post_id, user=user, require_visible=require_visible)


def approve_runtime_post(post: Any, admin_user: Any, note: str = ""):
    content_posts = get_runtime_content_posts_service(None)
    if content_posts is not None:
        return runtime_service_method(content_posts, "approve")(
            post.id,
            admin_user,
            note=note,
            discussion_counted_post_types=_discussion_counted_post_types(),
            user_counted_post_types=_user_counted_post_types(),
        )
    return _post_service.approve(post, admin_user, note=note)


def reject_runtime_post(post: Any, admin_user: Any, note: str = ""):
    content_posts = get_runtime_content_posts_service(None)
    if content_posts is not None:
        return runtime_service_method(content_posts, "reject")(
            post.id,
            admin_user,
            note=note,
            discussion_counted_post_types=_discussion_counted_post_types(),
            user_counted_post_types=_user_counted_post_types(),
        )
    return _post_service.reject(post, admin_user, note=note)


def list_runtime_post_approval_queue_items() -> list[dict]:
    content_posts = get_runtime_content_posts_service(None)
    if content_posts is not None:
        return list(runtime_service_method(content_posts, "list_approval_queue")() or [])
    return list(_post_service.list_approval_queue() or [])


def count_runtime_post_pending_approvals() -> int:
    content_posts = get_runtime_content_posts_service(None)
    if content_posts is not None:
        return int(runtime_service_method(content_posts, "count_pending_approvals")() or 0)
    return int(_post_service.count_pending_approvals() or 0)


def process_runtime_post_approval_item(*, content_id: int, action: str, actor: Any, note: str = "") -> dict:
    content_posts = get_runtime_content_posts_service(None)
    if content_posts is not None:
        return dict(runtime_service_method(content_posts, "process_approval")(
            content_id=content_id,
            action=action,
            actor=actor,
            note=note,
        ) or {})
    return dict(_post_service.process_approval(content_id=content_id, action=action, actor=actor, note=note) or {})


def get_runtime_post_approval_approved() -> str:
    value = _content_post_service.value("approval_approved", "") if get_runtime_content_posts_service(None) is not None else ""
    if not value:
        value = _post_service.value("approval_approved", "")
    if not value:
        raise RuntimeError("posts.service 未提供已审核状态常量")
    return str(value)


def get_runtime_post_approval_pending() -> str:
    value = _content_post_service.value("approval_pending", "") if get_runtime_content_posts_service(None) is not None else ""
    if not value:
        value = _post_service.value("approval_pending", "")
    if not value:
        raise RuntimeError("posts.service 未提供待审核状态常量")
    return str(value)


def get_runtime_post_approval_rejected() -> str:
    value = _content_post_service.value("approval_rejected", "") if get_runtime_content_posts_service(None) is not None else ""
    if not value:
        value = _post_service.value("approval_rejected", "")
    if not value:
        raise RuntimeError("posts.service 未提供已拒绝状态常量")
    return str(value)


def create_runtime_post(*, discussion_id: int, content: str, user: Any, reply_to_post_id: int | None = None):
    content_posts = get_runtime_content_posts_service(None)
    if content_posts is not None:
        return runtime_service_method(content_posts, "create")(
            discussion_id=discussion_id,
            content=content,
            user=user,
            reply_to_post_id=reply_to_post_id,
            default_post_type=_default_post_type(),
            discussion_counted_post_types=_discussion_counted_post_types(),
            user_counted_post_types=_user_counted_post_types(),
        )
    return _post_service.create(
        discussion_id=discussion_id,
        content=content,
        user=user,
        reply_to_post_id=reply_to_post_id,
    )


def update_runtime_post(post_id: int, user: Any, content: str):
    content_posts = get_runtime_content_posts_service(None)
    if content_posts is not None:
        return runtime_service_method(content_posts, "update")(post_id, user, content)
    return _post_service.update(post_id, user, content)


def delete_runtime_post(post_id: int, user: Any) -> bool:
    content_posts = get_runtime_content_posts_service(None)
    if content_posts is not None:
        return bool(runtime_service_method(content_posts, "delete")(
            post_id,
            user,
            discussion_counted_post_types=_discussion_counted_post_types(),
            user_counted_post_types=_user_counted_post_types(),
        ))
    return bool(_post_service.delete(post_id, user))


def set_runtime_post_hidden_state(post: Any, user: Any, hidden: bool):
    content_posts = get_runtime_content_posts_service(None)
    if content_posts is not None:
        return runtime_service_method(content_posts, "set_hidden_state")(
            post,
            user,
            hidden,
            discussion_counted_post_types=_discussion_counted_post_types(),
            user_counted_post_types=_user_counted_post_types(),
        )
    return _post_service.set_hidden_state(post, user, hidden)


def create_runtime_first_post(**kwargs):
    return _discussion_posts_method("create_first_post")(**kwargs)


def get_runtime_first_post(discussion: Any):
    return _discussion_posts_method("get_first_post")(discussion)


def resolve_runtime_post_content_html(post: Any) -> str:
    content_posts = get_runtime_content_posts_service(None)
    if content_posts is not None:
        return str(runtime_service_method(content_posts, "resolve_content_html")(post) or "")
    return str(_post_service.resolve_content_html(post) or "")


def resolve_runtime_discussion_post_content_html(post: Any) -> str:
    return str(_discussion_posts_method("resolve_content_html")(post) or "")


def update_runtime_first_post_content(discussion: Any, *, content: str, content_html: str, editor: Any):
    return _discussion_posts_method("update_first_post_content")(
        discussion,
        content=content,
        content_html=content_html,
        editor=editor,
    )


def resubmit_runtime_first_post(discussion: Any):
    return _discussion_posts_method("resubmit_first_post")(discussion)


def approve_runtime_first_post(discussion: Any, *, approved_at: Any, approved_by: Any, note: str = ""):
    return _discussion_posts_method("approve_first_post")(
        discussion,
        approved_at=approved_at,
        approved_by=approved_by,
        note=note,
    )


def reject_runtime_first_post(discussion: Any, *, rejected_at: Any, rejected_by: Any, note: str = ""):
    return _discussion_posts_method("reject_first_post")(
        discussion,
        rejected_at=rejected_at,
        rejected_by=rejected_by,
        note=note,
    )


def get_runtime_approved_reply_counts_by_author(
    discussion: Any,
    *,
    user_counted_post_types,
) -> dict:
    return dict(_discussion_posts_method("approved_reply_counts_by_author")(
        discussion,
        user_counted_post_types=user_counted_post_types,
    ) or {})


def get_runtime_approved_discussion_post_stats(
    discussion: Any,
    *,
    discussion_counted_post_types,
) -> dict:
    return dict(_discussion_posts_method("approved_discussion_stats")(
        discussion,
        discussion_counted_post_types=discussion_counted_post_types,
    ) or {})


def delete_runtime_discussion_posts(discussion: Any) -> tuple[dict, ...]:
    return tuple(_discussion_posts_method("delete_discussion_posts")(discussion) or ())


def is_runtime_post_not_found(exc: Exception) -> bool:
    try:
        return isinstance(exc, get_runtime_post_model().DoesNotExist)
    except Exception:
        return False


def serialize_runtime_post(post: Any, user: Any = None, **kwargs) -> dict:
    return _post_service.serialize(post, user=user, **kwargs)


def serialize_runtime_post_by_id(post_id: int, user: Any = None, **kwargs) -> dict | None:
    return _post_service.serialize_by_id(post_id, user=user, **kwargs)


def serialize_runtime_realtime_post_by_id(post_id: int, user: Any = None, **kwargs) -> dict | None:
    return _realtime_post_payload_service.serialize_by_id(post_id, user=user, **kwargs)


def create_runtime_post_event(**kwargs):
    content_posts = get_runtime_content_posts_service(None)
    if content_posts is not None:
        return runtime_service_method(content_posts, "create_event_post")(**kwargs)
    return _post_service.create_event_post(**kwargs)


def get_runtime_post_reply_notification_context(reply_to_post_id: int, post_id: int, from_user: Any):
    content_posts = get_runtime_content_posts_service(None)
    if content_posts is not None:
        return runtime_service_method(content_posts, "reply_notification_context")(reply_to_post_id, post_id, from_user)
    return _post_service.reply_notification_context(reply_to_post_id, post_id, from_user)


def get_runtime_post_notification_context(post_id: int):
    content_posts = get_runtime_content_posts_service(None)
    if content_posts is not None:
        return runtime_service_method(content_posts, "notification_context")(post_id)
    return _post_service.notification_context(post_id)


def get_runtime_post_number(post_id: int):
    return _post_service.get_number(post_id)


def get_runtime_discussion_post_number(post_id: int):
    return _discussion_posts_method("get_post_number")(post_id)

