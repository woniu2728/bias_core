from __future__ import annotations

from bias_core.models import AuditLog


def log_admin_action(user, action: str, **kwargs) -> AuditLog:
    if not getattr(user, "pk", None) and getattr(user, "auth", None) is not None:
        user = user.auth
    return AuditLog.objects.create(
        user=user,
        action=action,
        target_type=kwargs.get("target_type", ""),
        target_id=kwargs.get("target_id"),
        ip_address=kwargs.get("ip_address", ""),
        user_agent=kwargs.get("user_agent", ""),
        data=kwargs.get("data", {}),
    )
