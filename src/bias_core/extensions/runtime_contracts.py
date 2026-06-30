from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeFacadeContract:
    name: str
    domain: str
    provider_extension: str = ""
    stability: str = "public"
    missing_service: str = "see facade implementation"


_CORE_FACADES = (
    "get_extension_host_service",
    "get_runtime_resource_registry",
    "require_extension_host_service",
    "runtime_service_method",
)

_MODEL_FACADES = (
    "apply_runtime_model_visibility",
    "can_view_runtime_model_private",
    "can_view_runtime_private_instance",
    "evaluate_runtime_extension_policy",
    "evaluate_runtime_model_policy",
    "evaluate_runtime_query_model_policy",
    "generate_runtime_model_slug",
    "get_runtime_model_relation",
    "get_runtime_model_service",
    "get_runtime_model_url_service",
    "has_runtime_model_visibility",
    "is_runtime_model_private",
    "refresh_runtime_model_private",
    "resolve_runtime_model_relation",
    "resolve_runtime_model_slug",
    "resolve_runtime_model_slugs",
    "to_runtime_model_slug",
)

_DISCUSSION_FACADES = (
    "apply_runtime_counted_discussion_filter",
    "approve_runtime_discussion",
    "clamp_runtime_discussion_read_states",
    "count_runtime_discussion_pending_approvals",
    "create_runtime_discussion",
    "delete_runtime_discussion",
    "follow_runtime_discussion",
    "get_runtime_discussion_approval_approved",
    "get_runtime_discussion_model",
    "get_runtime_discussion_reply_notification_context",
    "get_runtime_discussion_service",
    "get_runtime_discussion_state_model",
    "get_runtime_discussion_subscription_state",
    "get_runtime_visible_discussion_ids",
    "has_runtime_discussion_visibility",
    "is_runtime_discussion_not_found",
    "list_runtime_discussion_approval_queue_items",
    "list_runtime_discussions",
    "list_runtime_pending_discussion_first_post_ids",
    "lock_runtime_discussion_for_post_number",
    "mark_runtime_discussion_read",
    "process_runtime_discussion_approval_item",
    "refresh_runtime_discussion_approved_stats",
    "reject_runtime_discussion",
    "require_runtime_discussion_service",
    "set_runtime_discussion_hidden_state",
    "set_runtime_discussion_subscription_state",
    "update_runtime_discussion",
    "validate_runtime_replyable_discussion",
)

_POST_FACADES = (
    "approve_runtime_first_post",
    "approve_runtime_post",
    "can_runtime_view_post",
    "count_runtime_post_pending_approvals",
    "create_runtime_first_post",
    "create_runtime_post",
    "create_runtime_post_event",
    "delete_runtime_discussion_posts",
    "delete_runtime_post",
    "get_runtime_approved_discussion_post_stats",
    "get_runtime_approved_reply_counts_by_author",
    "get_runtime_content_posts_service",
    "get_runtime_discussion_post_number",
    "get_runtime_discussion_posts_service",
    "get_runtime_first_post",
    "get_runtime_post_action_context",
    "get_runtime_post_approval_approved",
    "get_runtime_post_approval_pending",
    "get_runtime_post_approval_rejected",
    "get_runtime_post_by_id",
    "get_runtime_post_model",
    "get_runtime_post_model_or_none",
    "get_runtime_post_notification_context",
    "get_runtime_post_number",
    "get_runtime_post_reply_notification_context",
    "get_runtime_post_service",
    "get_runtime_visible_post_ids",
    "is_runtime_post_not_found",
    "list_runtime_post_approval_queue_items",
    "process_runtime_post_approval_item",
    "reject_runtime_first_post",
    "reject_runtime_post",
    "require_runtime_post_service",
    "resubmit_runtime_first_post",
    "resolve_runtime_discussion_post_content_html",
    "resolve_runtime_post_content_html",
    "serialize_runtime_post",
    "serialize_runtime_post_by_id",
    "serialize_runtime_realtime_post_by_id",
    "set_runtime_post_hidden_state",
    "update_runtime_first_post_content",
    "update_runtime_post",
)

_USER_FACADES = (
    "apply_runtime_user_comment_count_deltas",
    "apply_runtime_user_group_processors",
    "ensure_runtime_admin_user",
    "ensure_runtime_forum_permission",
    "ensure_runtime_user_email_confirmed",
    "ensure_runtime_user_not_suspended",
    "get_runtime_forum_permissions",
    "get_runtime_group_model",
    "get_runtime_permission_model",
    "get_runtime_user_by_id",
    "get_runtime_user_model",
    "get_runtime_user_preference",
    "get_runtime_user_preference_transformers",
    "get_runtime_user_service",
    "get_runtime_username_id_map",
    "has_runtime_forum_permission",
    "increment_runtime_user_comment_count",
    "increment_runtime_user_discussion_count",
    "list_runtime_users_by_usernames",
    "require_runtime_user_service",
    "requires_runtime_content_approval",
    "resolve_runtime_user_by_username",
    "serialize_runtime_user",
    "serialize_runtime_users_by_ids",
    "verify_runtime_user_password",
)

