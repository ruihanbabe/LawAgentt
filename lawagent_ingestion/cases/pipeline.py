from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import Counter, defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Datatype,
    Distance,
    PayloadSchemaType,
    PointStruct,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)
from tqdm import tqdm

from lawagent_ingestion.laws.embedder import BGEM3Embedder
from lawagent_ingestion.laws.pipeline import write_json, write_jsonl

from .models import CaseDocument, CaseRetrievalPoint, LegalBasisItem, PartyItem


VECTOR_SIZE = 1024
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "text_sparse"
ID_CARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
BANK_CARD_RE = re.compile(r"(?<!\d)\d{16,19}(?!\d)")


@dataclass(slots=True)
class SourceTask:
    source_path: str
    query_id: str
    template_query: str
    query_case: dict[str, Any]
    gt_idx: list[int]
    ctxs: dict[str, dict[str, Any]]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_task(path: Path, data_dir: Path) -> SourceTask:
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = {"q_i", "query", "query_case", "gt_idx", "ctxs"}
    missing = required - raw.keys()
    if missing:
        raise ValueError(f"missing top-level fields: {sorted(missing)}")
    return SourceTask(
        source_path=path.relative_to(data_dir).as_posix(),
        query_id=str(raw["q_i"]),
        template_query=str(raw["query"]),
        query_case=raw["query_case"],
        gt_idx=[int(value) for value in raw["gt_idx"]],
        ctxs=raw["ctxs"],
    )


def extract_categories(raw: dict[str, Any]) -> tuple[str | None, str | None]:
    categories = raw.get("Category") or []
    first = categories[0] if categories and isinstance(categories[0], dict) else {}
    return first.get("cat_1") or None, first.get("cat_2") or None


def extract_parties(raw: dict[str, Any]) -> list[PartyItem]:
    return [
        PartyItem(
            name=str(item.get("NameText") or item.get("Name") or ""),
            role=str(item.get("Prop") or ""),
            entity_type=item.get("LegalEntity"),
        )
        for item in (raw.get("Parties") or [])
        if isinstance(item, dict)
    ]


def redact_text(text: str, parties: list[PartyItem]) -> str:
    value = text or ""
    for party in sorted(parties, key=lambda item: len(item.name), reverse=True):
        if party.name and len(party.name) >= 2:
            replacement = f"[{party.role or '当事人'}]"
            value = value.replace(party.name, replacement)
    value = ID_CARD_RE.sub("[身份证号]", value)
    value = PHONE_RE.sub("[手机号]", value)
    value = BANK_CARD_RE.sub("[银行卡号]", value)
    return value


def build_retrieval_text(raw: dict[str, Any], parties: list[PartyItem]) -> str:
    category_l1, category_l2 = extract_categories(raw)
    parts: list[str] = []
    if raw.get("CaseType"):
        parts.append(f"案件类型：{raw['CaseType']}")
    if raw.get("CaseProc"):
        parts.append(f"审理程序：{raw['CaseProc']}")
    causes = [str(value) for value in (raw.get("CaseCause") or []) if value]
    if causes:
        parts.append(f"案由：{'；'.join(causes)}")
    categories = [value for value in (category_l1, category_l2) if value]
    if categories:
        parts.append(f"案件分类：{'；'.join(categories)}")
    if raw.get("CaseRecord"):
        parts.append(f"案件经过：{redact_text(str(raw['CaseRecord']), parties)}")
    if raw.get("JudgeAccusation"):
        parts.append(f"诉请与事实：{redact_text(str(raw['JudgeAccusation']), parties)}")
    keywords = [str(value) for value in (raw.get("Keywords") or []) if value]
    if keywords:
        parts.append(f"关键词：{'；'.join(keywords)}")
    return "\n".join(parts).strip() or "案例事实信息缺失"


