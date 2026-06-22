from __future__ import annotations

from typing import Any

from ninja.errors import HttpError


def api_error(message: str, status: int = 400, code: str = "error") -> HttpError:
    return HttpError(status, {"detail": message, "code": code})
