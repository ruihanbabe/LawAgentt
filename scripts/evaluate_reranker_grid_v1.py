#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lawagent_evaluation.reranker_grid import run_cached_grid


def main() -> int:
    parser = argparse.ArgumentParser(description="Cached Hybrid + reranker fusion grid")
    parser.add_argument("--cache", type=Path, default=Path(
        "data/evaluation/results/joint_retrieval_v0_1/full_case_to_case/joint_retrieval_cache.jsonl"
    ))
    parser.add_argument("--qrels", type=Path, default=Path("data/evaluation/cases_v0_1/qrels.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path(
        "data/evaluation/results/reranker_grid_v0_1/cached_phase_a"
    ))
    parser.add_argument("--candidate-ks", type=int, nargs="+", default=[10, 20, 30, 50])
    parser.add_argument("--hybrid-weights", type=float, nargs="+", default=[0, 0.25, 0.5, 0.75, 1])
    parser.add_argument("--ks", type=int, nargs="+", default=[5, 10])
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    summary = run_cached_grid(
        cache_path=args.cache, qrels_path=args.qrels, output_dir=args.output_dir,
        candidate_ks=args.candidate_ks, hybrid_weights=args.hybrid_weights,
        ks=args.ks, limit=args.limit,
    )
    print(json.dumps({
        "query_count": summary["query_count"],
        "baseline_hybrid": summary["baseline_hybrid"],
        "best": summary["best"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
