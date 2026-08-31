from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lawagent_evaluation.cases import load_qrels, per_query_metrics, read_jsonl
from lawagent_evaluation.joint_retrieval import load_query_case_labels
from lawagent_evaluation.legal_basis_callback import citations_from_legal_basis
from lawagent_ingestion.laws.pipeline import write_jsonl


def _rank_map(values: list[str], top_k: int = 10) -> dict[str, int]:
    return {case_id: rank for rank, case_id in enumerate(values[:top_k], start=1)}


def _tags(payload: dict[str, Any]) -> set[str]:
    return {
        value for value in (
            *(payload.get("case_causes") or []), payload.get("category_l1"), payload.get("category_l2")
        ) if value
    }


def _citation_text(items: Iterable[dict[str, Any]]) -> str:
    values = citations_from_legal_basis(items)
    return "；".join(f"{item.law_title} 第{item.article_no}条" for item in values) or "无"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a human-readable review report for joint retrieval")
    parser.add_argument("--evaluation-dir", type=Path, default=PROJECT_ROOT / "data/evaluation/cases_v0_1")
    parser.add_argument("--case-documents", type=Path, default=PROJECT_ROOT / "data/processed/cases_v0_1/documents.jsonl")
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--details", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()

    cache = {str(item["qrel_query_id"]): item for item in read_jsonl(args.cache)}
    details = {str(item["qrel_query_id"]): item for item in read_jsonl(args.details)}
    labels = load_query_case_labels(args.evaluation_dir / "query_case_references.jsonl")
    qrels = load_qrels(args.evaluation_dir / "qrels.jsonl")
    queries = {str(item["query_id"]): item for item in read_jsonl(args.evaluation_dir / "query_case_references.jsonl") if str(item["query_id"]) in cache}
    query_texts = {str(item["query_id"]): str(item["query_text"]) for item in read_jsonl(args.evaluation_dir / "case_queries.jsonl") if str(item["query_id"]) in cache}
    needed_ids = {case_id for query_id in cache for case_id in qrels.get(query_id, set())}
    documents: dict[str, dict[str, Any]] = {}
    for item in read_jsonl(args.case_documents):
        case_id = str(item["case_id"])
        if case_id in needed_ids:
            documents[case_id] = item

    report_rows: list[dict[str, Any]] = []
    markdown = [
        "# 前10个 Query Case 联合检索人工审阅报告", "",
        "> 本报告使用脱敏后的 query/candidate 检索视图。H=全库 Hybrid，S=结构化通道，J=两路联合；排名为空表示未进入该路 Top-10。", "",
    ]
    for query_id in sorted(cache, key=lambda value: int(value)):
        row = cache[query_id]
        detail = details[query_id]
        gold = qrels.get(query_id, set())
        query = queries[query_id].get("query_case") or {}
        query_tags = set(labels[query_id].structural_tags)
        rankings = {
            "hybrid": row["case_hybrid"],
            "structural": row.get("case_structural", []),
            "joint": row.get("case_hybrid_structural", row["case_hybrid"]),
            "reranker": row.get("case_reranked", []),
        }
        rank_maps = {name: _rank_map(values, args.top_k) for name, values in rankings.items()}
        candidate_ids = list(dict.fromkeys(
            rankings["hybrid"][:args.top_k] + rankings["structural"][:args.top_k] + rankings["joint"][:args.top_k]
        ))
        payloads = row["case_payloads"]
        candidates = []
        for case_id in candidate_ids:
            payload = payloads[case_id]
            candidates.append({
                "case_id": case_id, "title": payload.get("title"), "relevant": case_id in gold,
                "hybrid_rank": rank_maps["hybrid"].get(case_id),
                "structural_rank": rank_maps["structural"].get(case_id),
                "joint_rank": rank_maps["joint"].get(case_id),
                "shared_structural_tags": sorted(query_tags & _tags(payload)),
            })
        missed = [
            {"case_id": case_id, "title": documents.get(case_id, {}).get("title"),
             "legal_basis": documents.get(case_id, {}).get("legal_basis") or []}
            for case_id in sorted(gold) if case_id not in set(rankings["joint"][:args.top_k])
        ]
        review = {
            "query_id": query_id, "query_text": query_texts.get(query_id, ""),
            "query_structural_tags": sorted(query_tags), "query_keywords": sorted(labels[query_id].keywords),
            "query_legal_basis": query.get("LegalBasis") or [], "relevant_count": len(gold),
            "metrics": {name: per_query_metrics(values, gold, (5, 10, 50)) for name, values in rankings.items()},
            "top_candidates": candidates, "missed_relevant_top10": missed,
            "legal_metrics": detail.get("legal_metrics", {}), "callbacks": detail.get("callbacks", []),
        }
        report_rows.append(review)

        markdown.extend([
            f"## Query {query_id}", "", f"- 检索文本：{review['query_text']}",
            f"- 结构标签：{'；'.join(review['query_structural_tags']) or '无'}",
            f"- Keywords：{'；'.join(review['query_keywords']) or '无'}",
            f"- Query LegalBasis：{_citation_text(review['query_legal_basis'])}",
            f"- Relevant cases：{len(gold)}",
            f"- Recall@10：H={review['metrics']['hybrid']['recall@10']:.4f}；S={review['metrics']['structural']['recall@10']:.4f}；J={review['metrics']['joint']['recall@10']:.4f}；Reranker={review['metrics']['reranker']['recall@10']:.4f}",
            "", "| Relevant | H | S | J | Case ID | 共同结构标签 | 标题 |", "|---|---:|---:|---:|---|---|---|",
        ])
        for candidate in candidates:
            markdown.append(
                f"| {'是' if candidate['relevant'] else '否'} | {candidate['hybrid_rank'] or ''} | {candidate['structural_rank'] or ''} | {candidate['joint_rank'] or ''} | "
                f"`{candidate['case_id']}` | {'；'.join(candidate['shared_structural_tags']) or '无'} | {candidate['title'] or ''} |"
            )
        markdown.extend(["", f"### 未进入联合 Top-10 的 Relevant Cases（{len(missed)}）", ""])
        for item in missed:
            markdown.append(f"- `{item['case_id']}` {item['title'] or ''}；LegalBasis：{_citation_text(item['legal_basis'])}")
        markdown.extend(["", f"### 法条回调", "", f"- 指标：`{json.dumps(review['legal_metrics'], ensure_ascii=False)}`", ""])

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "manual_review.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    write_jsonl(args.output_dir / "manual_review.jsonl", report_rows)
    print(json.dumps({"queries": len(report_rows), "markdown": str(args.output_dir / 'manual_review.md'), "jsonl": str(args.output_dir / 'manual_review.jsonl')}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
