from __future__ import annotations

import unittest

from runtime.board_runtime import AnalysisAgent
from runtime.context import ContextService
from runtime.messages import AgentRole
from runtime.taskboard import AgentRunBoard, Artifact, ArtifactType, BoardTask
from scenario_pack import RentalDepositScenarioPack


class AnalysisAgentAmountFrameworkTests(unittest.TestCase):
    def execute(self, facts):
        board = AgentRunBoard(sanitized_input="分析")
        board.blackboard.confirmed_facts = dict(facts)
        evidence = Artifact(
            run_id=board.run_id,
            task_id="retrieval",
            artifact_type=ArtifactType.RAG_EVIDENCE_BUNDLE,
            producer_agent="retrieval",
            evidence_refs=["law:civil-code-509"],
            content={"results": []},
        )
        board.artifacts.append(evidence)
        task = BoardTask(
            run_id=board.run_id,
            task_type="analyze_evidence",
            objective="分析",
            deduplication_key="analysis:test",
            input_artifact_ids=[evidence.artifact_id],
        )
        context = ContextService().build(role=AgentRole.ANALYSIS, task=task, board=board)
        delivery = AnalysisAgent(scenario_pack=RentalDepositScenarioPack()).execute(board, task, context)
        return delivery.artifacts[0].content

    def test_generates_only_applicable_fixed_items_without_final_amount(self):
        content = self.execute({
            "deposit_amount": "3000元",
            "tenancy_ended": "yes",
            "event_date": "2026-08-20",
            "contract_terms": "包含违约金约定",
            "landlord_reason": "房屋损坏扣款存在争议",
        })

        items = content["amount_items"]
        self.assertEqual(len(items), 5)
        self.assertEqual(
            {item["display_name"] for item in items},
            {"应退押金基数", "扣除项", "违约金", "逾期利息/资金占用赔偿", "争议扣除项"},
        )
        self.assertTrue(all(item["legal_basis_refs"] == ["law:civil-code-509"] for item in items))
        self.assertTrue(all(item["requires_user_confirmation"] for item in items))
        self.assertTrue(all("final_amount" not in item for item in items))

    def test_out_of_scope_case_does_not_apply_deposit_framework(self):
        content = self.execute({"property_use": "non_residential", "deposit_amount": "3000元"})
        self.assertEqual(content["amount_items"], [])


if __name__ == "__main__":
    unittest.main()
