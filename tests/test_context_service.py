from __future__ import annotations

import unittest

from runtime.context import ContextService
from runtime.messages import AgentRole
from persistence.storage import HistoryMessage
from runtime.taskboard import AgentRunBoard, Artifact, ArtifactType, BoardTask


class ContextServiceTests(unittest.TestCase):
    def setUp(self):
        self.board = AgentRunBoard(sanitized_input="房东不退押金，手机号已脱敏")
        self.board.blackboard.confirmed_facts = {"tenancy_ended": "yes"}
        self.board.blackboard.candidate_facts = {"landlord_reason": "损坏"}
        self.board.blackboard.disputed_fact_keys = ["damage_amount"]
        self.board.blackboard.sufficiency.missing_fact_keys = ["contract_terms"]
        self.evidence = Artifact(
            run_id=self.board.run_id,
            task_id="retrieval-task",
            artifact_type=ArtifactType.RAG_EVIDENCE_BUNDLE,
            producer_agent="retrieval-agent",
            content={"results": [{"safe": "view"}]},
            evidence_refs=["law:1", "case:2"],
        )
        self.board.artifacts.append(self.evidence)
        self.history = [
            HistoryMessage(
                session_id="session-1",
                run_id=self.board.run_id,
                role="user",
                content="此前的脱敏消息",
            )
        ]

    def task(self, artifact_ids=None):
        return BoardTask(
            run_id=self.board.run_id,
            task_type="demo",
            objective="执行当前角色任务",
            deduplication_key="demo:context",
            input_artifact_ids=list(artifact_ids or []),
        )

    def test_safety_gets_current_message_but_not_case_facts_or_evidence(self):
        view = ContextService().build(
            role=AgentRole.SAFETY,
            task=self.task([self.evidence.artifact_id]),
            board=self.board,
            history=self.history,
        )

        self.assertEqual(view.current_message, self.board.sanitized_input)
        self.assertEqual(view.facts.confirmed, {})
        self.assertEqual(view.artifacts, ())
        self.assertEqual(view.evidence_ids, ())
        self.assertEqual(len(view.history), 1)

    def test_analysis_gets_facts_and_only_explicit_evidence_artifact(self):
        view = ContextService().build(
            role=AgentRole.ANALYSIS,
            task=self.task([self.evidence.artifact_id]),
            board=self.board,
            history=self.history,
        )

        self.assertIsNone(view.current_message)
        self.assertEqual(view.history, ())
        self.assertEqual(view.facts.confirmed, {"tenancy_ended": "yes"})
        self.assertEqual(view.facts.candidates, {"landlord_reason": "损坏"})
        self.assertEqual(view.evidence_ids, ("law:1", "case:2"))
        self.assertEqual(view.artifacts[0].artifact_id, self.evidence.artifact_id)
        self.assertTrue(any(ref.source_type == "artifact" for ref in view.source_refs))

    def test_retrieval_receives_only_allowlisted_tool_names(self):
        view = ContextService().build(
            role=AgentRole.RETRIEVAL,
            task=self.task(),
            board=self.board,
        )
        self.assertEqual(view.allowed_tool_names, ("search_statutes", "search_cases"))

    def test_review_follows_explicit_artifact_provenance_to_evidence(self):
        analysis = Artifact(
            run_id=self.board.run_id,
            task_id="analysis-task",
            artifact_type=ArtifactType.ISSUE_ANALYSIS,
            producer_agent="analysis-agent",
            source_artifact_ids=[self.evidence.artifact_id],
            evidence_refs=list(self.evidence.evidence_refs),
            content={"claims": []},
        )
        candidate = Artifact(
            run_id=self.board.run_id,
            task_id="response-task",
            artifact_type=ArtifactType.RESPONSE_CANDIDATE,
            producer_agent="response-agent",
            source_artifact_ids=[analysis.artifact_id],
            evidence_refs=list(self.evidence.evidence_refs),
            content={"response": "候选回复"},
        )
        self.board.artifacts.extend([analysis, candidate])
        view = ContextService().build(
            role=AgentRole.REVIEW,
            task=self.task([candidate.artifact_id]),
            board=self.board,
        )
        self.assertEqual(
            [item.artifact_type for item in view.artifacts],
            [ArtifactType.RESPONSE_CANDIDATE, ArtifactType.ISSUE_ANALYSIS, ArtifactType.RAG_EVIDENCE_BUNDLE],
        )
        self.assertEqual(view.evidence_ids, ("law:1", "case:2"))

    def test_history_is_dropped_before_required_context_when_over_budget(self):
        long_history = [self.history[0].model_copy(update={"content": "历史" * 1_000})]
        view = ContextService(max_chars=1_200).build(
            role=AgentRole.INTAKE,
            task=self.task(),
            board=self.board,
            history=long_history,
        )
        self.assertTrue(view.is_truncated)
        self.assertEqual(view.omitted_sections, ("history",))
        self.assertEqual(view.history, ())

    def test_view_is_immutable_and_hash_is_stable_for_same_payload(self):
        service = ContextService()
        task = self.task([self.evidence.artifact_id])
        first = service.build(role=AgentRole.ANALYSIS, task=task, board=self.board)
        second = service.build(role=AgentRole.ANALYSIS, task=task, board=self.board)
        self.assertEqual(first.content_hash, second.content_hash)
        with self.assertRaises(Exception):
            first.objective = "mutated"


if __name__ == "__main__":
    unittest.main()
