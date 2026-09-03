from __future__ import annotations

import unittest

from conversation.harness import build_default_harness
from runtime.taskboard import ArtifactType, RunStatus
from scenario_pack import PlaceholderScenarioPack


class ScenarioPackSwitchE2ETests(unittest.TestCase):
    def test_placeholder_pack_runs_complete_conversation_without_domain_leakage(self) -> None:
        harness = build_default_harness(scenario_pack=PlaceholderScenarioPack())

        pending = harness.handle("处理一个示例事项", session_id="placeholder-session")
        self.assertIn("请选择本次咨询", pending.response)
        result = harness.handle("A", session_id="placeholder-session")

        board = result.board
        self.assertEqual(board.status, RunStatus.COMPLETED)
        self.assertIsNotNone(board.accepted_artifact_id)
        sufficiency = next(
            item for item in board.artifacts
            if item.artifact_type == ArtifactType.SUFFICIENCY_ASSESSMENT
        )
        self.assertEqual(sufficiency.content["scenario_id"], "placeholder-v0.1")
        plan = next(
            item for item in board.artifacts
            if item.artifact_type == ArtifactType.RETRIEVAL_PLAN
        )
        queries = [intent["arguments"]["query"] for intent in plan.content["intents"]]
        self.assertTrue(all(query.startswith("一般事项处理") for query in queries))
        self.assertTrue(all("住宅租赁" not in query and "押金返还" not in query for query in queries))
        accepted = board.artifact(board.accepted_artifact_id)
        sections = accepted.content["sections"]
        self.assertEqual(sections["materials"], ["整理与事项直接相关的现有材料"])
        self.assertNotIn("押金支付记录", "".join(sections["materials"]))


if __name__ == "__main__":
    unittest.main()
