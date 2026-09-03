from __future__ import annotations

import unittest

from runtime.context import ContextService
from runtime.memory import MemoryService, sliding_window_context_manager
from runtime.messages import AgentRole
from runtime.taskboard import AgentRunBoard, BoardTask


class MemoryServiceTests(unittest.TestCase):
    def test_sliding_window_filters_roles_without_mutating_input(self) -> None:
        source = [
            {"role": "system", "content": "hidden"},
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
            {"role": "user", "content": "three"},
        ]

        result = sliding_window_context_manager(source, 2)

        self.assertEqual(result, [
            {"role": "assistant", "content": "two"},
            {"role": "user", "content": "three"},
        ])
        self.assertEqual(len(source), 4)

    def test_write_compresses_and_evicts_deterministically(self) -> None:
        memory = MemoryService(window_size=2, max_message_chars=12)
        memory.write("session", role="user", content="  first   message  ")
        memory.write("session", role="system", content="ignored")
        memory.write("session", role="assistant", content="second")
        memory.write("session", role="user", content="third")

        records = memory.read("session")

        self.assertEqual([(item.role, item.content) for item in records], [
            ("assistant", "second"), ("user", "third"),
        ])

    def test_context_service_reads_managed_memory_instead_of_raw_history(self) -> None:
        memory = MemoryService(window_size=5)
        memory.write("session", role="user", content="managed memory")
        service = ContextService(memory_service=memory)
        board = AgentRunBoard(session_id="session", sanitized_input="current")
        task = BoardTask(
            run_id=board.run_id,
            task_type="understand_message",
            objective="understand",
            deduplication_key="understand:test",
        )

        view = service.build(
            role=AgentRole.INTAKE,
            task=task,
            board=board,
            history=[type("Raw", (), {"message_id": "raw", "role": "user", "content": "raw"})()],
        )

        self.assertEqual([item.content for item in view.history], ["managed memory"])

    def test_delete_removes_session_memory(self) -> None:
        memory = MemoryService()
        memory.write("session", role="user", content="message")
        memory.delete("session")
        self.assertEqual(memory.read("session"), ())


if __name__ == "__main__":
    unittest.main()
