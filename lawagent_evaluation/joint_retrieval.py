from __future__ import annotations

import json
import math
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Sequence

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchAny, SparseVector
from tqdm import tqdm

from lawagent_evaluation.cases import EvalQuery, load_qrels, load_track, per_query_metrics, read_jsonl, rrf_fuse, weighted_rrf_fuse
from lawagent_evaluation.legal_basis_callback import (
    CallbackResult,
    LawCatalog,
    LegalCitation,
    citations_from_legal_basis,
    canonical_law_title,
    normalize_law_title,
)
from lawagent_evaluation.reranker import BGEReranker, RerankItem
from lawagent_ingestion.laws.embedder import BGEM3Embedder
from lawagent_ingestion.laws.pipeline import write_json, write_jsonl


@dataclass(frozen=True, slots=True)
class QueryLegalGold:
    query_id: str
    query_citations: frozenset[LegalCitation]
    relevant_support: dict[LegalCitation, int]
    relevant_case_count: int

    @property
    def consensus_citations(self) -> frozenset[LegalCitation]:
        threshold = max(3, math.ceil(self.relevant_case_count / 2))
        return frozenset(citation for citation, count in self.relevant_support.items() if count >= threshold)

    @property
    def graded_citations(self) -> dict[LegalCitation, int]:
        result = {citation: 1 for citation in self.relevant_support}
        result.update({citation: 2 for citation in self.consensus_citations})
        result.update({citation: 3 for citation in self.query_citations})
        return result


@dataclass(frozen=True, slots=True)
class QueryCaseLabels:
    case_causes: frozenset[str]
    category_l1: str | None
    category_l2: str | None
    keywords: frozenset[str]

    @property
    def structural_tags(self) -> frozenset[str]:
        return frozenset(value for value in (*self.case_causes, self.category_l1, self.category_l2) if value)


def load_query_case_labels(path: Path) -> dict[str, QueryCaseLabels]:
    result: dict[str, QueryCaseLabels] = {}
    for item in read_jsonl(path):
        query_id = str(item["query_id"])
        case = item.get("query_case") or {}
        categories = case.get("Category") or []
        first_category = categories[0] if categories and isinstance(categories[0], dict) else {}
        result[query_id] = QueryCaseLabels(
            frozenset(str(value) for value in (case.get("CaseCause") or []) if value),
            str(first_category.get("cat_1")) if first_category.get("cat_1") else None,
            str(first_category.get("cat_2")) if first_category.get("cat_2") else None,
            frozenset(str(value) for value in (case.get("Keywords") or []) if value),
        )
    return result


def label_match_score(labels: QueryCaseLabels, payload: dict[str, Any]) -> float:
    score = 0.0
    score += 4.0 * len(labels.case_causes & set(payload.get("case_causes") or []))
    if labels.category_l2 and labels.category_l2 == payload.get("category_l2"):
        score += 2.0
    if labels.category_l1 and labels.category_l1 == payload.get("category_l1"):
        score += 1.0
    score += 0.5 * len(labels.keywords & set(payload.get("keywords") or []))
    return score


def label_weighted_rerank(
    ranking: Sequence[str], payloads: dict[str, dict[str, Any]], labels: QueryCaseLabels,
    label_weight: float = 0.35,
) -> list[str]:
    if not 0.0 <= label_weight <= 1.0:
        raise ValueError("label_weight must be between 0 and 1")
    label_scores = {case_id: label_match_score(labels, payloads[case_id]) for case_id in ranking}
    maximum = max(label_scores.values(), default=0.0)
    combined: dict[str, float] = {}
    length = max(len(ranking), 1)
    for rank, case_id in enumerate(ranking):
        original_score = 1.0 - rank / length
        normalized_label = label_scores[case_id] / maximum if maximum else 0.0
        combined[case_id] = (1.0 - label_weight) * original_score + label_weight * normalized_label
    return sorted(ranking, key=lambda case_id: (-combined[case_id], ranking.index(case_id)))


