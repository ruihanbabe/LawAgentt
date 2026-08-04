from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, HasVectorCondition

from lawagent_ingestion.laws.pipeline import write_json, write_jsonl


EXPECTED_PAYLOAD_FIELDS = {
    "point_id", "case_id", "case_version_id", "title", "case_type", "procedure",
    "case_causes", "category_l1", "category_l2", "keywords", "jurisdiction",
    "source_count", "case_record", "claims_and_facts", "judge_reason", "judge_result",
    "legal_basis", "content_hash", "schema_version", "pipeline_version",
}
FORBIDDEN_PAYLOAD_FIELDS = {
    "parties", "source_paths", "retrieval_text", "gt_idx", "qrels",
    "reference_case_id", "ground_truth", "is_relevant",
}
REQUIRED_PAYLOAD_FIELDS = {
    "point_id", "case_id", "case_version_id", "title", "jurisdiction", "source_count",
    "content_hash", "schema_version", "pipeline_version",
}
EXPECTED_INDEXES = {
    "case_id": "keyword", "case_version_id": "uuid", "case_type": "keyword",
    "procedure": "keyword", "case_causes": "keyword", "category_l1": "keyword",
    "category_l2": "keyword", "keywords": "keyword", "jurisdiction": "keyword",
}
PII_PATTERNS = {
    "id_card": re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    "phone": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "bank_card": re.compile(r"(?<!\d)\d{16,19}(?!\d)"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "credit_code": re.compile(r"(?<![0-9A-Z])[0-9A-HJ-NPQRTUWXY]{18}(?![0-9A-Z])"),
}
TEXT_FIELDS = ("title", "case_record", "claims_and_facts", "judge_reason", "judge_result")


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number}: {exc}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_retrieval_text(point: dict[str, Any]) -> str:
    parts: list[str] = []
    if point.get("case_type"):
        parts.append(f"案件类型：{point['case_type']}")
    if point.get("procedure"):
        parts.append(f"审理程序：{point['procedure']}")
    if point.get("case_causes"):
        parts.append(f"案由：{'；'.join(point['case_causes'])}")
    categories = [value for value in (point.get("category_l1"), point.get("category_l2")) if value]
    if categories:
        parts.append(f"案件分类：{'；'.join(categories)}")
    if point.get("case_record"):
        parts.append(f"案件经过：{point['case_record']}")
    if point.get("claims_and_facts"):
        parts.append(f"诉请与事实：{point['claims_and_facts']}")
    if point.get("keywords"):
        parts.append(f"关键词：{'；'.join(point['keywords'])}")
    return "\n".join(parts).strip() or "案例事实信息缺失"


def _add_sample(samples: list[dict[str, Any]], value: dict[str, Any], limit: int) -> None:
    if len(samples) < limit:
        samples.append(value)


