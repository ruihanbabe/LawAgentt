from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lawagent_evaluation.cases import load_track, per_query_metrics, rrf_fuse, weighted_rrf_fuse


class CaseEvaluationTest(unittest.TestCase):
    def test_rrf_rewards_documents_present_in_both_rankings(self) -> None:
        self.assertEqual(rrf_fuse(["a", "b"], ["b", "c"])[0], "b")

    def test_weighted_rrf_can_add_an_independent_retrieval_lane(self) -> None:
        result = weighted_rrf_fuse(((['semantic'], 1.0), (['structural'], 2.0)))
        self.assertEqual(result[0], "structural")

    def test_metrics_support_multiple_relevant_cases(self) -> None:
        result = per_query_metrics(["x", "b", "a"], {"a", "b"}, [1, 3])
        self.assertEqual(result["recall@1"], 0.0)
        self.assertEqual(result["recall@3"], 1.0)
        self.assertEqual(result["mrr@3"], 0.5)
        self.assertGreater(result["ndcg@3"], 0.0)

    def test_user_track_inherits_source_query_qrels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "user_queries.jsonl"
            path.write_text(json.dumps({"query_id": "u-1", "source_query_id": "7", "query_text": "公司不发工资怎么办"}, ensure_ascii=False) + "\n", encoding="utf-8")
            query = load_track(Path(directory), "user_to_case")[0]
            self.assertEqual(query.query_id, "u-1")
            self.assertEqual(query.qrel_query_id, "7")


if __name__ == "__main__":
    unittest.main()