def load_query_legal_gold(query_path: Path, qrels_path: Path, documents_path: Path) -> dict[str, QueryLegalGold]:
    qrels = load_qrels(qrels_path)
    needed_case_ids = {case_id for case_ids in qrels.values() for case_id in case_ids}
    case_citations: dict[str, frozenset[LegalCitation]] = {}
    for document in read_jsonl(documents_path):
        case_id = str(document["case_id"])
        if case_id in needed_case_ids:
            case_citations[case_id] = frozenset(citations_from_legal_basis(document.get("legal_basis") or []))
    result: dict[str, QueryLegalGold] = {}
    for item in read_jsonl(query_path):
        query_id = str(item["query_id"])
        legal_basis = item.get("query_case", {}).get("LegalBasis") or []
        support: dict[LegalCitation, int] = defaultdict(int)
        relevant_ids = qrels.get(query_id, set())
        for case_id in relevant_ids:
            for citation in case_citations.get(case_id, frozenset()):
                support[citation] += 1
        result[query_id] = QueryLegalGold(
            query_id, frozenset(citations_from_legal_basis(legal_basis)), dict(support), len(relevant_ids),
        )
    return result


def callback_from_cases(
    case_ids: Sequence[str], case_payloads: dict[str, dict[str, Any]], catalog: LawCatalog,
    top_n: int, event_date=None,
) -> list[CallbackResult]:
    citations: list[LegalCitation] = []
    seen: set[LegalCitation] = set()
    for case_id in case_ids[:top_n]:
        for citation in citations_from_legal_basis(case_payloads.get(case_id, {}).get("legal_basis") or []):
            if citation not in seen:
                seen.add(citation)
                citations.append(citation)
    return [catalog.resolve(citation, event_date) for citation in citations]


