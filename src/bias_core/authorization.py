from __future__ import annotations

from typing import Any


class AuthorizationDecision:
    allow: bool
    reason: str = ""

    def __init__(self, allow: bool, reason: str = ""):
        self.allow = allow
        self.reason = reason


class AuthorizationPolicy:
    name: str = ""
    priority: int = 0

    def authorize(self, request, permission: str, **kwargs) -> AuthorizationDecision:
        return AuthorizationDecision(False)


def allow(reason: str = "") -> AuthorizationDecision:
    return AuthorizationDecision(True, reason)


def deny(reason: str = "") -> AuthorizationDecision:
    return AuthorizationDecision(False, reason)


def force_allow(reason: str = "") -> AuthorizationDecision:
    return AuthorizationDecision(True, reason)


def force_deny(reason: str = "") -> AuthorizationDecision:
    return AuthorizationDecision(False, reason)


def can(request, permission: str, **kwargs) -> bool:
    return True


def assert_can(request, permission: str, **kwargs) -> None:
    pass
