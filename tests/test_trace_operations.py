from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import httpx

import api.sse as sse_api
from runtime.board_runtime import TaskBoardRuntime, build_default_agents
from conversation.harness import ConversationHarness, RuntimeRegistry, TracePersistenceError
from persistence.storage import (
    FaultInjectingConversationRepository,
    InMemoryConversationRepository,
)
from runtime.taskboard import EventType
from main import app


def build_harness(repository=None) -> ConversationHarness:
    registry = RuntimeRegistry()
    registry.register("taskboard-v0.1", TaskBoardRuntime(build_default_agents()))
    return ConversationHarness(registry, conversation_repository=repository)


class TraceFailClosedTests(unittest.TestCase):
    def test_trace_failure_prevents_delivery_and_assistant_history(self):
        inner = InMemoryConversationRepository()
        repository = FaultInjectingConversationRepository(inner)
        repository.inject("save_trace")
        harness = build_harness(repository)

        with self.assertRaisesRegex(TracePersistenceError, "TRACE_PERSISTENCE_FAILED"):
            harness.handle("房东不退押金", session_id="trace-failure")

        self.assertEqual([item.role for item in inner.history], ["user"])
        self.assertEqual(inner.traces, {})
        self.assertEqual(harness.run_store, {})
        self.assertEqual(harness.trace_store, {})


class TraceHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.harness = build_harness()
        self.first = self.harness.handle("房东不退押金", session_id="trace-http")
        self.transport = httpx.ASGITransport(app=app)

    async def test_trace_view_and_replay(self):
        with patch.object(sse_api, "conversation_harness", self.harness), patch.dict(
            os.environ, {"LAWAGENT_DEV_MODE": "true", "LAWAGENT_DEV_TOKEN": "test-token"}
        ):
            async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
                trace_response = await client.get(
                    f"/api/dev/runs/{self.first.board.run_id}/trace",
                    headers={"X-LawAgent-Dev-Token": "test-token"},
                )
                replay_response = await client.post(
                    f"/api/dev/runs/{self.first.board.run_id}/replay",
                    headers={"X-LawAgent-Dev-Token": "test-token"},
                )

        self.assertEqual(trace_response.status_code, 200)
        self.assertNotIn("sanitized_input", trace_response.json())
        self.assertEqual(replay_response.status_code, 200)
        replay_id = replay_response.json()["replay_run_id"]
        replay_trace = self.harness.conversation_repository.get_trace(replay_id)
        self.assertIn(EventType.REPLAY_STARTED, [item.event_type for item in replay_trace.events])

    async def test_dev_routes_are_hidden_by_default(self):
        with patch.object(sse_api, "conversation_harness", self.harness), patch.dict(
            os.environ, {"LAWAGENT_DEV_MODE": "false"}
        ):
            async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
                response = await client.get(f"/api/dev/runs/{self.first.board.run_id}/trace")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
