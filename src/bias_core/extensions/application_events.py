from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from bias_core.domain_events import DomainEventBus
from bias_core.extensions.application_event_helpers import (
    build_event_bus_listener_key,
    build_forum_event_listener_definition,
    event_type_key,
    event_value_key,
    resolve_event_name,
    resolve_event_type,
    resolve_event_value,
)
from bias_core.extensions.types import (
    ExtensionEventListenerDefinition,
    ExtensionRealtimeDiscussionBroadcastDefinition,
    ExtensionRealtimeDiscussionTransportDefinition,
    ExtensionRealtimeIncludedDefinition,
    ExtensionSystemHookDefinition,
)

if TYPE_CHECKING:
    from bias_core.extensions.application import ExtensionHost


class ApplicationEventService:
    def __init__(self, host: "ExtensionHost", event_bus: DomainEventBus) -> None:
        self._host = host
        self._event_bus = event_bus
        self._pending_listeners: list[tuple[str, Any]] = []

    def register_listener(self, extension_id: str, definition) -> None:
        normalized_extension_id = str(extension_id or "").strip()
        if not normalized_extension_id:
            return
        event_type = resolve_event_type(getattr(definition, "event_type", None))
        if event_type is None:
            pending = (normalized_extension_id, definition)
            if pending not in self._pending_listeners:
                self._pending_listeners.append(pending)
            return
        definition = replace(definition, event_type=event_type)

        view = self._host._get_or_create_runtime_view(normalized_extension_id)
        listener_key = build_event_bus_listener_key(normalized_extension_id, definition)
        view.event_listeners = tuple([
            *(
                item
                for item in view.event_listeners
                if build_event_bus_listener_key(normalized_extension_id, item) != listener_key
            ),
            definition,
        ])
        self._host.forum.register_event_listener(build_forum_event_listener_definition(normalized_extension_id, definition))
        self._event_bus.register(
            event_type,
            definition.handler,
            listener_key=listener_key,
            replace=True,
        )

    def resolve_pending_listeners(self, *, strict: bool = False) -> None:
        pending = list(self._pending_listeners)
        self._pending_listeners = []
        unresolved: list[tuple[str, Any]] = []
        for extension_id, definition in pending:
            before_count = len(self.get_listeners(extension_id=extension_id))
            self.register_listener(extension_id, definition)
            after_count = len(self.get_listeners(extension_id=extension_id))
            if before_count == after_count and resolve_event_type(getattr(definition, "event_type", None)) is None:
                unresolved.append((extension_id, definition))
        self._pending_listeners = unresolved
        if strict and self._pending_listeners:
            unresolved_types = ", ".join(
                str(getattr(definition, "event_type", None))
                for _, definition in self._pending_listeners
            )
            raise RuntimeError(f"无法解析扩展事件类型: {unresolved_types}")

    def get_listeners(self, *, extension_id: str | None = None) -> list[ExtensionEventListenerDefinition]:
        if extension_id is not None:
            view = self._host.get_runtime_view(extension_id)
            if view is None:
                return []
            return list(view.event_listeners)

        listeners: list[ExtensionEventListenerDefinition] = []
        for view in self._host.get_runtime_views():
            listeners.extend(view.event_listeners)
        return listeners


