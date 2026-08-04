from __future__ import annotations

import unittest

from pydantic import ValidationError

from lawagent_runtime.state import (
    Budget,
    EvidenceGap,
    EvidenceItem,
    FactItem,
    FactStatus,
    FinalDecision,
    GapType,
    RunState,
    SourceType,
    Stage,
    StopReason,
    ToolIntent,
)


class RunStateTest(unittest.TestCase):
    def test_start_initializes_identity_and_normalized_query(self) -> None:
        state = RunState.start("  我的租房押金不退，怎么办？  ", session_id="session-1")
        self.assertEqual(state.session_id, "session-1")
        self.assertEqual(state.jurisdiction, "CN")
        self.assertEqual(state.normalized_query, "我的租房押金不退，怎么办？")
        self.assertEqual(state.stage, Stage.INITIALIZED)

    def test_missing_facts_and_open_gaps_are_derived_views(self) -> None:
        state = RunState.start("押金问题")
        state.facts.append(FactItem(name="合同到期时间", status=FactStatus.MISSING))
        state.evidence_gaps.append(
            EvidenceGap(issue_id="issue-1", gap_type=GapType.MISSING_STATUTE, description="缺少押金返还依据")
        )
        self.assertEqual([item.name for item in state.missing_critical_facts], ["合同到期时间"])
        self.assertEqual(len(state.open_gaps), 1)

    def test_state_tracks_tool_intent_without_qdrant_filter_contract(self) -> None:
        state = RunState.start("民法典第七百零三条")
        state.tool_intents.append(
            ToolIntent(
                tool_name="search_statutes",
                objective="检索租赁合同定义条文",
                query_terms=["租赁合同", "第七百零三条"],
                filters_as_slots={"article_no": "703", "document_type": ["law"]},
            )
        )
        self.assertEqual(state.tool_intents[0].filters_as_slots["article_no"], "703")

    def test_evidence_keeps_snippet_and_reference_ids(self) -> None:
        evidence = EvidenceItem(
            evidence_id="law-chunk-1",
            source_type=SourceType.STATUTE,
            source_id="chunk-1",
            parent_id="law-version-1",
            title="中华人民共和国民法典",
            citation_label="《中华人民共和国民法典》第七百零三条",
            content_snippet="租赁合同是出租人将租赁物交付承租人使用...",
            score=0.8,
            rerank_score=0.9,
            issue_ids=["issue-1"],
        )
        self.assertEqual(evidence.source_type, SourceType.STATUTE)
        self.assertEqual(evidence.parent_id, "law-version-1")

    def test_budget_rejects_impossible_counts(self) -> None:
        with self.assertRaises(ValidationError):
            Budget(max_steps=1, step_count=2)

    def test_completed_state_requires_decision(self) -> None:
        with self.assertRaises(ValidationError):
            RunState(raw_query="押金问题", stage=Stage.COMPLETED)

    def test_trace_and_advance_update_control_fields(self) -> None:
        state = RunState.start("押金问题")
        state.add_trace("understand", input_summary="用户问题", output_summary="抽取租赁事实")
        state.advance(stage=Stage.PLANNING, next_node="plan_issues", route_reason="facts_extracted")
        self.assertEqual(len(state.trace), 1)
        self.assertEqual(state.budget.step_count, 1)
        self.assertEqual(state.next_node, "plan_issues")

    def test_complete_sets_terminal_fields(self) -> None:
        state = RunState.start("押金问题")
        state.complete(FinalDecision.SUPPORTED_ANSWER, StopReason.EVIDENCE_SUFFICIENT)
        self.assertEqual(state.stage, Stage.COMPLETED)
        self.assertEqual(state.final_decision, FinalDecision.SUPPORTED_ANSWER)


if __name__ == "__main__":
    unittest.main()
