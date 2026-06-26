import logging

from django.apps import AppConfig


logger = logging.getLogger(__name__)


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bias_core"
    label = "core"

    def ready(self):
        from django.db.backends.signals import connection_created

        connection_created.connect(
            configure_sqlite_pragmas,
            dispatch_uid="bias_core.configure_sqlite_pragmas",
        )

        self._bootstrap_extensions()

    def _bootstrap_extensions(self):
        from bias_core.extensions.runtime_event_listeners import bootstrap_extension_runtime_event_listeners
        from bias_core.extensions.signal_bootstrap import bootstrap_extension_signal_proxies
        from bias_core.extensions.forum import get_forum_registry
        from bias_core.forum_resources import bootstrap_forum_resource_fields

        get_forum_registry()
        bootstrap_extension_runtime_event_listeners()
        bootstrap_forum_resource_fields()
        bootstrap_extension_signal_proxies()


def configure_sqlite_pragmas(sender, connection, **kwargs):
    if connection.vendor != "sqlite":
        return

    if getattr(connection, "_bias_sqlite_configured", False):
        return

    try:
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=10000;")
    except Exception:
        logger.warning("Failed to configure SQLite runtime pragmas.", exc_info=True)
        return

    connection._bias_sqlite_configured = True