class ApplicationRealtimeService:
    def __init__(self, host: "ExtensionHost") -> None:
        self._host = host
        self._discussion_transports_by_extension: dict[str, tuple[ExtensionRealtimeDiscussionTransportDefinition, ...]] = {}
        self._pending_discussion_broadcasts: list[tuple[str, ExtensionRealtimeDiscussionBroadcastDefinition]] = []

    def register_included_enricher(self, extension_id: str, definition: ExtensionRealtimeIncludedDefinition) -> None:
        normalized_extension_id = str(extension_id or "").strip()
        normalized_key = str(getattr(definition, "key", "") or "").strip()
        handler = getattr(definition, "handler", None)
        if not normalized_extension_id or not normalized_key or not callable(handler):
            return

        view = self._host._get_or_create_runtime_view(normalized_extension_id)
        view.realtime_included = tuple([
            *(
                item
                for item in view.realtime_included
                if str(getattr(item, "key", "") or "").strip() != normalized_key
            ),
            definition,
        ])

    def register_discussion_visibility_resolver(self, extension_id: str, definition: ExtensionSystemHookDefinition) -> None:
        normalized_extension_id = str(extension_id or "").strip()
        normalized_key = str(getattr(definition, "key", "") or "").strip()
        handler = getattr(definition, "callback", None)
        if not normalized_extension_id or not normalized_key or not callable(handler):
            return

        definition = replace(definition, module_id=definition.module_id or normalized_extension_id)
        view = self._host._get_or_create_runtime_view(normalized_extension_id)
        view.realtime_discussion_visibility = tuple([
            *(
                item
                for item in view.realtime_discussion_visibility
                if str(getattr(item, "key", "") or "").strip() != normalized_key
            ),
            definition,
        ])

    def register_discussion_transport(
        self,
        extension_id: str,
        definition: ExtensionRealtimeDiscussionTransportDefinition,
    ) -> None:
        normalized_extension_id = str(extension_id or "").strip()
        normalized_key = str(getattr(definition, "key", "") or "").strip()
        handler = getattr(definition, "handler", None)
        if not normalized_extension_id or not normalized_key or not callable(handler):
            return

        current = tuple(
            item
            for item in self._discussion_transports_by_extension.get(normalized_extension_id, ())
            if str(getattr(item, "key", "") or "").strip() != normalized_key
        )
        definitions = tuple([*current, definition])
        self._discussion_transports_by_extension[normalized_extension_id] = definitions
        self._host._get_or_create_runtime_view(normalized_extension_id).realtime_discussion_transports = definitions

    def register_discussion_broadcast(
        self,
        extension_id: str,
        definition: ExtensionRealtimeDiscussionBroadcastDefinition,
    ) -> None:
        normalized_extension_id = str(extension_id or "").strip()
        if not normalized_extension_id:
            return

        event_type = resolve_event_type(definition.event_type)
        event_name_key = event_value_key(definition.event_name)
        if not event_name_key:
            return
        if event_type is None:
            pending = (normalized_extension_id, definition)
            if pending not in self._pending_discussion_broadcasts:
                self._pending_discussion_broadcasts.append(pending)
            return

        view = self._host._get_or_create_runtime_view(normalized_extension_id)
        view.realtime_discussion_broadcasts = tuple([
            *(
                item
                for item in view.realtime_discussion_broadcasts
                if not (
                    resolve_event_type(item.event_type) == event_type
                    and event_value_key(item.event_name) == event_name_key
                )
            ),
            replace(definition, event_type=event_type),
        ])

        handler = self._build_discussion_broadcast_handler(definition)
        self._host.event_bus.register(
            event_type,
            handler,
            listener_key=(
                "realtime.discussion",
                normalized_extension_id,
                event_type_key(event_type),
                event_name_key,
            ),
            replace=True,
        )

    def resolve_pending_discussion_broadcasts(self, *, strict: bool = False) -> None:
        pending = list(self._pending_discussion_broadcasts)
        self._pending_discussion_broadcasts = []
        unresolved: list[tuple[str, ExtensionRealtimeDiscussionBroadcastDefinition]] = []
        for extension_id, definition in pending:
            before_count = len(self.get_discussion_broadcasts(extension_id=extension_id))
            self.register_discussion_broadcast(extension_id, definition)
            after_count = len(self.get_discussion_broadcasts(extension_id=extension_id))
            if before_count == after_count and resolve_event_type(definition.event_type) is None:
                unresolved.append((extension_id, definition))
        self._pending_discussion_broadcasts = unresolved
        if strict and self._pending_discussion_broadcasts:
            unresolved_types = ", ".join(
                str(definition.event_type)
                for _, definition in self._pending_discussion_broadcasts
            )
            raise RuntimeError(f"无法解析实时讨论事件类型: {unresolved_types}")

    def get_included_enrichers(self, *, extension_id: str | None = None) -> list[ExtensionRealtimeIncludedDefinition]:
        if extension_id is not None:
            view = self._host.get_runtime_view(extension_id)
            if view is None:
                return []
            return list(view.realtime_included)

        definitions: list[ExtensionRealtimeIncludedDefinition] = []
        for view in self._host.get_runtime_views():
            definitions.extend(view.realtime_included)
        return definitions

    def get_discussion_visibility_resolvers(self, *, extension_id: str | None = None) -> list[ExtensionSystemHookDefinition]:
        if extension_id is not None:
            view = self._host.get_runtime_view(extension_id)
            if view is None:
                return []
            return list(view.realtime_discussion_visibility)

        definitions: list[ExtensionSystemHookDefinition] = []
        for view in self._host.get_runtime_views():
            definitions.extend(view.realtime_discussion_visibility)
        return definitions

    def get_discussion_transports(
        self,
        *,
        extension_id: str | None = None,
    ) -> list[ExtensionRealtimeDiscussionTransportDefinition]:
        if extension_id is not None:
            return list(self._discussion_transports_by_extension.get(str(extension_id or "").strip(), ()))

        definitions: list[ExtensionRealtimeDiscussionTransportDefinition] = []
        for items in self._discussion_transports_by_extension.values():
            definitions.extend(items)
        return definitions

    def broadcast_discussion_event(self, discussion_id: int, event_type: str, payload: dict) -> None:
        for definition in self.get_discussion_transports():
            handler = getattr(definition, "handler", None)
            if callable(handler):
                handler(discussion_id, event_type, payload)

    def get_discussion_broadcasts(
        self,
        *,
        extension_id: str | None = None,
    ) -> list[ExtensionRealtimeDiscussionBroadcastDefinition]:
        if extension_id is not None:
            view = self._host.get_runtime_view(extension_id)
            if view is None:
                return []
            return list(view.realtime_discussion_broadcasts)

        definitions: list[ExtensionRealtimeDiscussionBroadcastDefinition] = []
        for view in self._host.get_runtime_views():
            definitions.extend(view.realtime_discussion_broadcasts)
        return definitions

    def _build_discussion_broadcast_handler(self, definition: ExtensionRealtimeDiscussionBroadcastDefinition):
        def handle(event) -> None:
            condition = getattr(definition, "condition", None)
            if condition is not None and not bool(resolve_event_value(condition, event, default=True)):
                return

            discussion_id = resolve_event_value(definition.discussion_id, event)
            try:
                normalized_discussion_id = int(discussion_id)
            except (TypeError, ValueError):
                return
            if normalized_discussion_id <= 0:
                return

            event_name = resolve_event_name(definition.event_name, event)
            normalized_event_name = str(event_name or "").strip()
            if not normalized_event_name:
                return

            post_id = resolve_event_value(definition.post_id, event)
            if post_id is None and definition.include_post:
                post_id = getattr(event, "post_id", None)
            try:
                normalized_post_id = int(post_id) if post_id is not None else None
            except (TypeError, ValueError):
                normalized_post_id = None

            extension_context = resolve_event_value(definition.extension_context, event, default=None)
            broadcaster = self._host.make("realtime.discussion_broadcaster", None)
            if not callable(broadcaster):
                raise RuntimeError("扩展运行时服务未注册: realtime.discussion_broadcaster")

            broadcaster(
                normalized_discussion_id,
                normalized_event_name,
                include_discussion=definition.include_discussion,
                include_post=definition.include_post,
                post_id=normalized_post_id,
                post_id_getter=definition.post_id_getter,
                extension_context=extension_context,
            )

        return handle


