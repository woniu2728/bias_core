from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeServiceContract:
    service_key: str
    provider_extension: str
    required_methods: tuple[str, ...] = ()
    required_values: tuple[str, ...] = ()
    optional_methods: tuple[str, ...] = ()


RUNTIME_SERVICE_CONTRACTS = {
    "content.discussions": RuntimeServiceContract(
        service_key="content.discussions",
        provider_extension="content",
        required_values=(
            "approval_approved",
            "model",
            "state_model",
        ),
        required_methods=(
            "apply_counted_filter",
            "approve",
            "clamp_read_states",
            "count_pending_approvals",
            "create",
            "delete",
            "follow_if_enabled",
            "get_visible_ids",
            "has_visibility",
            "is_subscribed",
            "list",
            "list_approval_queue",
            "lock_for_post_number",
            "mark_read",
            "pending_first_post_ids",
            "process_approval",
            "refresh_approved_stats",
            "reject",
            "reply_notification_context",
            "set_hidden_state",
            "set_subscription",
            "update",
            "validate_replyable",
        ),
        optional_methods=(
            "serialize",
            "serialize_by_id",
        ),
    ),
    "content.posts": RuntimeServiceContract(
        service_key="content.posts",
        provider_extension="content",
        required_values=(
            "approval_approved",
            "approval_pending",
            "approval_rejected",
            "model",
        ),
        required_methods=(
            "approve",
            "approved_discussion_stats",
            "approved_reply_counts_by_author",
            "can_view",
            "count_pending_approvals",
            "create",
            "create_event_post",
            "create_first_post",
            "delete",
            "delete_discussion_posts",
            "get_action_context",
            "get_by_id",
            "get_first_post",
            "get_post_number",
            "get_visible_ids",
            "list_approval_queue",
            "process_approval",
            "reject",
            "reject_first_post",
            "reply_notification_context",
            "resolve_content_html",
            "resubmit_first_post",
            "serialize",
            "serialize_by_id",
            "set_hidden_state",
            "update",
            "update_first_post_content",
        ),
    ),
    "discussion.posts": RuntimeServiceContract(
        service_key="discussion.posts",
        provider_extension="content",
        required_methods=(
            "approve_first_post",
            "approved_discussion_stats",
            "approved_reply_counts_by_author",
            "create_first_post",
            "delete_discussion_posts",
            "get_first_post",
            "get_post_number",
            "reject_first_post",
            "resolve_content_html",
            "resubmit_first_post",
            "update_first_post_content",
        ),
    ),
    "discussions.service": RuntimeServiceContract(
        service_key="discussions.service",
        provider_extension="discussions",
        required_values=(
            "approval_approved",
            "model",
            "state_model",
        ),
        required_methods=(
            "apply_counted_filter",
            "approve",
            "clamp_read_states",
            "count_pending_approvals",
            "create",
            "delete",
            "follow_if_enabled",
            "get_visible_ids",
            "has_visibility",
            "is_subscribed",
            "list",
            "list_approval_queue",
            "lock_for_post_number",
            "mark_read",
            "pending_first_post_ids",
            "process_approval",
            "refresh_approved_stats",
            "reject",
            "reply_notification_context",
            "set_hidden_state",
            "set_subscription",
            "update",
            "validate_replyable",
        ),
    ),
    "posts.service": RuntimeServiceContract(
        service_key="posts.service",
        provider_extension="posts",
        required_values=(
            "approval_approved",
            "approval_pending",
            "approval_rejected",
            "model",
        ),
        required_methods=(
            "approve",
            "can_view",
            "count_pending_approvals",
            "create",
            "create_event_post",
            "delete",
            "get_action_context",
            "get_by_id",
            "get_number",
            "get_visible_ids",
            "list_approval_queue",
            "notification_context",
            "process_approval",
            "reject",
            "reply_notification_context",
            "resolve_content_html",
            "serialize",
            "serialize_by_id",
            "set_hidden_state",
            "update",
        ),
    ),
    "users.service": RuntimeServiceContract(
        service_key="users.service",
        provider_extension="users",
        required_values=(
            "group_model",
            "model",
            "permission_model",
        ),
        required_methods=(
            "apply_comment_count_deltas",
            "ensure_admin",
            "ensure_email_confirmed",
            "ensure_forum_permission",
            "ensure_not_suspended",
            "get_by_id",
            "get_by_username",
            "get_forum_permissions",
            "get_preference",
            "increment_comment_count",
            "increment_discussion_count",
            "list_by_usernames",
            "requires_content_approval",
            "serialize_many_by_ids",
            "username_id_map",
        ),
    ),
    "tags.service": RuntimeServiceContract(
        service_key="tags.service",
        provider_extension="tags",
        required_values=(
            "model",
            "relationship_model",
            "state_model",
        ),
        required_methods=(
            "can_add_to_discussion",
            "can_reply_in_tag",
            "can_start_discussion_in_tag",
            "can_view_tag",
            "create_tag",
            "delete_tag",
            "dispatch_refresh_tag_stats",
            "ensure_can_change_discussion_tags",
            "ensure_can_start_discussion",
            "filter_tags_for_user",
            "get_scope_label",
            "mark_tag_read",
            "move_tag",
            "order_tags",
            "prefetch_state_for_user",
            "refresh_discussion_tag_stats",
            "refresh_tag_stats",
            "state_for_user",
            "summaries_by_slugs",
            "update_tag",
            "validate_parent_assignment",
            "validate_scope_configuration",
        ),
    ),
}


