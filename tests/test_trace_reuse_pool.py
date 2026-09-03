from __future__ import annotations

import json
import unittest
from datetime import date

from conversation.harness import ConversationHarness
from intake.blackboard import SufficiencyDecision
from persistence.storage import (
    InMemoryTraceReusePool,
    TraceReuseClaimItem,
    TraceReuseExample,
)
from persistence.trace_reuse_tools import TraceReuseSearchAdapter
from runtime.board_runtime import AnalysisAgent, ResponseAgent, ReviewAgent
from runtime.context import ContextService
from runtime.messages import AgentRole
from runtime.taskboard import AgentRunBoard, Artifact, ArtifactType, BoardTask
from runtime.tools import ToolExecutor, ToolPermission, ToolRegistry
from safety.delivery_gate import DeliveryGate
from scenario_pack import RentalDepositScenarioPack
from tests.test_delivery_gate_e2e import COMPLETE_FACTS, build_failure_harness, build_success_harness


class RecordingAnalysisCandidate:
    def __init__(self, evidence_id: str, pack: RentalDepositScenarioPack) -> None:
        self.evidence_id = evidence_id
        self.pack = pack
        self.examples = ()

    def generate(self, **kwargs):
        self.examples = kwargs["context"].auxiliary_examples
        return {
            "claims": [{"text": "仅引用本轮证据", "evidence_ids": [self.evidence_id]}],
            "limitations": ["仅供参考"],
            "claim_item_assessments": [
                {
                    "item_key": item.item_key,
                    "applicability": "applicable" if item.relief_kind != "disputed_catchall" else "uncertain",
                    "evidence_ids": [self.evidence_id],
                }
                for item in self.pack.claim_items()
            ],
        }


class TraceReusePoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_delivery_blocked_run_does_not_create_example(self) -> None:
        harness = build_failure_harness()

        await harness.handle_async("请直接给结论", session_id="failed", pseudonymous_user_id="user-failed")
        await harness.drain_background_tasks()

        examples = await _search(harness, "rental-deposit-v0.1", {})
        self.assertEqual(examples, [])

    async def test_gate_accepted_run_is_summarized_without_raw_statement_and_is_deletable(self) -> None:
        harness = build_success_harness()
        raw_statement = COMPLETE_FACTS + "，我的手机号是13800138000。"
        await harness.handle_async(
            raw_statement, session_id="accepted", pseudonymous_user_id="user-accepted"
        )
        await harness.handle_async("A", session_id="accepted", pseudonymous_user_id="user-accepted")
        await harness.drain_background_tasks()

        examples = await _search(harness, "rental-deposit-v0.1", {})

        self.assertTrue(examples)
        serialized = json.dumps(
            [item.model_dump(mode="json") for item in examples], ensure_ascii=False
        )
        self.assertNotIn(raw_statement, serialized)
        self.assertNotIn("sanitized_input", serialized)
        self.assertNotIn("raw_input", serialized)
        self.assertNotIn("13800138000", serialized)
        self.assertEqual(await harness.delete_trace_reuse_for_user("user-accepted"), len(examples))
        self.assertEqual(await _search(harness, "rental-deposit-v0.1", {}), [])

    async def test_retrieved_examples_are_auxiliary_and_never_enter_evidence_or_citations(self) -> None:
        pool = InMemoryTraceReusePool()
        pool.save_example(TraceReuseExample(
            run_id="old-run",
            session_id="old-session",
            scenario_id="rental-deposit-v0.1",
            confirmed_facts_summary={"tenancy_ended": "yes"},
            claim_items=(TraceReuseClaimItem(
                item_key="refundable_deposit_base",
                applicability="applicable",
                evidence_ids=("law:old-not-current-evidence",),
            ),),
            action_template_condition_key="old-branch",
        ))
        registry = ToolRegistry()
        registry.register(TraceReuseSearchAdapter(pool))
        executor = ToolExecutor(registry, {ToolPermission.SEARCH_TRACE_EXAMPLES})
        pack = RentalDepositScenarioPack()
        current_evidence = "law:current"
        generator = RecordingAnalysisCandidate(current_evidence, pack)
        board = AgentRunBoard(sanitized_input="当前消息")
        board.blackboard.confirmed_facts = {"tenancy_ended": "yes"}
        board.blackboard.event_date = date(2024, 1, 1)
        board.blackboard.sufficiency.decision = SufficiencyDecision.START_RETRIEVAL
        evidence = Artifact(
            run_id=board.run_id,
            task_id="retrieval",
            artifact_type=ArtifactType.RAG_EVIDENCE_BUNDLE,
            producer_agent="retrieval",
            evidence_refs=[current_evidence],
            content={"results": [{"items": [{
                "kind": "law", "chunk_id": "current", "law_family_id": "family",
                "law_version_id": "version", "title": "规则", "content": "规则内容",
                "validity_status": "current", "effective_from": "2021-01-01",
            }]}]},
        )
        board.artifacts.append(evidence)
        analysis_task = _task(board, "analyze_evidence", [evidence.artifact_id])
        analysis_context = ContextService().build(
            role=AgentRole.ANALYSIS, task=analysis_task, board=board
        )

        analysis_delivery = AnalysisAgent(generator, pack, executor).execute(
            board, analysis_task, analysis_context
        )
        analysis = analysis_delivery.artifacts[0]
        board.artifacts.append(analysis)
        response_task = _task(board, "compose_response", [analysis.artifact_id])
        response = ResponseAgent(scenario_pack=pack).execute(
            board,
            response_task,
            ContextService().build(role=AgentRole.DRAFTING, task=response_task, board=board),
        ).artifacts[0]
        board.artifacts.append(response)
        review_task = _task(board, "review_response", [response.artifact_id])
        review_delivery = ReviewAgent().execute(
            board,
            review_task,
            ContextService().build(role=AgentRole.REVIEW, task=review_task, board=board),
        )
        board.artifacts.extend(review_delivery.artifacts)
        gate = DeliveryGate().evaluate(board)
        final = review_delivery.artifacts[-1]

        self.assertTrue(generator.examples)
        self.assertFalse(generator.examples[0]["is_evidence"])
        self.assertEqual(analysis.evidence_refs, [current_evidence])
        self.assertTrue(gate.approved)
        self.assertEqual(final.content["citation_map"], {"claim:0": [current_evidence]})
        serialized_final = json.dumps(final.content, ensure_ascii=False)
        self.assertNotIn("old-not-current-evidence", serialized_final)
        self.assertNotIn("old-branch", serialized_final)


def _task(board: AgentRunBoard, task_type: str, artifact_ids: list[str]) -> BoardTask:
    return BoardTask(
        run_id=board.run_id,
        task_type=task_type,
        objective=task_type,
        deduplication_key=f"{task_type}:trace-reuse",
        input_artifact_ids=artifact_ids,
    )


async def _search(
    harness: ConversationHarness, scenario_id: str, facts: dict[str, str]
) -> list[TraceReuseExample]:
    result = harness.trace_reuse_pool.search_examples(scenario_id, facts)
    if hasattr(result, "__await__"):
        return await result
    return result


if __name__ == "__main__":
    unittest.main()
