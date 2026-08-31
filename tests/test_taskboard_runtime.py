from __future__ import annotations

import unittest

from lawagent_runtime.board_runtime import (
    AgentDelivery,
    IntentAgent,
    SafeResponseAgent,
    TaskBoardRuntime,
    build_default_agents,
)
from lawagent_runtime.harness import ConversationHarness, RuntimeRegistry
from lawagent_runtime.messages import AgentRole
from lawagent_runtime.evidence_views import CaseEvidenceView, LawEvidenceView
from lawagent_runtime.tools import (
    ToolExecutor,
    ToolPermission,
    ToolRegistry,
    ToolResult,
    ToolResultStatus,
    ToolSpec,
)
from lawagent_runtime.taskboard import (
    AgentRunBoard,
    Artifact,
    ArtifactType,
    BoardLimits,
    BoardTask,
    EventType,
    RunStatus,
    TaskStatus,
)


class ClaimingAgent:
    role = AgentRole.ANALYSIS
    capabilities = frozenset({"demo"})

    def __init__(self, agent_id: str, confidence: float):
        self.agent_id = agent_id
        self.confidence = confidence
        self.calls = 0

    def confidence_for(self, board, task):
        return self.confidence

    def execute(self, board, task, context):
        self.calls += 1
        return AgentDelivery(
            artifacts=[
                Artifact(
                    run_id=board.run_id,
                    task_id=task.task_id,
                    artifact_type=ArtifactType.FINAL_RESPONSE,
                    producer_agent=self.agent_id,
                    content={"response": self.agent_id},
                )
            ]
        )


class EvidenceAdapter:
    def __init__(self, name, permission, item):
        self.spec = ToolSpec(
            name=name,
            description=f"fake {name}",
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}},
                "additionalProperties": False,
            },
            output_schema={},
            permissions=[permission],
        )
        self.item = item
        self.calls = []

    def execute(self, arguments):
        self.calls.append(dict(arguments))
        return ToolResult(
            tool_name=self.spec.name,
            status=ToolResultStatus.SUCCESS,
            items=[self.item],
        )


class TaskBoardRuntimeTests(unittest.TestCase):
    def test_higher_confidence_claim_wins_but_unreviewed_final_is_blocked(self):
        low = ClaimingAgent("agent-low", 0.4)
        high = ClaimingAgent("agent-high", 0.9)
        runtime = TaskBoardRuntime([low, high])
        board = AgentRunBoard(sanitized_input="测试")
        runtime.add_task(
            board,
            BoardTask(
                run_id=board.run_id,
                task_type="demo",
                objective="测试claim仲裁",
                required_capabilities=["demo"],
                deduplication_key="demo:1",
            ),
        )

        runtime.run(board)

        self.assertEqual(low.calls, 0)
        self.assertEqual(high.calls, 1)
        self.assertEqual(board.status, RunStatus.FAILED)
        self.assertEqual(board.artifact(board.accepted_artifact_id).producer_agent, "delivery-gate-v0.1")
        self.assertEqual(board.artifact(board.accepted_artifact_id).content["decision"], "safe_error")
        event_types = [event.event_type for event in board.events]
        self.assertIn(EventType.CLAIM_REJECTED, event_types)
        self.assertIn(EventType.DELIVERY_BLOCKED, event_types)
        self.assertIn(EventType.ARTIFACT_ACCEPTED, event_types)

    def test_task_deduplication_prevents_duplicate_open_work(self):
        runtime = TaskBoardRuntime([])
        board = AgentRunBoard(sanitized_input="测试")
        first = BoardTask(
            run_id=board.run_id,
            task_type="demo",
            objective="第一次",
            deduplication_key="same-key",
        )
        duplicate = BoardTask(
            run_id=board.run_id,
            task_type="demo",
            objective="重复",
            deduplication_key="same-key",
        )
        self.assertIsNotNone(runtime.add_task(board, first))
        self.assertIsNone(runtime.add_task(board, duplicate))
        self.assertEqual(len(board.tasks), 1)
        self.assertEqual(board.events[-1].event_type, EventType.TASK_DEDUPLICATED)

    def test_unclaimed_task_becomes_blocked_without_loop(self):
        runtime = TaskBoardRuntime([])
        board = AgentRunBoard(
            sanitized_input="测试",
            limits=BoardLimits(max_rounds=3, max_no_progress_rounds=1),
        )
        runtime.add_task(
            board,
            BoardTask(
                run_id=board.run_id,
                task_type="unsupported",
                objective="没有Agent可执行",
                required_capabilities=["missing"],
                deduplication_key="unsupported:1",
            ),
        )
        runtime.run(board)
        self.assertEqual(board.tasks[0].status, TaskStatus.BLOCKED)
        self.assertEqual(board.status, RunStatus.LIMITED)
        self.assertLessEqual(board.round, 2)


