from __future__ import annotations

from dataclasses import dataclass

from django.test import TestCase, override_settings

from bias_core.domain_events import DomainEvent, DomainEventBus
from bias_core.extensions.types import ExtensionResourceFieldResolver

class DomainEventBusTests(TestCase):
    def test_dispatches_registered_event_handlers(self):
        bus = DomainEventBus()
        received = []

        def handle_created(event):
            received.append((event.discussion_id, event.actor_user_id, event.is_approved))

        bus.register(TestDiscussionCreatedEvent, handle_created)
        bus.dispatch(
            TestDiscussionCreatedEvent(
                discussion_id=7,
                actor_user_id=3,
                is_approved=True,
            )
        )

        self.assertEqual(received, [(7, 3, True)])

    def test_register_deduplicates_explicit_listener_key(self):
        bus = DomainEventBus()
        received = []

        def handle_created(event):
            received.append("first")

        def reloaded_handle_created(event):
            received.append("reloaded")

        listener_key = ("alpha-tools", "DiscussionCreatedEvent", "handle_created")
        bus.register(TestDiscussionCreatedEvent, handle_created, listener_key=listener_key)
        bus.register(TestDiscussionCreatedEvent, reloaded_handle_created, listener_key=listener_key)
        bus.dispatch(
            TestDiscussionCreatedEvent(
                discussion_id=7,
                actor_user_id=3,
                is_approved=True,
            )
        )

        self.assertEqual(received, ["first"])

    def test_register_can_replace_explicit_listener_key(self):
        bus = DomainEventBus()
        received = []

        def handle_created(event):
            received.append("first")

        def reloaded_handle_created(event):
            received.append("reloaded")

        listener_key = ("alpha-tools", "DiscussionCreatedEvent", "handle_created")
        bus.register(TestDiscussionCreatedEvent, handle_created, listener_key=listener_key)
        bus.register(
            TestDiscussionCreatedEvent,
            reloaded_handle_created,
            listener_key=listener_key,
            replace=True,
        )
        bus.dispatch(
            TestDiscussionCreatedEvent(
                discussion_id=7,
                actor_user_id=3,
                is_approved=True,
            )
        )

        self.assertEqual(received, ["reloaded"])

    def test_dispatches_handlers_for_additional_domain_events(self):
        bus = DomainEventBus()
        received = []

        def handle_suspended(event):
            received.append(("suspended", event.user_id, event.actor_user_id))

        def handle_unsuspended(event):
            received.append(("unsuspended", event.user_id, event.actor_user_id))

        bus.register(TestUserSuspendedEvent, handle_suspended)
        bus.register(TestUserUnsuspendedEvent, handle_unsuspended)
        bus.dispatch(TestUserSuspendedEvent(user_id=9, actor_user_id=2))
        bus.dispatch(TestUserUnsuspendedEvent(user_id=9, actor_user_id=2))

        self.assertEqual(
            received,
            [("suspended", 9, 2), ("unsuspended", 9, 2)],
        )


@dataclass(frozen=True)
class AlphaStringEvent(DomainEvent):
    value: str


@dataclass(frozen=True)
class TestDiscussionCreatedEvent(DomainEvent):
    discussion_id: int
    actor_user_id: int
    is_approved: bool = True


@dataclass(frozen=True)
class TestUserSuspendedEvent(DomainEvent):
    user_id: int
    actor_user_id: int | None


@dataclass(frozen=True)
class TestUserUnsuspendedEvent(DomainEvent):
    user_id: int
    actor_user_id: int | None

