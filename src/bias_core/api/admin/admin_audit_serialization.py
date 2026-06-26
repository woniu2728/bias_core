from __future__ import annotations

from bias_core.models import AuditLog


def serialize_audit_log(log: AuditLog) -> dict:
    user = log.user
    return {
        "id": log.id,
        "action": log.action,
        "target_type": log.target_type,
        "target_id": log.target_id,
        "ip_address": log.ip_address,
        "user_agent": log.user_agent,
        "data": log.data,
        "created_at": log.created_at,
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": getattr(user, "display_name", "") or user.get_username(),
        } if user else None,
    }
