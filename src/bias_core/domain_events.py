from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class DomainEvent:
    event_type: str
    data: dict = field(default_factory=dict)


class DomainEventBus:
    _listeners: dict[str, list[Callable]] = {}

    @classmethod
    def register(cls, event_type: str, listener: Callable) -> None:
        if event_type not in cls._listeners:
            cls._listeners[event_type] = []
        cls._listeners[event_type].append(listener)

    @classmethod
    def dispatch(cls, event: DomainEvent) -> None:
        for listener in cls._listeners.get(event.event_type, []):
            listener(event)


def get_forum_event_bus() -> DomainEventBus:
    return DomainEventBus


def dispatch_forum_event_after_commit(event_type: str, **kwargs) -> None:
    DomainEventBus.dispatch(DomainEvent(event_type=event_type, data=kwargs))