def normalize_case(raw: dict[str, Any], sources: list[str]) -> tuple[CaseDocument, CaseRetrievalPoint]:
    case_id = str(raw.get("CaseId") or "").strip()
    if not case_id:
        raise ValueError("missing CaseId")
    digest = content_hash(raw)
    version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"case|{case_id}|{digest}"))
    point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"case-point|{version_id}"))
    parties = extract_parties(raw)
    category_l1, category_l2 = extract_categories(raw)
    legal_basis = [
        LegalBasisItem(
            law=str(item.get("law") or ""),
            terms=str(item.get("terms") or ""),
        )
        for item in (raw.get("LegalBasis") or [])
        if isinstance(item, dict)
    ]
    retrieval_text = build_retrieval_text(raw, parties)
    redacted_title = redact_text(str(raw.get("Case") or ""), parties)
    shared = {
        "case_id": case_id,
        "case_version_id": version_id,
        "title": redacted_title,
        "case_type": raw.get("CaseType") or None,
        "procedure": raw.get("CaseProc") or None,
        "case_causes": [str(value) for value in (raw.get("CaseCause") or []) if value],
        "category_l1": category_l1,
        "category_l2": category_l2,
        "keywords": [str(value) for value in (raw.get("Keywords") or []) if value],
        "case_record": redact_text(str(raw.get("CaseRecord") or ""), parties),
        "claims_and_facts": redact_text(str(raw.get("JudgeAccusation") or ""), parties),
        "judge_reason": redact_text(str(raw.get("JudgeReason") or ""), parties),
        "judge_result": redact_text(str(raw.get("JudgeResult") or ""), parties),
        "legal_basis": legal_basis,
        "content_hash": digest,
    }
    document = CaseDocument(
        **shared,
        parties=parties,
        source_paths=sorted(sources),
        source_count=len(sources),
    )
    point = CaseRetrievalPoint(
        **{key: value for key, value in shared.items() if key != "parties"},
        point_id=point_id,
        source_count=len(sources),
        retrieval_text=retrieval_text,
    )
    return document, point


def file_manifest(files: list[Path], data_dir: Path) -> tuple[list[dict], str, int]:
    records: list[dict] = []
    aggregate = hashlib.sha256()
    total_bytes = 0
    for path in files:
        raw = path.read_bytes()
        relative = path.relative_to(data_dir).as_posix()
        digest = hashlib.sha256(raw).hexdigest()
        records.append({"source_path": relative, "size_bytes": len(raw), "sha256": digest})
        aggregate.update(f"{relative}\0{digest}\n".encode("utf-8"))
        total_bytes += len(raw)
    return records, aggregate.hexdigest(), total_bytes