def merge_law_rankings(direct_chunk_ids: Sequence[str], callbacks: Sequence[CallbackResult]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for chunk_id in list(direct_chunk_ids) + [item.record.chunk_id for item in callbacks if item.record]:
        if chunk_id not in seen:
            seen.add(chunk_id)
            result.append(chunk_id)
    return result


def legal_metrics(
    direct_records: Sequence[dict[str, Any]], callbacks: Sequence[CallbackResult], gold: QueryLegalGold,
) -> dict[str, float | int]:
    citation_key = lambda item: (canonical_law_title(item.law_title), item.article_no)
    query_pairs = {citation_key(item) for item in gold.query_citations}
    consensus_pairs = {citation_key(item) for item in gold.consensus_citations}
    graded = {citation_key(item): grade for item, grade in gold.graded_citations.items()}
    direct_ranking = [(canonical_law_title(str(item.get("title") or "")), str(item.get("article_no") or "")) for item in direct_records]
    callback_ranking = [
        (canonical_law_title(item.record.title), item.record.article_no)
        for item in callbacks if item.status == "matched" and item.record is not None
    ]
    joint_ranking = list(dict.fromkeys(direct_ranking + callback_ranking))
    direct_pairs, callback_pairs, joint_pairs = set(direct_ranking), set(callback_ranking), set(joint_ranking)
    query_hits = query_pairs & joint_pairs
    consensus_hits = consensus_pairs & joint_pairs
    gains = [graded.get(pair, 0) for pair in joint_ranking]
    dcg = sum((2**gain - 1) / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
    ideal_gains = sorted(graded.values(), reverse=True)[:len(joint_ranking)]
    idcg = sum((2**gain - 1) / math.log2(rank + 1) for rank, gain in enumerate(ideal_gains, start=1))
    return {
        "has_query_legal_gold": float(bool(query_pairs)),
        "query_legal_basis_count": len(query_pairs),
        "query_legal_basis_hit": float(bool(query_hits)),
        "query_legal_basis_recall": len(query_hits) / len(query_pairs) if query_pairs else 0.0,
        "direct_query_legal_basis_hit": float(bool(query_pairs & direct_pairs)),
        "callback_query_legal_basis_hit": float(bool(query_pairs & callback_pairs)),
        "consensus_legal_basis_count": len(consensus_pairs),
        "consensus_legal_basis_hit": float(bool(consensus_hits)),
        "consensus_legal_basis_recall": len(consensus_hits) / len(consensus_pairs) if consensus_pairs else 0.0,
        "graded_legal_ndcg": dcg / idcg if idcg else 0.0,
        "callback_added_query_gold": len((query_pairs & callback_pairs) - direct_pairs),
        "callback_attempts": len(callbacks),
        "callback_matched": sum(item.status == "matched" for item in callbacks),
        "callback_unmapped": sum(item.status != "matched" for item in callbacks),
    }


def reconstruct_case_text(payload: dict[str, Any]) -> str:
    """Build the compact, non-leaking cross-encoder document view."""
    fields = (
        ("诉请与核心事实", payload.get("claims_and_facts")),
        ("案由", "；".join(payload.get("case_causes") or [])),
        ("关键词", "；".join(payload.get("keywords") or [])),
        ("案件分类", "；".join(value for value in (payload.get("category_l1"), payload.get("category_l2")) if value)),
        ("案件类型", payload.get("case_type")),
        ("审理程序", payload.get("procedure")),
    )
    return "\n".join(f"{label}：{value}" for label, value in fields if value).strip() or "案例事实信息缺失"


def compact_query_text(query_text: str) -> str:
    """Reorder an existing structured query and drop procedural case-record boilerplate."""
    values: dict[str, str] = {}
    for line in query_text.splitlines():
        label, separator, value = line.partition("：")
        if separator and value.strip():
            values[label.strip()] = value.strip()
    fields = (
        ("诉请与核心事实", values.get("诉请与事实")),
        ("案由", values.get("案由")),
        ("关键词", values.get("关键词")),
        ("案件分类", values.get("案件分类")),
        ("案件类型", values.get("案件类型")),
        ("审理程序", values.get("审理程序")),
    )
    compact = "\n".join(f"{label}：{value}" for label, value in fields if value)
    return compact or query_text.strip() or "案例事实信息缺失"


def average_numeric(rows: Iterable[dict[str, float | int]]) -> dict[str, float]:
    values: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for key, value in row.items():
            values[key].append(float(value))
    return {key: sum(items) / len(items) for key, items in sorted(values.items())}


class JointRetrievalEvaluator:
    def __init__(
        self, qdrant_url: str, cases_collection: str, laws_collection: str,
        embedding_model_path: Path, reranker_model_path: Path, device: str,
        embed_batch_size: int = 32, rerank_batch_size: int = 32,
    ) -> None:
        self.client = QdrantClient(url=qdrant_url, timeout=120, check_compatibility=False, trust_env=False)
        self.cases_collection = cases_collection
        self.laws_collection = laws_collection
        self.embedder = BGEM3Embedder(embedding_model_path, device=device, batch_size=embed_batch_size)
        self.reranker = BGEReranker(reranker_model_path, device=device, batch_size=rerank_batch_size)

    def retrieve_one(self, query: EvalQuery, labels: QueryCaseLabels, dense: list[float], sparse_indices: list[int], sparse_values: list[float], candidate_k: int, law_k: int) -> dict[str, Any]:
        started = time.perf_counter()
        case_dense = self.client.query_points(
            self.cases_collection, query=dense, using="dense", limit=candidate_k,
            with_payload=True, with_vectors=False,
        ).points
        case_sparse = self.client.query_points(
            self.cases_collection, query=SparseVector(indices=sparse_indices, values=sparse_values),
            using="text_sparse", limit=candidate_k, with_payload=True, with_vectors=False,
        ).points
        retrieval_ms = (time.perf_counter() - started) * 1000
        payloads = {
            str(point.payload["case_id"]): point.payload
            for point in list(case_dense) + list(case_sparse)
        }
        hybrid = rrf_fuse(
            [str(point.payload["case_id"]) for point in case_dense],
            [str(point.payload["case_id"]) for point in case_sparse],
        )[:candidate_k]
        structural_dense = []
        structural_sparse = []
        structural_started = time.perf_counter()
        if labels.structural_tags:
            structural_filter = Filter(should=[
                FieldCondition(key=field, match=MatchAny(any=sorted(labels.structural_tags)))
                for field in ("case_causes", "category_l1", "category_l2")
            ])
            structural_dense = self.client.query_points(
                self.cases_collection, query=dense, using="dense", query_filter=structural_filter,
                limit=candidate_k, with_payload=True, with_vectors=False,
            ).points
            structural_sparse = self.client.query_points(
                self.cases_collection, query=SparseVector(indices=sparse_indices, values=sparse_values),
                using="text_sparse", query_filter=structural_filter, limit=candidate_k,
                with_payload=True, with_vectors=False,
            ).points
            payloads.update({
                str(point.payload["case_id"]): point.payload
                for point in list(structural_dense) + list(structural_sparse)
            })
        structural = rrf_fuse(
            [str(point.payload["case_id"]) for point in structural_dense],
            [str(point.payload["case_id"]) for point in structural_sparse],
        )[:candidate_k]
        structural_ms = (time.perf_counter() - structural_started) * 1000
        hybrid_structural = weighted_rrf_fuse(((hybrid, 1.0), (structural, 1.0)))[:candidate_k]
        started = time.perf_counter()
        reranked_pairs = self.reranker.rank(
            compact_query_text(query.query_text),
            [RerankItem(case_id, reconstruct_case_text(payloads[case_id])) for case_id in hybrid_structural],
        )
        rerank_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        law_dense = self.client.query_points(
            self.laws_collection, query=dense, using="dense", limit=law_k,
            with_payload=True, with_vectors=False,
        ).points
        law_sparse = self.client.query_points(
            self.laws_collection, query=SparseVector(indices=sparse_indices, values=sparse_values),
            using="text_sparse", limit=law_k, with_payload=True, with_vectors=False,
        ).points
        law_ms = (time.perf_counter() - started) * 1000
        law_payloads = {str(point.payload["chunk_id"]): point.payload for point in list(law_dense) + list(law_sparse)}
        law_hybrid = rrf_fuse(
            [str(point.payload["chunk_id"]) for point in law_dense],
            [str(point.payload["chunk_id"]) for point in law_sparse],
        )[:law_k]
        return {
            "query_id": query.query_id, "qrel_query_id": query.qrel_query_id,
            "case_hybrid": hybrid, "case_structural": structural,
            "case_hybrid_structural": hybrid_structural,
            "case_reranked": [item[0] for item in reranked_pairs],
            "case_rerank_scores": {case_id: score for case_id, score in reranked_pairs},
            "case_payloads": payloads, "law_direct": law_hybrid,
            "law_payloads": law_payloads, "retrieval_latency_ms": retrieval_ms + structural_ms + law_ms,
            "rerank_latency_ms": rerank_ms,
        }

    def retrieve(self, queries: Sequence[EvalQuery], query_labels: dict[str, QueryCaseLabels], candidate_k: int, law_k: int) -> list[dict[str, Any]]:
        encoded = self.embedder.encode([query.query_text for query in queries])
        return [
            self.retrieve_one(query, query_labels[query.qrel_query_id], encoded.dense[index], encoded.sparse_indices[index], encoded.sparse_values[index], candidate_k, law_k)
            for index, query in enumerate(tqdm(queries, desc="Joint case/law retrieval"))
        ]


def _latency_summary(values: Sequence[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "p50_ms": statistics.median(ordered) if ordered else 0.0,
        "p95_ms": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))] if ordered else 0.0,
    }


