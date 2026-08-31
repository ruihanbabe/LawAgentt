from __future__ import annotations

import unittest

from pydantic import ValidationError

from lawagent_runtime import (
    AgentRole,
    CaseEvidenceView,
    PatchTarget,
    PIIPolicy,
    PIIReviewer,
    PIIStatus,
    RunState,
    ToolExecutor,
    ToolPermission,
    ToolRegistry,
    ToolResult,
    ToolResultStatus,
    ToolSpec,
    apply_authorized_patch,
    build_case_evidence_view,
    build_law_evidence_view,
    tool_result_to_state_patches,
)


def case_payload() -> dict:
    return {
        "case_id": "case-1",
        "title": "张三与[Missing]合同纠纷",
        "case_causes": ["租赁合同纠纷"],
        "category_l1": "合同事务",
        "category_l2": "租赁合同",
        "claims_and_facts": "张三电话13812345678，邮箱test@example.com，主张返还押金。",
        "judge_reason": "身份证110101199001011234",
        "judge_result": "返还押金。",
        "legal_basis": [{"law": "", "terms": ""}],
        "source_count": 2,
        "parties": [{"name": "张三"}],
        "source_paths": ["1.json#ctxs/1"],
    }


class FakeToolAdapter:
    def __init__(self, spec: ToolSpec, result: ToolResult | None = None, error: Exception | None = None) -> None:
        self.spec = spec
        self.result = result
        self.error = error
        self.calls: list[dict] = []

    def execute(self, arguments: dict) -> ToolResult:
        self.calls.append(arguments)
        if self.error:
            raise self.error
        if self.result is None:
            return ToolResult(tool_name=self.spec.name, status=ToolResultStatus.EMPTY)
        return self.result


def search_cases_spec(name: str = "search_cases") -> ToolSpec:
    return ToolSpec(
        name=name,
        description="检索脱敏案例",
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
        output_schema=CaseEvidenceView.model_json_schema(),
        permissions=[ToolPermission.SEARCH_SANITIZED_CASES],
    )


