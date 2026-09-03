from __future__ import annotations

import unittest

from intake.blackboard import SufficiencyDecision
from runtime.board_runtime import ResponseAgent
from runtime.context import ContextService
from runtime.messages import AgentRole
from runtime.taskboard import AgentRunBoard, Artifact, ArtifactType, BoardTask
from scenario_pack import ActionTemplateSpec, PartyLabels, RentalDepositScenarioPack


class ConditionalActionScenarioPack(RentalDepositScenarioPack):
    scenario_id = "conditional-actions-v1"

    def action_templates(self, facts):
        focus = facts.get("focus", "default")
        return ActionTemplateSpec(
            condition_key=focus,
            materials=(f"material:{focus}",),
            low_cost_communication=(f"communication:{focus}",),
            formal_notice=(f"notice:{focus}",),
            other_remedies=(f"remedy:{focus}",),
        )

    def party_labels(self, facts):
        return PartyLabels(self_label="申请方", counterparty_label=facts.get("label", "回应方"))


class ResponseAgentScenarioTests(unittest.TestCase):
    def test_final_sections_come_from_injected_scenario_pack(self) -> None:
        pack = ConditionalActionScenarioPack()
        board = AgentRunBoard(sanitized_input="生成答复")
        board.blackboard.confirmed_facts = {"focus": "missing-proof"}
        board.blackboard.sufficiency.decision = SufficiencyDecision.DELIVER_LIMITED_RESPONSE
        source = Artifact(
            run_id=board.run_id,
            task_id="analysis",
            artifact_type=ArtifactType.ISSUE_ANALYSIS,
            producer_agent="analysis",
            content={"decision": "limited_answer", "claims": [], "limitations": ["证据不足"]},
        )
        board.artifacts.append(source)
        task = BoardTask(
            run_id=board.run_id,
            task_type="compose_response",
            objective="生成答复",
            deduplication_key="response:test",
            input_artifact_ids=[source.artifact_id],
        )
        context = ContextService(scenario_id=pack.scenario_id).build(
            role=AgentRole.DRAFTING,
            task=task,
            board=board,
        )

        delivery = ResponseAgent(scenario_pack=pack).execute(board, task, context)

        sections = delivery.artifacts[0].content["sections"]
        self.assertEqual(sections["materials"], ["material:missing-proof"])
        self.assertEqual(sections["low_cost_communication"], ["communication:missing-proof"])
        self.assertEqual(sections["formal_notice"], ["notice:missing-proof"])
        self.assertEqual(sections["other_remedies"], ["remedy:missing-proof"])
        self.assertNotIn("合同、押金支付记录、交房记录和沟通记录", sections["materials"])

    def test_counterparty_heading_uses_injected_party_label(self) -> None:
        pack = ConditionalActionScenarioPack()
        board = AgentRunBoard(sanitized_input="生成答复")
        board.blackboard.confirmed_facts = {
            "label": "受理方",
            "counterparty_position": "不同意当前请求",
        }
        board.blackboard.sufficiency.decision = SufficiencyDecision.DELIVER_LIMITED_RESPONSE
        source = Artifact(
            run_id=board.run_id,
            task_id="analysis",
            artifact_type=ArtifactType.ISSUE_ANALYSIS,
            producer_agent="analysis",
            content={"decision": "limited_answer", "claims": [], "limitations": ["需核验"]},
        )
        board.artifacts.append(source)
        task = BoardTask(
            run_id=board.run_id,
            task_type="compose_response",
            objective="生成答复",
            deduplication_key="response:labels",
            input_artifact_ids=[source.artifact_id],
        )
        context = ContextService(scenario_id=pack.scenario_id).build(
            role=AgentRole.DRAFTING, task=task, board=board,
        )

        delivery = ResponseAgent(scenario_pack=pack).execute(board, task, context)

        section = delivery.artifacts[0].content["sections"]["counterparty_position_analysis"]
        self.assertEqual(section, ["受理方主张分析：已记录不同意当前请求；是否成立仍需结合合同、凭证和法律依据核验。"])


if __name__ == "__main__":
    unittest.main()
