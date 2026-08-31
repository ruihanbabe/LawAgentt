from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Protocol, Sequence

from qdrant_client import QdrantClient
from qdrant_client.models import DatetimeRange, FieldCondition, Filter, MatchAny, MatchValue, Range, SparseVector

from lawagent_ingestion.laws.embedder import BGEM3Embedder, EmbeddedBatch

from .evidence_views import (
    CaseEvidenceView,
    LawEvidenceView,
    build_case_evidence_view,
    build_law_evidence_view,
)
from .pii import PIIPolicy
from .tools import ToolExecutor, ToolPermission, ToolResult, ToolResultStatus, ToolSpec


DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "text_sparse"


class Embedder(Protocol):
    def encode(self, texts: Sequence[str]) -> EmbeddedBatch:
        ...


class QdrantLikeClient(Protocol):
    def query_points(self, collection_name: str, **kwargs: Any) -> Any:
        ...

    def scroll(self, collection_name: str, **kwargs: Any) -> Any:
        ...


def build_runtime_tool_registry(
    *,
    qdrant_url: str,
    model_path: Path,
    cases_collection: str = "cases_collection",
    laws_collection: str = "laws_collection",
    device: str = "auto",
    embed_batch_size: int = 32,
):
    from .tools import ToolRegistry

    client = QdrantClient(url=qdrant_url, timeout=120, check_compatibility=False, trust_env=False)
    embedder = BGEM3Embedder(model_path, device=device, batch_size=embed_batch_size)
    registry = ToolRegistry()
    registry.register(SearchCasesAdapter(client=client, embedder=embedder, collection=cases_collection))
    registry.register(SearchStatutesAdapter(client=client, embedder=embedder, collection=laws_collection))
    registry.register(FetchCaseEvidenceAdapter(client=client, collection=cases_collection))
    return registry


@dataclass(slots=True)
class LazyRuntimeToolExecutor:
    """首次真实检索时加载 embedding 模型，避免健康检查初始化重资源。"""

    qdrant_url: str
    model_path: Path
    device: str = "auto"
    cases_collection: str = "cases_collection"
    laws_collection: str = "laws_collection"
    embed_batch_size: int = 8
    _executor: ToolExecutor | None = None

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        try:
            if self._executor is None:
                registry = build_runtime_tool_registry(
                    qdrant_url=self.qdrant_url,
                    model_path=self.model_path,
                    cases_collection=self.cases_collection,
                    laws_collection=self.laws_collection,
                    device=self.device,
                    embed_batch_size=self.embed_batch_size,
                )
                self._executor = ToolExecutor(
                    registry,
                    {
                        ToolPermission.SEARCH_PUBLIC_LAW,
                        ToolPermission.SEARCH_SANITIZED_CASES,
                        ToolPermission.FETCH_CASE_EVIDENCE,
                    },
                )
            return self._executor.execute(tool_name, arguments)
        except Exception as exc:
            return ToolResult(
                tool_name=tool_name,
                status=ToolResultStatus.FAILED,
                error=f"runtime_tool_initialization_failed: {type(exc).__name__}",
                warnings=["runtime_tool_initialization_failed"],
                metadata={"error_code": "runtime_tool_initialization_failed"},
            )


