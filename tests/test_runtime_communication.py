from __future__ import annotations

import unittest

from pydantic import ValidationError

from lawagent_runtime.messages import AgentMessage, AgentRole, MessageType
from lawagent_runtime.observations import Observation, ObservationStatus
from lawagent_runtime.patches import PatchOperation, PatchTarget, StatePatch
from lawagent_runtime.permissions import PermissionError, apply_authorized_patch
from lawagent_runtime.state import EvidenceRelation, FactStatus, RunState, SourceType, Stage


class RuntimeCommunicationTest(unittest.TestCase):
    def test_agent_message_validates_human_target(self) -> None:
        state = RunState.start("押金不退")
        message = AgentMessage(
            run_id=state.run_id,
            from_role=AgentRole.HUMAN,
            to_role=AgentRole.ORCHESTRATOR,
            message_type=MessageType.USER_PROBLEM,
            payload={"raw_query": state.raw_query},
        )
        self.assertEqual(message.run_id, state.run_id)
        with self.assertRaises(ValidationError):
            AgentMessage(
                run_id=state.run_id,
                from_role=AgentRole.HUMAN,
                to_role=AgentRole.INTAKE,
                message_type=MessageType.USER_PROBLEM,
            )

    def test_retrieval_agent_can_append_evidence(self) -> None:
        state = RunState.start("租赁合同押金")
        patch = StatePatch(
            run_id=state.run_id,
            author_role=AgentRole.RETRIEVAL,
            target=PatchTarget.EVIDENCE_ITEMS,
            operation=PatchOperation.APPEND,
            payload={
                "evidence_id": "law-1",
                "source_type": SourceType.STATUTE,
                "source_id": "chunk-1",
                "title": "中华人民共和国民法典",
                "citation_label": "《中华人民共和国民法典》第七百零三条",
                "content_snippet": "租赁合同是出租人将租赁物交付承租人使用、收益...",
                "supports": EvidenceRelation.SUPPORTS,
            },
            reason="法规检索命中租赁合同定义",
        )
        apply_authorized_patch(state, patch)
        self.assertEqual(len(state.evidence_items), 1)
        self.assertEqual(state.evidence_items[0].evidence_id, "law-1")
        self.assertEqual(state.trace[-1].node_name, "apply_state_patch")

    def test_intake_agent_cannot_append_evidence(self) -> None:
        state = RunState.start("租赁合同押金")
        patch = StatePatch(
            run_id=state.run_id,
            author_role=AgentRole.INTAKE,
            target=PatchTarget.EVIDENCE_ITEMS,
            operation=PatchOperation.APPEND,
            payload={"evidence_id": "bad", "source_type": "statute", "source_id": "chunk"},
            reason="越权写入证据",
        )
        with self.assertRaises(PermissionError):
            apply_authorized_patch(state, patch)
        self.assertEqual(state.evidence_items, [])

    def test_review_agent_can_append_gap_but_cannot_confirm_fact(self) -> None:
        state = RunState.start("被辞退赔偿")
        gap_patch = StatePatch(
            run_id=state.run_id,
            author_role=AgentRole.REVIEW,
            target=PatchTarget.EVIDENCE_GAPS,
            operation=PatchOperation.APPEND,
            payload={
                "issue_id": "issue-1",
                "gap_type": "missing_fact",
                "description": "缺少解除劳动合同通知时间",
            },
            reason="审核发现关键事实缺失",
        )
        apply_authorized_patch(state, gap_patch)
        self.assertEqual(len(state.evidence_gaps), 1)

        fact_patch = StatePatch(
            run_id=state.run_id,
            author_role=AgentRole.REVIEW,
            target=PatchTarget.FACTS,
            operation=PatchOperation.APPEND,
            payload={"name": "解除时间", "value": "2026-08-01", "status": FactStatus.USER_CONFIRMED},
            reason="越权确认用户事实",
        )
        with self.assertRaises(PermissionError):
            apply_authorized_patch(state, fact_patch)

    def test_intake_agent_cannot_confirm_fact_in_v0(self) -> None:
        state = RunState.start("未签劳动合同")
        patch = StatePatch(
            run_id=state.run_id,
            author_role=AgentRole.INTAKE,
            target=PatchTarget.FACTS,
            operation=PatchOperation.APPEND,
            payload={"name": "未签合同", "value": True, "status": FactStatus.USER_CONFIRMED},
            reason="抽取事实",
        )
        with self.assertRaises(PermissionError):
            apply_authorized_patch(state, patch)

    def test_orchestrator_can_set_control_fields(self) -> None:
        state = RunState.start("保险拒赔")
        patch = StatePatch(
            run_id=state.run_id,
            author_role=AgentRole.ORCHESTRATOR,
            target=PatchTarget.CONTROL,
            operation=PatchOperation.SET_CONTROL,
            payload={"stage": Stage.RETRIEVING, "next_node": "retrieve", "route_reason": "facts_ready"},
            reason="进入检索阶段",
        )
        apply_authorized_patch(state, patch)
        self.assertEqual(state.stage, Stage.RETRIEVING)
        self.assertEqual(state.next_node, "retrieve")

    def test_non_orchestrator_cannot_set_control_fields(self) -> None:
        state = RunState.start("消费退款")
        patch = StatePatch(
            run_id=state.run_id,
            author_role=AgentRole.ANALYSIS,
            target=PatchTarget.CONTROL,
            operation=PatchOperation.SET_CONTROL,
            payload={"stage": Stage.COMPLETED},
            reason="越权结束流程",
        )
        with self.assertRaises(PermissionError):
            apply_authorized_patch(state, patch)

    def test_observation_groups_message_and_patches(self) -> None:
        state = RunState.start("拖欠工资")
        message = AgentMessage(
            run_id=state.run_id,
            from_role=AgentRole.INTAKE,
            to_role=AgentRole.ORCHESTRATOR,
            message_type=MessageType.FACT_PROFILE,
            payload={"facts": [{"name": "争议类型", "value": "拖欠工资"}]},
        )
        patch = StatePatch.from_message(
            message,
            target=PatchTarget.FACTS,
            operation=PatchOperation.APPEND,
            payload={"name": "争议类型", "value": "拖欠工资", "status": FactStatus.SYSTEM_EXTRACTED},
            reason="抽取劳动纠纷事实",
        )
        observation = Observation(
            node_name="intake",
            agent_role=AgentRole.INTAKE,
            status=ObservationStatus.SUCCESS,
            message=message,
            state_patches=[patch],
        )
        self.assertEqual(observation.state_patches[0].source_message_id, message.message_id)


if __name__ == "__main__":
    unittest.main()
