from __future__ import annotations

import unittest

from runtime.board_runtime import RetrievalAgent
from runtime.context import ContextService
from runtime.messages import AgentRole
from runtime.taskboard import AgentRunBoard, ArtifactType, BoardTask
from scenario_pack import RentalDepositScenarioPack


class ShippingScenarioPack(RentalDepositScenarioPack):
    scenario_id = "shipping-v1"

    def retrieval_query_prefix(self) -> str:
        return "货运合同 运费争议"


class RetrievalAgentScenarioTests(unittest.TestCase):
    def test_query_prefix_comes_from_injected_scenario_pack(self) -> None:
        pack = ShippingScenarioPack()
        board = AgentRunBoard(sanitized_input="查询")
        board.blackboard.confirmed_facts = {"fee": "5000元"}
        task = BoardTask(
            run_id=board.run_id,
            task_type="retrieve_context",
            objective="检索",
            deduplication_key="retrieve:test",
        )
        context = ContextService(scenario_id=pack.scenario_id).build(
            role=AgentRole.RETRIEVAL,
            task=task,
            board=board,
        )

        delivery = RetrievalAgent(scenario_pack=pack).execute(board, task, context)

        plan = next(
            item for item in delivery.artifacts
            if item.artifact_type == ArtifactType.RETRIEVAL_PLAN
        )
        queries = {intent["arguments"]["query"] for intent in plan.content["intents"]}
        self.assertEqual(queries, {"货运合同 运费争议 5000元"})
        self.assertNotIn("住宅租赁", next(iter(queries)))


if __name__ == "__main__":
    unittest.main()
