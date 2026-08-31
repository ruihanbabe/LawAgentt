from __future__ import annotations

import unittest

from lawagent_runtime.blackboard import SufficiencyDecision
from lawagent_runtime.board_runtime import (
    AnalysisAgent,
    ResponseAgent,
    RetrievalAgent,
    ReviewAgent,
    SafetyAgent,
    UnderstandingAgent,
)
from lawagent_runtime.context import ContextService
from lawagent_runtime.messages import AgentRole
from lawagent_runtime.model_provider import ModelProfile
from lawagent_runtime.taskboard import AgentRunBoard, Artifact, ArtifactType, BoardTask


class RecordingGenerator:
    def __init__(self, outputs):
        self.outputs = outputs
        self.profiles = []

    def generate(self, **kwargs):
        profile = kwargs["profile"]
        self.profiles.append(profile)
        return self.outputs.get(profile)


class AgentModelCandidateTests(unittest.TestCase):
    def setUp(self):
        self.board = AgentRunBoard(sanitized_input="我已退租，房东说房屋损坏")
        self.contexts = ContextService()

    def task(self, task_type, objective, artifact_ids=None):
        return BoardTask(
            run_id=self.board.run_id,
            task_type=task_type,
            objective=objective,
            deduplication_key=f"{task_type}:model-test",
            input_artifact_ids=list(artifact_ids or []),
        )

    def context(self, role, task):
        return self.contexts.build(role=role, task=task, board=self.board)

    def test_safety_model_can_raise_but_not_lower_deterministic_risk(self):
        generator = RecordingGenerator({
            ModelProfile.SAFETY_FAST: {
                "level": "low", "signal_types": [], "recommended_action": "continue",
            }
        })
        self.board.sanitized_input = "房东正在打我"
        task = self.task("assess_safety", "评估风险")
        delivery = SafetyAgent(generator).execute(self.board, task, self.context(AgentRole.SAFETY, task))
        self.assertEqual(delivery.artifacts[0].risk_level, "high")

    def test_understanding_model_facts_remain_candidates(self):
        generator = RecordingGenerator({
            ModelProfile.UNDERSTANDING_STRUCTURED: {
                "candidate_facts": {"deposit_amount": "5000", "invented": "candidate"},
            }
        })
        task = self.task("understand_message", "理解消息")
        UnderstandingAgent(generator).execute(self.board, task, self.context(AgentRole.INTAKE, task))
        self.assertEqual(self.board.blackboard.candidate_facts["deposit_amount"], "5000")
        self.assertNotIn("deposit_amount", self.board.blackboard.confirmed_facts)

    def test_retrieval_model_only_changes_query_not_tool_names(self):
        generator = RecordingGenerator({ModelProfile.RETRIEVAL_PLANNER: {"query": "租赁押金 扣款依据"}})
        source = Artifact(
            run_id=self.board.run_id, task_id="source", artifact_type=ArtifactType.SUFFICIENCY_ASSESSMENT,
            producer_agent="intake", content={},
        )
        self.board.artifacts.append(source)
        task = self.task("retrieve_context", "规划检索", [source.artifact_id])
        delivery = RetrievalAgent(candidate_generator=generator).execute(
            self.board, task, self.context(AgentRole.RETRIEVAL, task)
        )
        intents = delivery.artifacts[0].content["intents"]
        self.assertEqual([item["tool_name"] for item in intents], ["search_statutes", "search_cases"])
        self.assertEqual({item["arguments"]["query"] for item in intents}, {"租赁押金 扣款依据"})

    def test_analysis_drops_claims_with_unknown_evidence(self):
        generator = RecordingGenerator({
            ModelProfile.LEGAL_ANALYSIS: {
                "claims": [{"text": "无效主张", "evidence_ids": ["law:unknown"]}],
                "limitations": [],
            }
        })
        evidence = Artifact(
            run_id=self.board.run_id, task_id="retrieval", artifact_type=ArtifactType.RAG_EVIDENCE_BUNDLE,
            producer_agent="retrieval", content={}, evidence_refs=["law:known"],
        )
        self.board.artifacts.append(evidence)
        task = self.task("analyze_evidence", "分析证据", [evidence.artifact_id])
        delivery = AnalysisAgent(generator).execute(self.board, task, self.context(AgentRole.ANALYSIS, task))
        content = delivery.artifacts[0].content
        self.assertEqual(content["claims"], [])
        self.assertEqual(content["decision"], "constructive_abstention")
        self.assertIn("版本", content["limitations"][0])

    def test_response_uses_model_text_without_changing_source_claims(self):
        generator = RecordingGenerator({ModelProfile.RESPONSE_GENERATION: {"response": "模型候选答复"}})
        self.board.blackboard.sufficiency.decision = SufficiencyDecision.DELIVER_LIMITED_RESPONSE
        analysis = Artifact(
            run_id=self.board.run_id, task_id="analysis", artifact_type=ArtifactType.ISSUE_ANALYSIS,
            producer_agent="analysis", content={
                "decision": "limited_answer", "claims": [],
                "limitations": ["现有材料不足，仅提供有限答复。"],
            },
        )
        self.board.artifacts.append(analysis)
        task = self.task("compose_response", "生成答复", [analysis.artifact_id])
        delivery = ResponseAgent(generator).execute(self.board, task, self.context(AgentRole.DRAFTING, task))
        self.assertEqual(delivery.artifacts[0].content["response"], "模型候选答复")
        self.assertEqual(delivery.artifacts[0].content["claims"], [])

    def test_review_model_can_veto_but_cannot_approve_ungrounded_claim(self):
        generator = RecordingGenerator({
            ModelProfile.INDEPENDENT_REVIEW: {"approved": True, "reason": "模型认为可交付"}
        })
        candidate = Artifact(
            run_id=self.board.run_id, task_id="response", artifact_type=ArtifactType.RESPONSE_CANDIDATE,
            producer_agent="response", content={
                "response": "候选", "claims": [{"text": "无证据", "evidence_ids": []}],
            },
        )
        self.board.artifacts.append(candidate)
        task = self.task("review_response", "复核", [candidate.artifact_id])
        delivery = ReviewAgent(generator).execute(self.board, task, self.context(AgentRole.REVIEW, task))
        self.assertFalse(delivery.artifacts[0].content["approved"])
        self.assertEqual(delivery.artifacts[0].content["reason"], "invalid_candidate")
        self.assertEqual(delivery.artifacts[1].validation_status, "invalid")


if __name__ == "__main__":
    unittest.main()
