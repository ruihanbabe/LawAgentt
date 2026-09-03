from __future__ import annotations

import unittest

from intake.blackboard import ConsultationIntent
from runtime.board_runtime import SchedulerAgent, TaskBoardRuntime, build_default_agents
from runtime.context import ContextService
from runtime.messages import AgentRole
from runtime.scheduling import EscalationReasonCode, EscalationRequest, TaskIntent
from runtime.taskboard import AgentRunBoard, ArtifactType, BoardTask
from scenario_pack import RentalDepositScenarioPack


class RecordingCandidate:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def generate(self, **kwargs):
        self.calls += 1
        return self.result


class SchedulerAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = RentalDepositScenarioPack()
        self.board = AgentRunBoard(sanitized_input="test")

    def task(self, suffix: str = "one") -> BoardTask:
        return BoardTask(
            run_id=self.board.run_id,
            task_type="schedule_next",
            objective="schedule",
            required_capabilities=["task_scheduling"],
            deduplication_key=f"schedule:{suffix}",
        )

    def context(self, task: BoardTask):
        return ContextService().build(role=AgentRole.SCHEDULER, task=task, board=self.board)

    def complete_intake(self) -> None:
        self.board.blackboard.confirmed_facts = {
            spec.key: "confirmed"
            for spec in self.pack.required_fact_keys("intake")
            if spec.required
        }
        self.board.blackboard.sufficiency.confirmed_intent = ConsultationIntent.LEGAL_BASIS

    def test_incomplete_intake_uses_understanding_fast_path_without_model(self) -> None:
        candidate = RecordingCandidate({"required_capability": "context_retrieval"})
        agent = SchedulerAgent(candidate, self.pack)
        task = self.task()

        decision = agent.decide_next_step(self.board, task, self.context(task))

        self.assertIsInstance(decision, TaskIntent)
        self.assertEqual(decision.required_capability, "understanding")
        self.assertEqual(candidate.calls, 0)
        self.assertIn("confirmed_facts", self.pack.dispatch_trigger_fields())

    def test_unconfirmed_intent_remains_within_fast_path(self) -> None:
        self.board.blackboard.confirmed_facts = {
            spec.key: "confirmed" for spec in self.pack.required_fact_keys("intake") if spec.required
        }
        candidate = RecordingCandidate(None)
        agent = SchedulerAgent(candidate, self.pack)
        task = self.task()

        decision = agent.decide_next_step(self.board, task, self.context(task))

        self.assertEqual(decision.required_capability, "understanding")
        self.assertEqual(candidate.calls, 0)

    def test_ready_intake_calls_model_and_creates_capability_task_not_agent_target(self) -> None:
        self.complete_intake()
        candidate = RecordingCandidate({
            "required_capability": "context_retrieval",
            "priority": 80,
            "context_refs": [],
            "budget_hint": 2,
            "reason_code": None,
            "reason_detail": None,
        })
        agent = SchedulerAgent(candidate, self.pack)
        task = self.task()

        delivery = agent.execute(self.board, task, self.context(task))

        self.assertEqual(candidate.calls, 1)
        self.assertEqual(delivery.artifacts[0].artifact_type, ArtifactType.TASK_INTENT)
        self.assertEqual(delivery.derived_tasks[0].required_capabilities, ["context_retrieval"])
        self.assertEqual(delivery.derived_tasks[0].task_type, "retrieve_context")
        self.assertNotIn("agent_id", delivery.artifacts[0].content)

    def test_unknown_capability_becomes_escalation(self) -> None:
        self.complete_intake()
        candidate = RecordingCandidate({
            "required_capability": "specific-agent-v1",
            "priority": 0,
            "context_refs": [],
            "budget_hint": None,
            "reason_code": None,
            "reason_detail": None,
        })
        agent = SchedulerAgent(candidate, self.pack)
        task = self.task()

        decision = agent.decide_next_step(self.board, task, self.context(task))

        self.assertIsInstance(decision, EscalationRequest)
        self.assertEqual(decision.reason_code, EscalationReasonCode.CAPABILITY_MISMATCH)

    def test_repeated_scheduler_decision_is_stopped_deterministically(self) -> None:
        self.complete_intake()
        candidate = RecordingCandidate({
            "required_capability": "context_retrieval", "priority": 80,
            "context_refs": [], "budget_hint": None,
            "reason_code": None, "reason_detail": None,
        })
        agent = SchedulerAgent(candidate, self.pack)
        deliveries = []
        for index in range(3):
            task = self.task(str(index))
            deliveries.append(agent.execute(self.board, task, self.context(task)))

        self.assertEqual(deliveries[-1].artifacts[0].artifact_type, ArtifactType.ESCALATION_REQUEST)
        self.assertEqual(deliveries[-1].derived_tasks, [])

    def test_default_runtime_always_executes_safety_before_scheduler(self) -> None:
        board = AgentRunBoard(sanitized_input="普通咨询")
        runtime = TaskBoardRuntime(build_default_agents())

        runtime.run(board)

        self.assertGreaterEqual(len(board.tasks), 2)
        self.assertEqual(board.tasks[0].task_type, "assess_safety")
        self.assertEqual(board.tasks[1].task_type, "schedule_next")
        self.assertEqual(board.tasks[1].claimed_by, "scheduler-agent-v0")


if __name__ == "__main__":
    unittest.main()
