from __future__ import annotations

from typing import Any

from ninja.errors import HttpError


def require_staff(request) -> Any:
    user = getattr(request, "auth", None)
    if user is None or not getattr(user, "is_staff", False):
        return HttpError(403, {"detail": "Staff access required"})
    return None