def validate_cases(
    data_dir: Path,
    processed_dir: Path,
    evaluation_dir: Path,
    report_dir: Path,
    qdrant_url: str,
    collection: str,
    vector_sample_size: int = 1024,
    issue_sample_limit: int = 100,
) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    def stage(message: str) -> None:
        print(f"[{datetime.now(timezone.utc).isoformat()}] {message}", flush=True)

    documents_path = processed_dir / "documents.jsonl"
    points_path = processed_dir / "retrieval_points.jsonl"
    manifest = json.loads((report_dir / "manifest.json").read_text(encoding="utf-8"))

    stage("phase 1/7: scan normalized documents and source pointers")
    document_ids: set[str] = set()
    document_point_ids: dict[str, str] = {}
    document_meta: dict[str, tuple[str, str]] = {}
    party_names: dict[str, list[str]] = {}
    source_refs: dict[str, list[tuple[str, str]]] = defaultdict(list)
    duplicate_document_ids: list[dict[str, Any]] = []
    for document in read_jsonl(documents_path):
        case_id = document["case_id"]
        if case_id in document_ids:
            _add_sample(duplicate_document_ids, {"case_id": case_id}, issue_sample_limit)
        document_ids.add(case_id)
        document_meta[case_id] = (document["case_version_id"], document["content_hash"])
        party_names[case_id] = sorted({str(p.get("name") or "") for p in document.get("parties", []) if len(str(p.get("name") or "")) >= 2}, key=len, reverse=True)
        for source in document.get("source_paths", []):
            source_path, separator, pointer = source.partition("#ctxs/")
            if not separator:
                source_refs[source_path].append(("", case_id))
            else:
                source_refs[source_path].append((pointer, case_id))

    stage(f"phase 1/7 complete: documents={len(document_ids)}; phase 2/7: scan retrieval points, leakage and PII")
    retrieval_ids: set[str] = set()
    point_ids: set[str] = set()
    retrieval_meta: dict[str, tuple[str, str, str]] = {}
    retrieval_text_mismatches: list[dict[str, Any]] = []
    confirmed_party_leaks: list[dict[str, Any]] = []
    local_pii_counts: Counter[str] = Counter()
    local_pii_samples: list[dict[str, Any]] = []
    duplicate_retrieval_ids: list[dict[str, Any]] = []
    for point in read_jsonl(points_path):
        case_id = point["case_id"]
        if case_id in retrieval_ids:
            _add_sample(duplicate_retrieval_ids, {"case_id": case_id}, issue_sample_limit)
        retrieval_ids.add(case_id)
        point_ids.add(point["point_id"])
        retrieval_meta[case_id] = (point["point_id"], point["case_version_id"], point["content_hash"])
        expected = expected_retrieval_text(point)
        if expected != point.get("retrieval_text"):
            _add_sample(retrieval_text_mismatches, {"case_id": case_id}, issue_sample_limit)
        searchable_text = "\n".join(str(point.get(field) or "") for field in TEXT_FIELDS)
        for name in party_names.get(case_id, []):
            if name in searchable_text:
                _add_sample(confirmed_party_leaks, {"case_id": case_id, "party_name": name}, issue_sample_limit)
        for kind, pattern in PII_PATTERNS.items():
            for match in pattern.finditer(searchable_text):
                local_pii_counts[kind] += 1
                _add_sample(local_pii_samples, {"case_id": case_id, "field_group": "retrieval_point", "kind": kind, "value": match.group(0)}, issue_sample_limit)

    stage(f"phase 2/7 complete: retrieval_points={len(retrieval_ids)}; phase 3/7: validate queries and qrels")
    queries = {item["query_id"]: item for item in read_jsonl(evaluation_dir / "case_queries.jsonl")}
    query_case_ids = {str(item["query_case"].get("CaseId") or "") for item in read_jsonl(evaluation_dir / "query_case_references.jsonl")}
    qrel_pairs: set[tuple[str, str]] = set()
    qrel_case_ids: set[str] = set()
    qrel_counts: Counter[str] = Counter()
    invalid_qrels: list[dict[str, Any]] = []
    duplicate_qrels: list[dict[str, Any]] = []
    for qrel in read_jsonl(evaluation_dir / "qrels.jsonl"):
        pair = (qrel["query_id"], qrel["case_id"])
        if pair in qrel_pairs:
            _add_sample(duplicate_qrels, {"query_id": pair[0], "case_id": pair[1]}, issue_sample_limit)
        qrel_pairs.add(pair)
        qrel_case_ids.add(pair[1])
        qrel_counts[pair[0]] += 1
        if pair[0] not in queries or pair[1] not in retrieval_ids or qrel.get("relevance") != 1:
            _add_sample(invalid_qrels, qrel, issue_sample_limit)

    stage(f"phase 3/7 complete: queries={len(queries)}, qrels={len(qrel_pairs)}; phase 4/7: full source trace")
    source_trace_failures: list[dict[str, Any]] = []
    for source_path, references in source_refs.items():
        path = data_dir / source_path
        if not path.exists():
            _add_sample(source_trace_failures, {"source_path": source_path, "error": "file_missing"}, issue_sample_limit)
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        contexts = raw.get("ctxs") or {}
        for pointer, expected_case_id in references:
            actual = contexts.get(pointer) if pointer else None
            actual_case_id = str((actual or {}).get("CaseId") or "")
            if actual_case_id != expected_case_id:
                _add_sample(source_trace_failures, {"source_path": source_path, "ctx_idx": pointer, "expected": expected_case_id, "actual": actual_case_id}, issue_sample_limit)

    stage(f"phase 4/7 complete: source_files={len(source_refs)}; phase 5/7: Qdrant counts and payload scan")
    client = QdrantClient(url=qdrant_url, timeout=120, check_compatibility=False, trust_env=False)
    info = client.get_collection(collection)
    dense_count = client.count(collection, count_filter=Filter(must=[HasVectorCondition(has_vector="dense")]), exact=True).count
    sparse_count = client.count(collection, count_filter=Filter(must=[HasVectorCondition(has_vector="text_sparse")]), exact=True).count
    qdrant_ids: set[str] = set()
    qdrant_point_ids: list[str] = []
    qdrant_meta_mismatches: list[dict[str, Any]] = []
    payload_field_issues: list[dict[str, Any]] = []
    qdrant_pii_counts: Counter[str] = Counter()
    qdrant_pii_samples: list[dict[str, Any]] = []
    offset = None
    while True:
        records, offset = client.scroll(collection, limit=256, offset=offset, with_payload=True, with_vectors=False)
        for record in records:
            payload = record.payload or {}
            case_id = str(payload.get("case_id") or "")
            qdrant_ids.add(case_id)
            qdrant_point_ids.append(str(record.id))
            missing = sorted(REQUIRED_PAYLOAD_FIELDS - payload.keys())
            forbidden = sorted(FORBIDDEN_PAYLOAD_FIELDS & payload.keys())
            unexpected = sorted(payload.keys() - EXPECTED_PAYLOAD_FIELDS)
            if missing or forbidden or unexpected or str(record.id) != str(payload.get("point_id")):
                _add_sample(payload_field_issues, {"case_id": case_id, "missing": missing, "forbidden": forbidden, "unexpected": unexpected, "record_id": str(record.id), "payload_point_id": payload.get("point_id")}, issue_sample_limit)
            expected_meta = retrieval_meta.get(case_id)
            actual_meta = (str(record.id), payload.get("case_version_id"), payload.get("content_hash"))
            if expected_meta != actual_meta or payload.get("schema_version") != "cases-v0.1" or payload.get("pipeline_version") != "cases-ingest-v0.1" or payload.get("jurisdiction") != "CN" or int(payload.get("source_count") or 0) < 1:
                _add_sample(qdrant_meta_mismatches, {"case_id": case_id, "expected": expected_meta, "actual": actual_meta}, issue_sample_limit)
            text = "\n".join(str(payload.get(field) or "") for field in TEXT_FIELDS)
            for kind, pattern in PII_PATTERNS.items():
                for match in pattern.finditer(text):
                    qdrant_pii_counts[kind] += 1
                    _add_sample(qdrant_pii_samples, {"case_id": case_id, "kind": kind, "value": match.group(0)}, issue_sample_limit)
        if offset is None:
            break

    stage(f"phase 5/7 complete: qdrant_ids={len(qdrant_ids)}; phase 6/7: vector structure samples")
    sample_ids = qdrant_point_ids[::max(1, len(qdrant_point_ids) // max(1, vector_sample_size))][:vector_sample_size]
    invalid_vector_samples: list[dict[str, Any]] = []
    for start in range(0, len(sample_ids), 128):
        for record in client.retrieve(collection, ids=sample_ids[start:start + 128], with_payload=False, with_vectors=True):
            vectors = record.vector or {}
            dense = vectors.get("dense") or []
            sparse = vectors.get("text_sparse")
            sparse_indices = getattr(sparse, "indices", [])
            sparse_values = getattr(sparse, "values", [])
            valid = len(dense) == 1024 and all(math.isfinite(float(value)) for value in dense) and len(sparse_indices) > 0 and len(sparse_indices) == len(sparse_values) and all(math.isfinite(float(value)) for value in sparse_values)
            if not valid:
                _add_sample(invalid_vector_samples, {"point_id": str(record.id), "dense_dim": len(dense), "sparse_indices": len(sparse_indices), "sparse_values": len(sparse_values)}, issue_sample_limit)

    stage(f"phase 6/7 complete: vector_samples={len(sample_ids)}; phase 7/7: summarize and write reports")
    payload_indexes = {name: str(schema.data_type.value if hasattr(schema.data_type, "value") else schema.data_type) for name, schema in info.payload_schema.items()}
    index_mismatches = {name: {"expected": expected, "actual": payload_indexes.get(name)} for name, expected in EXPECTED_INDEXES.items() if payload_indexes.get(name) != expected}
    source_manifest_hash = sha256_file(report_dir / "source_files.jsonl")
    expected_source_manifest_hash = manifest["input"]["source_manifest_sha256"]
    deterministic_failures = {
        "duplicate_document_ids": len(duplicate_document_ids),
        "duplicate_retrieval_ids": len(duplicate_retrieval_ids),
        "document_retrieval_id_difference": len(document_ids ^ retrieval_ids),
        "document_qdrant_id_difference": len(document_ids ^ qdrant_ids),
        "document_point_count_mismatch": abs(len(document_ids) - len(point_ids)),
        "retrieval_text_mismatches": len(retrieval_text_mismatches),
        "confirmed_party_leaks_sampled": len(confirmed_party_leaks),
        "invalid_qrels_sampled": len(invalid_qrels),
        "duplicate_qrels_sampled": len(duplicate_qrels),
        "queries_without_qrels": len(set(queries) - set(qrel_counts)),
        "qrel_cases_missing_from_corpus": len(qrel_case_ids - retrieval_ids),
        "query_case_corpus_overlap": len(query_case_ids & retrieval_ids),
        "source_trace_failures_sampled": len(source_trace_failures),
        "qdrant_meta_mismatches_sampled": len(qdrant_meta_mismatches),
        "payload_field_issues_sampled": len(payload_field_issues),
        "invalid_vector_samples": len(invalid_vector_samples),
        "payload_index_mismatches": len(index_mismatches),
        "source_manifest_hash_mismatch": int(source_manifest_hash != expected_source_manifest_hash),
        "qdrant_points_count_mismatch": int(info.points_count != len(document_ids)),
        "dense_vector_count_mismatch": int(dense_count != len(document_ids)),
        "sparse_vector_count_mismatch": int(sparse_count != len(document_ids)),
    }
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": (datetime.now(timezone.utc) - started).total_seconds(),
        "collection": collection,
        "status": "PASS" if sum(deterministic_failures.values()) == 0 else "FAIL",
        "privacy_review_status": "REVIEW_REQUIRED" if sum(local_pii_counts.values()) or sum(qdrant_pii_counts.values()) else "NO_REGEX_MATCHES",
        "counts": {
            "documents": len(document_ids), "retrieval_points": len(retrieval_ids), "unique_point_ids": len(point_ids),
            "qdrant_points": info.points_count, "qdrant_ids_scrolled": len(qdrant_ids), "dense_vectors": dense_count,
            "sparse_vectors": sparse_count, "queries": len(queries), "qrels": len(qrel_pairs),
            "qrel_case_ids": len(qrel_case_ids), "query_case_ids": len(query_case_ids), "source_files_traced": len(source_refs),
        },
        "hashes": {"source_files_jsonl_actual": source_manifest_hash, "source_files_jsonl_expected": expected_source_manifest_hash},
        "deterministic_failures": deterministic_failures,
        "pii_regex_counts": {"processed": dict(local_pii_counts), "qdrant": dict(qdrant_pii_counts)},
        "payload_indexes": payload_indexes,
        "payload_index_mismatches": index_mismatches,
        "vector_sample_size": len(sample_ids),
        "samples": {
            "duplicate_document_ids": duplicate_document_ids, "duplicate_retrieval_ids": duplicate_retrieval_ids,
            "retrieval_text_mismatches": retrieval_text_mismatches, "confirmed_party_leaks": confirmed_party_leaks,
            "invalid_qrels": invalid_qrels, "duplicate_qrels": duplicate_qrels, "source_trace_failures": source_trace_failures,
            "qdrant_meta_mismatches": qdrant_meta_mismatches, "payload_field_issues": payload_field_issues,
            "invalid_vector_samples": invalid_vector_samples, "processed_pii": local_pii_samples, "qdrant_pii": qdrant_pii_samples,
        },
    }
    write_json(report_dir / "validation_report.json", report)
    write_jsonl(report_dir / "suspicious_pii_samples.jsonl", local_pii_samples + qdrant_pii_samples)
    stage(f"validation complete: status={report['status']}, privacy_review_status={report['privacy_review_status']}")
    return report