def run_joint_evaluation(
    evaluation_dir: Path, law_chunks_path: Path, case_documents_path: Path, output_dir: Path, evaluator: JointRetrievalEvaluator | None,
    track: str = "case_to_case", candidate_k: int = 50, rerank_top_n: int = 10,
    callback_case_top_n: int = 5, law_k: int = 10, ks: Sequence[int] = (5, 10), limit: int | None = None,
    retrieval_cache: Path | None = None,
) -> dict[str, Any]:
    queries = load_track(evaluation_dir, track)
    if limit is not None:
        queries = queries[:limit]
    qrels = load_qrels(evaluation_dir / "qrels.jsonl")
    legal_gold = load_query_legal_gold(
        evaluation_dir / "query_case_references.jsonl", evaluation_dir / "qrels.jsonl", case_documents_path,
    )
    query_labels = load_query_case_labels(evaluation_dir / "query_case_references.jsonl")
    catalog = LawCatalog.from_jsonl(law_chunks_path)
    if retrieval_cache is not None:
        rows = list(read_jsonl(retrieval_cache))
        if len(rows) != len(queries):
            raise ValueError(f"retrieval cache has {len(rows)} rows, expected {len(queries)}")
    else:
        if evaluator is None:
            raise ValueError("evaluator is required when retrieval_cache is not provided")
        rows = evaluator.retrieve(queries, query_labels, candidate_k, law_k)
        write_jsonl(output_dir / "joint_retrieval_cache.jsonl", rows)
    case_hybrid_metrics: list[dict[str, float]] = []
    case_structural_metrics: list[dict[str, float]] = []
    case_hybrid_structural_metrics: list[dict[str, float]] = []
    case_label_weighted_metrics: list[dict[str, float]] = []
    case_rerank_metrics: list[dict[str, float]] = []
    legal_metric_rows: list[dict[str, float | int]] = []
    details: list[dict[str, Any]] = []
    for row in rows:
        relevant = qrels.get(row["qrel_query_id"], set())
        case_hybrid_metrics.append(per_query_metrics(row["case_hybrid"], relevant, ks))
        case_structural_metrics.append(per_query_metrics(row.get("case_structural", []), relevant, ks))
        case_hybrid_structural_metrics.append(per_query_metrics(row.get("case_hybrid_structural", row["case_hybrid"]), relevant, ks))
        labels = query_labels[row["qrel_query_id"]]
        label_weighted = label_weighted_rerank(row["case_hybrid"], row["case_payloads"], labels)
        case_label_weighted_metrics.append(per_query_metrics(label_weighted, relevant, ks))
        reranked = row["case_reranked"][:rerank_top_n]
        case_rerank_metrics.append(per_query_metrics(reranked, relevant, ks))
        callbacks = callback_from_cases(reranked, row["case_payloads"], catalog, callback_case_top_n)
        direct_records = [row["law_payloads"][chunk_id] for chunk_id in row["law_direct"]]
        gold = legal_gold.get(row["qrel_query_id"], QueryLegalGold(row["qrel_query_id"], frozenset(), {}, 0))
        law_metrics = legal_metrics(direct_records, callbacks, gold)
        legal_metric_rows.append(law_metrics)
        details.append({
            "query_id": row["query_id"], "qrel_query_id": row["qrel_query_id"],
            "case_hybrid": row["case_hybrid"], "case_label_weighted": label_weighted,
            "case_structural": row.get("case_structural", []),
            "case_hybrid_structural": row.get("case_hybrid_structural", row["case_hybrid"]),
            "case_label_scores": {case_id: label_match_score(labels, row["case_payloads"][case_id]) for case_id in label_weighted},
            "case_reranked": reranked,
            "law_direct": row["law_direct"],
            "callbacks": [{"law_title": item.citation.law_title, "article_no": item.citation.article_no, "status": item.status, "chunk_id": item.record.chunk_id if item.record else None} for item in callbacks],
            "legal_metrics": law_metrics,
            "retrieval_latency_ms": row["retrieval_latency_ms"], "rerank_latency_ms": row["rerank_latency_ms"],
        })
    summary = {
        "track": track, "query_count": len(rows), "candidate_k": candidate_k,
        "rerank_top_n": rerank_top_n, "callback_case_top_n": callback_case_top_n, "law_k": law_k,
        "ablation": {
            "case_matching_hybrid": average_numeric(case_hybrid_metrics),
            "case_matching_structural": average_numeric(case_structural_metrics),
            "case_matching_hybrid_structural": average_numeric(case_hybrid_structural_metrics),
            "case_matching_hybrid_label_weighted": average_numeric(case_label_weighted_metrics),
            "case_matching_hybrid_reranker": average_numeric(case_rerank_metrics),
            "hybrid_reranker_legal_basis_callback": {
                "all_queries": average_numeric(legal_metric_rows),
                "query_gold_eligible_queries": average_numeric(row for row in legal_metric_rows if row["has_query_legal_gold"]),
                "query_gold_eligible_query_count": sum(bool(row["has_query_legal_gold"]) for row in legal_metric_rows),
            },
        },
        "latency": {
            "retrieval": _latency_summary([float(row["retrieval_latency_ms"]) for row in rows]),
            "reranker": _latency_summary([float(row["rerank_latency_ms"]) for row in rows]),
            "end_to_end": _latency_summary([float(row["retrieval_latency_ms"] + row["rerank_latency_ms"]) for row in rows]),
        },
    }
    write_json(output_dir / "joint_summary.json", summary)
    write_jsonl(output_dir / "joint_details.jsonl", details)
    return summary
