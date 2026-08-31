from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

from lawagent_evaluation.cases import load_qrels, per_query_metrics, read_jsonl
from lawagent_ingestion.laws.pipeline import write_json, write_jsonl


def _minmax(values: dict[str, float], ordered_ids: Sequence[str]) -> dict[str, float]:
    selected = [values[item] for item in ordered_ids]
    low, high = min(selected), max(selected)
    if high == low:
        return {item: 0.5 for item in ordered_ids}
    return {item: (values[item] - low) / (high - low) for item in ordered_ids}


def fuse_hybrid_reranker(
    hybrid: Sequence[str],
    rerank_scores: dict[str, float],
    *,
    candidate_k: int,
    hybrid_weight: float,
) -> list[str]:
    """Fuse cached Hybrid rank and cross-encoder logits within a Hybrid prefix."""
    if candidate_k <= 0:
        raise ValueError("candidate_k must be positive")
    if not 0.0 <= hybrid_weight <= 1.0:
        raise ValueError("hybrid_weight must be between 0 and 1")
    candidates = list(hybrid[:candidate_k])
    missing = [item for item in candidates if item not in rerank_scores]
    if missing:
        raise ValueError(f"missing reranker scores for {len(missing)} candidates")
    length = len(candidates)
    hybrid_scores = {
        item: 1.0 if length == 1 else 1.0 - (rank / (length - 1))
        for rank, item in enumerate(candidates)
    }
    normalized_rerank = _minmax(rerank_scores, candidates)
    original_rank = {item: rank for rank, item in enumerate(candidates)}
    combined = {
        item: hybrid_weight * hybrid_scores[item] + (1.0 - hybrid_weight) * normalized_rerank[item]
        for item in candidates
    }
    return sorted(candidates, key=lambda item: (-combined[item], original_rank[item]))


def _average(rows: Iterable[dict[str, float]]) -> dict[str, float]:
    values: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for key, value in row.items():
            values[key].append(value)
    return {key: sum(items) / len(items) for key, items in sorted(values.items())}


def run_cached_grid(
    *,
    cache_path: Path,
    qrels_path: Path,
    output_dir: Path,
    candidate_ks: Sequence[int],
    hybrid_weights: Sequence[float],
    ks: Sequence[int] = (5, 10),
    limit: int | None = None,
) -> dict[str, Any]:
    rows = list(read_jsonl(cache_path))
    if limit is not None:
        rows = rows[:limit]
    if not rows:
        raise ValueError("retrieval cache is empty")
    available_k = min(len(row.get("case_hybrid") or []) for row in rows)
    invalid = sorted({value for value in candidate_ks if value <= 0 or value > available_k})
    if invalid:
        raise ValueError(f"candidate_ks outside cached range 1..{available_k}: {invalid}")
    if max(ks) > max(candidate_ks):
        raise ValueError("largest metric k cannot exceed largest candidate_k")

    qrels = load_qrels(qrels_path)
    baseline_per_query: dict[str, dict[str, float]] = {}
    for row in rows:
        baseline_per_query[str(row["query_id"])] = per_query_metrics(
            row["case_hybrid"], qrels.get(str(row["qrel_query_id"]), set()), ks,
        )
    baseline = _average(baseline_per_query.values())

    configurations: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    comparison_key = f"ndcg@{max(ks)}"
    for candidate_k in candidate_ks:
        for hybrid_weight in hybrid_weights:
            metric_rows: list[dict[str, float]] = []
            wins = ties = losses = 0
            for row in rows:
                ranking = fuse_hybrid_reranker(
                    row["case_hybrid"], row["case_rerank_scores"],
                    candidate_k=candidate_k, hybrid_weight=hybrid_weight,
                )
                metrics = per_query_metrics(
                    ranking, qrels.get(str(row["qrel_query_id"]), set()), ks,
                )
                baseline_value = baseline_per_query[str(row["query_id"])][comparison_key]
                delta = metrics[comparison_key] - baseline_value
                wins += delta > 1e-12
                losses += delta < -1e-12
                ties += abs(delta) <= 1e-12
                metric_rows.append(metrics)
                details.append({
                    "query_id": str(row["query_id"]),
                    "qrel_query_id": str(row["qrel_query_id"]),
                    "candidate_k": candidate_k,
                    "hybrid_weight": hybrid_weight,
                    "ranking": ranking[:max(ks)],
                    **metrics,
                })
            configurations.append({
                "candidate_k": candidate_k,
                "hybrid_weight": hybrid_weight,
                "reranker_weight": 1.0 - hybrid_weight,
                "metrics": _average(metric_rows),
                f"paired_{comparison_key}": {"wins": wins, "ties": ties, "losses": losses},
            })

    primary = (f"recall@{max(ks)}", f"ndcg@{max(ks)}", f"mrr@{max(ks)}")
    best = max(
        configurations,
        key=lambda item: tuple(item["metrics"][key] for key in primary),
    )
    summary = {
        "mode": "cached_phase_a",
        "query_count": len(rows),
        "cache_path": str(cache_path),
        "cached_candidate_limit": available_k,
        "candidate_ks": list(candidate_ks),
        "hybrid_weights": list(hybrid_weights),
        "ks": list(ks),
        "score_normalization": "per-query min-max for reranker logits; linear rank score for Hybrid",
        "baseline_hybrid": baseline,
        "selection_order": list(primary),
        "best": best,
        "configurations": configurations,
        "limitations": [
            "Reuses cached logits, so it does not test reranker max_length or text templates.",
            "candidate_k is a prefix of the cached Hybrid Top-50, not a new Qdrant retrieval.",
            "qrels are local to each source JSON and incomplete across the full corpus.",
        ],
    }
    write_json(output_dir / "reranker_grid_summary.json", summary)
    write_jsonl(output_dir / "reranker_grid_details.jsonl", details)
    return summary
