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


def dispatch_forum_event_after_commit(event: DomainEvent) -> None:
    transaction.on_commit(lambda: get_forum_event_bus().dispatch(event))
