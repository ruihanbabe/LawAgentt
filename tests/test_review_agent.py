from __future__ import annotations

import unittest

from runtime.board_runtime import ReviewAgent, SchedulerAgent
from runtime.context import ContextService
from runtime.messages import AgentRole
from runtime.scheduling import EscalationReasonCode, EscalationRequest, TaskIntent
from runtime.taskboard import AgentRunBoard, Artifact, ArtifactType, BoardTask


class SafetyRecheckCandidate:
    def generate(self, **kwargs):
        return {
            "approved": False,
            "reason": "需要重新检查风险",
            "request_safety_recheck": True,
            "safety_reason": "候选回答与当前风险记录可能不一致",
        }


class ReviewAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.board = AgentRunBoard(sanitized_input="已脱敏的当前消息")
        self.board.blackboard.confirmed_facts = {"confirmed": "yes"}
        self.board.blackboard.candidate_facts = {"candidate": "pending"}
        self.board.blackboard.disputed_fact_keys = ["disputed"]
        self.board.blackboard.sufficiency.missing_fact_keys = ["missing"]
        self.risk = Artifact(
            run_id=self.board.run_id,
            task_id="risk-task",
            artifact_type=ArtifactType.RISK_REVIEW,
            producer_agent="safety",
            content={"level": "low"},
        )
        self.candidate = Artifact(
            run_id=self.board.run_id,
            task_id="response-task",
            artifact_type=ArtifactType.RESPONSE_CANDIDATE,
            producer_agent="drafting",
            source_artifact_ids=[self.risk.artifact_id],
            content={"response": "候选回复", "claims": []},
        )
        self.board.artifacts.extend([self.risk, self.candidate])
        self.task = BoardTask(
            run_id=self.board.run_id,
            task_type="review_response",
            objective="review",
            deduplication_key="review:test",
            input_artifact_ids=[self.candidate.artifact_id],
        )

    def context(self):
        return ContextService().build(
            role=AgentRole.REVIEW, task=self.task, board=self.board
        )

    def test_review_context_has_explicitly_expanded_blackboard_and_artifacts(self) -> None:
        context = self.context()

        self.assertEqual(context.current_message, "已脱敏的当前消息")
        self.assertEqual(context.facts.confirmed, {"confirmed": "yes"})
        self.assertEqual(context.facts.candidates, {"candidate": "pending"})
        self.assertEqual(context.facts.disputed_keys, ("disputed",))
        self.assertEqual(context.facts.missing_keys, ("missing",))
        self.assertEqual(
            {item.artifact_type for item in context.artifacts},
            {ArtifactType.RESPONSE_CANDIDATE, ArtifactType.RISK_REVIEW},
        )

    def test_review_reuses_f18_escalation_schema_and_does_not_reschedule_safety_itself(self) -> None:
        delivery = ReviewAgent(SafetyRecheckCandidate()).execute(
            self.board, self.task, self.context()
        )

        escalation_artifact = next(
            item for item in delivery.artifacts
            if item.artifact_type == ArtifactType.ESCALATION_REQUEST
        )
        request = EscalationRequest.model_validate(escalation_artifact.content)
        self.assertEqual(request.reason_code, EscalationReasonCode.POLICY_CONFLICT)
        self.assertEqual(delivery.derived_tasks[0].task_type, "schedule_next")
        self.assertNotIn("assess_safety", [item.task_type for item in delivery.derived_tasks])
        self.assertNotIn(ArtifactType.FINAL_RESPONSE, [item.artifact_type for item in delivery.artifacts])

    def test_scheduler_not_review_decides_to_request_safety_capability(self) -> None:
        escalation = EscalationRequest(
            task_id=self.task.task_id,
            board_id=self.board.run_id,
            origin_agent="review-agent-v0",
            reason_code=EscalationReasonCode.POLICY_CONFLICT,
            reason_detail="需要重新评估安全风险",
        )
        artifact = Artifact(
            run_id=self.board.run_id,
            task_id=self.task.task_id,
            artifact_type=ArtifactType.ESCALATION_REQUEST,
            producer_agent="review-agent-v0",
            content=escalation.model_dump(mode="json"),
        )
        self.board.artifacts.append(artifact)
        scheduler_task = BoardTask(
            run_id=self.board.run_id,
            task_type="schedule_next",
            objective="decide",
            deduplication_key="scheduler:review",
            input_artifact_ids=[artifact.artifact_id],
        )
        context = ContextService().build(
            role=AgentRole.SCHEDULER, task=scheduler_task, board=self.board
        )

        decision = SchedulerAgent().decide_next_step(self.board, scheduler_task, context)

        self.assertIsInstance(decision, TaskIntent)
        self.assertEqual(decision.required_capability, "risk_assessment")


if __name__ == "__main__":
    unittest.main()
