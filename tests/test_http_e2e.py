from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

import api.sse as sse_api
from lawagent_runtime.board_runtime import TaskBoardRuntime, build_default_agents
from lawagent_runtime.harness import ConversationHarness, RuntimeRegistry
from lawagent_runtime.storage import FaultInjectingConversationRepository, InMemoryConversationRepository
from main import app


def build_harness(repository=None) -> ConversationHarness:
    registry = RuntimeRegistry()
    registry.register("taskboard-v0.1", TaskBoardRuntime(build_default_agents()))
    return ConversationHarness(registry, conversation_repository=repository)


class HttpStreamingE2ETests(unittest.IsolatedAsyncioTestCase):
    async def post_chat(self, harness, *, user_id):
        transport = httpx.ASGITransport(app=app)
        with patch.object(sse_api, "conversation_harness", harness):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                async with client.stream(
                    "POST", "/chat", json={"text": "房东不退押金", "user_id": user_id}
                ) as response:
                    body = "".join([part async for part in response.aiter_text()])
                    return response, body

    async def test_http_stream_completes_without_starlette_testclient(self):
        response, body = await self.post_chat(build_harness(), user_id="http-success")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertIn('"type": "chunk"', body)
        self.assertIn('"type": "done"', body)
        self.assertTrue(body.endswith("data: [DONE]\n\n"))

    async def test_http_trace_failure_returns_only_safe_error(self):
        inner = InMemoryConversationRepository()
        repository = FaultInjectingConversationRepository(inner)
        repository.inject("save_trace")
        response, body = await self.post_chat(
            build_harness(repository), user_id="http-trace-failure"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('"type": "error"', body)
        self.assertNotIn('"type": "chunk"', body)
        self.assertTrue(body.endswith("data: [DONE]\n\n"))


if __name__ == "__main__":
    unittest.main()
