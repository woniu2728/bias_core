from __future__ import annotations

from django.db import transaction

from bias_core.services import domain_events as _domain_events

DomainEvent = _domain_events.DomainEvent
DomainEventBus = _domain_events.DomainEventBus
DomainEventHandler = _domain_events.DomainEventHandler


def __getattr__(name):
    return getattr(_domain_events, name)


def get_forum_event_bus():
    return _domain_events.get_forum_event_bus()


def get_runtime_forum_event_bus():
    try:
        from bias_core.extensions.bootstrap import get_extension_host

        host = get_extension_host()
        event_bus = getattr(host, "event_bus", None) if host is not None else None
        if event_bus is not None:
            return event_bus
    except Exception:
        pass
    return get_forum_event_bus()


def dispatch_forum_event_after_commit(event: DomainEvent) -> None:
    transaction.on_commit(lambda: get_runtime_forum_event_bus().dispatch(event))
