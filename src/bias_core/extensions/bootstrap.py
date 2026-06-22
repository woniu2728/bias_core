from __future__ import annotations

from django.apps import apps as django_apps
from django.db import OperationalError, ProgrammingError

from bias_core.extensions.bootstrap_state import (
    is_extension_host_bootstrapped,
    mark_extension_host_bootstrapped,
    reset_extension_host_bootstrap_state,
)
from bias_core.extensions.registry import get_extension_registry
from bias_core.extensions.site_extenders import build_site_extension, load_site_extenders


_extension_application = None
_extension_application_base_dir = ""


def get_extension_host(*, force: bool = False):
    return bootstrap_extension_host(force=force)


def get_extension_application(*, force: bool = False):
    return get_extension_host(force=force)


def clear_bootstrapped_extension_application() -> None:
    global _extension_application
    global _extension_application_base_dir
    _extension_application = None
    _extension_application_base_dir = ""


def clear_bootstrapped_extension_host() -> None:
    clear_bootstrapped_extension_application()


def reset_extension_application_bootstrap() -> None:
    reset_extension_host_bootstrap()


def reset_extension_application_bootstrap_state() -> None:
    reset_extension_host_bootstrap()


def reset_extension_host_bootstrap() -> None:
    clear_bootstrapped_extension_host()
    reset_extension_host_bootstrap_state()


def get_extension_host_bootstrap_base_dir() -> str:
    return _extension_application_base_dir


def bootstrap_extension_host(*, force: bool = False):
    global _extension_application
    global _extension_application_base_dir

    from bias_core.conf.bootstrap import get_site_config_path

    if _extension_application is not None and not force:
        return _extension_application

    if is_extension_host_bootstrapped() and not force:
        return _extension_application
    mark_extension_host_bootstrapped()

    registry = get_extension_registry()

    extension_assembly = load_site_extenders(registry)
    _extension_application = extension_assembly
    return _extension_application


def bootstrap_extension_application(*, force: bool = False):
    return bootstrap_extension_host(force=force)


def build_extension_application():
    return bootstrap_extension_host(force=True)
