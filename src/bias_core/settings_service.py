from __future__ import annotations

from bias_core.models import Setting
from typing import Any


class SettingsService:
    @staticmethod
    def get(key: str, default: Any = None) -> Any:
        try:
            setting = Setting.objects.get(key=key)
            return setting.value
        except Setting.DoesNotExist:
            return default

    @staticmethod
    def set(key: str, value: str) -> None:
        Setting.objects.update_or_create(key=key, defaults={"value": str(value)})

    @staticmethod
    def get_int(key: str, default: int = 0) -> int:
        val = SettingsService.get(key)
        if val is None:
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def get_bool(key: str, default: bool = False) -> bool:
        val = SettingsService.get(key)
        if val is None:
            return default
        return str(val).lower() in {"1", "true", "yes", "on"}


def get_setting_value(key: str, default: Any = None) -> Any:
    return SettingsService.get(key, default)


def set_setting_value(key: str, value: str) -> None:
    SettingsService.set(key, value)


def get_advanced_settings() -> dict:
    return {}


def get_setting_group(key: str) -> dict:
    return {}


def get_advanced_settings_defaults() -> dict:
    return {}
