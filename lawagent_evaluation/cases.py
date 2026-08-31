from __future__ import annotations

import json
import math
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from qdrant_client import QdrantClient
from qdrant_client.models import SparseVector
from tqdm import tqdm

from lawagent_ingestion.laws.embedder import BGEM3Embedder, EmbeddedBatch
from lawagent_ingestion.laws.pipeline import write_json, write_jsonl


TRACK_FILES = {
    "case_to_case": "case_queries.jsonl",
    "template_to_case": "template_queries.jsonl",
    "user_to_case": "user_queries.jsonl",
}


@dataclass(frozen=True, slots=True)
class EvalQuery:
    query_id: str
    query_text: str
    qrel_query_id: str


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def load_qrels(path: Path) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for item in read_jsonl(path):
        if int(item.get("relevance", 0)) > 0:
            result[str(item["query_id"])].add(str(item["case_id"]))
    return dict(result)


def load_track(evaluation_dir: Path, track: str) -> list[EvalQuery]:
    if track not in TRACK_FILES:
        raise ValueError(f"unknown track: {track}")
    path = evaluation_dir / TRACK_FILES[track]
    if not path.exists():
        if track == "user_to_case":
            return []
        raise FileNotFoundError(path)
    queries: list[EvalQuery] = []
    seen: set[str] = set()
    for item in read_jsonl(path):
        query_id = str(item["query_id"])
        if query_id in seen:
            raise ValueError(f"duplicate query_id in {path}: {query_id}")
        seen.add(query_id)
        source_query_id = str(item.get("source_query_id") or query_id)
        text = str(item.get("query_text") or "").strip()
        if not text:
            raise ValueError(f"empty query_text: {query_id}")
        queries.append(EvalQuery(query_id, text, source_query_id))
    return queries


def weighted_rrf_fuse(rankings: Sequence[tuple[Sequence[str], float]], rrf_k: int = 60) -> list[str]:
    scores: dict[str, float] = defaultdict(float)
    first_seen: dict[str, int] = {}
    ordinal = 0
    for ranking, weight in rankings:
        for rank, case_id in enumerate(ranking, start=1):
            if case_id not in first_seen:
                first_seen[case_id] = ordinal
                ordinal += 1
            scores[case_id] += weight / (rrf_k + rank)
    return sorted(scores, key=lambda case_id: (-scores[case_id], first_seen[case_id]))


def rrf_fuse(dense: Sequence[str], sparse: Sequence[str], rrf_k: int = 60) -> list[str]:
    return weighted_rrf_fuse(((dense, 1.0), (sparse, 1.0)), rrf_k)


def per_query_metrics(ranking: Sequence[str], relevant: set[str], ks: Sequence[int]) -> dict[str, float]:
    result: dict[str, float] = {}
    for k in ks:
        top = list(ranking[:k])
        hits = [1 if case_id in relevant else 0 for case_id in top]
        hit_count = sum(hits)
        result[f"hit_rate@{k}"] = float(hit_count > 0)
        result[f"recall@{k}"] = hit_count / len(relevant) if relevant else 0.0
        result[f"mrr@{k}"] = next((1.0 / rank for rank, hit in enumerate(hits, start=1) if hit), 0.0)
        dcg = sum(hit / math.log2(rank + 1) for rank, hit in enumerate(hits, start=1))
        ideal = min(k, len(relevant))
        idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal + 1))
        result[f"ndcg@{k}"] = dcg / idcg if idcg else 0.0
    return result


def aggregate_metrics(rows: Sequence[dict[str, float]], latencies_ms: Sequence[float]) -> dict[str, float | int]:
    keys = sorted({key for row in rows for key in row})
    result: dict[str, float | int] = {key: sum(row[key] for row in rows) / len(rows) for key in keys} if rows else {}
    ordered = sorted(latencies_ms)
    result["query_count"] = len(rows)
    result["latency_p50_ms"] = statistics.median(ordered) if ordered else 0.0
    result["latency_p95_ms"] = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] if ordered else 0.0
    return result


