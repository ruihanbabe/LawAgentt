#!/usr/bin/env python3
from __future__ import annotations

import argparse, asyncio, json, os, sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lawagent_evaluation.ragas_retrieval import build_ragas_samples, read_jsonl, write_jsonl


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Unified RAGAS proxy evaluation for case and law retrieval")
    p.add_argument("--retrieval-cache", type=Path, default=Path("data/evaluation/results/joint_retrieval_v0_1/full_case_to_case/joint_retrieval_cache.jsonl"))
    p.add_argument("--joint-details", type=Path, default=Path("data/evaluation/results/joint_retrieval_v0_1/full_case_to_case/joint_details.jsonl"))
    p.add_argument("--compact-scores", type=Path, default=Path("data/evaluation/results/reranker_grid_v0_1/compact_scores.jsonl"))
    p.add_argument("--references", type=Path, default=Path("data/evaluation/cases_v0_1/query_case_references.jsonl"))
    p.add_argument("--queries", type=Path, default=Path("data/evaluation/cases_v0_1/case_queries.jsonl"))
    p.add_argument("--qrels", type=Path, default=Path("data/evaluation/cases_v0_1/qrels.jsonl"))
    p.add_argument("--law-chunks", type=Path, default=Path("data/processed/laws_v0_2/chunks.jsonl"))
    p.add_argument("--output-dir", type=Path, default=Path("/tmp/lawagent-ragas-unified-calibration"))
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--compact-hybrid-weight", type=float, default=0.75)
    p.add_argument("--model", default="glm-4.7-flash")
    p.add_argument("--base-url", default="https://open.bigmodel.cn/api/paas/v4")
    p.add_argument("--api-key-env", default="ZAI_API_KEY")
    p.add_argument("--prepare-only", action="store_true")
    return p.parse_args()


def _known_positive(retrieved: list[str], relevant: set[str]) -> dict[str, float]:
    hits = sum(item in relevant for item in retrieved)
    return {"precision": hits / len(retrieved) if retrieved else 0.0, "recall": hits / len(relevant) if relevant else 0.0}


async def run(args: argparse.Namespace) -> None:
    samples = build_ragas_samples(
        retrieval_cache_path=args.retrieval_cache, joint_details_path=args.joint_details,
        references_path=args.references, queries_path=args.queries, qrels_path=args.qrels,
        law_chunks_path=args.law_chunks, compact_scores_path=args.compact_scores,
        compact_hybrid_weight=args.compact_hybrid_weight, limit=args.limit,
        top_k=args.top_k, include_law_variants=True,
    )
    prepared = args.output_dir / "prepared_samples.jsonl"
    write_jsonl(prepared, (sample.to_dict() for sample in samples))
    print(json.dumps({"prepared": len(samples), "path": str(prepared)}, ensure_ascii=False))
    if args.prepare_only:
        return
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise RuntimeError(f"missing required environment variable: {args.api_key_env}")

    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.metrics.collections import ContextPrecision, ContextRecall, ContextRelevance
    client = AsyncOpenAI(api_key=api_key, base_url=args.base_url, timeout=180.0)
    llm = llm_factory(args.model, provider="openai", client=client, temperature=0, max_tokens=2048, extra_body={"thinking": {"type": "disabled"}})
    metrics = {"context_precision": ContextPrecision(llm=llm), "context_recall": ContextRecall(llm=llm), "context_relevance": ContextRelevance(llm=llm)}
    result_path = args.output_dir / "scores.jsonl"
    completed = {(str(x["query_id"]), str(x["variant"]), str(x["metric"])) for x in read_jsonl(result_path) if x.get("status") == "success"} if result_path.exists() else set()
    variants = ("case_hybrid", "case_reranked", "law_direct", "law_callback", "law_combined")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with result_path.open("a", encoding="utf-8") as handle:
        for sample in samples:
            for variant in variants:
                contexts = sample.contexts.get(variant) or []
                if not contexts:
                    continue
                for name, metric in metrics.items():
                    if (sample.query_id, variant, name) in completed:
                        continue
                    print(f"RAGAS start query={sample.query_id} variant={variant} metric={name}", flush=True)
                    row: dict[str, Any] = {"query_id": sample.query_id, "variant": variant, "metric": name}
                    if variant.startswith("case_"):
                        row["known_positive"] = _known_positive(sample.context_ids[variant], set(sample.reference_case_ids))
                    try:
                        kwargs: dict[str, Any] = {"user_input": sample.user_input, "retrieved_contexts": contexts}
                        if name != "context_relevance":
                            kwargs["reference"] = sample.law_reference if variant.startswith("law_") else sample.reference
                        result = await metric.ascore(**kwargs)
                        row.update(score=float(result.value), status="success")
                    except Exception as error:
                        message = str(error)
                        fatal = any(x in message for x in ("AllocationQuota.FreeTierOnly", "InsufficientBalance", "余额不足"))
                        row.update(status="failed", error_type=type(error).__name__, error=message[:1000], fatal_free_access_unavailable=fatal)
                    handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"); handle.flush()
                    print(f"RAGAS {row['status']} query={sample.query_id} variant={variant} metric={name}", flush=True)
                    if row.get("fatal_free_access_unavailable"):
                        return


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