def get_runtime_service_contracts(*, provider_extension: str | None = None) -> tuple[RuntimeServiceContract, ...]:
    normalized_provider = str(provider_extension or "").strip()
    contracts = tuple(
        RUNTIME_SERVICE_CONTRACTS[key]
        for key in sorted(RUNTIME_SERVICE_CONTRACTS)
    )
    if not normalized_provider:
        return contracts
    return tuple(
        contract
        for contract in contracts
        if contract.provider_extension == normalized_provider
    )


def inspect_runtime_service_contracts(host: Any, *, provider_extension: str | None = None) -> list[dict]:
    issues: list[dict] = []
    if host is None:
        return issues
    for contract in get_runtime_service_contracts(provider_extension=provider_extension):
        if not _host_provider_registered(host, contract):
            issues.append(_issue(contract, "missing_provider_registration", contract.service_key))
        service = _resolve_host_service(host, contract.service_key)
        if service is None:
            issues.append(_issue(contract, "missing_service", contract.service_key))
            continue
        for name in contract.required_values:
            if _service_value(service, name, _MISSING) is _MISSING:
                issues.append(_issue(contract, "missing_value", name))
        for name in contract.required_methods:
            if not callable(_service_value(service, name, None)):
                issues.append(_issue(contract, "missing_method", name))
    return issues


def snapshot_runtime_service_contracts() -> list[dict]:
    return [
        {
            "service_key": contract.service_key,
            "provider_extension": contract.provider_extension,
            "required_methods": sorted(contract.required_methods),
            "required_values": sorted(contract.required_values),
            "optional_methods": sorted(contract.optional_methods),
        }
        for contract in get_runtime_service_contracts()
    ]


def _resolve_host_service(host: Any, key: str):
    getter = getattr(host, "make", None) or getattr(host, "get_service", None)
    if not callable(getter):
        return None
    try:
        return getter(key, None)
    except TypeError:
        try:
            return getter(key)
        except (KeyError, TypeError):
            return None
    except KeyError:
        return None


def _host_provider_registered(host: Any, contract: RuntimeServiceContract) -> bool:
    getter = getattr(host, "get_service_provider_keys", None)
    if not callable(getter):
        return True
    try:
        keys = getter(extension_id=contract.provider_extension)
    except TypeError:
        return True
    return contract.service_key in {str(item or "").strip() for item in keys or ()}


def _service_value(service: Any, name: str, default: Any = None):
    if isinstance(service, dict):
        return service.get(name, default)
    return getattr(service, name, default)


def _issue(contract: RuntimeServiceContract, code: str, member: str) -> dict:
    return {
        "code": code,
        "service_key": contract.service_key,
        "provider_extension": contract.provider_extension,
        "member": member,
    }


def _validate_runtime_service_contracts() -> None:
    for service_key, contract in RUNTIME_SERVICE_CONTRACTS.items():
        if service_key != contract.service_key:
            raise RuntimeError(f"runtime service contract key mismatch: {service_key} != {contract.service_key}")
        if not contract.provider_extension:
            raise RuntimeError(f"runtime service contract is missing provider extension: {service_key}")
        for field in ("required_methods", "required_values", "optional_methods"):
            values = tuple(getattr(contract, field))
            normalized_values = tuple(str(item or "").strip() for item in values)
            if values != normalized_values:
                raise RuntimeError(f"runtime service contract {service_key}.{field} contains unnormalized names")
            if any(not item for item in normalized_values):
                raise RuntimeError(f"runtime service contract {service_key}.{field} contains empty names")
            if tuple(sorted(normalized_values)) != normalized_values:
                raise RuntimeError(f"runtime service contract {service_key}.{field} must be sorted")
            if len(set(normalized_values)) != len(normalized_values):
                raise RuntimeError(f"runtime service contract {service_key}.{field} contains duplicate names")
        overlap = set(contract.required_methods) & set(contract.optional_methods)
        if overlap:
            names = ", ".join(sorted(overlap))
            raise RuntimeError(f"runtime service contract {service_key} has required/optional overlap: {names}")


_MISSING = object()


_validate_runtime_service_contracts()


__all__ = [
    "RUNTIME_SERVICE_CONTRACTS",
    "RuntimeServiceContract",
    "get_runtime_service_contracts",
    "inspect_runtime_service_contracts",
    "snapshot_runtime_service_contracts",
]
