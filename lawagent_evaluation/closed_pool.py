from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Sequence

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchAny, SparseVector
from tqdm import tqdm

from lawagent_evaluation.cases import aggregate_metrics, per_query_metrics, weighted_rrf_fuse
from lawagent_evaluation.joint_retrieval import QueryCaseLabels, label_match_score
from lawagent_evaluation.reranker import BGEReranker, RerankItem
from lawagent_ingestion.cases.pipeline import build_retrieval_text, extract_categories, extract_parties
from lawagent_ingestion.laws.embedder import BGEM3Embedder
from lawagent_ingestion.laws.pipeline import write_json, write_jsonl


def _labels(raw: dict[str, Any]) -> QueryCaseLabels:
    category_l1, category_l2 = extract_categories(raw)
    return QueryCaseLabels(
        frozenset(str(value) for value in (raw.get("CaseCause") or []) if value),
        category_l1, category_l2,
        frozenset(str(value) for value in (raw.get("Keywords") or []) if value),
    )


def _payload(raw: dict[str, Any]) -> dict[str, Any]:
    category_l1, category_l2 = extract_categories(raw)
    return {
        "case_causes": [str(value) for value in (raw.get("CaseCause") or []) if value],
        "category_l1": category_l1, "category_l2": category_l2,
        "keywords": [str(value) for value in (raw.get("Keywords") or []) if value],
    }


def _ranking(ids: Sequence[str], scores: Sequence[float]) -> list[str]:
    return [ids[index] for index in sorted(range(len(ids)), key=lambda index: (-float(scores[index]), index))]


class ClosedPoolEvaluator:
    def __init__(
        self, qdrant_url: str, collection: str, embedding_model_path: Path,
        reranker_model_path: Path, device: str, embed_batch_size: int = 32,
        rerank_batch_size: int = 32, rerank_candidate_k: int = 20,
    ) -> None:
        self.client = QdrantClient(url=qdrant_url, timeout=120, check_compatibility=False, trust_env=False)
        self.collection = collection
        self.embedder = BGEM3Embedder(embedding_model_path, device=device, batch_size=embed_batch_size)
        self.reranker = BGEReranker(reranker_model_path, device=device, batch_size=rerank_batch_size)
        self.rerank_candidate_k = rerank_candidate_k

    def evaluate_file(self, path: Path) -> dict[str, Any]:
        task = json.loads(path.read_text(encoding="utf-8"))
        query_case = task["query_case"]
        contexts = task.get("ctxs") or {}
        ordered = [(str(index), contexts[str(index)]) for index in sorted(map(int, contexts))]
        candidate_ids = [str(item.get("CaseId") or f"{path.stem}:{index}") for index, item in ordered]
        candidate_texts = [build_retrieval_text(item, extract_parties(item)) for _, item in ordered]
        query_text = build_retrieval_text(query_case, extract_parties(query_case))
        started = time.perf_counter()
        encoded = self.embedder.encode([query_text])
        embedding_ms = (time.perf_counter() - started) * 1000
        candidate_filter = Filter(must=[FieldCondition(key="case_id", match=MatchAny(any=candidate_ids))])
        started = time.perf_counter()
        dense_points = self.client.query_points(
            self.collection, query=encoded.dense[0], using="dense", query_filter=candidate_filter,
            limit=len(candidate_ids), with_payload=["case_id"], with_vectors=False,
        ).points
        sparse_points = self.client.query_points(
            self.collection,
            query=SparseVector(indices=encoded.sparse_indices[0], values=encoded.sparse_values[0]),
            using="text_sparse", query_filter=candidate_filter, limit=len(candidate_ids),
            with_payload=["case_id"], with_vectors=False,
        ).points
        qdrant_ms = (time.perf_counter() - started) * 1000
        dense = [str(point.payload["case_id"]) for point in dense_points]
        sparse = [str(point.payload["case_id"]) for point in sparse_points]
        available = set(dense) | set(sparse)
        missing = sorted(set(candidate_ids) - available)
        hybrid = weighted_rrf_fuse(((dense, 1.0), (sparse, 1.0)))
        labels = _labels(query_case)
        id_to_raw = {case_id: item for case_id, (_, item) in zip(candidate_ids, ordered, strict=True)}
        structural_ids = [case_id for case_id in candidate_ids if case_id in available]
        structural_scores = [label_match_score(labels, _payload(id_to_raw[case_id])) for case_id in structural_ids]
        structural = _ranking(structural_ids, structural_scores)
        hybrid_structural = weighted_rrf_fuse(((hybrid, 1.0), (structural, 1.0)))
        id_to_text = dict(zip(candidate_ids, candidate_texts, strict=True))
        started = time.perf_counter()
        reranked = [item[0] for item in self.reranker.rank(
            query_text, [RerankItem(case_id, id_to_text[case_id]) for case_id in hybrid_structural[:self.rerank_candidate_k]],
        )]
        rerank_ms = (time.perf_counter() - started) * 1000
        gt_indices = {str(index) for index in task.get("gt_idx") or []}
        relevant = {str(contexts[index].get("CaseId") or f"{path.stem}:{index}") for index in gt_indices}
        return {
            "query_id": str(task.get("q_i", path.stem)), "source_path": path.name,
            "candidate_count": len(candidate_ids), "relevant_count": len(relevant),
            "qdrant_candidate_count": len(available), "missing_from_collection": missing,
            "missing_relevant_case_ids": sorted(relevant & set(missing)),
            "relevant_case_ids": sorted(relevant), "query_text": query_text,
            "rankings": {"dense": dense, "sparse": sparse, "hybrid": hybrid, "structural": structural, "hybrid_structural": hybrid_structural, "reranker": reranked},
            "embedding_latency_ms": embedding_ms, "qdrant_latency_ms": qdrant_ms,
            "rerank_latency_ms": rerank_ms,
        }


def run_closed_pool(
    data_dir: Path, output_dir: Path, evaluator: ClosedPoolEvaluator,
    ks: Sequence[int] = (1, 3, 5, 10, 20), limit: int | None = 10,
) -> dict[str, Any]:
    paths = sorted(data_dir.glob("*.json"))
    if limit is not None:
        paths = paths[:limit]
    rows = [evaluator.evaluate_file(path) for path in tqdm(paths, desc="Closed-pool case evaluation")]
    modes = ("dense", "sparse", "hybrid", "structural", "hybrid_structural", "reranker")
    summary: dict[str, Any] = {
        "query_count": len(rows), "ks": list(ks), "candidate_scope": "per-source-json ctxs CaseIds filtered in Qdrant",
        "source_candidates": sum(row["candidate_count"] for row in rows),
        "qdrant_candidates": sum(row["qdrant_candidate_count"] for row in rows),
        "missing_from_collection": sum(len(row["missing_from_collection"]) for row in rows),
        "missing_relevant": sum(len(row["missing_relevant_case_ids"]) for row in rows),
        "metrics": {},
    }
    for mode in modes:
        metric_rows = [per_query_metrics(row["rankings"][mode], set(row["relevant_case_ids"]), ks) for row in rows]
        latency = [
            row["rerank_latency_ms"] if mode == "reranker" else row["embedding_latency_ms"] + row["qdrant_latency_ms"]
            for row in rows
        ]
        summary["metrics"][mode] = aggregate_metrics(metric_rows, latency)
    write_json(output_dir / "closed_pool_summary.json", summary)
    write_jsonl(output_dir / "closed_pool_details.jsonl", rows)
    return summary
