from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lawagent_evaluation.reranker_grid import fuse_hybrid_reranker, run_cached_grid


class RerankerGridTests(unittest.TestCase):
    def test_weight_extremes_reproduce_hybrid_or_reranker(self) -> None:
        hybrid = ["a", "b", "c"]
        scores = {"a": 0.0, "b": 2.0, "c": 1.0}
        self.assertEqual(
            fuse_hybrid_reranker(hybrid, scores, candidate_k=3, hybrid_weight=1.0),
            ["a", "b", "c"],
        )
        self.assertEqual(
            fuse_hybrid_reranker(hybrid, scores, candidate_k=3, hybrid_weight=0.0),
            ["b", "c", "a"],
        )

    def test_cached_grid_writes_summary_and_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache.jsonl"
            qrels = root / "qrels.jsonl"
            cache.write_text(json.dumps({
                "query_id": "q", "qrel_query_id": "q",
                "case_hybrid": ["bad", "good"],
                "case_rerank_scores": {"bad": 0.0, "good": 2.0},
            }) + "\n", encoding="utf-8")
            qrels.write_text(json.dumps({
                "query_id": "q", "case_id": "good", "relevance": 1,
            }) + "\n", encoding="utf-8")
            summary = run_cached_grid(
                cache_path=cache, qrels_path=qrels, output_dir=root / "out",
                candidate_ks=[2], hybrid_weights=[0.0, 1.0], ks=[1, 2],
            )
            self.assertEqual(summary["query_count"], 1)
            self.assertEqual(summary["best"]["hybrid_weight"], 0.0)
            self.assertTrue((root / "out/reranker_grid_summary.json").exists())
            self.assertEqual(
                len((root / "out/reranker_grid_details.jsonl").read_text().splitlines()), 2,
            )


if __name__ == "__main__":
    unittest.main()