class HarnessTests(unittest.TestCase):
    def build_harness(self):
        registry = RuntimeRegistry()
        registry.register("taskboard-v0.1", TaskBoardRuntime(build_default_agents()))
        return ConversationHarness(registry)

    def test_harness_masks_pii_and_keeps_only_sanitized_input_on_board(self):
        harness = self.build_harness()
        result = harness.handle("我的手机号是13812345678，租房押金不退怎么办？", session_id="s-1")
        board = result.board

        self.assertNotIn("13812345678", board.sanitized_input)
        self.assertFalse(hasattr(board, "raw_input"))
        self.assertEqual(board.status, RunStatus.COMPLETED)
        self.assertIsNotNone(board.accepted_artifact_id)
        self.assertIn("请补充", result.response)
        self.assertGreaterEqual(len(board.messages), 1)
        self.assertEqual([event.sequence for event in board.events], list(range(len(board.events))))
        self.assertEqual(board.events[1].event_type, EventType.INPUT_SANITIZED)
        trace = harness.trace_store[board.run_id]
        self.assertEqual(trace.accepted_artifact_id, board.accepted_artifact_id)
        self.assertEqual(len(trace.tasks), 4)
        self.assertGreaterEqual(len(trace.messages), 1)
        self.assertEqual(
            harness.conversation_repository.get_trace(board.run_id).accepted_artifact_id,
            board.accepted_artifact_id,
        )
        self.assertEqual(
            [item.artifact_type for item in trace.artifacts],
            [
                ArtifactType.USER_PROFILE_SNAPSHOT,
                ArtifactType.RISK_REVIEW,
                ArtifactType.SUFFICIENCY_ASSESSMENT,
                ArtifactType.RESPONSE_CANDIDATE,
                ArtifactType.REVIEW_RESULT,
                ArtifactType.FINAL_RESPONSE,
            ],
        )

    def test_runtime_registry_rejects_unknown_profile(self):
        registry = RuntimeRegistry()
        with self.assertRaises(KeyError):
            registry.get("missing")

    def test_same_session_restores_blackboard_and_enters_retrieval_when_sufficient(self):
        harness = self.build_harness()
        first = harness.handle("房东不退租房押金", session_id="matter-session")
        second = harness.handle(
            "争议发生于2024-06-01，我已经退租并交还钥匙，房东说房屋损坏，合同写了押金条款，我有转账和聊天记录。",
            session_id="matter-session",
        )

        self.assertEqual(first.board.blackboard.sufficiency.clarification_round, 1)
        self.assertEqual(second.board.blackboard.state_version, 2)
        self.assertEqual(len(second.board.blackboard.risk_assessments), 2)
        self.assertEqual(second.board.blackboard.sufficiency.decision.value, "start_retrieval")
        self.assertIn("retrieve_context", [task.task_type for task in second.board.tasks])
        self.assertIn("有限结果", second.response)

    def test_clarification_stops_after_two_rounds_without_repeating_questions(self):
        harness = self.build_harness()
        first = harness.handle("房东不退租房押金", session_id="two-round-session")
        second = harness.handle(
            "我已经退租，房东说损坏，合同有押金约定。",
            session_id="two-round-session",
        )
        third = harness.handle("我没有其他材料", session_id="two-round-session")

        self.assertIn("交还房屋", first.response)
        self.assertNotIn("交还房屋", second.response)
        self.assertIn("沟通记录", second.response)
        self.assertEqual(second.board.blackboard.sufficiency.clarification_round, 2)
        self.assertEqual(third.board.blackboard.sufficiency.clarification_round, 2)
        self.assertNotIn("请补充", third.response)
        self.assertIn("有限结果", third.response)

    def test_retrieval_agent_uses_tool_executor_and_response_keeps_evidence_refs(self):
        law = EvidenceAdapter(
            "search_statutes",
            ToolPermission.SEARCH_PUBLIC_LAW,
            LawEvidenceView(
                chunk_id="law-1", law_family_id="civil-code", law_version_id="v1",
                title="民法典", article_no="509", content="当事人应当按照约定全面履行自己的义务。",
                validity_status="current",
                effective_from="2021-01-01",
            ),
        )
        case = EvidenceAdapter(
            "search_cases",
            ToolPermission.SEARCH_SANITIZED_CASES,
            CaseEvidenceView(case_id="case-1", title="租赁合同纠纷样例"),
        )
        registry = ToolRegistry()
        registry.register(law)
        registry.register(case)
        executor = ToolExecutor(
            registry,
            {ToolPermission.SEARCH_PUBLIC_LAW, ToolPermission.SEARCH_SANITIZED_CASES},
        )
        runtime_registry = RuntimeRegistry()
        runtime_registry.register("taskboard-v0.1", TaskBoardRuntime(build_default_agents(executor)))
        harness = ConversationHarness(runtime_registry)

        result = harness.handle(
            "争议发生于2024-06-01，我已退租交还钥匙，房东说损坏，合同有押金条款，我有转账和聊天记录。",
            session_id="tool-session",
        )

        self.assertEqual(len(law.calls), 1)
        self.assertEqual(len(case.calls), 1)
        self.assertEqual(result.board.blackboard.evidence_ids, ["law:law-1", "case:case-1"])
        self.assertIn("law:law-1", result.response)
        self.assertIn("case:case-1", result.response)
        evidence = next(
            item for item in result.board.artifacts
            if item.artifact_type == ArtifactType.RAG_EVIDENCE_BUNDLE
        )
        self.assertEqual(evidence.content["evidence_count"], 2)


if __name__ == "__main__":
    unittest.main()
