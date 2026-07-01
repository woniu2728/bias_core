from __future__ import annotations

import os
import sys

from django.core.checks import Critical, run_checks
from django.core.exceptions import ImproperlyConfigured


STARTUP_GUARD_EXEMPT_COMMANDS = {
    "create_extension",
    "inspect_extensions",
    "validate_extensions",
}


def should_enforce_startup_guard(argv: list[str]) -> bool:
    if len(argv) < 2:
        return True
    return argv[1] not in STARTUP_GUARD_EXEMPT_COMMANDS


def run_django_management_with_startup_guard(argv: list[str] | None = None) -> None:
    argv = argv or sys.argv

    import django

    django.setup()
    if should_enforce_startup_guard(argv):
        enforce_production_runtime_checks()

    from django.core.management import execute_from_command_line

    execute_from_command_line(argv)


def enforce_celery_runtime_checks() -> None:
    enforce_production_runtime_checks()


def enforce_production_runtime_checks() -> None:
    from bias_core.runtime_checks import PRODUCTION_RUNTIME_CHECK_TAG, is_production_runtime

    if not is_production_runtime():
        return

    messages = run_checks(tags=[PRODUCTION_RUNTIME_CHECK_TAG])
    criticals = [message for message in messages if isinstance(message, Critical)]
    if os.getenv("BIAS_INSTALLING") == "1":
        criticals = [
            message
            for message in criticals
            if message.id != "bias.email-backend-development-production"
        ]
    if not criticals:
        return

    lines = ["Bias 生产启动自检失败，已拒绝启动："]
    for message in criticals:
        entry = f"- [{message.id}] {message.msg}"
        if message.hint:
            entry += f"  建议：{message.hint}"
        lines.append(entry)

    raise ImproperlyConfigured("\n".join(lines))
