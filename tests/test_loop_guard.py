from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from infrastructure.glm_provider import GLMProvider
from runtime.model_provider import ProviderRequest
from runtime.scheduling import (
    EscalationReasonCode,
    EscalationRequest,
    HandoffGuard,
    LoopGuard,
    LoopReason,
    SchedulingBudget,
    TaskIntent,
    action_fingerprint,
    terminate_for_guard,
)
from runtime.taskboard import AgentRunBoard, BoardTask, EventType, TaskStatus


class FakeCompletions:
    def create(self, **kwargs):
        message = json.dumps({"required_capability": "context_retrieval"})
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=message),
                finish_reason="stop",
            )],
            usage=SimpleNamespace(prompt_tokens=8, completion_tokens=5),
        )


class LoopGuardTests(unittest.TestCase):
    def test_fake_provider_parses_complete_glm_wrapper(self) -> None:
        client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
        request = ProviderRequest(
            request_id="request",
            model="fake",
            system_prompt="",
            user_prompt="decide",
            context={},
            response_schema={"type": "object"},
            max_output_tokens=100,
            temperature=0,
            timeout_ms=1000,
        )

        response = GLMProvider(client=client).generate(request)

        self.assertEqual(response.structured_output, {"required_capability": "context_retrieval"})
        self.assertEqual((response.input_tokens, response.output_tokens), (8, 5))

    def test_fingerprint_masks_pii_and_removes_volatile_values(self) -> None:
        first = action_fingerprint({
            "task_id": "task_random_one",
            "payload": {"phone": "13800138000", "capability": "analysis"},
            "created_at": "2026-01-01T01:02:03Z",
        })
        second = action_fingerprint({
            "created_at": "2027-02-02T03:04:05Z",
            "payload": {"capability": "analysis", "phone": "13900139000"},
            "task_id": "task_random_two",
        })
        self.assertEqual(first, second)

    def test_three_identical_decisions_trigger_repeated_action(self) -> None:
        guard = LoopGuard()
        for _ in range(2):
            self.assertFalse(guard.observe({"capability": "analysis"}, made_progress=True).detected)
        result = guard.observe({"capability": "analysis"}, made_progress=True)
        self.assertEqual(result.reason, LoopReason.REPEATED_ACTION)

    def test_three_distinct_no_progress_actions_trigger(self) -> None:
        guard = LoopGuard()
        for value in (1, 2):
            guard.observe({"step": value}, made_progress=False)
        result = guard.observe({"step": 3}, made_progress=False)
        self.assertEqual(result.reason, LoopReason.NO_PROGRESS)

    def test_period_two_cycle_triggers(self) -> None:
        guard = LoopGuard()
        for value in ("a", "b", "a"):
            guard.observe({"step": value}, made_progress=True)
        result = guard.observe({"step": "b"}, made_progress=True)
        self.assertEqual(result.reason, LoopReason.SHORT_CYCLE)

    def test_three_equal_errors_trigger(self) -> None:
        guard = LoopGuard()
        for value in (1, 2):
            guard.observe({"step": value}, made_progress=True, error_code="timeout")
        result = guard.observe({"step": 3}, made_progress=True, error_code="timeout")
        self.assertEqual(result.reason, LoopReason.REPEATED_ERROR)

    def test_protocol_models_forbid_agent_target_and_are_frozen(self) -> None:
        intent = TaskIntent(board_id="run", required_capability="analysis")
        with self.assertRaises(ValueError):
            TaskIntent(board_id="run", required_capability="analysis", agent_id="specific")
        with self.assertRaises(Exception):
            intent.priority = 10
        request = EscalationRequest(
            task_id="task", board_id="run", origin_agent="origin",
            reason_code=EscalationReasonCode.OTHER, reason_detail="needs review",
        )
        with self.assertRaises(Exception):
            request.attempted_count = 2

    def test_three_level_budget_is_monotonic_and_cannot_reset_on_retry(self) -> None:
        budget = SchedulingBudget(max_node_steps=2, max_task_steps=3, max_run_steps=4)
        self.assertTrue(budget.consume(node_id="node-a", task_id="task-a"))
        self.assertTrue(budget.consume(node_id="node-a", task_id="task-a"))
        self.assertFalse(budget.consume(node_id="node-a", task_id="task-a"))
        self.assertEqual(budget.node_steps["node-a"], 2)
        self.assertTrue(budget.consume(node_id="node-b", task_id="task-a"))
        self.assertFalse(budget.consume(node_id="node-c", task_id="task-a"))
        self.assertEqual(budget.task_steps["task-a"], 3)

    def test_handoff_limit_allows_exactly_one_fallback_replan(self) -> None:
        guard = HandoffGuard(max_handoffs=3)
        self.assertEqual([guard.next_action() for _ in range(3)], ["handoff"] * 3)
        self.assertEqual(guard.next_action(), "fallback_replan")
        self.assertEqual(guard.next_action(), "terminate")

    def test_guard_termination_cancels_task_records_event_and_releases(self) -> None:
        board = AgentRunBoard(sanitized_input="test")
        task = BoardTask(
            run_id=board.run_id, task_type="work", objective="work",
            deduplication_key="work:test",
        )
        board.tasks.append(task)
        released: list[bool] = []

        request = terminate_for_guard(
            board, task, origin_agent="worker", detail="loop", release=lambda: released.append(True)
        )

        self.assertEqual(task.status, TaskStatus.CANCELLED)
        self.assertEqual(request.reason_code, EscalationReasonCode.BUDGET_AT_RISK)
        self.assertEqual(board.events[-1].event_type, EventType.BUDGET_EXHAUSTED)
        self.assertEqual(released, [True])


if __name__ == "__main__":
    unittest.main()