class RuntimeToolContractTest(unittest.TestCase):
    def test_pii_reviewer_masks_known_patterns_and_party_names(self) -> None:
        review = PIIReviewer().review(
            "张三电话13812345678，身份证110101199001011234，邮箱a@b.com",
            party_names=["张三"],
        )
        self.assertEqual(review.status, PIIStatus.MASKED)
        self.assertNotIn("张三", review.text)
        self.assertNotIn("13812345678", review.text)
        self.assertNotIn("110101199001011234", review.text)
        self.assertNotIn("a@b.com", review.text)
        self.assertEqual({item.kind for item in review.detections}, {"party_name", "phone", "id_card", "email"})

    def test_block_policy_returns_no_sensitive_text(self) -> None:
        review = PIIReviewer().review("联系电话13812345678", policy=PIIPolicy.BLOCK)
        self.assertTrue(review.blocked)
        self.assertEqual(review.text, "")
        self.assertEqual(review.status, PIIStatus.REVIEW_REQUIRED)

    def test_case_builder_returns_whitelist_dto_and_normalizes_missing_role(self) -> None:
        payload = case_payload()
        view = build_case_evidence_view(payload, score=0.8, party_names=["张三"])
        serialized = view.model_dump()
        self.assertNotIn("parties", serialized)
        self.assertNotIn("source_paths", serialized)
        self.assertIn("[角色未标注的当事人]", view.title)
        self.assertNotIn("张三", view.title + view.fact_snippet)
        self.assertEqual(view.legal_basis[0].law, "")
        self.assertEqual(view.pii_status, PIIStatus.MASKED)

    def test_case_builder_blocks_sensitive_fields_and_enforces_budget(self) -> None:
        payload = case_payload()
        payload["judge_result"] = "无敏感信息" * 20
        view = build_case_evidence_view(payload, party_names=["张三"], policy=PIIPolicy.BLOCK, max_chars_per_field=20)
        self.assertEqual(view.pii_status, PIIStatus.REVIEW_REQUIRED)
        self.assertEqual(view.fact_snippet, "")
        self.assertLessEqual(len(view.result_summary), 21)
        self.assertTrue(any(item.startswith("truncated:judge_result") for item in view.warnings))

    def test_law_builder_returns_law_view(self) -> None:
        view = build_law_evidence_view(
            {
                "chunk_id": "chunk-1",
                "law_family_id": "family-1",
                "law_version_id": "version-1",
                "title": "中华人民共和国民法典",
                "article_no": "703",
                "content": "第七百零三条 租赁合同是出租人将租赁物交付承租人使用。",
                "effective_from": "2021-01-01",
                "validity_status": "unverified",
            },
            score=0.7,
        )
        self.assertEqual(view.kind, "law")
        self.assertEqual(view.article_no, "703")

    def test_tool_spec_is_schema_driven(self) -> None:
        spec = ToolSpec(
            name="search_cases",
            description="检索脱敏案例",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            output_schema=CaseEvidenceView.model_json_schema(),
            permissions=[ToolPermission.SEARCH_SANITIZED_CASES],
        )
        self.assertEqual(spec.pii_policy, PIIPolicy.MASK)

    def test_tool_result_status_invariants(self) -> None:
        item = build_case_evidence_view(case_payload(), party_names=["张三"])
        result = ToolResult(tool_name="search_cases", status=ToolResultStatus.SUCCESS, items=[item])
        self.assertEqual(result.items[0].kind, "case")
        with self.assertRaises(ValidationError):
            ToolResult(tool_name="search_cases", status=ToolResultStatus.FAILED)
        with self.assertRaises(ValidationError):
            ToolResult(tool_name="search_cases", status=ToolResultStatus.BLOCKED, pii_blocked_count=0)

    def test_tool_registry_returns_sorted_specs_and_rejects_duplicates(self) -> None:
        registry = ToolRegistry()
        registry.register(FakeToolAdapter(search_cases_spec("search_statutes")))
        registry.register(FakeToolAdapter(search_cases_spec("search_cases")))
        self.assertEqual([spec.name for spec in registry.specs()], ["search_cases", "search_statutes"])
        with self.assertRaises(ValueError):
            registry.register(FakeToolAdapter(search_cases_spec("search_cases")))

    def test_tool_executor_runs_adapter_after_permission_and_schema_checks(self) -> None:
        item = build_case_evidence_view(case_payload(), party_names=["张三"])
        result = ToolResult(
            tool_name="search_cases",
            status=ToolResultStatus.SUCCESS,
            items=[item],
            metadata={"normalized_query": "押金返还", "top_k": 3},
        )
        adapter = FakeToolAdapter(search_cases_spec(), result=result)
        registry = ToolRegistry()
        registry.register(adapter)

        executor = ToolExecutor(registry, granted_permissions={ToolPermission.SEARCH_SANITIZED_CASES})
        actual = executor.execute("search_cases", {"query": "押金返还", "top_k": 3, "case_causes": ["租赁合同纠纷"]})

        self.assertEqual(actual.status, ToolResultStatus.SUCCESS)
        self.assertEqual(adapter.calls, [{"query": "押金返还", "top_k": 3, "case_causes": ["租赁合同纠纷"]}])
        self.assertIsNotNone(actual.latency_ms)

    def test_tool_executor_denies_missing_permission_before_adapter_call(self) -> None:
        adapter = FakeToolAdapter(search_cases_spec())
        registry = ToolRegistry()
        registry.register(adapter)

        result = ToolExecutor(registry).execute("search_cases", {"query": "押金返还"})

        self.assertEqual(result.status, ToolResultStatus.FAILED)
        self.assertEqual(result.metadata["error_code"], "permission_denied")
        self.assertEqual(adapter.calls, [])

    def test_tool_executor_rejects_invalid_input_before_adapter_call(self) -> None:
        adapter = FakeToolAdapter(search_cases_spec())
        registry = ToolRegistry()
        registry.register(adapter)

        executor = ToolExecutor(registry, granted_permissions={ToolPermission.SEARCH_SANITIZED_CASES})
        result = executor.execute("search_cases", {"query": "押金返还", "unexpected": True})

        self.assertEqual(result.status, ToolResultStatus.FAILED)
        self.assertEqual(result.metadata["error_code"], "invalid_input")
        self.assertEqual(adapter.calls, [])

    def test_tool_executor_wraps_adapter_exception(self) -> None:
        adapter = FakeToolAdapter(search_cases_spec(), error=RuntimeError("qdrant unavailable"))
        registry = ToolRegistry()
        registry.register(adapter)

        executor = ToolExecutor(registry, granted_permissions={ToolPermission.SEARCH_SANITIZED_CASES})
        result = executor.execute("search_cases", {"query": "押金返还"})

        self.assertEqual(result.status, ToolResultStatus.FAILED)
        self.assertEqual(result.metadata["error_code"], "tool_execution_error")
        self.assertIn("qdrant unavailable", result.error or "")

    def test_tool_result_to_state_patches_can_update_run_state(self) -> None:
        item = build_case_evidence_view(case_payload(), party_names=["张三"], score=0.8)
        result = ToolResult(
            tool_name="search_cases",
            status=ToolResultStatus.SUCCESS,
            items=[item],
            latency_ms=12,
            metadata={
                "normalized_query": "押金返还",
                "top_k": 5,
                "applied_filters": {"case_causes": ["租赁合同纠纷"]},
            },
        )
        state = RunState.start("租房押金不退怎么办")

        patches = tool_result_to_state_patches(
            result,
            run_id=state.run_id,
            author_role=AgentRole.RETRIEVAL,
            intent_id="intent-1",
            issue_id="issue-1",
        )
        self.assertEqual([patch.target for patch in patches], [PatchTarget.RETRIEVAL_ATTEMPTS, PatchTarget.EVIDENCE_ITEMS])
        for patch in patches:
            apply_authorized_patch(state, patch)

        self.assertEqual(len(state.retrieval_attempts), 1)
        self.assertEqual(state.retrieval_attempts[0].status.value, "success")
        self.assertEqual(state.retrieval_attempts[0].result_count, 1)
        self.assertEqual(state.retrieval_attempts[0].applied_filters, {"case_causes": ["租赁合同纠纷"]})
        self.assertEqual(len(state.evidence_items), 1)
        self.assertEqual(state.evidence_items[0].source_type.value, "case")
        self.assertEqual(state.evidence_items[0].issue_ids, ["issue-1"])


if __name__ == "__main__":
    unittest.main()