@dataclass(slots=True)
class SearchCasesAdapter:
    client: QdrantLikeClient
    embedder: Embedder
    collection: str = "cases_collection"
    default_top_k: int = 10
    candidate_k_multiplier: int = 3
    pii_policy: PIIPolicy = PIIPolicy.MASK

    spec: ClassVar[ToolSpec] = ToolSpec(
        name="search_cases",
        description="检索脱敏裁判案例，返回可进入 Agent 状态的安全案例证据视图。",
        input_schema={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
                "jurisdiction": {"type": "string"},
                "case_type": {"type": "string"},
                "procedure": {"type": "string"},
                "case_causes": {"type": "array", "items": {"type": "string"}},
                "category_l1": {"type": "string"},
                "category_l2": {"type": "string"},
                "keywords": {"type": "array", "items": {"type": "string"}},
                "party_names": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
        output_schema=CaseEvidenceView.model_json_schema(),
        permissions=[ToolPermission.SEARCH_SANITIZED_CASES],
        pii_policy=PIIPolicy.MASK,
    )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = _required_text(arguments, "query")
        top_k = _top_k(arguments.get("top_k"), self.default_top_k)
        candidate_k = max(top_k, top_k * self.candidate_k_multiplier)
        encoded = self.embedder.encode([query])
        filters = _case_filter(arguments)
        dense_points = _query_points(
            self.client,
            self.collection,
            encoded.dense[0],
            DENSE_VECTOR_NAME,
            candidate_k,
            filters,
        )
        sparse_points = _query_points(
            self.client,
            self.collection,
            SparseVector(indices=encoded.sparse_indices[0], values=encoded.sparse_values[0]),
            SPARSE_VECTOR_NAME,
            candidate_k,
            filters,
        )
        payloads = _payloads_by_id(dense_points + sparse_points, "case_id")
        dense_ids = [str(point.payload["case_id"]) for point in dense_points if point.payload and point.payload.get("case_id")]
        sparse_ids = [str(point.payload["case_id"]) for point in sparse_points if point.payload and point.payload.get("case_id")]
        ranking = _rrf_fuse(dense_ids, sparse_ids)[:top_k]
        party_names = _string_list(arguments.get("party_names"))
        items = [
            build_case_evidence_view(
                payloads[case_id],
                score=_score_by_id(dense_points + sparse_points, "case_id").get(case_id),
                party_names=party_names,
                policy=self.pii_policy,
            )
            for case_id in ranking
            if case_id in payloads
        ]
        return ToolResult(
            tool_name=self.spec.name,
            status=ToolResultStatus.SUCCESS if items else ToolResultStatus.EMPTY,
            items=items,
            pii_blocked_count=sum(1 for item in items if item.pii_status.value == "review_required"),
            warnings=[],
            metadata={
                "normalized_query": query,
                "top_k": top_k,
                "candidate_k": candidate_k,
                "applied_filters": _filter_metadata(arguments, CASE_FILTER_FIELDS),
            },
        )


@dataclass(slots=True)
class SearchStatutesAdapter:
    client: QdrantLikeClient
    embedder: Embedder
    collection: str = "laws_collection"
    default_top_k: int = 10
    candidate_k_multiplier: int = 3

    spec: ClassVar[ToolSpec] = ToolSpec(
        name="search_statutes",
        description="检索规范性法律文献，返回可进入 Agent 状态的安全法规证据视图。",
        input_schema={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
                "jurisdiction": {"type": "string"},
                "document_type": {"type": "array", "items": {"type": "string"}},
                "authority": {"type": "string"},
                "authority_level": {"type": "string"},
                "validity_status": {"type": "array", "items": {"type": "string"}},
                "law_titles": {"type": "array", "items": {"type": "string"}},
                "article_no": {"type": "string"},
                "event_date": {"type": "string"},
            },
            "additionalProperties": False,
        },
        output_schema=LawEvidenceView.model_json_schema(),
        permissions=[ToolPermission.SEARCH_PUBLIC_LAW],
    )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = _required_text(arguments, "query")
        top_k = _top_k(arguments.get("top_k"), self.default_top_k)
        candidate_k = max(top_k, top_k * self.candidate_k_multiplier)
        encoded = self.embedder.encode([query])
        filters = _statute_filter(arguments)
        dense_points = _query_points(
            self.client,
            self.collection,
            encoded.dense[0],
            DENSE_VECTOR_NAME,
            candidate_k,
            filters,
        )
        sparse_points = _query_points(
            self.client,
            self.collection,
            SparseVector(indices=encoded.sparse_indices[0], values=encoded.sparse_values[0]),
            SPARSE_VECTOR_NAME,
            candidate_k,
            filters,
        )
        payloads = _payloads_by_id(dense_points + sparse_points, "chunk_id")
        dense_ids = [str(point.payload["chunk_id"]) for point in dense_points if point.payload and point.payload.get("chunk_id")]
        sparse_ids = [str(point.payload["chunk_id"]) for point in sparse_points if point.payload and point.payload.get("chunk_id")]
        ranking = _rrf_fuse(dense_ids, sparse_ids)[:top_k]
        scores = _score_by_id(dense_points + sparse_points, "chunk_id")
        items = [
            build_law_evidence_view(payloads[chunk_id], score=scores.get(chunk_id))
            for chunk_id in ranking
            if chunk_id in payloads
        ]
        warnings = []
        if arguments.get("event_date"):
            warnings.append("event_date_filter_uses_effective_from_only_v0")
        return ToolResult(
            tool_name=self.spec.name,
            status=ToolResultStatus.SUCCESS if items else ToolResultStatus.EMPTY,
            items=items,
            warnings=warnings,
            metadata={
                "normalized_query": query,
                "top_k": top_k,
                "candidate_k": candidate_k,
                "applied_filters": _filter_metadata(arguments, STATUTE_FILTER_FIELDS),
            },
        )


