from __future__ import annotations

from collections import defaultdict
from typing import Callable, DefaultDict, List, TypeVar
from django.db import transaction

class DomainEvent:
    """Base type for in-process domain events."""


EventT = TypeVar("EventT", bound=DomainEvent)
DomainEventHandler = Callable[[EventT], None]


class DomainEventBus:
    def __init__(self):
        self._listeners: DefaultDict[type[DomainEvent], List[DomainEventHandler]] = defaultdict(list)
        self._listener_keys: DefaultDict[type[DomainEvent], set[str]] = defaultdict(set)
        self._listener_key_handlers: DefaultDict[type[DomainEvent], dict[str, DomainEventHandler]] = defaultdict(dict)
        self._bootstrapping_extensions = False

    def register(
        self,
        event_type: type[EventT],
        handler: DomainEventHandler[EventT],
        *,
        listener_key: object = None,
        replace: bool = False,
    ) -> None:
        listeners = self._listeners[event_type]
        if listener_key is not None:
            normalized_key = str(listener_key)
            if normalized_key in self._listener_keys[event_type]:
                if not replace:
                    return
                previous = self._listener_key_handlers[event_type].get(normalized_key)
                if previous in listeners:
                    listeners.remove(previous)
            self._listener_keys[event_type].add(normalized_key)
            self._listener_key_handlers[event_type][normalized_key] = handler
        if handler not in listeners:
            listeners.append(handler)

    def clear(self) -> None:
        self._listeners.clear()
        self._listener_keys.clear()
        self._listener_key_handlers.clear()

    def dispatch(self, event: DomainEvent) -> None:
        self._ensure_extension_listeners_bootstrapped()
        for event_type, handlers in list(self._listeners.items()):
            if isinstance(event, event_type):
                for handler in list(handlers):
                    handler(event)

    def _ensure_extension_listeners_bootstrapped(self) -> None:
        if self._bootstrapping_extensions:
            return
        self._bootstrapping_extensions = True
        try:
            try:
                from bias_core.extensions.bootstrap import get_extension_host

                get_extension_host()
            except (ImportError, Exception):
                pass
        finally:
            self._bootstrapping_extensions = False


_forum_event_bus: DomainEventBus | None = None


def get_forum_event_bus() -> DomainEventBus:
    global _forum_event_bus
    if _forum_event_bus is None:
        _forum_event_bus = DomainEventBus()
    return _forum_event_bus


def get_runtime_forum_event_bus() -> DomainEventBus:
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
