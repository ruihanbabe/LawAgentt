from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lawagent_evaluation.ragas_retrieval import build_ragas_samples


def write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


class RagasRetrievalPreparationTests(unittest.TestCase):
    def test_builds_safe_case_and_law_variants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            query = {
                "CaseId": "query-case", "Case": "张三诉李四", "CaseRecord": "张三手机号13800138000",
                "JudgeAccusation": "张三请求退款", "JudgeReason": "李四应当退款",
                "JudgeResult": "支持张三", "LegalBasis": [{"law": "《测试法》", "terms": "第一条"}],
                "Parties": [{"NameText": "张三", "Prop": "原告"}, {"NameText": "李四", "Prop": "被告"}],
            }
            case_payload = {
                "case_id": "case-1", "title": "张三相关案件", "claims_and_facts": "电话13800138000",
                "judge_reason": "李四应退款", "judge_result": "支持", "case_causes": ["合同纠纷"],
                "legal_basis": [], "source_count": 1,
            }
            law_payload = {
                "chunk_id": "law-1", "law_family_id": "family-1", "law_version_id": "version-1",
                "title": "测试法", "article_no": "1", "content": "第一条 应当退款。",
            }
            write_rows(root / "references.jsonl", [{"query_id": "q1", "query_case": query}])
            write_rows(root / "queries.jsonl", [{"query_id": "q1", "query_text": "张三电话13800138000退款"}])
            write_rows(root / "qrels.jsonl", [{"query_id": "q1", "case_id": "case-1"}])
            write_rows(root / "cache.jsonl", [{
                "query_id": "q1", "qrel_query_id": "q1", "case_hybrid": ["case-1"],
                "case_reranked": ["case-1"], "case_payloads": {"case-1": case_payload},
                "law_direct": ["law-1"], "law_payloads": {"law-1": law_payload},
            }])
            write_rows(root / "details.jsonl", [{
                "query_id": "q1", "callbacks": [{"status": "matched", "chunk_id": "law-1"}],
            }])
            write_rows(root / "laws.jsonl", [law_payload])

            sample = build_ragas_samples(
                retrieval_cache_path=root / "cache.jsonl", joint_details_path=root / "details.jsonl",
                references_path=root / "references.jsonl", queries_path=root / "queries.jsonl",
                qrels_path=root / "qrels.jsonl", law_chunks_path=root / "laws.jsonl", limit=1,
            )[0]

            serialized = json.dumps(sample.to_dict(), ensure_ascii=False)
            self.assertNotIn("13800138000", serialized)
            self.assertNotIn("张三", sample.reference)
            self.assertNotIn("裁判结果", sample.law_reference)
            self.assertIn("法律依据", sample.law_reference)
            self.assertEqual(sample.reference_case_ids, ["case-1"])
            self.assertEqual(sample.context_ids["law_combined"], ["law-1"])
            self.assertTrue(sample.contexts["case_hybrid"])

            case_only = build_ragas_samples(
                retrieval_cache_path=root / "cache.jsonl", joint_details_path=root / "details.jsonl",
                references_path=root / "references.jsonl", queries_path=root / "queries.jsonl",
                qrels_path=root / "qrels.jsonl", law_chunks_path=root / "laws.jsonl", limit=1,
                include_law_variants=False,
            )[0]
            self.assertEqual(set(case_only.contexts), {"case_hybrid", "case_reranked"})
            self.assertEqual(set(case_only.context_ids), {"case_hybrid", "case_reranked"})


if __name__ == "__main__":
    unittest.main()
