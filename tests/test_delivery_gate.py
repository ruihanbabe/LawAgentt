from __future__ import annotations

import unittest
from datetime import date

from safety.delivery_gate import DeliveryGate
from runtime.taskboard import AgentRunBoard, Artifact, ArtifactType, BoardTask


class DeliveryGateTests(unittest.TestCase):
    def setUp(self):
        self.board = AgentRunBoard(sanitized_input="押金纠纷")
        self.board.blackboard.event_date = date(2024, 6, 1)
        self.task = BoardTask(
            run_id=self.board.run_id,
            task_type="review_response",
            objective="review",
            deduplication_key="review:1",
        )
        self.board.tasks.append(self.task)

    def add_valid_chain(self):
        evidence = Artifact(
            run_id=self.board.run_id,
            task_id=self.task.task_id,
            artifact_type=ArtifactType.RAG_EVIDENCE_BUNDLE,
            producer_agent="retrieval",
            evidence_refs=["law:1"],
            content={"results": [{"items": [{
                "kind": "law",
                "chunk_id": "1",
                "law_family_id": "civil-code",
                "law_version_id": "v1",
                "validity_status": "current",
                "effective_from": "2021-01-01",
                "effective_to": None,
            }]}]},
        )
        candidate = Artifact(
            run_id=self.board.run_id,
            task_id=self.task.task_id,
            artifact_type=ArtifactType.RESPONSE_CANDIDATE,
            producer_agent="response",
            evidence_refs=["law:1"],
            content={
                "response": "根据现有材料可作初步分析。",
                "decision": "supported_answer",
                "claims": [{"text": "应结合合同约定判断。", "evidence_ids": ["law:1"]}],
                "sections": {
                    "current_situation": [], "preliminary_assessment": [],
                    "counterparty_position_analysis": [], "statutes": [], "similar_cases": [],
                    "disputed_items": [],
                    "materials": [], "low_cost_communication": [], "formal_notice": [],
                    "other_remedies": [], "limitations": ["仅为基于固定快照的初步分析。"],
                },
                "citation_map": {"claim:0": ["law:1"]},
                "confirmed_facts": {}, "unresolved_facts": [], "source_snapshot_versions": ["v1"],
                "limitations": ["仅为基于固定快照的初步分析。"],
            },
        )
        review = Artifact(
            run_id=self.board.run_id,
            task_id=self.task.task_id,
            artifact_type=ArtifactType.REVIEW_RESULT,
            producer_agent="review",
            source_artifact_ids=[candidate.artifact_id],
            content={"approved": True, "reason": "grounded"},
            review_status="approved",
        )
        final = Artifact(
            run_id=self.board.run_id,
            task_id=self.task.task_id,
            artifact_type=ArtifactType.FINAL_RESPONSE,
            producer_agent="review",
            source_artifact_ids=[candidate.artifact_id, review.artifact_id],
            evidence_refs=["law:1"],
            content=dict(candidate.content),
            review_status="approved",
            validation_status="valid",
        )
        self.board.artifacts.extend([evidence, candidate, review, final])
        return final

    def test_accepts_reviewed_grounded_final(self):
        final = self.add_valid_chain()
        result = DeliveryGate().evaluate(self.board)
        self.assertTrue(result.approved)
        self.assertEqual(result.final_artifact_id, final.artifact_id)
        self.assertEqual(result.failure_codes, ())

    def test_blocks_unknown_evidence(self):
        final = self.add_valid_chain()
        final.evidence_refs = ["law:unknown"]
        result = DeliveryGate().evaluate(self.board)
        self.assertFalse(result.approved)
        self.assertIn("CLAIMS_UNGROUNDED", result.failure_codes)
        self.assertIn("EVIDENCE_NOT_FOUND", result.failure_codes)

    def test_blocks_claim_item_with_evidence_outside_final_bundle(self):
        final = self.add_valid_chain()
        final.content["sections"]["amount_items"] = [{
            "item_key": "item",
            "display_name": "请求项目",
            "relief_kind": "monetary",
            "applicability": "applicable",
            "legal_basis_hint": "请求项目依据",
            "evidence_ids": ["law:unknown"],
            "calculation_logic": "核对基数与标准，不输出最终精确数额",
            "requires_user_confirmation": True,
        }]
        result = DeliveryGate().evaluate(self.board)
        self.assertFalse(result.approved)
        self.assertIn("EVIDENCE_NOT_FOUND", result.failure_codes)

    def test_blocks_pii_in_response(self):
        final = self.add_valid_chain()
        final.content["response"] = "请联系13812345678。"
        result = DeliveryGate().evaluate(self.board)
        self.assertFalse(result.approved)
        self.assertIn("PII_LEAK", result.failure_codes)

    def test_blocks_supported_answer_with_unverified_law_version(self):
        self.add_valid_chain()
        evidence = next(
            item for item in self.board.artifacts
            if item.artifact_type == ArtifactType.RAG_EVIDENCE_BUNDLE
        )
        evidence.content["results"][0]["items"][0]["validity_status"] = "unverified"
        result = DeliveryGate().evaluate(self.board)
        self.assertFalse(result.approved)
        self.assertIn("LAW_TEMPORAL_VALIDITY_UNCONFIRMED", result.failure_codes)

    def test_effective_from_is_inclusive(self):
        self.add_valid_chain()
        self.board.blackboard.event_date = date(2021, 1, 1)
        result = DeliveryGate().evaluate(self.board)
        self.assertTrue(result.approved)

    def test_effective_to_is_exclusive(self):
        self.add_valid_chain()
        evidence = next(
            item for item in self.board.artifacts
            if item.artifact_type == ArtifactType.RAG_EVIDENCE_BUNDLE
        )
        evidence.content["results"][0]["items"][0]["effective_to"] = "2024-06-01"
        result = DeliveryGate().evaluate(self.board)
        self.assertFalse(result.approved)
        self.assertIn("LAW_TEMPORAL_VALIDITY_UNCONFIRMED", result.failure_codes)

    def test_blocks_prohibited_promise_and_internal_identifier(self):
        final = self.add_valid_chain()
        final.content["response"] = "保证胜诉，内部任务是 task_secret。"
        result = DeliveryGate().evaluate(self.board)
        self.assertFalse(result.approved)
        self.assertIn("PROHIBITED_PROMISE", result.failure_codes)
        self.assertIn("INTERNAL_IDENTIFIER_LEAK", result.failure_codes)

    def test_blocks_supported_answer_without_limitations(self):
        final = self.add_valid_chain()
        final.content["limitations"] = []
        result = DeliveryGate().evaluate(self.board)
        self.assertFalse(result.approved)
        self.assertIn("RESPONSE_STRUCTURE_INVALID", result.failure_codes)


if __name__ == "__main__":
    unittest.main()
