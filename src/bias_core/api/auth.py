from __future__ import annotations

import re
from typing import Any

from ninja.security import HttpBearer
from django.http import HttpRequest


class AuthBearer(HttpBearer):
    def authenticate(self, request: HttpRequest, token: str) -> Any:
        return token


def get_optional_user(request) -> Any:
    if hasattr(request, "auth") and request.auth:
        return request.auth
    try:
        from bias_core.api.jwt_auth import resolve_authenticated_user

        return resolve_authenticated_user(request)
    except Exception:
        return None