def build_dry_run(data_dir: Path, output_dir: Path, evaluation_dir: Path, report_dir: Path, workers: int) -> tuple[list[CaseRetrievalPoint], dict]:
    files = sorted(data_dir.glob("*.json"))
    source_files, source_hash, source_bytes = file_manifest(files, data_dir)
    errors: list[dict] = []
    tasks: list[SourceTask] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [(path, pool.submit(load_task, path, data_dir)) for path in files]
        for path, future in futures:
            try:
                tasks.append(future.result())
            except Exception as exc:
                errors.append({"source_path": path.name, "error": str(exc)})
    tasks.sort(key=lambda task: task.source_path)

    query_case_ids = {str(task.query_case.get("CaseId") or "") for task in tasks}
    candidates: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    candidate_sources: dict[tuple[str, str], list[str]] = defaultdict(list)
    template_queries: list[dict] = []
    case_queries: list[dict] = []
    references: list[dict] = []
    qrels: list[dict] = []
    invalid_qrels: list[dict] = []

    for task in tasks:
        query_parties = extract_parties(task.query_case)
        template_queries.append({"query_id": task.query_id, "query_text": task.template_query, "source_path": task.source_path})
        case_queries.append({
            "query_id": task.query_id,
            "query_text": build_retrieval_text(task.query_case, query_parties),
            "reference_case_id": str(task.query_case.get("CaseId") or ""),
            "source_path": task.source_path,
        })
        references.append({"query_id": task.query_id, "source_path": task.source_path, "query_case": task.query_case})
        for raw_index, raw_case in task.ctxs.items():
            case_id = str(raw_case.get("CaseId") or "").strip()
            if not case_id:
                errors.append({"source_path": task.source_path, "ctx_idx": raw_index, "error": "missing CaseId"})
                continue
            digest = content_hash(raw_case)
            candidates[case_id][digest] = raw_case
            candidate_sources[(case_id, digest)].append(f"{task.source_path}#ctxs/{raw_index}")
        for index in task.gt_idx:
            raw_case = task.ctxs.get(str(index))
            if raw_case is None:
                invalid_qrels.append({"query_id": task.query_id, "gt_idx": index, "error": "ctx index missing"})
                continue
            qrels.append({"query_id": task.query_id, "case_id": str(raw_case.get("CaseId") or ""), "relevance": 1})

    conflicts: list[dict] = []
    documents: list[CaseDocument] = []
    points: list[CaseRetrievalPoint] = []
    excluded_query_cases = 0
    for case_id in sorted(candidates):
        versions = candidates[case_id]
        if case_id in query_case_ids:
            excluded_query_cases += 1
            continue
        if len(versions) > 1:
            conflicts.append({
                "case_id": case_id,
                "content_hashes": sorted(versions),
                "sources": {digest: candidate_sources[(case_id, digest)] for digest in sorted(versions)},
            })
            continue
        digest, raw_case = next(iter(versions.items()))
        document, point = normalize_case(raw_case, candidate_sources[(case_id, digest)])
        documents.append(document)
        points.append(point)

    corpus_ids = {point.case_id for point in points}
    qrel_ids = {item["case_id"] for item in qrels}
    missing_qrel_case_ids = sorted(qrel_ids - corpus_ids)
    gt_query_case_overlap = sorted(qrel_ids & query_case_ids)
    lengths = sorted(len(point.retrieval_text) for point in points)
    profile = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files_total": len(files),
        "files_valid": len(tasks),
        "files_invalid": len(errors),
        "query_cases_unique": len(query_case_ids),
        "candidate_case_ids_unique": len(candidates),
        "query_case_ids_excluded_from_corpus": excluded_query_cases,
        "corpus_points": len(points),
        "conflicting_case_ids_excluded": len(conflicts),
        "template_queries": len(template_queries),
        "case_queries": len(case_queries),
        "references": len(references),
        "qrels": len(qrels),
        "qrel_case_ids_unique": len(qrel_ids),
        "invalid_qrels": len(invalid_qrels),
        "missing_qrel_case_ids": len(missing_qrel_case_ids),
        "gt_query_case_overlap": len(gt_query_case_overlap),
        "retrieval_text_length": {
            "min": lengths[0] if lengths else 0,
            "p50": lengths[len(lengths) // 2] if lengths else 0,
            "p95": lengths[int(len(lengths) * 0.95)] if lengths else 0,
            "max": lengths[-1] if lengths else 0,
        },
        "case_type_counts": dict(sorted(Counter(point.case_type or "null" for point in points).items())),
    }

    document_count, document_hash = write_jsonl(output_dir / "documents.jsonl", (item.model_dump(mode="json") for item in documents))
    point_count, point_hash = write_jsonl(output_dir / "retrieval_points.jsonl", (item.model_dump(mode="json") for item in points))
    write_jsonl(output_dir / "case_conflicts.jsonl", conflicts)
    write_jsonl(evaluation_dir / "template_queries.jsonl", template_queries)
    write_jsonl(evaluation_dir / "case_queries.jsonl", case_queries)
    write_jsonl(evaluation_dir / "qrels.jsonl", qrels)
    write_jsonl(evaluation_dir / "query_case_references.jsonl", references)
    write_json(report_dir / "profile.json", profile)
    write_json(report_dir / "issues.json", {"file_errors": errors, "invalid_qrels": invalid_qrels, "missing_qrel_case_ids": missing_qrel_case_ids, "gt_query_case_overlap": gt_query_case_overlap})
    source_count, source_manifest_hash = write_jsonl(report_dir / "source_files.jsonl", source_files)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input": {"path": str(data_dir), "files": source_count, "total_bytes": source_bytes, "aggregate_sha256": source_hash, "source_manifest_sha256": source_manifest_hash},
        "outputs": {
            "documents": {"count": document_count, "sha256": document_hash},
            "retrieval_points": {"count": point_count, "sha256": point_hash},
        },
        "profile": profile,
    }
    write_json(report_dir / "manifest.json", manifest)
    return points, manifest


