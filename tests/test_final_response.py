from __future__ import annotations

import unittest

from pydantic import ValidationError

from intake.blackboard import SufficiencyDecision
from runtime.board_runtime import ResponseAgent
from runtime.context import ContextService
from runtime.final_response import AmountFrameworkItem
from runtime.messages import AgentRole
from runtime.taskboard import AgentRunBoard, Artifact, ArtifactType, BoardTask


AMOUNT_ITEM = {
    "item_key": "refundable_deposit_base",
    "display_name": "应退押金基数",
    "relief_kind": "monetary",
    "applicability": "applicable",
    "legal_basis_hint": "押金返还 合同约定",
    "evidence_ids": ["law:509"],
    "calculation_logic": "以有支付凭证支持的合同押金金额作为待核对基数",
    "requires_user_confirmation": True,
}


class FinalResponseSectionsTests(unittest.TestCase):
    def test_amount_framework_rejects_unapproved_final_amount_field(self) -> None:
        with self.assertRaises(ValidationError):
            AmountFrameworkItem.model_validate({**AMOUNT_ITEM, "final_amount": "3000元"})

    def test_relevant_claim_item_requires_evidence(self) -> None:
        with self.assertRaisesRegex(ValidationError, "requires evidence_ids"):
            AmountFrameworkItem.model_validate({**AMOUNT_ITEM, "evidence_ids": []})

    def test_response_populates_claim_document_and_counterparty_sections(self) -> None:
        board = AgentRunBoard(sanitized_input="生成结果")
        board.blackboard.confirmed_facts = {
            "counterparty_position": "房屋损坏",
            "deposit_amount": "3000元",
        }
        board.blackboard.sufficiency.decision = SufficiencyDecision.DELIVER_LIMITED_RESPONSE
        source = Artifact(
            run_id=board.run_id,
            task_id="analysis",
            artifact_type=ArtifactType.ISSUE_ANALYSIS,
            producer_agent="analysis",
            evidence_refs=["law:509"],
            content={
                "decision": "limited_answer",
                "claims": [],
                "limitations": ["仍需核对材料"],
                "amount_items": [AMOUNT_ITEM],
            },
        )
        board.artifacts.append(source)
        task = BoardTask(
            run_id=board.run_id,
            task_type="compose_response",
            objective="生成结果",
            deduplication_key="final-response:test",
            input_artifact_ids=[source.artifact_id],
        )
        context = ContextService().build(role=AgentRole.DRAFTING, task=task, board=board)

        delivery = ResponseAgent().execute(board, task, context)

        sections = delivery.artifacts[0].content["sections"]
        self.assertEqual(sections["amount_items"], [AMOUNT_ITEM])
        self.assertIn("房屋损坏", sections["counterparty_position_analysis"][0])
        self.assertTrue(sections["document_draft_points"])
        self.assertNotIn("final_amount", sections["amount_items"][0])


if __name__ == "__main__":
    unittest.main()
