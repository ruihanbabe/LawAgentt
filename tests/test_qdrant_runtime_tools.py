from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any, Sequence

from lawagent_ingestion.laws.embedder import EmbeddedBatch
from lawagent_runtime import (
    FetchCaseEvidenceAdapter,
    SearchCasesAdapter,
    SearchStatutesAdapter,
    ToolExecutor,
    ToolPermission,
    ToolRegistry,
    ToolResultStatus,
)


@dataclass(slots=True)
class FakePoint:
    payload: dict[str, Any]
    score: float


class FakeResponse:
    def __init__(self, points: list[FakePoint]) -> None:
        self.points = points


class FakeEmbedder:
    def __init__(self) -> None:
        self.texts: list[list[str]] = []

    def encode(self, texts: Sequence[str]) -> EmbeddedBatch:
        self.texts.append(list(texts))
        return EmbeddedBatch(dense=[[0.1, 0.2]], sparse_indices=[[1, 3]], sparse_values=[[0.7, 0.2]])


class FakeQdrantClient:
    def __init__(self) -> None:
        self.query_calls: list[dict[str, Any]] = []
        self.scroll_calls: list[dict[str, Any]] = []
        self.points_by_collection: dict[str, list[FakePoint]] = {}
        self.scroll_points: list[FakePoint] = []

    def query_points(self, collection_name: str, **kwargs: Any) -> FakeResponse:
        self.query_calls.append({"collection_name": collection_name, **kwargs})
        using = kwargs["using"]
        points = self.points_by_collection.get(f"{collection_name}:{using}", [])
        return FakeResponse(points)

    def scroll(self, collection_name: str, **kwargs: Any):
        self.scroll_calls.append({"collection_name": collection_name, **kwargs})
        return self.scroll_points, None


def case_payload(case_id: str, title: str, score: float = 0.9) -> FakePoint:
    return FakePoint(
        payload={
            "case_id": case_id,
            "title": title,
            "case_causes": ["房屋租赁合同纠纷"],
            "category_l1": "合同事务",
            "category_l2": "租赁合同",
            "claims_and_facts": "张三电话13812345678，主张返还押金。",
            "judge_reason": "法院认为押金应按约处理。",
            "judge_result": "返还押金。",
            "legal_basis": [{"law": "中华人民共和国民法典", "terms": "第七百零三条"}],
            "source_count": 2,
            "parties": [{"name": "张三"}],
            "source_paths": ["raw.json#ctxs/1"],
        },
        score=score,
    )


def law_payload(chunk_id: str, score: float = 0.8) -> FakePoint:
    return FakePoint(
        payload={
            "chunk_id": chunk_id,
            "law_family_id": "family-civil-code",
            "law_version_id": "version-civil-code-2021",
            "title": "中华人民共和国民法典",
            "article_no": "703",
            "content": "第七百零三条 租赁合同是出租人将租赁物交付承租人使用。",
            "effective_from": "2021-01-01",
            "effective_to": None,
            "validity_status": "unverified",
        },
        score=score,
    )


class QdrantRuntimeToolAdapterTest(unittest.TestCase):
    def test_search_cases_adapter_returns_safe_views_and_records_filters(self) -> None:
        client = FakeQdrantClient()
        client.points_by_collection["cases_collection:dense"] = [
            case_payload("case-1", "张三与[Missing]房屋租赁合同纠纷", 0.91)
        ]
        client.points_by_collection["cases_collection:text_sparse"] = [
            case_payload("case-2", "李四与王五租赁合同纠纷", 0.82),
            case_payload("case-1", "张三与[Missing]房屋租赁合同纠纷", 0.78),
        ]
        adapter = SearchCasesAdapter(client=client, embedder=FakeEmbedder())

        result = adapter.execute(
            {
                "query": "租房押金不退",
                "top_k": 2,
                "jurisdiction": "CN",
                "case_causes": ["房屋租赁合同纠纷"],
                "party_names": ["张三"],
            }
        )

        self.assertEqual(result.status, ToolResultStatus.SUCCESS)
        self.assertEqual([item.case_id for item in result.items], ["case-1", "case-2"])
        self.assertNotIn("source_paths", result.items[0].model_dump())
        self.assertNotIn("张三", result.items[0].title + result.items[0].fact_snippet)
        self.assertEqual(result.metadata["applied_filters"], {"jurisdiction": "CN", "case_causes": ["房屋租赁合同纠纷"]})
        self.assertEqual([call["using"] for call in client.query_calls], ["dense", "text_sparse"])
        self.assertIsNotNone(client.query_calls[0]["query_filter"])

    def test_search_statutes_adapter_returns_law_views_with_event_date_warning(self) -> None:
        client = FakeQdrantClient()
        client.points_by_collection["laws_collection:dense"] = [law_payload("chunk-1", 0.88)]
        client.points_by_collection["laws_collection:text_sparse"] = [law_payload("chunk-2", 0.71)]
        adapter = SearchStatutesAdapter(client=client, embedder=FakeEmbedder())

        result = adapter.execute(
            {
                "query": "租赁合同押金",
                "top_k": 2,
                "jurisdiction": "CN",
                "law_titles": ["中华人民共和国民法典"],
                "article_no": "703",
                "event_date": "2024-01-01",
            }
        )

        self.assertEqual(result.status, ToolResultStatus.SUCCESS)
        self.assertEqual([item.chunk_id for item in result.items], ["chunk-1", "chunk-2"])
        self.assertEqual(result.items[0].title, "中华人民共和国民法典")
        self.assertIn("event_date_filter_uses_effective_from_only_v0", result.warnings)
        self.assertEqual(result.metadata["applied_filters"]["article_no"], "703")
        self.assertIsNotNone(client.query_calls[0]["query_filter"])

    def test_fetch_case_evidence_adapter_uses_case_id_filter(self) -> None:
        client = FakeQdrantClient()
        client.scroll_points = [case_payload("case-1", "张三与[Missing]房屋租赁合同纠纷")]
        adapter = FetchCaseEvidenceAdapter(client=client)

        result = adapter.execute({"case_id": "case-1", "party_names": ["张三"]})

        self.assertEqual(result.status, ToolResultStatus.SUCCESS)
        self.assertEqual(result.items[0].case_id, "case-1")
        self.assertEqual(result.metadata["applied_filters"], {"case_id": "case-1"})
        self.assertEqual(client.scroll_calls[0]["collection_name"], "cases_collection")
        self.assertIsNotNone(client.scroll_calls[0]["scroll_filter"])

    def test_adapters_work_through_tool_executor_permissions(self) -> None:
        client = FakeQdrantClient()
        client.points_by_collection["cases_collection:dense"] = [case_payload("case-1", "合同纠纷")]
        adapter = SearchCasesAdapter(client=client, embedder=FakeEmbedder())
        registry = ToolRegistry()
        registry.register(adapter)
        executor = ToolExecutor(registry, granted_permissions={ToolPermission.SEARCH_SANITIZED_CASES})

        result = executor.execute("search_cases", {"query": "押金", "top_k": 1})

        self.assertEqual(result.status, ToolResultStatus.SUCCESS)
        self.assertEqual(result.items[0].case_id, "case-1")


if __name__ == "__main__":
    unittest.main()