def batched(items: list[CaseRetrievalPoint], size: int) -> Iterator[list[CaseRetrievalPoint]]:
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def ensure_collection(client: QdrantClient, collection_name: str) -> None:
    existing = {item.name for item in client.get_collections().collections}
    if collection_name not in existing:
        client.create_collection(
            collection_name=collection_name,
            vectors_config={DENSE_VECTOR_NAME: VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE, datatype=Datatype.FLOAT32)},
            sparse_vectors_config={SPARSE_VECTOR_NAME: SparseVectorParams()},
        )
    info = client.get_collection(collection_name)
    if info.config.params.vectors[DENSE_VECTOR_NAME].size != VECTOR_SIZE:
        raise RuntimeError("existing cases collection has incompatible dense vector size")
    if SPARSE_VECTOR_NAME not in info.config.params.sparse_vectors:
        raise RuntimeError("existing cases collection lacks text_sparse")
    indexes = {
        "case_id": PayloadSchemaType.KEYWORD,
        "case_version_id": PayloadSchemaType.UUID,
        "case_type": PayloadSchemaType.KEYWORD,
        "procedure": PayloadSchemaType.KEYWORD,
        "case_causes": PayloadSchemaType.KEYWORD,
        "category_l1": PayloadSchemaType.KEYWORD,
        "category_l2": PayloadSchemaType.KEYWORD,
        "keywords": PayloadSchemaType.KEYWORD,
        "jurisdiction": PayloadSchemaType.KEYWORD,
    }
    for field_name, field_schema in indexes.items():
        client.create_payload_index(collection_name, field_name=field_name, field_schema=field_schema, wait=True)


def _upsert(client: QdrantClient, collection_name: str, points: list[PointStruct]) -> int:
    client.upsert(collection_name=collection_name, points=points, wait=True)
    return len(points)


def index_points(points: list[CaseRetrievalPoint], collection_name: str, qdrant_url: str, model_path: Path, device: str, embed_batch_size: int, upload_workers: int, checkpoint_path: Path, max_in_flight: int = 4) -> dict:
    client = QdrantClient(url=qdrant_url, timeout=120, check_compatibility=False, trust_env=False)
    ensure_collection(client, collection_name)
    embedder = BGEM3Embedder(model_path, device=device, batch_size=embed_batch_size)
    all_batches = list(batched(points, embed_batch_size))
    start_batch = 0
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("collection") != collection_name or checkpoint.get("batch_size") != embed_batch_size:
            raise RuntimeError("checkpoint collection or batch size mismatch")
        start_batch = int(checkpoint.get("completed_batches", 0))
    submitted = completed = 0
    in_flight: list[tuple[int, Future[int]]] = []

    def complete_oldest() -> None:
        nonlocal completed
        batch_number, future = in_flight.pop(0)
        completed += future.result()
        write_json(checkpoint_path, {"collection": collection_name, "batch_size": embed_batch_size, "completed_batches": batch_number + 1, "total_batches": len(all_batches), "updated_at": datetime.now(timezone.utc).isoformat()})

    with ThreadPoolExecutor(max_workers=max(1, upload_workers)) as pool:
        progress = tqdm(enumerate(all_batches[start_batch:], start=start_batch), total=len(all_batches), initial=start_batch, desc=f"Case embedding/upload ({embedder.device})")
        for batch_number, batch in progress:
            vectors = embedder.encode([item.retrieval_text for item in batch])
            qdrant_points = [
                PointStruct(
                    id=item.point_id,
                    vector={DENSE_VECTOR_NAME: vectors.dense[index], SPARSE_VECTOR_NAME: SparseVector(indices=vectors.sparse_indices[index], values=vectors.sparse_values[index])},
                    payload=item.qdrant_payload(),
                )
                for index, item in enumerate(batch)
            ]
            in_flight.append((batch_number, pool.submit(_upsert, client, collection_name, qdrant_points)))
            submitted += len(qdrant_points)
            if len(in_flight) >= max_in_flight:
                complete_oldest()
        while in_flight:
            complete_oldest()
    info = client.get_collection(collection_name)
    return {"collection": collection_name, "device": embedder.device, "submitted": submitted, "completed": completed, "resumed_from_batch": start_batch, "total_batches": len(all_batches), "points_count": info.points_count, "indexed_vectors_count": info.indexed_vectors_count}