_TAG_FACADES = (
    "can_runtime_add_to_discussion",
    "can_runtime_reply_in_tag",
    "can_runtime_start_discussion_in_tag",
    "can_runtime_view_tag",
    "create_runtime_tag",
    "delete_runtime_tag",
    "dispatch_runtime_tag_stats_refresh",
    "ensure_can_change_runtime_discussion_tags",
    "ensure_can_start_discussion_in_runtime_tags",
    "filter_runtime_tags_for_user",
    "get_runtime_discussion_tag_model",
    "get_runtime_tag_model",
    "get_runtime_tag_scope_label",
    "get_runtime_tag_service",
    "get_runtime_tag_state_for_user",
    "get_runtime_tag_state_model",
    "get_runtime_tag_summaries_by_slugs",
    "mark_runtime_tag_read",
    "move_runtime_tag",
    "order_runtime_tags",
    "prefetch_runtime_tag_state_for_user",
    "refresh_runtime_discussion_tag_stats",
    "refresh_runtime_tag_stats",
    "require_runtime_tag_service",
    "runtime_tag_method",
    "update_runtime_tag",
    "validate_runtime_tag_parent_assignment",
    "validate_runtime_tag_scope_configuration",
)

_NOTIFICATION_FACADES = (
    "create_runtime_notification",
    "delete_runtime_discussion_reply_notifications_for_post",
    "delete_runtime_notifications",
    "delete_runtime_user_mentioned_notifications_for_post",
    "get_runtime_notification_model",
    "get_runtime_notification_service",
    "notify_runtime_notification",
    "require_runtime_notification_service",
    "sync_runtime_notifications",
)

_SEARCH_FACADES = (
    "apply_runtime_discussion_search",
    "get_runtime_search_extension_service",
    "get_runtime_search_service",
)

_MODERATION_FACADES = (
    "bulk_process_runtime_approval_items",
    "can_runtime_like_post",
    "delete_runtime_post_flags",
    "get_runtime_approval_service",
    "get_runtime_flag_service",
    "get_runtime_like_service",
    "get_runtime_post_flag_model",
    "get_runtime_post_like_model",
    "like_runtime_post",
    "list_runtime_approval_queue_items",
    "list_runtime_post_flags",
    "process_runtime_approval_item",
    "report_runtime_post_flag",
    "require_runtime_approval_service",
    "require_runtime_flag_service",
    "require_runtime_like_service",
    "resolve_runtime_post_flag",
    "resolve_runtime_post_flags",
    "unlike_runtime_post",
)

_SERVICE_FACADES = (
    "broadcast_runtime_discussion_event",
    "create_runtime_timeline_from_builder",
    "get_runtime_discussion_lifecycle_service",
    "get_runtime_formatter_service",
    "get_runtime_locale_service",
    "get_runtime_post_event_data_service",
    "get_runtime_post_lifecycle_service",
    "get_runtime_timeline_service",
    "get_runtime_view_service",
    "render_runtime_template",
)

_SYSTEM_FACADES = (
    "RuntimeHumanVerificationError",
    "RuntimeHumanVerificationUnavailableError",
    "get_runtime_human_verification_handlers",
    "verify_runtime_human_verification",
)

_FACADE_DOMAINS = {
    "core": _CORE_FACADES,
    "models": _MODEL_FACADES,
    "discussions": _DISCUSSION_FACADES,
    "posts": _POST_FACADES,
    "users": _USER_FACADES,
    "tags": _TAG_FACADES,
    "notifications": _NOTIFICATION_FACADES,
    "search": _SEARCH_FACADES,
    "moderation": _MODERATION_FACADES,
    "services": _SERVICE_FACADES,
    "system": _SYSTEM_FACADES,
}

