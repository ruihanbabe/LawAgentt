from __future__ import annotations

import unittest
from unittest.mock import patch

from api.sse import ChatInput, build_chat_stream
from runtime.board_runtime import AgentDelivery, TaskBoardRuntime, build_default_agents
from knowledge.evidence_views import CaseEvidenceView, LawEvidenceView
from conversation.harness import ConversationHarness, RuntimeRegistry
from runtime.messages import AgentRole
from runtime.taskboard import Artifact, ArtifactType, EventType, RunStatus
from runtime.tools import (
    ToolExecutor,
    ToolPermission,
    ToolRegistry,
    ToolResult,
    ToolResultStatus,
    ToolSpec,
)


class ConnectedRequest:
    async def is_disconnected(self):
        return False


class EvidenceAdapter:
    def __init__(self, name, permission, item):
        self.spec = ToolSpec(
            name=name,
            description=name,
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

    def execute(self, arguments):
        return ToolResult(tool_name=self.spec.name, status=ToolResultStatus.SUCCESS, items=[self.item])


class UnreviewedFinalAgent:
    agent_id = "unsafe-direct-final"
    role = AgentRole.SAFETY
    capabilities = frozenset({"risk_assessment"})

    def confidence_for(self, board, task):
        return 1.0

    def execute(self, board, task, context):
        return AgentDelivery(artifacts=[Artifact(
            run_id=board.run_id,
            task_id=task.task_id,
            artifact_type=ArtifactType.FINAL_RESPONSE,
            producer_agent=self.agent_id,
            content={"response": "未经复核的法律结论", "decision": "supported_answer", "claims": []},
        )])


def build_success_harness():
    registry = ToolRegistry()
    registry.register(EvidenceAdapter(
        "search_statutes",
        ToolPermission.SEARCH_PUBLIC_LAW,
        LawEvidenceView(
            chunk_id="law-e2e",
            law_family_id="civil-code",
            law_version_id="snapshot-v1",
            title="民法典",
            article_no="509",
            content="当事人应当按照约定全面履行自己的义务。",
            validity_status="current",
            effective_from="2021-01-01",
        ),
    ))
    registry.register(EvidenceAdapter(
        "search_cases",
        ToolPermission.SEARCH_SANITIZED_CASES,
        CaseEvidenceView(case_id="case-e2e", title="租赁合同纠纷样例"),
    ))
    executor = ToolExecutor(
        registry,
        {ToolPermission.SEARCH_PUBLIC_LAW, ToolPermission.SEARCH_SANITIZED_CASES},
    )
    runtimes = RuntimeRegistry()
    runtimes.register("taskboard-v0.1", TaskBoardRuntime(build_default_agents(executor)))
    return ConversationHarness(runtimes)


def build_failure_harness():
    runtimes = RuntimeRegistry()
    runtimes.register("taskboard-v0.1", TaskBoardRuntime([UnreviewedFinalAgent()]))
    return ConversationHarness(runtimes)


def build_limited_harness():
    runtimes = RuntimeRegistry()
    runtimes.register("taskboard-v0.1", TaskBoardRuntime(build_default_agents()))
    return ConversationHarness(runtimes)


def build_unverified_law_harness():
    registry = ToolRegistry()
    registry.register(EvidenceAdapter(
        "search_statutes",
        ToolPermission.SEARCH_PUBLIC_LAW,
        LawEvidenceView(
            chunk_id="law-unverified",
            law_family_id="civil-code",
            law_version_id="unknown-version",
            title="民法典快照",
            content="未经效力核验的法规内容。",
            validity_status="unverified",
            effective_from="2021-01-01",
        ),
    ))
    registry.register(EvidenceAdapter(
        "search_cases",
        ToolPermission.SEARCH_SANITIZED_CASES,
        CaseEvidenceView(case_id="case-unverified", title="租赁纠纷案例夹具"),
    ))
    executor = ToolExecutor(
        registry,
        {ToolPermission.SEARCH_PUBLIC_LAW, ToolPermission.SEARCH_SANITIZED_CASES},
    )
    runtimes = RuntimeRegistry()
    runtimes.register("taskboard-v0.1", TaskBoardRuntime(build_default_agents(executor)))
    return ConversationHarness(runtimes)


class DeliveryGateSseE2ETests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_success_delivers_only_after_gate_accepts(self):
        harness = build_success_harness()
        with patch("api.sse.conversation_harness", harness):
            frames = [item async for item in build_chat_stream(
                req=ChatInput(
                    text="争议发生于2024-06-01，我已退租交还钥匙，房东说损坏，合同有押金条款，我有转账和聊天记录。",
                    user_id="delivery-success",
                ),
                request=ConnectedRequest(),
            )]
        stream = "".join(frames)
        self.assertIn("初步分析", stream)
        self.assertIn("law:law-e2e", stream)
        self.assertEqual(frames[-1], "data: [DONE]\n\n")
        board = next(iter(harness.run_store.values()))
        self.assertEqual(board.status, RunStatus.COMPLETED)
        self.assertIn(EventType.DELIVERY_ACCEPTED, [item.event_type for item in board.events])
        self.assertEqual(board.artifact(board.accepted_artifact_id).content["decision"], "supported_answer")

    async def test_chat_failure_returns_deterministic_safe_error(self):
        harness = build_failure_harness()
        with patch("api.sse.conversation_harness", harness):
            frames = [item async for item in build_chat_stream(
                req=ChatInput(text="请直接给我结论。", user_id="delivery-failure"),
                request=ConnectedRequest(),
            )]
        stream = "".join(frames)
        self.assertIn("当前无法安全生成回复", stream)
        self.assertNotIn("未经复核的法律结论", stream)
        self.assertEqual(frames[-1], "data: [DONE]\n\n")
        board = next(iter(harness.run_store.values()))
        self.assertEqual(board.status, RunStatus.FAILED)
        self.assertIn(EventType.DELIVERY_BLOCKED, [item.event_type for item in board.events])
        self.assertEqual(board.artifact(board.accepted_artifact_id).content["decision"], "safe_error")

    async def test_chat_limited_answer_when_retrieval_is_unavailable(self):
        harness = build_limited_harness()
        with patch("api.sse.conversation_harness", harness):
            frames = [item async for item in build_chat_stream(
                req=ChatInput(
                    text="争议发生于2024-06-01，我已退租交还钥匙，房东说损坏，合同有押金条款，我有转账和聊天记录。",
                    user_id="delivery-limited",
                ),
                request=ConnectedRequest(),
            )]
        stream = "".join(frames)
        self.assertIn("本轮只提供有限结果", stream)
        board = next(iter(harness.run_store.values()))
        accepted = board.artifact(board.accepted_artifact_id)
        self.assertEqual(board.status, RunStatus.COMPLETED)
        self.assertEqual(accepted.content["decision"], "limited_answer")
        self.assertTrue(accepted.content["limitations"])

    async def test_chat_abstains_when_law_version_is_unverified(self):
        harness = build_unverified_law_harness()
        with patch("api.sse.conversation_harness", harness):
            frames = [item async for item in build_chat_stream(
                req=ChatInput(
                    text="争议发生于2024-06-01，我已退租交还钥匙，房东说损坏，合同有押金条款，我有转账和聊天记录。",
                    user_id="delivery-abstention",
                ),
                request=ConnectedRequest(),
            )]
        stream = "".join(frames)
        self.assertIn("法规版本或效力状态尚未确认", stream)
        board = next(iter(harness.run_store.values()))
        accepted = board.artifact(board.accepted_artifact_id)
        self.assertEqual(board.status, RunStatus.COMPLETED)
        self.assertEqual(accepted.content["decision"], "constructive_abstention")
        self.assertEqual(accepted.content["claims"], [])


if __name__ == "__main__":
    unittest.main()