class CaseRetrievalEvaluator:
    def __init__(self, qdrant_url: str, collection: str, model_path: Path, device: str, embed_batch_size: int = 32):
        self.client = QdrantClient(url=qdrant_url, timeout=120, check_compatibility=False, trust_env=False)
        self.collection = collection
        self.embedder = BGEM3Embedder(model_path, device=device, batch_size=embed_batch_size)

    def retrieve(self, queries: Sequence[EvalQuery], candidate_k: int) -> list[dict[str, Any]]:
        encoded: EmbeddedBatch = self.embedder.encode([query.query_text for query in queries])
        rows: list[dict[str, Any]] = []
        for index, query in enumerate(tqdm(queries, desc="Qdrant dense+sparse retrieval")):
            started = time.perf_counter()
            dense_response = self.client.query_points(
                self.collection, query=encoded.dense[index], using="dense", limit=candidate_k,
                with_payload=["case_id"], with_vectors=False,
            )
            dense_ms = (time.perf_counter() - started) * 1000
            started = time.perf_counter()
            sparse_response = self.client.query_points(
                self.collection,
                query=SparseVector(indices=encoded.sparse_indices[index], values=encoded.sparse_values[index]),
                using="text_sparse", limit=candidate_k, with_payload=["case_id"], with_vectors=False,
            )
            sparse_ms = (time.perf_counter() - started) * 1000
            dense = [str(point.payload["case_id"]) for point in dense_response.points]
            sparse = [str(point.payload["case_id"]) for point in sparse_response.points]
            rows.append({
                "query_id": query.query_id, "qrel_query_id": query.qrel_query_id,
                "dense": dense, "sparse": sparse, "hybrid": rrf_fuse(dense, sparse)[:candidate_k],
                "dense_latency_ms": dense_ms, "sparse_latency_ms": sparse_ms,
            })
        return rows


def evaluate_rankings(track: str, rows: Sequence[dict[str, Any]], qrels: dict[str, set[str]], ks: Sequence[int]) -> dict[str, Any]:
    modes = ("dense", "sparse", "hybrid")
    report: dict[str, Any] = {"track": track, "queries": len(rows), "metrics": {}}
    details: list[dict[str, Any]] = []
    for mode in modes:
        metric_rows: list[dict[str, float]] = []
        latencies: list[float] = []
        for row in rows:
            relevant = qrels.get(row["qrel_query_id"], set())
            metrics = per_query_metrics(row[mode], relevant, ks)
            metric_rows.append(metrics)
            if mode == "dense":
                latency = row["dense_latency_ms"]
            elif mode == "sparse":
                latency = row["sparse_latency_ms"]
            else:
                latency = row["dense_latency_ms"] + row["sparse_latency_ms"]
            latencies.append(latency)
            details.append({"track": track, "mode": mode, "query_id": row["query_id"], "qrel_query_id": row["qrel_query_id"], "relevant_count": len(relevant), "ranking": row[mode][:max(ks)], **metrics})
        report["metrics"][mode] = aggregate_metrics(metric_rows, latencies)
    report["details"] = details
    return report


def run_tracks(
    evaluation_dir: Path, output_dir: Path, tracks: Sequence[str], evaluator: CaseRetrievalEvaluator,
    candidate_k: int = 50, ks: Sequence[int] = (5, 10), limit: int | None = None,
) -> dict[str, Any]:
    qrels = load_qrels(evaluation_dir / "qrels.jsonl")
    summary: dict[str, Any] = {"candidate_k": candidate_k, "ks": list(ks), "tracks": {}, "skipped": {}}
    all_details: list[dict[str, Any]] = []
    for track in tracks:
        queries = load_track(evaluation_dir, track)
        if not queries:
            summary["skipped"][track] = "query file missing or empty; add user_queries.jsonl"
            continue
        if limit is not None:
            queries = queries[:limit]
        missing_qrels = sorted({query.qrel_query_id for query in queries if query.qrel_query_id not in qrels})
        if missing_qrels:
            raise ValueError(f"{track}: missing qrels for {len(missing_qrels)} source query IDs")
        rows = evaluator.retrieve(queries, candidate_k)
        write_jsonl(output_dir / f"{track}_retrieval_cache.jsonl", rows)
        report = evaluate_rankings(track, rows, qrels, ks)
        all_details.extend(report.pop("details"))
        summary["tracks"][track] = report
    write_json(output_dir / "retrieval_summary.json", summary)
    write_jsonl(output_dir / "retrieval_details.jsonl", all_details)
    return summary