_PROVIDER_FACADE_GROUPS = {
    "content": (
        "apply_runtime_counted_discussion_filter",
        "approve_runtime_discussion",
        "approve_runtime_first_post",
        "approve_runtime_post",
        "can_runtime_view_post",
        "clamp_runtime_discussion_read_states",
        "count_runtime_discussion_pending_approvals",
        "count_runtime_post_pending_approvals",
        "create_runtime_discussion",
        "create_runtime_first_post",
        "create_runtime_post",
        "create_runtime_post_event",
        "delete_runtime_discussion",
        "delete_runtime_discussion_posts",
        "delete_runtime_post",
        "follow_runtime_discussion",
        "get_runtime_approved_discussion_post_stats",
        "get_runtime_approved_reply_counts_by_author",
        "get_runtime_content_posts_service",
        "get_runtime_discussion_approval_approved",
        "get_runtime_discussion_model",
        "get_runtime_discussion_post_number",
        "get_runtime_discussion_posts_service",
        "get_runtime_discussion_reply_notification_context",
        "get_runtime_discussion_state_model",
        "get_runtime_discussion_subscription_state",
        "get_runtime_first_post",
        "get_runtime_post_action_context",
        "get_runtime_post_by_id",
        "get_runtime_post_model",
        "get_runtime_post_model_or_none",
        "get_runtime_post_notification_context",
        "get_runtime_post_number",
        "get_runtime_post_reply_notification_context",
        "get_runtime_visible_discussion_ids",
        "get_runtime_visible_post_ids",
        "has_runtime_discussion_visibility",
        "is_runtime_discussion_not_found",
        "is_runtime_post_not_found",
        "list_runtime_discussion_approval_queue_items",
        "list_runtime_discussions",
        "list_runtime_pending_discussion_first_post_ids",
        "list_runtime_post_approval_queue_items",
        "lock_runtime_discussion_for_post_number",
        "mark_runtime_discussion_read",
        "process_runtime_discussion_approval_item",
        "process_runtime_post_approval_item",
        "refresh_runtime_discussion_approved_stats",
        "reject_runtime_discussion",
        "reject_runtime_first_post",
        "reject_runtime_post",
        "resubmit_runtime_first_post",
        "resolve_runtime_discussion_post_content_html",
        "resolve_runtime_post_content_html",
        "serialize_runtime_post",
        "serialize_runtime_post_by_id",
        "serialize_runtime_realtime_post_by_id",
        "set_runtime_discussion_hidden_state",
        "set_runtime_discussion_subscription_state",
        "set_runtime_post_hidden_state",
        "update_runtime_discussion",
        "update_runtime_first_post_content",
        "update_runtime_post",
        "validate_runtime_replyable_discussion",
    ),
    "discussions": (
        "create_runtime_timeline_from_builder",
        "get_runtime_discussion_lifecycle_service",
        "get_runtime_discussion_service",
        "get_runtime_timeline_service",
        "require_runtime_discussion_service",
    ),
    "posts": (
        "get_runtime_post_approval_approved",
        "get_runtime_post_approval_pending",
        "get_runtime_post_approval_rejected",
        "get_runtime_post_service",
        "require_runtime_post_service",
    ),
    "users": tuple(name for name in _USER_FACADES if name != "get_runtime_user_preference_transformers"),
    "tags": _TAG_FACADES,
    "notifications": _NOTIFICATION_FACADES,
    "search": _SEARCH_FACADES,
    "likes": (
        "can_runtime_like_post",
        "get_runtime_like_service",
        "get_runtime_post_like_model",
        "like_runtime_post",
        "require_runtime_like_service",
        "unlike_runtime_post",
    ),
    "flags": (
        "delete_runtime_post_flags",
        "get_runtime_flag_service",
        "get_runtime_post_flag_model",
        "list_runtime_post_flags",
        "report_runtime_post_flag",
        "require_runtime_flag_service",
        "resolve_runtime_post_flag",
        "resolve_runtime_post_flags",
    ),
    "approval": (
        "bulk_process_runtime_approval_items",
        "get_runtime_approval_service",
        "list_runtime_approval_queue_items",
        "process_runtime_approval_item",
        "require_runtime_approval_service",
    ),
    "realtime": (
        "broadcast_runtime_discussion_event",
    ),
}


def _build_provider_index() -> dict[str, str]:
    provider_index: dict[str, str] = {}
    for provider_extension, names in _PROVIDER_FACADE_GROUPS.items():
        for name in names:
            if name in provider_index:
                raise RuntimeError(f"runtime facade provider is duplicated: {name}")
            provider_index[name] = provider_extension
    return provider_index


def _build_contracts() -> dict[str, RuntimeFacadeContract]:
    provider_index = _build_provider_index()
    contracts: dict[str, RuntimeFacadeContract] = {}
    for domain, names in _FACADE_DOMAINS.items():
        for name in names:
            if name in contracts:
                raise RuntimeError(f"runtime facade domain is duplicated: {name}")
            contracts[name] = RuntimeFacadeContract(
                name=name,
                domain=domain,
                provider_extension=provider_index.get(name, ""),
            )
    unknown_provider_facades = sorted(set(provider_index) - set(contracts))
    if unknown_provider_facades:
        names = ", ".join(unknown_provider_facades)
        raise RuntimeError(f"runtime facade providers reference unknown facades: {names}")
    return contracts


RUNTIME_FACADE_CONTRACTS = _build_contracts()
RUNTIME_FACADE_EXTENSION_DEPENDENCIES = {
    name: contract.provider_extension
    for name, contract in RUNTIME_FACADE_CONTRACTS.items()
    if contract.provider_extension
}

__all__ = [
    "RUNTIME_FACADE_CONTRACTS",
    "RUNTIME_FACADE_EXTENSION_DEPENDENCIES",
    "RuntimeFacadeContract",
]
