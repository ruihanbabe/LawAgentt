#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lawagent_evaluation.cases import read_jsonl
from lawagent_evaluation.joint_retrieval import compact_query_text, reconstruct_case_text
from lawagent_evaluation.reranker import BGEReranker, RerankItem


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-score cached Hybrid candidates with compact reranker views")
    parser.add_argument("--input-cache", type=Path, default=Path(
        "data/evaluation/results/joint_retrieval_v0_1/full_case_to_case/joint_retrieval_cache.jsonl"
    ))
    parser.add_argument("--queries", type=Path, default=Path("data/evaluation/cases_v0_1/case_queries.jsonl"))
    parser.add_argument("--output-cache", type=Path, default=Path(
        "data/evaluation/results/reranker_grid_v0_1/compact_scores.jsonl"
    ))
    parser.add_argument("--model", type=Path, default=Path("models/bge-reranker-v2-m3"))
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--candidate-k", type=int, default=50)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    query_texts = {str(row["query_id"]): compact_query_text(str(row["query_text"])) for row in read_jsonl(args.queries)}
    completed = {
        str(row["query_id"]) for row in read_jsonl(args.output_cache)
    } if args.output_cache.exists() else set()
    reranker = BGEReranker(args.model, device=args.device, batch_size=args.batch_size, max_length=512)
    args.output_cache.parent.mkdir(parents=True, exist_ok=True)
    processed = 0
    with args.output_cache.open("a", encoding="utf-8") as output:
        for index, row in enumerate(read_jsonl(args.input_cache)):
            if args.limit is not None and index >= args.limit:
                break
            query_id = str(row["query_id"])
            if query_id in completed:
                continue
            hybrid = [str(item) for item in row["case_hybrid"][:args.candidate_k]]
            pairs = reranker.rank(
                query_texts[query_id],
                [RerankItem(case_id, reconstruct_case_text(row["case_payloads"][case_id])) for case_id in hybrid],
            )
            output.write(json.dumps({
                "query_id": query_id,
                "qrel_query_id": str(row["qrel_query_id"]),
                "case_hybrid": hybrid,
                "case_rerank_scores": {case_id: score for case_id, score in pairs},
            }, ensure_ascii=False, separators=(",", ":")) + "\n")
            output.flush()
            processed += 1
            if processed % 25 == 0:
                print(f"compact rerank completed={len(completed) + processed}", flush=True)
    print(json.dumps({"newly_processed": processed, "output": str(args.output_cache)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
