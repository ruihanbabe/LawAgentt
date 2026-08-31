from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lawagent_evaluation.closed_pool import ClosedPoolEvaluator, run_closed_pool


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate case ranking inside each source JSON ctxs pool")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data/cases")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data/evaluation/results/closed_pool_v0_1/smoke_first_10")
    parser.add_argument("--embedding-model", type=Path, default=PROJECT_ROOT / "models/bge-m3")
    parser.add_argument("--reranker-model", type=Path, default=PROJECT_ROOT / "models/bge-reranker-v2-m3")
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"))
    parser.add_argument("--collection", default=os.getenv("CASES_COLLECTION", "cases_collection"))
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default=os.getenv("DEVICE", "auto"))
    parser.add_argument("--embed-batch-size", type=int, default=32)
    parser.add_argument("--rerank-batch-size", type=int, default=32)
    parser.add_argument("--rerank-candidate-k", type=int, default=20)
    parser.add_argument("--ks", type=int, nargs="+", default=[1, 3, 5, 10, 20])
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    evaluator = ClosedPoolEvaluator(
        args.qdrant_url, args.collection, args.embedding_model, args.reranker_model,
        args.device, args.embed_batch_size, args.rerank_batch_size, args.rerank_candidate_k,
    )
    summary = run_closed_pool(args.data_dir, args.output_dir, evaluator, args.ks, args.limit)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
