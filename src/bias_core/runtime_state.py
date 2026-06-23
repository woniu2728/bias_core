from __future__ import annotations

import sys
from enum import Enum

from bias_core.version import APP_VERSION


class RuntimeState(str, Enum):
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"
    MAINTENANCE = "maintenance"


class RuntimeStatus:
    def __init__(self) -> None:
        self._state: RuntimeState = RuntimeState.STARTING
        self._current_version: str = APP_VERSION
        self._installed_version: str = APP_VERSION
        self._errors: list[str] = []

    @property
    def state(self) -> RuntimeState:
        return self._state

    @state.setter
    def state(self, value: RuntimeState) -> None:
        self._state = value

    @property
    def current_version(self) -> str:
        return self._current_version

    @current_version.setter
    def current_version(self, value: str) -> None:
        self._current_version = value

    @property
    def installed_version(self) -> str:
        return self._installed_version

    @installed_version.setter
    def installed_version(self, value: str) -> None:
        self._installed_version = value

    @property
    def errors(self) -> list[str]:
        return self._errors

    def add_error(self, error: str) -> None:
        self._errors.append(error)


_runtime_status: RuntimeStatus | None = None


def get_runtime_status() -> RuntimeStatus:
    global _runtime_status
    if _runtime_status is None:
        _runtime_status = RuntimeStatus()
    return _runtime_status


def clear_runtime_status_cache() -> None:
    global _runtime_status
    _runtime_status = None