@dataclass(slots=True)
class FetchCaseEvidenceAdapter:
    client: QdrantLikeClient
    collection: str = "cases_collection"
    pii_policy: PIIPolicy = PIIPolicy.MASK

    spec: ClassVar[ToolSpec] = ToolSpec(
        name="fetch_case_evidence",
        description="按 case_id 获取单条脱敏案例证据视图。",
        input_schema={
            "type": "object",
            "required": ["case_id"],
            "properties": {
                "case_id": {"type": "string"},
                "party_names": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        },
        output_schema=CaseEvidenceView.model_json_schema(),
        permissions=[ToolPermission.FETCH_CASE_EVIDENCE],
        pii_policy=PIIPolicy.MASK,
    )

    def execute(self, arguments: dict[str, Any]) -> ToolResult:
        case_id = _required_text(arguments, "case_id")
        filters = Filter(must=[FieldCondition(key="case_id", match=MatchValue(value=case_id))])
        points = _scroll_points(self.client, self.collection, filters, limit=1)
        if not points:
            return ToolResult(
                tool_name=self.spec.name,
                status=ToolResultStatus.EMPTY,
                metadata={"applied_filters": {"case_id": case_id}, "top_k": 1},
            )
        item = build_case_evidence_view(
            points[0].payload or {},
            score=getattr(points[0], "score", None),
            party_names=_string_list(arguments.get("party_names")),
            policy=self.pii_policy,
        )
        return ToolResult(
            tool_name=self.spec.name,
            status=ToolResultStatus.SUCCESS,
            items=[item],
            pii_blocked_count=1 if item.pii_status.value == "review_required" else 0,
            metadata={"applied_filters": {"case_id": case_id}, "top_k": 1},
        )


CASE_FILTER_FIELDS = (
    "jurisdiction",
    "case_type",
    "procedure",
    "case_causes",
    "category_l1",
    "category_l2",
    "keywords",
)

STATUTE_FILTER_FIELDS = (
    "jurisdiction",
    "document_type",
    "authority",
    "authority_level",
    "validity_status",
    "law_titles",
    "article_no",
    "event_date",
)


def _query_points(
    client: QdrantLikeClient,
    collection: str,
    query: list[float] | SparseVector,
    vector_name: str,
    limit: int,
    query_filter: Filter | None,
) -> list[Any]:
    response = client.query_points(
        collection,
        query=query,
        using=vector_name,
        query_filter=query_filter,
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    return list(getattr(response, "points", response))


def _scroll_points(client: QdrantLikeClient, collection: str, filters: Filter, limit: int) -> list[Any]:
    response = client.scroll(
        collection,
        scroll_filter=filters,
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    if isinstance(response, tuple):
        return list(response[0])
    return list(getattr(response, "points", response))


def _case_filter(arguments: dict[str, Any]) -> Filter | None:
    conditions: list[FieldCondition] = []
    _add_match_value(conditions, "jurisdiction", arguments.get("jurisdiction"))
    _add_match_value(conditions, "case_type", arguments.get("case_type"))
    _add_match_value(conditions, "procedure", arguments.get("procedure"))
    _add_match_any(conditions, "case_causes", arguments.get("case_causes"))
    _add_match_value(conditions, "category_l1", arguments.get("category_l1"))
    _add_match_value(conditions, "category_l2", arguments.get("category_l2"))
    _add_match_any(conditions, "keywords", arguments.get("keywords"))
    return Filter(must=conditions) if conditions else None


def _statute_filter(arguments: dict[str, Any]) -> Filter | None:
    conditions: list[FieldCondition] = []
    _add_match_value(conditions, "jurisdiction", arguments.get("jurisdiction"))
    _add_match_any(conditions, "document_type", arguments.get("document_type"))
    _add_match_value(conditions, "authority", arguments.get("authority"))
    _add_match_value(conditions, "authority_level", arguments.get("authority_level"))
    _add_match_any(conditions, "validity_status", arguments.get("validity_status"))
    _add_match_any(conditions, "title", arguments.get("law_titles"))
    _add_match_value(conditions, "article_no", arguments.get("article_no"))
    event_date = _clean_text(arguments.get("event_date"))
    if event_date:
        conditions.append(FieldCondition(key="effective_from", range=DatetimeRange(lte=event_date)))
    return Filter(must=conditions) if conditions else None


def _add_match_value(conditions: list[FieldCondition], field: str, value: Any) -> None:
    text = _clean_text(value)
    if text:
        conditions.append(FieldCondition(key=field, match=MatchValue(value=text)))


def _add_match_any(conditions: list[FieldCondition], field: str, value: Any) -> None:
    items = _string_list(value)
    if items:
        conditions.append(FieldCondition(key=field, match=MatchAny(any=items)))


def _filter_metadata(arguments: dict[str, Any], fields: Sequence[str]) -> dict[str, str | int | float | bool | list[str] | None]:
    result: dict[str, str | int | float | bool | list[str] | None] = {}
    for field in fields:
        value = arguments.get(field)
        if isinstance(value, list):
            cleaned = _string_list(value)
            if cleaned:
                result[field] = cleaned
        elif _clean_text(value):
            result[field] = _clean_text(value)
    return result


def _payloads_by_id(points: Sequence[Any], id_field: str) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    for point in points:
        payload = getattr(point, "payload", None) or {}
        item_id = payload.get(id_field)
        if item_id is not None:
            payloads.setdefault(str(item_id), payload)
    return payloads


def _score_by_id(points: Sequence[Any], id_field: str) -> dict[str, float]:
    scores: dict[str, float] = {}
    for point in points:
        payload = getattr(point, "payload", None) or {}
        item_id = payload.get(id_field)
        score = getattr(point, "score", None)
        if item_id is not None and isinstance(score, int | float):
            scores[str(item_id)] = max(scores.get(str(item_id), float("-inf")), float(score))
    return {key: value for key, value in scores.items() if value != float("-inf")}


def _rrf_fuse(dense: Sequence[str], sparse: Sequence[str], rrf_k: int = 60) -> list[str]:
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    order = 0
    for ranking in (dense, sparse):
        for rank, item_id in enumerate(ranking, start=1):
            if item_id not in first_seen:
                first_seen[item_id] = order
                order += 1
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (rrf_k + rank)
    return sorted(scores, key=lambda item_id: (-scores[item_id], first_seen[item_id]))


def _top_k(value: Any, default: int, maximum: int = 50) -> int:
    if value is None:
        return default
    top_k = int(value)
    if top_k < 1 or top_k > maximum:
        raise ValueError(f"top_k must be between 1 and {maximum}")
    return top_k


def _required_text(arguments: dict[str, Any], field: str) -> str:
    value = _clean_text(arguments.get(field))
    if not value:
        raise ValueError(f"{field} cannot be empty")
    return value


def _clean_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return []
    return [text for text in (_clean_text(item) for item in value) if text]
