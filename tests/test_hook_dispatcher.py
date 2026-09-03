from __future__ import annotations

import unittest

from runtime.hooks import BufferedEventForwarder, HookDispatcher
from runtime.taskboard import CollaborationEvent, EventType, EventVisibility


def event(visibility: EventVisibility, *, sequence: int = 0) -> CollaborationEvent:
    return CollaborationEvent(
        run_id="run-test",
        sequence=sequence,
        event_type=EventType.TASK_STARTED,
        actor_type="agent",
        actor_id="agent-test",
        payload={"safe": "value"},
        visibility=visibility,
    )


class HookDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_subscribers_are_filtered_and_failures_are_isolated(self):
        dispatcher = HookDispatcher()
        user_events = []
        developer_events = []

        def failing_handler(_event):
            raise RuntimeError("subscriber failed")

        dispatcher.subscribe(failing_handler, min_visibility=EventVisibility.USER)
        dispatcher.subscribe(user_events.append, min_visibility=EventVisibility.USER)
        dispatcher.subscribe(developer_events.append, min_visibility=EventVisibility.DEVELOPER)

        dispatcher.dispatch(event(EventVisibility.DEVELOPER))
        dispatcher.dispatch(event(EventVisibility.USER, sequence=1))

        self.assertEqual([item.sequence for item in user_events], [1])
        self.assertEqual([item.sequence for item in developer_events], [0, 1])

    async def test_handler_mutation_cannot_change_source_or_other_delivery(self):
        dispatcher = HookDispatcher()
        received = []

        def mutating_handler(item):
            item.payload["safe"] = "changed"

        dispatcher.subscribe(mutating_handler, min_visibility=EventVisibility.USER)
        dispatcher.subscribe(received.append, min_visibility=EventVisibility.USER)
        source = event(EventVisibility.USER)

        dispatcher.dispatch(source)

        self.assertEqual(source.payload, {"safe": "value"})
        self.assertEqual(received[0].payload, {"safe": "value"})

    async def test_buffered_forwarder_keeps_async_io_off_dispatch_path(self):
        forwarder = BufferedEventForwarder(max_queue_size=1)
        sent = []
        source = event(EventVisibility.DEVELOPER)

        async def sender(item):
            sent.append(item)

        forwarder.enqueue(source)
        forwarder.enqueue(source)
        forwarded = await forwarder.forward_one(sender)

        self.assertTrue(forwarded)
        self.assertEqual(len(sent), 1)
        self.assertEqual(forwarder.dropped_count, 1)


if __name__ == "__main__":
    unittest.main()
