import asyncio
import json
import unittest
from unittest.mock import patch

from api.sse import (
    ChatInput,
    build_chat_stream,
    encode_sse,
    history_store,
    sliding_window_context_manager,
    iter_agent_events,
)
from conversation.harness import HarnessResult
from runtime.taskboard import AgentRunBoard, Artifact, ArtifactType, EventType, EventVisibility


TOKEN = "a" * 32


class ConnectedRequest:
    async def is_disconnected(self):
        return False


class ApiSseTests(unittest.TestCase):
    def test_chat_input_strips_text_and_rejects_unknown_fields(self):
        request = ChatInput(text="  押金能否退还？  ", user_id=" demo ", token=TOKEN)
        self.assertEqual(request.text, "押金能否退还？")
        self.assertEqual(request.user_id, "demo")

        with self.assertRaises(Exception):
            ChatInput(text="问题", user_id="demo", token=TOKEN, unexpected=True)

    def test_sliding_window_returns_latest_messages_without_mutation(self):
        history = [
            {"role": "user", "content": "1"},
            {"role": "assistant", "content": "2"},
            {"role": "user", "content": "3"},
        ]
        actual = sliding_window_context_manager(history, 2)
        self.assertEqual([item["content"] for item in actual], ["2", "3"])
        self.assertEqual(len(history), 3)

    def test_encode_sse_uses_json_and_done_marker(self):
        frame = encode_sse({"type": "chunk", "content": "法律依据"})
        payload = frame.removeprefix("data: ").strip()
        self.assertEqual(json.loads(payload)["content"], "法律依据")
        self.assertEqual(encode_sse("[DONE]"), "data: [DONE]\n\n")


class ApiSseStreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        history_store.clear()

    async def test_stream_emits_chunks_done_marker_and_saves_history(self):
        async def fake_agent_events(_messages, **_kwargs):
            yield {"type": "chunk", "content": "可以"}
            yield {"type": "chunk", "content": "主张返还。"}

        request = ChatInput(text="押金能退吗？", user_id="demo", token=TOKEN)
        with patch("api.sse.iter_agent_events", fake_agent_events):
            frames = [
                frame
                async for frame in build_chat_stream(
                    req=request,
                    request=ConnectedRequest(),
                )
            ]

        self.assertEqual(frames[-1], "data: [DONE]\n\n")
        self.assertTrue(any('"type": "done"' in frame for frame in frames))
        self.assertEqual(history_store["demo"][-1]["content"], "可以主张返还。")

    async def test_user_progress_is_emitted_before_runtime_finishes(self):
        release = asyncio.Event()

        class PausingHarness:
            async def handle_async(self, _text, *, event_sink, **_kwargs):
                board = AgentRunBoard(sanitized_input="问题")
                board._event_sink = event_sink
                board.append_event(
                    EventType.TASK_STARTED,
                    actor_type="agent",
                    actor_id="test-agent",
                    task_id="task-test",
                    payload={"task_type": "understand_message"},
                    visibility=EventVisibility.USER,
                )
                await release.wait()
                final = Artifact(
                    run_id=board.run_id,
                    task_id="task-test",
                    artifact_type=ArtifactType.FINAL_RESPONSE,
                    producer_agent="test-agent",
                    content={"response": "完成"},
                )
                board.artifacts.append(final)
                board.accepted_artifact_id = final.artifact_id
                return HarnessResult(board)

        with patch("api.sse.conversation_harness", PausingHarness()):
            stream = iter_agent_events([{"role": "user", "content": "问题"}])
            started = await stream.__anext__()
            progress = await stream.__anext__()
            self.assertFalse(release.is_set())
            self.assertEqual(started["type"], "run_started")
            self.assertEqual(progress, {
                "type": "status_changed",
                "content": "understand_message:started",
            })
            release.set()
            remaining = [event async for event in stream]

        self.assertIn({"type": "chunk", "content": "完成"}, remaining)


if __name__ == "__main__":
    unittest.main()
