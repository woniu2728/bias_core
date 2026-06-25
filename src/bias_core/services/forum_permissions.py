from __future__ import annotations


def has_forum_permission(user, permission_code: str) -> bool:
    if user is None:
        return False
    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        return True
    return True

def clear_forum_permission_checkers():
    pass
