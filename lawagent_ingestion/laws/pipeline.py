from __future__ import annotations

import json
import os
import hashlib
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

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

from .embedder import BGEM3Embedder
from .models import LawChunk
from .parser import LawParser, ParseResult, sha256_text


VECTOR_SIZE = 1024
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "text_sparse"


def batched(items: list[LawChunk], size: int) -> Iterator[list[LawChunk]]:
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def write_jsonl(path: Path, records: Iterable[dict]) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    count = 0
    with temporary.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    temporary.replace(path)
    return count, sha256_text(path.read_text(encoding="utf-8"))


def source_file_manifest(files: list[Path], data_dir: Path) -> tuple[list[dict], str, int]:
    records: list[dict] = []
    aggregate = hashlib.sha256()
    total_bytes = 0
    for path in files:
        raw = path.read_bytes()
        relative = path.relative_to(data_dir).as_posix()
        digest = hashlib.sha256(raw).hexdigest()
        size = len(raw)
        records.append({"source_path": relative, "size_bytes": size, "sha256": digest})
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(digest.encode("ascii"))
        aggregate.update(b"\n")
        total_bytes += size
    return records, aggregate.hexdigest(), total_bytes


def profile_results(results: list[ParseResult]) -> dict:
    included = [result for result in results if result.document is not None]
    chunks = [chunk for result in included for chunk in result.chunks]
    warnings = Counter(warning for result in results for warning in (result.warnings or []))
    excluded = Counter(result.excluded_reason for result in results if result.excluded_reason)
    types = Counter(result.document.document_type.value for result in included if result.document)
    chunk_types = Counter(chunk.chunk_type for chunk in chunks)
    effective_missing = sum(result.document.effective_from is None for result in included if result.document)
    duplicate_chunk_ids = len(chunks) - len({chunk.chunk_id for chunk in chunks})
    duplicate_version_ids = len(included) - len({result.document.law_version_id for result in included if result.document})
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files_total": len(results),
        "files_included": len(included),
        "files_excluded": sum(excluded.values()),
        "excluded_by_reason": dict(sorted(excluded.items())),
        "documents_by_type": dict(sorted(types.items())),
        "chunks_total": len(chunks),
        "chunks_by_type": dict(sorted(chunk_types.items())),
        "effective_from_missing": effective_missing,
        "effective_from_present": len(included) - effective_missing,
        "warnings": dict(sorted(warnings.items())),
        "duplicate_chunk_ids": duplicate_chunk_ids,
        "duplicate_version_ids": duplicate_version_ids,
        "empty_included_documents": sum(not result.chunks for result in included),
    }


def parse_and_write(
    data_dir: Path,
    output_dir: Path,
    report_dir: Path,
    parse_workers: int,
) -> tuple[list[ParseResult], list[LawChunk], dict]:
    parser = LawParser(data_dir)
    files = sorted(data_dir.rglob("*.md"))
    source_records, source_aggregate_hash, source_total_bytes = source_file_manifest(files, data_dir)
    results = parser.parse_all(files, workers=parse_workers)
    canonical_versions: dict[str, str] = {}
    for result in results:
        if result.document is None:
            continue
        version_id = result.document.law_version_id
        if version_id in canonical_versions:
            result.excluded_reason = f"duplicate_exact_document:{canonical_versions[version_id]}"
            result.warnings = [*(result.warnings or []), "duplicate_source_alias"]
            result.document = None
            result.chunks = []
        else:
            canonical_versions[version_id] = result.source_path
    documents = [result.document for result in results if result.document is not None]
    chunks = [chunk for result in results for chunk in result.chunks]
    profile = profile_results(results)

    doc_count, doc_hash = write_jsonl(
        output_dir / "documents.jsonl",
        (document.model_dump(mode="json") for document in documents),
    )
    chunk_count, chunk_hash = write_jsonl(
        output_dir / "chunks.jsonl",
        (chunk.model_dump(mode="json") for chunk in chunks),
    )
    source_count, source_manifest_hash = write_jsonl(
        report_dir / "source_files.jsonl",
        source_records,
    )
    issues = [
        {
            "source_path": result.source_path,
            "excluded_reason": result.excluded_reason,
            "warnings": result.warnings or [],
        }
        for result in results
        if result.excluded_reason or result.warnings
    ]
    write_json(report_dir / "profile.json", profile)
    write_json(report_dir / "issues.json", issues)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "path": str(data_dir),
            "files": source_count,
            "total_bytes": source_total_bytes,
            "aggregate_sha256": source_aggregate_hash,
            "source_manifest_sha256": source_manifest_hash,
        },
        "output": str(output_dir),
        "documents": {"count": doc_count, "sha256": doc_hash},
        "chunks": {"count": chunk_count, "sha256": chunk_hash},
        "profile": profile,
    }
    write_json(report_dir / "manifest.json", manifest)
    return results, chunks, manifest


