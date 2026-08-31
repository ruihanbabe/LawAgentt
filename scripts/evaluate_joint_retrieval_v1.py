from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lawagent_evaluation.joint_retrieval import JointRetrievalEvaluator, run_joint_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(description="Joint cases + laws retrieval, rerank and LegalBasis callback evaluation")
    parser.add_argument("--evaluation-dir", type=Path, default=PROJECT_ROOT / "data/evaluation/cases_v0_1")
    parser.add_argument("--law-chunks", type=Path, default=PROJECT_ROOT / "data/processed/laws_v0_2/chunks.jsonl")
    parser.add_argument("--case-documents", type=Path, default=PROJECT_ROOT / "data/processed/cases_v0_1/documents.jsonl")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data/evaluation/results/joint_retrieval_v0_1")
    parser.add_argument("--embedding-model", type=Path, default=PROJECT_ROOT / "models/bge-m3")
    parser.add_argument("--reranker-model", type=Path, default=PROJECT_ROOT / "models/bge-reranker-v2-m3")
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"))
    parser.add_argument("--cases-collection", default=os.getenv("CASES_COLLECTION", "cases_collection"))
    parser.add_argument("--laws-collection", default=os.getenv("LAWS_COLLECTION", "laws_collection"))
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default=os.getenv("DEVICE", "auto"))
    parser.add_argument("--track", choices=("case_to_case", "template_to_case", "user_to_case"), default="case_to_case")
    parser.add_argument("--candidate-k", type=int, default=50)
    parser.add_argument("--rerank-top-n", type=int, default=10)
    parser.add_argument("--callback-case-top-n", type=int, default=5)
    parser.add_argument("--law-k", type=int, default=10)
    parser.add_argument("--ks", type=int, nargs="+", default=[5, 10, 50])
    parser.add_argument("--embed-batch-size", type=int, default=32)
    parser.add_argument("--rerank-batch-size", type=int, default=32)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--retrieval-cache", type=Path, help="Reuse a completed joint_retrieval_cache.jsonl")
    args = parser.parse_args()
    evaluator = None
    if args.retrieval_cache is None:
        evaluator = JointRetrievalEvaluator(
            args.qdrant_url, args.cases_collection, args.laws_collection,
            args.embedding_model, args.reranker_model, args.device,
            args.embed_batch_size, args.rerank_batch_size,
        )
    summary = run_joint_evaluation(
        args.evaluation_dir, args.law_chunks, args.case_documents, args.output_dir, evaluator,
        args.track, args.candidate_k, args.rerank_top_n, args.callback_case_top_n,
        args.law_k, args.ks, args.limit,
        args.retrieval_cache,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
