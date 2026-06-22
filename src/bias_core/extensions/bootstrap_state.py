from __future__ import annotations

_extension_host_bootstrapped = False


def is_extension_host_bootstrapped() -> bool:
    global _extension_host_bootstrapped
    return _extension_host_bootstrapped


def mark_extension_host_bootstrapped() -> None:
    global _extension_host_bootstrapped
    _extension_host_bootstrapped = True


def reset_extension_host_bootstrap_state() -> None:
    global _extension_host_bootstrapped
    _extension_host_bootstrapped = False


def reset_extension_application_bootstrap_state() -> None:
    reset_extension_host_bootstrap_state()


def mark_extension_application_bootstrapped() -> None:
    mark_extension_host_bootstrapped()


def is_extension_application_bootstrapped() -> bool:
    return is_extension_host_bootstrapped()