def ensure_collection(client: QdrantClient, collection_name: str) -> None:
    existing = {item.name for item in client.get_collections().collections}
    if collection_name not in existing:
        client.create_collection(
            collection_name=collection_name,
            vectors_config={
                DENSE_VECTOR_NAME: VectorParams(
                    size=VECTOR_SIZE,
                    distance=Distance.COSINE,
                    datatype=Datatype.FLOAT32,
                )
            },
            sparse_vectors_config={SPARSE_VECTOR_NAME: SparseVectorParams()},
        )
    info = client.get_collection(collection_name)
    dense_config = info.config.params.vectors[DENSE_VECTOR_NAME]
    if dense_config.size != VECTOR_SIZE:
        raise RuntimeError(f"existing collection dense size is {dense_config.size}, expected {VECTOR_SIZE}")
    if SPARSE_VECTOR_NAME not in info.config.params.sparse_vectors:
        raise RuntimeError(f"existing collection lacks sparse vector {SPARSE_VECTOR_NAME}")

    indexes = {
        "law_family_id": PayloadSchemaType.UUID,
        "law_version_id": PayloadSchemaType.UUID,
        "document_type": PayloadSchemaType.KEYWORD,
        "jurisdiction": PayloadSchemaType.KEYWORD,
        "authority": PayloadSchemaType.KEYWORD,
        "authority_level": PayloadSchemaType.KEYWORD,
        "validity_status": PayloadSchemaType.KEYWORD,
        "effective_from": PayloadSchemaType.DATETIME,
        "article_no": PayloadSchemaType.KEYWORD,
        "chunk_type": PayloadSchemaType.KEYWORD,
        "source_path": PayloadSchemaType.KEYWORD,
    }
    for field_name, field_schema in indexes.items():
        client.create_payload_index(
            collection_name=collection_name,
            field_name=field_name,
            field_schema=field_schema,
            wait=True,
        )


def _upsert(client: QdrantClient, collection_name: str, points: list[PointStruct]) -> int:
    client.upsert(collection_name=collection_name, points=points, wait=True)
    return len(points)


def index_chunks(
    chunks: list[LawChunk],
    collection_name: str,
    qdrant_url: str,
    model_path: Path,
    device: str,
    embed_batch_size: int,
    upload_workers: int,
    checkpoint_path: Path,
    max_in_flight: int = 4,
) -> dict:
    client = QdrantClient(
        url=qdrant_url,
        timeout=120,
        check_compatibility=False,
        trust_env=False,
    )
    ensure_collection(client, collection_name)
    embedder = BGEM3Embedder(model_path, device=device, batch_size=embed_batch_size)
    start_batch = 0
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("collection") != collection_name or checkpoint.get("batch_size") != embed_batch_size:
            raise RuntimeError("checkpoint collection or batch size does not match this run")
        start_batch = int(checkpoint.get("completed_batches", 0))
    submitted = 0
    completed = 0
    in_flight: list[tuple[int, Future[int]]] = []
    all_batches = list(batched(chunks, embed_batch_size))

    def complete_oldest() -> None:
        nonlocal completed
        batch_number, future = in_flight.pop(0)
        completed += future.result()
        write_json(
            checkpoint_path,
            {
                "collection": collection_name,
                "batch_size": embed_batch_size,
                "completed_batches": batch_number + 1,
                "total_batches": len(all_batches),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    with ThreadPoolExecutor(max_workers=max(1, upload_workers)) as pool:
        progress = tqdm(
            enumerate(all_batches[start_batch:], start=start_batch),
            total=len(all_batches),
            initial=start_batch,
            desc=f"Embedding/uploading ({embedder.device})",
        )
        for batch_number, chunk_batch in progress:
            vectors = embedder.encode([chunk.embedding_text for chunk in chunk_batch])
            points = [
                PointStruct(
                    id=chunk.chunk_id,
                    vector={
                        DENSE_VECTOR_NAME: vectors.dense[index],
                        SPARSE_VECTOR_NAME: SparseVector(
                            indices=vectors.sparse_indices[index],
                            values=vectors.sparse_values[index],
                        ),
                    },
                    payload=chunk.qdrant_payload(),
                )
                for index, chunk in enumerate(chunk_batch)
            ]
            in_flight.append((batch_number, pool.submit(_upsert, client, collection_name, points)))
            submitted += len(points)
            if len(in_flight) >= max_in_flight:
                complete_oldest()
        while in_flight:
            complete_oldest()
    info = client.get_collection(collection_name)
    return {
        "collection": collection_name,
        "device": embedder.device,
        "submitted": submitted,
        "completed": completed,
        "resumed_from_batch": start_batch,
        "total_batches": len(all_batches),
        "points_count": info.points_count,
        "indexed_vectors_count": info.indexed_vectors_count,
    }
