from __future__ import annotations

import unittest

from lawagent_runtime.board_runtime import TaskBoardRuntime, build_default_agents
from lawagent_runtime.harness import ConversationHarness, RuntimeRegistry
from lawagent_runtime.storage import (
    InMemoryConversationRepository,
    InMemoryUserProfileStore,
    UserProfile,
)


class RuntimeStorageTests(unittest.TestCase):
    def build_harness(self):
        registry = RuntimeRegistry()
        registry.register("taskboard-v0.1", TaskBoardRuntime(build_default_agents()))
        profiles = InMemoryUserProfileStore()
        conversations = InMemoryConversationRepository()
        harness = ConversationHarness(
            registry,
            profile_store=profiles,
            conversation_repository=conversations,
        )
        return harness, profiles, conversations

    def test_profile_store_upsert_is_versioned_and_delete_is_supported(self):
        store = InMemoryUserProfileStore()
        first = store.upsert(UserProfile(pseudonymous_user_id="user-1", jurisdiction="CN"))
        second = store.upsert(first.model_copy(update={"explanation_preference": "concise"}))
        self.assertEqual(first.version, 1)
        self.assertEqual(second.version, 2)
        self.assertEqual(store.get("user-1").explanation_preference, "concise")
        self.assertTrue(store.delete("user-1"))
        self.assertIsNone(store.get("user-1"))

    def test_harness_writes_only_sanitized_history_and_trace(self):
        harness, profiles, repository = self.build_harness()
        result = harness.handle(
            "手机号13812345678，租房押金不退怎么办？",
            session_id="session-1",
            pseudonymous_user_id="user-1",
        )
        history = repository.list_history("session-1")

        self.assertEqual([item.role for item in history], ["user", "assistant"])
        self.assertNotIn("13812345678", history[0].content)
        self.assertGreaterEqual(len(repository.agent_messages), 1)
        self.assertEqual(repository.get_trace(result.board.run_id).run_id, result.board.run_id)
        self.assertIsNotNone(profiles.get("user-1"))

    def test_history_limit_and_session_isolation(self):
        harness, _, repository = self.build_harness()
        harness.handle("你好", session_id="session-a", pseudonymous_user_id="a")
        harness.handle("你好", session_id="session-b", pseudonymous_user_id="b")
        self.assertEqual(len(repository.list_history("session-a")), 2)
        self.assertEqual(repository.list_history("missing"), [])
        self.assertEqual(len(repository.list_history("session-a", limit=1)), 1)


if __name__ == "__main__":
    unittest.main()
