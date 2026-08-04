from __future__ import annotations

import unittest

from lawagent_runtime.messages import AgentMessage, AgentRole, MessageType
from lawagent_runtime.nodes import NodeConfig, NodeRegistry
from lawagent_runtime.observations import Observation, ObservationStatus
from lawagent_runtime.patches import PatchOperation, PatchTarget, StatePatch
from lawagent_runtime.runtime import AgentRuntime
from lawagent_runtime.state import (
    EvidenceRelation,
    FactStatus,
    FinalDecision,
    IssueStatus,
    RunState,
    SourceType,
    Stage,
)


class StubNode:
    def __init__(self, name: str, role: AgentRole, observation: Observation) -> None:
        self.config = NodeConfig(name=name, agent_role=role)
        self.observation = observation

    def run(self, state: RunState) -> Observation:
        return self.observation


def register(registry: NodeRegistry, *nodes: StubNode) -> NodeRegistry:
    for node in nodes:
        registry.register(node)
    return registry


class RuntimeExecutionTest(unittest.TestCase):
    def test_runtime_executes_minimal_intake_plan_retrieve_answer_flow(self) -> None:
        state = RunState.start("公司拖欠工资怎么办")
        intake_message = AgentMessage(
            run_id=state.run_id,
            from_role=AgentRole.INTAKE,
            to_role=AgentRole.ORCHESTRATOR,
            message_type=MessageType.FACT_PROFILE,
        )
        plan_message = AgentMessage(
            run_id=state.run_id,
            from_role=AgentRole.INTAKE,
            to_role=AgentRole.ORCHESTRATOR,
            message_type=MessageType.FACT_PROFILE,
        )
        retrieve_message = AgentMessage(
            run_id=state.run_id,
            from_role=AgentRole.RETRIEVAL,
            to_role=AgentRole.ORCHESTRATOR,
            message_type=MessageType.RETRIEVAL_RESULT,
        )
        registry = register(
            NodeRegistry(),
            StubNode(
                "intake",
                AgentRole.INTAKE,
                Observation(
                    node_name="intake",
                    agent_role=AgentRole.INTAKE,
                    status=ObservationStatus.SUCCESS,
                    message=intake_message,
                    state_patches=[
                        StatePatch.from_message(
                            intake_message,
                            target=PatchTarget.FACTS,
                            operation=PatchOperation.APPEND,
                            payload={"name": "争议类型", "value": "拖欠工资", "status": FactStatus.SYSTEM_EXTRACTED},
                            reason="抽取初始事实",
                        )
                    ],
                ),
            ),
            StubNode(
                "plan",
                AgentRole.INTAKE,
                Observation(
                    node_name="plan",
                    agent_role=AgentRole.INTAKE,
                    status=ObservationStatus.SUCCESS,
                    message=plan_message,
                    state_patches=[
                        StatePatch.from_message(
                            plan_message,
                            target=PatchTarget.LEGAL_ISSUES,
                            operation=PatchOperation.APPEND,
                            payload={
                                "title": "拖欠工资能否主张支付",
                                "required_sources": [SourceType.STATUTE],
                                "status": IssueStatus.PENDING,
                            },
                            reason="规划劳动争议子问题",
                        )
                    ],
                ),
            ),
            StubNode(
                "retrieve",
                AgentRole.RETRIEVAL,
                Observation(
                    node_name="retrieve",
                    agent_role=AgentRole.RETRIEVAL,
                    status=ObservationStatus.SUCCESS,
                    message=retrieve_message,
                    state_patches=[
                        StatePatch.from_message(
                            retrieve_message,
                            target=PatchTarget.EVIDENCE_ITEMS,
                            operation=PatchOperation.APPEND,
                            payload={
                                "evidence_id": "law-labor-1",
                                "source_type": SourceType.STATUTE,
                                "source_id": "chunk-labor-1",
                                "citation_label": "《中华人民共和国劳动法》第五十条",
                                "content_snippet": "工资应当以货币形式按月支付给劳动者本人。",
                                "supports": EvidenceRelation.SUPPORTS,
                            },
                            reason="检索到工资支付依据",
                        )
                    ],
                ),
            ),
            StubNode(
                "answer",
                AgentRole.ANALYSIS,
                Observation(node_name="answer", agent_role=AgentRole.ANALYSIS, status=ObservationStatus.SUCCESS),
            ),
        )

        result = AgentRuntime(registry).run(state)

        self.assertEqual(result.state.stage, Stage.COMPLETED)
        self.assertEqual(result.state.final_decision, FinalDecision.SUPPORTED_ANSWER)
        self.assertEqual([item.node_name for item in result.observations], ["intake", "plan", "retrieve", "answer"])
        self.assertEqual(len(result.state.facts), 1)
        self.assertEqual(len(result.state.legal_issues), 1)
        self.assertEqual(len(result.state.evidence_items), 1)

    def test_missing_fact_routes_to_clarify_and_stops(self) -> None:
        state = RunState.start("我被辞退了")
        intake_message = AgentMessage(
            run_id=state.run_id,
            from_role=AgentRole.INTAKE,
            to_role=AgentRole.ORCHESTRATOR,
            message_type=MessageType.FACT_PROFILE,
        )
        registry = register(
            NodeRegistry(),
            StubNode(
                "intake",
                AgentRole.INTAKE,
                Observation(
                    node_name="intake",
                    agent_role=AgentRole.INTAKE,
                    status=ObservationStatus.SUCCESS,
                    message=intake_message,
                    state_patches=[
                        StatePatch.from_message(
                            intake_message,
                            target=PatchTarget.FACTS,
                            operation=PatchOperation.APPEND,
                            payload={"name": "解除原因", "status": FactStatus.MISSING},
                            reason="缺少解除原因",
                        )
                    ],
                ),
            ),
            StubNode(
                "clarify",
                AgentRole.INTAKE,
                Observation(node_name="clarify", agent_role=AgentRole.INTAKE, status=ObservationStatus.SUCCESS),
            ),
        )

        result = AgentRuntime(registry).run(state)

        self.assertEqual([item.node_name for item in result.observations], ["intake", "clarify"])
        self.assertEqual(result.state.final_decision, FinalDecision.CLARIFICATION_NEEDED)

    def test_permission_denied_patch_fails_run(self) -> None:
        state = RunState.start("押金问题")
        message = AgentMessage(
            run_id=state.run_id,
            from_role=AgentRole.INTAKE,
            to_role=AgentRole.ORCHESTRATOR,
            message_type=MessageType.FACT_PROFILE,
        )
        registry = register(
            NodeRegistry(),
            StubNode(
                "intake",
                AgentRole.INTAKE,
                Observation(
                    node_name="intake",
                    agent_role=AgentRole.INTAKE,
                    status=ObservationStatus.SUCCESS,
                    message=message,
                    state_patches=[
                        StatePatch.from_message(
                            message,
                            target=PatchTarget.EVIDENCE_ITEMS,
                            operation=PatchOperation.APPEND,
                            payload={"evidence_id": "bad", "source_type": "statute", "source_id": "chunk"},
                            reason="越权证据写入",
                        )
                    ],
                ),
            ),
        )

        result = AgentRuntime(registry).run(state)

        self.assertEqual(result.state.stage, Stage.FAILED)
        self.assertEqual(result.state.final_decision, FinalDecision.FAILED)
        self.assertEqual(result.observations[-1].error_code, "permission_denied")

    def test_missing_node_becomes_failed_observation(self) -> None:
        state = RunState.start("退款问题")
        result = AgentRuntime(NodeRegistry()).run(state)

        self.assertEqual(result.state.stage, Stage.FAILED)
        self.assertEqual(result.state.final_decision, FinalDecision.FAILED)
        self.assertEqual(result.observations[0].node_name, "intake")
        self.assertEqual(result.observations[0].error_code, "node_execution_error")


if __name__ == "__main__":
    unittest.main()
