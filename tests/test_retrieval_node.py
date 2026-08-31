from __future__ import annotations

import unittest

from lawagent_runtime import (
    AgentRole,
    ObservationStatus,
    RetrievalToolNode,
    RunState,
    ToolExecutor,
    ToolIntent,
    ToolPermission,
    ToolRegistry,
    ToolResult,
    ToolResultStatus,
    ToolSpec,
    apply_authorized_patch,
    build_case_evidence_view,
)


def case_payload() -> dict:
    return {
        "case_id": "case-1",
        "title": "房屋租赁合同纠纷",
        "case_causes": ["房屋租赁合同纠纷"],
        "claims_and_facts": "承租人主张返还押金。",
        "judge_reason": "法院认为应依据合同约定处理。",
        "judge_result": "返还押金。",
        "legal_basis": [{"law": "中华人民共和国民法典", "terms": "第七百零三条"}],
    }


class RecordingAdapter:
    spec = ToolSpec(
        name="search_cases",
        description="检索案例",
        input_schema={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
                "case_causes": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
        output_schema={},
        permissions=[ToolPermission.SEARCH_SANITIZED_CASES],
    )

    def __init__(self, result: ToolResult | None = None) -> None:
        self.calls: list[dict] = []
        self.result = result

    def execute(self, arguments: dict) -> ToolResult:
        self.calls.append(arguments)
        if self.result is not None:
            return self.result
        return ToolResult(
            tool_name="search_cases",
            status=ToolResultStatus.SUCCESS,
            items=[build_case_evidence_view(case_payload(), score=0.8)],
            metadata={
                "normalized_query": str(arguments["query"]),
                "top_k": arguments.get("top_k") or 10,
                "applied_filters": {"case_causes": arguments.get("case_causes") or []},
            },
        )


def node_with_adapter(adapter: RecordingAdapter) -> RetrievalToolNode:
    registry = ToolRegistry()
    registry.register(adapter)
    executor = ToolExecutor(registry, granted_permissions={ToolPermission.SEARCH_SANITIZED_CASES})
    return RetrievalToolNode(executor)


class RetrievalToolNodeTest(unittest.TestCase):
    def test_node_executes_next_tool_intent_and_returns_state_patches(self) -> None:
        state = RunState.start("租房押金不退怎么办")
        state.tool_intents.append(
            ToolIntent(
                tool_name="search_cases",
                objective="检索押金返还类案",
                query_terms=["租房", "押金", "返还"],
                filters_as_slots={"top_k": 1, "case_causes": ["房屋租赁合同纠纷"]},
                priority=20,
            )
        )
        adapter = RecordingAdapter()
        observation = node_with_adapter(adapter).run(state)

        self.assertEqual(observation.status, ObservationStatus.SUCCESS)
        self.assertEqual(adapter.calls[0]["query"], "租房 押金 返还")
        self.assertEqual(len(observation.state_patches), 2)
        for patch in observation.state_patches:
            apply_authorized_patch(state, patch)
        self.assertEqual(len(state.retrieval_attempts), 1)
        self.assertEqual(state.retrieval_attempts[0].tool_name, "search_cases")
        self.assertEqual(len(state.evidence_items), 1)
        self.assertEqual(state.evidence_items[0].source_type.value, "case")

    def test_node_prefers_lowest_priority_pending_intent(self) -> None:
        state = RunState.start("押金争议")
        state.tool_intents.append(
            ToolIntent(tool_name="search_cases", objective="低优先级", query_terms=["低"], priority=100)
        )
        state.tool_intents.append(
            ToolIntent(tool_name="search_cases", objective="高优先级", query_terms=["高"], priority=1)
        )
        adapter = RecordingAdapter()

        observation = node_with_adapter(adapter).run(state)

        self.assertEqual(observation.status, ObservationStatus.SUCCESS)
        self.assertEqual(adapter.calls[0]["query"], "高")

    def test_node_skips_without_runnable_intent(self) -> None:
        state = RunState.start("押金争议")

        observation = node_with_adapter(RecordingAdapter()).run(state)

        self.assertEqual(observation.status, ObservationStatus.SKIPPED)
        self.assertEqual(observation.state_patches, [])
        self.assertIn("no_pending_tool_intent", observation.warnings)

    def test_failed_tool_result_is_recorded_as_failed_attempt_patch(self) -> None:
        state = RunState.start("押金争议")
        state.tool_intents.append(
            ToolIntent(tool_name="search_cases", objective="检索案例", query_terms=["押金"], priority=1)
        )
        adapter = RecordingAdapter(
            ToolResult(
                tool_name="search_cases",
                status=ToolResultStatus.FAILED,
                error="qdrant unavailable",
                metadata={"error_code": "tool_execution_error"},
            )
        )

        observation = node_with_adapter(adapter).run(state)

        self.assertEqual(observation.status, ObservationStatus.PARTIAL)
        self.assertEqual(observation.error_code, "tool_execution_error")
        self.assertEqual(len(observation.state_patches), 1)
        self.assertEqual(observation.state_patches[0].author_role, AgentRole.RETRIEVAL)
        apply_authorized_patch(state, observation.state_patches[0])
        self.assertEqual(state.retrieval_attempts[0].status.value, "failed")
        self.assertEqual(state.retrieval_attempts[0].error_code, "tool_execution_error")


if __name__ == "__main__":
    unittest.main()
