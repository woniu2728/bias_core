from __future__ import annotations

from typing import Any
from datetime import timedelta
from django.conf import settings

ACCESS_TOKEN_COOKIE_NAME = "bias_access_token"
ACCESS_TOKEN_COOKIE_PATH = "/api/"
REFRESH_TOKEN_COOKIE_NAME = "bias_refresh_token"
REFRESH_TOKEN_COOKIE_PATH = "/api/"


class AccessTokenAuth:
    def __call__(self, request) -> Any:
        return getattr(request, "auth", None)


def access_token_max_age() -> int:
    return getattr(settings, "NINJA_JWT", {}).get("ACCESS_TOKEN_LIFETIME", 900)


def refresh_token_max_age() -> int:
    return getattr(settings, "NINJA_JWT", {}).get("REFRESH_TOKEN_LIFETIME", 86400)


def auth_cookie_secure() -> bool:
    return not settings.DEBUG


def blacklist_jwt_token(token: str) -> None:
    pass


def is_jwt_blacklisted(token: str) -> bool:
    return False


def set_access_token_cookie(response, token: str) -> None:
    response.set_cookie(
        ACCESS_TOKEN_COOKIE_NAME,
        token,
        max_age=access_token_max_age(),
        path=ACCESS_TOKEN_COOKIE_PATH,
        secure=auth_cookie_secure(),
        httponly=True,
        samesite="Lax",
    )


def set_refresh_token_cookie(response, token: str) -> None:
    response.set_cookie(
        REFRESH_TOKEN_COOKIE_NAME,
        token,
        max_age=refresh_token_max_age(),
        path=REFRESH_TOKEN_COOKIE_PATH,
        secure=auth_cookie_secure(),
        httponly=True,
        samesite="Lax",
    )


def clear_access_token_cookie(response) -> None:
    response.delete_cookie(ACCESS_TOKEN_COOKIE_NAME, path=ACCESS_TOKEN_COOKIE_PATH)


def clear_refresh_token_cookie(response) -> None:
    response.delete_cookie(REFRESH_TOKEN_COOKIE_NAME, path=REFRESH_TOKEN_COOKIE_PATH)

def resolve_user_from_access_token(token: str):
    """Resolve a user from an access token (stub)."""
    from django.contrib.auth import get_user_model
    from ninja_jwt.tokens import AccessToken
    try:
        access_token = AccessToken(token)
        user_id = access_token.get("user_id")
        if user_id:
            return get_user_model().objects.get(id=user_id)
    except Exception:
        pass
    return None
