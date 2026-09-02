from __future__ import annotations

import unittest

from runtime.board_runtime import UnderstandingAgent
from runtime.context import ContextService
from runtime.messages import AgentRole
from runtime.taskboard import AgentRunBoard, BoardTask
from scenario_pack import ActionTemplateSpec, FactKeySpec


class DemoScenarioPack:
    scenario_id = "demo-v1"

    def required_fact_keys(self, layer):
        if layer != "intake":
            return []
        return [FactKeySpec(key="topic", layer="intake", required=True, description="请说明主题？")]

    def extract_facts(self, text, existing_facts):
        return {} if "topic" in existing_facts else ({"topic": "demo"} if "演示" in text else {})

    def is_out_of_scope(self, facts):
        return facts.get("topic") == "excluded"

    def amount_calculation_items(self):
        return []

    def is_amount_item_applicable(self, item_key, facts):
        return False

    def action_templates(self, facts):
        return ActionTemplateSpec(condition_key="demo")


class UnderstandingAgentScenarioTests(unittest.TestCase):
    def execute(self, text, pack=None):
        board = AgentRunBoard(sanitized_input=text)
        task = BoardTask(
            run_id=board.run_id,
            task_type="understand_message",
            objective="理解",
            deduplication_key="understand:test",
        )
        context = ContextService(scenario_id=(pack.scenario_id if pack else "rental-deposit-v0.1")).build(
            role=AgentRole.INTAKE, task=task, board=board,
        )
        delivery = UnderstandingAgent(scenario_pack=pack).execute(board, task, context)
        return board, delivery.artifacts[0]

    def test_uses_injected_fact_extractor_and_scenario_id(self):
        board, artifact = self.execute("这是演示", DemoScenarioPack())
        self.assertEqual(board.blackboard.confirmed_facts, {"topic": "demo"})
        self.assertEqual(artifact.content["scenario_id"], "demo-v1")
        self.assertEqual(artifact.content["intent"], "demo-v1")
        self.assertEqual(artifact.content["missing_fact_keys"], [])

    def test_questions_come_from_pack_not_agent_dictionary(self):
        _, artifact = self.execute("没有主题", DemoScenarioPack())
        self.assertEqual(artifact.content["question_keys"], ["topic"])
        self.assertEqual(artifact.content["questions"], ["请说明主题？"])
        self.assertFalse(hasattr(UnderstandingAgent, "_questions"))

    def test_deposit_amount_is_required_and_extracted(self):
        board, artifact = self.execute("押金3000元，有转账记录")
        self.assertEqual(board.blackboard.confirmed_facts["deposit_amount"], "3000元")
        self.assertNotIn("deposit_amount", artifact.content["missing_fact_keys"])

    def test_out_of_scope_result_is_exposed_in_artifact(self):
        _, artifact = self.execute("商铺押金3000元")
        self.assertTrue(artifact.content["out_of_scope"])


if __name__ == "__main__":
    unittest.main()
