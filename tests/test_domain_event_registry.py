from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings

from bias_core.domain_events import DomainEventBus, dispatch_forum_event_after_commit, get_forum_event_bus
from bias_core.testing import capture_runtime_events

class DomainEventRegistryTests(TestCase):
    def test_runtime_reset_clears_extension_event_listeners_and_restores_runtime_listeners(self):
        from bias_core.extensions.lifecycle import reset_extension_runtime_state
        from bias_core.extensions.bootstrap import get_extension_host

        class TemporaryExtensionEvent:
            pass

        bus = get_forum_event_bus()
        bus.clear()

        def handle_temporary_event(event):
            return None

        bus.register(TemporaryExtensionEvent, handle_temporary_event)
        self.assertIn(TemporaryExtensionEvent, bus._listeners)

        reset_extension_runtime_state()

        self.assertNotIn(handle_temporary_event, bus._listeners.get(TemporaryExtensionEvent, []))
        get_extension_host()
        self.assertTrue(any(event_type is not TemporaryExtensionEvent for event_type in bus._listeners))

    def test_dispatches_handlers_for_extension_events(self):
        class DiscussionRefreshEvent:
            def __init__(self, discussion_id: int):
                self.discussion_id = discussion_id

        class RelatedRecordsRefreshEvent:
            def __init__(self, record_ids):
                self.record_ids = tuple(record_ids)

        bus = DomainEventBus()
        received = []

        def handle_discussion_refresh(event):
            received.append(("discussion", event.discussion_id))

        def handle_related_refresh(event):
            received.append(("related", event.record_ids))

        bus.register(DiscussionRefreshEvent, handle_discussion_refresh)
        bus.register(RelatedRecordsRefreshEvent, handle_related_refresh)
        bus.dispatch(DiscussionRefreshEvent(discussion_id=12))
        bus.dispatch(RelatedRecordsRefreshEvent(record_ids=(3, 7)))

        self.assertEqual(received, [("discussion", 12), ("related", (3, 7))])

    def test_after_commit_dispatch_uses_runtime_host_event_bus(self):
        class RuntimeOnlyEvent:
            pass

        global_bus = get_forum_event_bus()
        global_bus.clear()
        runtime_bus = DomainEventBus()
        received = []

        runtime_bus.register(RuntimeOnlyEvent, lambda event: received.append(event))

        with patch(
            "bias_core.extensions.bootstrap.get_extension_host",
            return_value=SimpleNamespace(event_bus=runtime_bus),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                event = RuntimeOnlyEvent()
                dispatch_forum_event_after_commit(event)

        self.assertEqual(received, [event])
        self.assertNotIn(RuntimeOnlyEvent, global_bus._listeners)

    def test_capture_runtime_events_keeps_real_runtime_listeners_active(self):
        class CapturedEvent:
            pass

        runtime_bus = DomainEventBus()
        handled = []
        runtime_bus.register(CapturedEvent, lambda event: handled.append(event))

        with patch(
            "bias_core.extensions.bootstrap.get_extension_host",
            return_value=SimpleNamespace(event_bus=runtime_bus),
        ):
            events, dispatch_patch = capture_runtime_events()
            with dispatch_patch:
                event = CapturedEvent()
                runtime_bus.dispatch(event)

        self.assertEqual(events, [event])
        self.assertEqual(handled, [event])

    def test_event_type_alias_registry_resolves_public_extension_event_names(self):
        from bias_core.extensions.application_event_helpers import (
            clear_event_type_aliases,
            register_event_type_alias,
            resolve_event_type,
        )

        class PublicContractEvent:
            pass

        clear_event_type_aliases()
        self.addCleanup(clear_event_type_aliases)

        register_event_type_alias("demo.event.created", PublicContractEvent)

        self.assertIs(resolve_event_type("demo.event.created"), PublicContractEvent)

    def test_build_runtime_event_constructs_event_from_public_alias(self):
        from bias_core.extensions.application_event_helpers import (
            clear_event_type_aliases,
            register_event_type_alias,
        )
        from bias_core.testing import build_runtime_event

        class PublicContractEvent:
            def __init__(self, record_id: int):
                self.record_id = record_id

        clear_event_type_aliases()
        self.addCleanup(clear_event_type_aliases)
        register_event_type_alias("demo.event.constructed", PublicContractEvent)

        event = build_runtime_event("demo.event.constructed", record_id=42)

        self.assertIsInstance(event, PublicContractEvent)
        self.assertEqual(event.record_id, 42)

    def test_runtime_reset_clears_event_type_alias_registry(self):
        from bias_core.extensions.application_event_helpers import (
            register_event_type_alias,
            resolve_event_type,
        )
        from bias_core.extensions.lifecycle import reset_extension_runtime_state

        class TemporaryPublicEvent:
            pass

        register_event_type_alias("temporary.event", TemporaryPublicEvent)
        self.assertIs(resolve_event_type("temporary.event"), TemporaryPublicEvent)

        reset_extension_runtime_state()

        self.assertIsNone(resolve_event_type("temporary.event"))


