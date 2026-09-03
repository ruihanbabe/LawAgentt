from __future__ import annotations

import unittest

from runtime.board_runtime import AnalysisAgent
from runtime.context import ContextService
from runtime.messages import AgentRole
from runtime.taskboard import AgentRunBoard, Artifact, ArtifactType, BoardTask
from scenario_pack import RentalDepositScenarioPack


class RecordingClassificationGenerator:
    def __init__(self):
        self.call_count = 0

    def generate(self, **kwargs):
        self.call_count += 1
        catalog = RentalDepositScenarioPack().claim_items()
        return {
            "claims": [],
            "limitations": [],
            "claim_item_assessments": [
                {
                    "item_key": item.item_key,
                    "applicability": (
                        "uncertain" if item.relief_kind == "disputed_catchall" else "applicable"
                    ),
                    "evidence_ids": ["law:civil-code-509"],
                }
                for item in catalog
            ],
        }


class AnalysisAgentAmountFrameworkTests(unittest.TestCase):
    def execute(self, facts, generator=None, pack=None):
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
        delivery = AnalysisAgent(
            candidate_generator=generator,
            scenario_pack=pack or RentalDepositScenarioPack(),
        ).execute(board, task, context)
        return delivery.artifacts[0].content

    def test_generates_only_applicable_fixed_items_without_final_amount(self):
        content = self.execute({
            "deposit_amount": "3000元",
            "tenancy_ended": "yes",
            "event_date": "2026-08-20",
            "contract_terms": "包含违约金约定",
            "counterparty_position": "房屋损坏扣款存在争议",
        })

        items = content["amount_items"]
        self.assertEqual(len(items), 5)
        self.assertEqual(
            {item["display_name"] for item in items},
            {"应退押金基数", "扣除项", "违约金", "逾期利息/资金占用赔偿", "争议扣除项"},
        )
        self.assertTrue(all(item["evidence_ids"] == ["law:civil-code-509"] for item in items))
        self.assertTrue(all(item["requires_user_confirmation"] for item in items))
        self.assertTrue(all("final_amount" not in item for item in items))

    def test_out_of_scope_case_does_not_apply_deposit_framework(self):
        content = self.execute({"property_use": "non_residential", "deposit_amount": "3000元"})
        self.assertEqual(content["amount_items"], [])

    def test_single_structured_call_binds_evidence_and_groups_disputes(self):
        generator = RecordingClassificationGenerator()
        content = self.execute({"deposit_amount": "3000元"}, generator=generator)

        self.assertEqual(generator.call_count, 1)
        self.assertEqual(len(content["amount_items"]), 5)
        for item in content["amount_items"]:
            if item["applicability"] in {"applicable", "uncertain"}:
                self.assertEqual(item["evidence_ids"], ["law:civil-code-509"])
        self.assertEqual(
            [item["item_key"] for item in content["disputed_items"]],
            ["disputed_deductions"],
        )

    def test_model_call_count_does_not_scale_with_catalog_size(self):
        class OneItemPack(RentalDepositScenarioPack):
            def claim_items(self):
                return [super().claim_items()[-1]]

        generator = RecordingClassificationGenerator()
        self.execute({}, generator=generator, pack=OneItemPack())
        self.assertEqual(generator.call_count, 1)


if __name__ == "__main__":
    unittest.main()
