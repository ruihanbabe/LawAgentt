from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from lawagent_ingestion.cases.pipeline import build_retrieval_text, extract_parties
from lawagent_evaluation.reranker_grid import fuse_hybrid_reranker
from lawagent_runtime.evidence_views import build_case_evidence_view, build_law_evidence_view
from lawagent_runtime.pii import PIIPolicy, PIIReviewer


@dataclass(frozen=True)
class RagasRetrievalSample:
    query_id: str
    user_input: str
    reference: str
    law_reference: str
    reference_case_ids: list[str]
    contexts: dict[str, list[str]]
    context_ids: dict[str, list[str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "user_input": self.user_input,
            "reference": self.reference,
            "law_reference": self.law_reference,
            "reference_case_ids": self.reference_case_ids,
            "contexts": self.contexts,
            "context_ids": self.context_ids,
        }


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _index_jsonl(path: Path, key: str) -> dict[str, dict[str, Any]]:
    return {str(row[key]): row for row in read_jsonl(path)}


def _legal_basis_text(items: Iterable[dict[str, Any]]) -> str:
    values = []
    for item in items:
        law = str(item.get("law") or "").strip()
        terms = str(item.get("terms") or "").strip()
        if law or terms:
            values.append(" ".join(value for value in (law, terms) if value))
    return "；".join(values)


def _safe_reference(raw: dict[str, Any], reviewer: PIIReviewer) -> str:
    parties = extract_parties(raw)
    names = [party.name for party in parties if party.name]
    parts = []
    for label, key in (("裁判理由", "JudgeReason"), ("裁判结果", "JudgeResult")):
        reviewed = reviewer.review(raw.get(key), party_names=names, policy=PIIPolicy.MASK)
        if reviewed.text.strip():
            parts.append(f"{label}：{reviewed.text.strip()}")
    legal_basis = _legal_basis_text(raw.get("LegalBasis") or [])
    if legal_basis:
        parts.append(f"法律依据：{legal_basis}")
    return "\n".join(parts).strip()


def _safe_law_reference(raw: dict[str, Any], reviewer: PIIReviewer) -> str:
    parties = extract_parties(raw)
    names = [party.name for party in parties if party.name]
    reason = reviewer.review(raw.get("JudgeReason"), party_names=names, policy=PIIPolicy.MASK).text.strip()
    basis = _legal_basis_text(raw.get("LegalBasis") or [])
    parts = [f"法律适用理由：{reason}" if reason else "", f"法律依据：{basis}" if basis else ""]
    return "\n".join(part for part in parts if part)


def _case_context(payload: dict[str, Any], reviewer: PIIReviewer) -> str:
    view = build_case_evidence_view(payload, reviewer=reviewer, max_chars_per_field=1200)
    basis = "；".join(
        " ".join(value for value in (item.law, item.terms) if value)
        for item in view.legal_basis
        if item.law or item.terms
    )
    parts = [
        f"标题：{view.title}",
        f"案由：{'；'.join(view.case_causes)}" if view.case_causes else "",
        f"分类：{'；'.join(x for x in (view.category_l1, view.category_l2) if x)}"
        if view.category_l1 or view.category_l2 else "",
        f"事实：{view.fact_snippet}" if view.fact_snippet else "",
        f"裁判理由：{view.reasoning_snippet}" if view.reasoning_snippet else "",
        f"裁判结果：{view.result_summary}" if view.result_summary else "",
        f"法律依据：{basis}" if basis else "",
    ]
    return "\n".join(part for part in parts if part)


def _law_context(payload: dict[str, Any], reviewer: PIIReviewer) -> str:
    view = build_law_evidence_view(payload, reviewer=reviewer, max_chars=4000)
    article = f" 第{view.article_no}条" if view.article_no else ""
    return f"{view.title}{article}\n{view.content}"


def _load_law_payloads(chunks_path: Path, needed_ids: set[str]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    if not needed_ids:
        return found
    for payload in read_jsonl(chunks_path):
        chunk_id = str(payload.get("chunk_id") or "")
        if chunk_id in needed_ids:
            found[chunk_id] = payload
            if len(found) == len(needed_ids):
                break
    return found


def build_ragas_samples(
    *,
    retrieval_cache_path: Path,
    joint_details_path: Path,
    references_path: Path,
    queries_path: Path,
    qrels_path: Path,
    law_chunks_path: Path,
    compact_scores_path: Path | None = None,
    compact_hybrid_weight: float = 0.75,
    limit: int | None = None,
    top_k: int = 10,
    include_law_variants: bool = True,
) -> list[RagasRetrievalSample]:
    references = _index_jsonl(references_path, "query_id")
    queries = _index_jsonl(queries_path, "query_id")
    qrels: dict[str, list[str]] = {}
    for row in read_jsonl(qrels_path):
        qrels.setdefault(str(row["query_id"]), []).append(str(row["case_id"]))

    cache_rows: list[dict[str, Any]] = []
    for row in read_jsonl(retrieval_cache_path):
        cache_rows.append(row)
        if limit is not None and len(cache_rows) >= limit:
            break
    details = _index_jsonl(joint_details_path, "query_id") if include_law_variants else {}
    callback_ids = {
        str(item["chunk_id"])
        for row in cache_rows
        for item in details[str(row["query_id"])].get("callbacks", [])
        if item.get("status") == "matched" and item.get("chunk_id")
    } if include_law_variants else set()
    callback_payloads = _load_law_payloads(law_chunks_path, callback_ids)
    compact_scores = _index_jsonl(compact_scores_path, "query_id") if compact_scores_path else {}
    reviewer = PIIReviewer()
    samples: list[RagasRetrievalSample] = []

    for cache in cache_rows:
        query_id = str(cache["query_id"])
        qrel_query_id = str(cache["qrel_query_id"])
        raw_query = references[qrel_query_id]["query_case"]
        user_input = str(queries[query_id]["query_text"] or "").strip()
        user_input = reviewer.review(user_input, policy=PIIPolicy.MASK).text
        reference = _safe_reference(raw_query, reviewer)
        law_reference = _safe_law_reference(raw_query, reviewer)

        case_payloads = cache.get("case_payloads") or {}
        hybrid_ids = [str(value) for value in cache.get("case_hybrid", [])[:top_k]]
        if query_id in compact_scores:
            compact = compact_scores[query_id]
            reranked_ids = fuse_hybrid_reranker(
                compact["case_hybrid"], compact["case_rerank_scores"],
                candidate_k=len(compact["case_hybrid"]), hybrid_weight=compact_hybrid_weight,
            )[:top_k]
        else:
            reranked_ids = [str(value) for value in cache.get("case_reranked", [])[:top_k]]
        contexts = {
            "case_hybrid": [_case_context(case_payloads[item], reviewer) for item in hybrid_ids],
            "case_reranked": [_case_context(case_payloads[item], reviewer) for item in reranked_ids],
        }
        context_ids = {
            "case_hybrid": hybrid_ids,
            "case_reranked": reranked_ids,
        }
        if include_law_variants:
            direct_ids = [str(value) for value in cache.get("law_direct", [])[:top_k]]
            callback_for_query = [
                str(item["chunk_id"])
                for item in details[query_id].get("callbacks", [])
                if item.get("status") == "matched" and item.get("chunk_id")
            ]
            callback_ids_ordered = list(dict.fromkeys(callback_for_query))[:top_k]
            combined_ids = list(dict.fromkeys([*callback_ids_ordered, *direct_ids]))[:top_k]
            law_payloads = {**(cache.get("law_payloads") or {}), **callback_payloads}
            contexts.update({
                "law_direct": [_law_context(law_payloads[item], reviewer) for item in direct_ids],
                "law_callback": [_law_context(law_payloads[item], reviewer) for item in callback_ids_ordered],
                "law_combined": [_law_context(law_payloads[item], reviewer) for item in combined_ids],
            })
            context_ids.update({
                "law_direct": direct_ids,
                "law_callback": callback_ids_ordered,
                "law_combined": combined_ids,
            })
        samples.append(RagasRetrievalSample(
            query_id=query_id,
            user_input=user_input,
            reference=reference,
            law_reference=law_reference,
            reference_case_ids=sorted(set(qrels.get(qrel_query_id, []))),
            contexts=contexts,
            context_ids=context_ids,
        ))
    return samples


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
