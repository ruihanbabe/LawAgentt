from __future__ import annotations

import unittest

from intake.blackboard import RiskAssessment, RiskLevel, SufficiencyDecision
from runtime.board_runtime import (
    CRITICAL_RISK_MARKERS,
    HIGH_RISK_MARKERS,
    MEDIUM_RECOMMENDED_ACTION,
    ResponseAgent,
    SafetyAgent,
    TaskBoardRuntime,
    build_default_agents,
)
from runtime.context import ContextService
from runtime.messages import AgentRole
from runtime.taskboard import AgentRunBoard, Artifact, ArtifactType, BoardTask, RunStatus


class StaticSafetyCandidate:
    def __init__(self, level: str = "low") -> None:
        self.level = level

    def generate(self, **kwargs):
        return {
            "level": self.level,
            "signal_types": ["soft_signal"] if self.level != "low" else [],
            "recommended_action": MEDIUM_RECOMMENDED_ACTION if self.level == "medium" else "continue",
        }


class SafetyAgentTests(unittest.TestCase):
    def _task(self, board: AgentRunBoard, task_type: str = "assess_safety") -> BoardTask:
        return BoardTask(
            run_id=board.run_id,
            task_type=task_type,
            objective="安全评估",
            deduplication_key=f"{task_type}:test",
        )

    def _context(self, board: AgentRunBoard, task: BoardTask, role: AgentRole = AgentRole.SAFETY):
        return ContextService().build(role=role, task=task, board=board)

    def test_marker_catalogs_are_disjoint_and_avoid_single_character_matches(self) -> None:
        self.assertTrue(CRITICAL_RISK_MARKERS)
        self.assertTrue(HIGH_RISK_MARKERS)
        self.assertFalse(set(CRITICAL_RISK_MARKERS) & set(HIGH_RISK_MARKERS))
        self.assertTrue(all(len(marker) >= 2 for marker in (*CRITICAL_RISK_MARKERS, *HIGH_RISK_MARKERS)))

    def test_critical_route_skips_normal_analysis_but_keeps_review_and_gate(self) -> None:
        board = AgentRunBoard(sanitized_input="我准备自杀")

        TaskBoardRuntime(build_default_agents()).run(board)

        self.assertEqual(board.status, RunStatus.COMPLETED)
        self.assertEqual([task.task_type for task in board.tasks], ["assess_safety", "review_response"])
        self.assertEqual(board.blackboard.risk_assessments[-1].level, RiskLevel.CRITICAL)
        final = board.artifact(board.accepted_artifact_id or "")
        self.assertEqual(final.content["decision"], "limited_answer")
        self.assertTrue(final.content["sections"]["safety_guidance"])
        self.assertIn("紧急服务", final.content["response"])

    def test_personal_threat_is_high_and_continues_normal_flow(self) -> None:
        board = AgentRunBoard(sanitized_input="有人持刀威胁我")
        task = self._task(board)

        delivery = SafetyAgent(StaticSafetyCandidate("low")).execute(
            board, task, self._context(board, task)
        )

        self.assertEqual(delivery.artifacts[0].risk_level, RiskLevel.HIGH.value)
        self.assertEqual(delivery.derived_tasks[0].task_type, "schedule_next")

    def test_model_cannot_create_hard_rule_levels(self) -> None:
        board = AgentRunBoard(sanitized_input="普通咨询")
        task = self._task(board)

        delivery = SafetyAgent(StaticSafetyCandidate("critical")).execute(
            board, task, self._context(board, task)
        )

        self.assertEqual(delivery.artifacts[0].risk_level, RiskLevel.LOW.value)
        self.assertEqual(delivery.derived_tasks[0].task_type, "schedule_next")

    def test_two_recent_soft_risks_create_cross_turn_medium_floor(self) -> None:
        board = AgentRunBoard(sanitized_input="继续咨询")
        board.blackboard.risk_assessments.extend([
            RiskAssessment(assessed_through_message_id="m1", level=RiskLevel.MEDIUM),
            RiskAssessment(assessed_through_message_id="m2", level=RiskLevel.MEDIUM),
        ])
        task = self._task(board)

        delivery = SafetyAgent(StaticSafetyCandidate("low")).execute(
            board, task, self._context(board, task)
        )

        assessment = delivery.artifacts[0].content
        self.assertEqual(assessment["level"], RiskLevel.MEDIUM.value)
        self.assertIn("cross_turn_risk_trend", assessment["signal_types"])

    def test_response_displays_recommended_action(self) -> None:
        board = AgentRunBoard(sanitized_input="生成答复")
        board.blackboard.risk_assessments.append(RiskAssessment(
            assessed_through_message_id="m1",
            level=RiskLevel.MEDIUM,
            recommended_action=MEDIUM_RECOMMENDED_ACTION,
        ))
        board.blackboard.sufficiency.decision = SufficiencyDecision.DELIVER_LIMITED_RESPONSE
        source = Artifact(
            run_id=board.run_id,
            task_id="analysis",
            artifact_type=ArtifactType.ISSUE_ANALYSIS,
            producer_agent="analysis",
            content={"decision": "limited_answer", "claims": [], "limitations": ["信息有限"]},
        )
        board.artifacts.append(source)
        task = self._task(board, "compose_response")
        task.input_artifact_ids = [source.artifact_id]

        delivery = ResponseAgent().execute(
            board, task, self._context(board, task, AgentRole.DRAFTING)
        )

        content = delivery.artifacts[0].content
        self.assertIn(MEDIUM_RECOMMENDED_ACTION, content["response"])
        self.assertEqual(content["sections"]["safety_guidance"], [MEDIUM_RECOMMENDED_ACTION])


if __name__ == "__main__":
    unittest.main()
