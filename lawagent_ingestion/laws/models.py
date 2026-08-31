from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SCHEMA_VERSION = "laws-v0.2"
PIPELINE_VERSION = "laws-ingest-v0.2"


class DocumentType(StrEnum):
    LAW = "law"
    ADMINISTRATIVE_REGULATION = "administrative_regulation"
    JUDICIAL_INTERPRETATION = "judicial_interpretation"
    DEPARTMENT_RULE = "department_rule"
    AMENDMENT = "amendment"
    OTHER_NORMATIVE = "other_normative"
    NON_NORMATIVE = "non_normative"


class ValidityStatus(StrEnum):
    PENDING = "pending"
    EFFECTIVE = "effective"
    AMENDED = "amended"
    REPEALED = "repealed"
    UNVERIFIED = "unverified"


class LawDocumentVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    law_family_id: str
    law_version_id: str
    title: str
    normalized_title: str
    document_type: DocumentType
    authority: str | None = None
    authority_level: str | None = None
    jurisdiction: str = "CN"
    effective_from: date | None = None
    effective_from_method: str | None = None
    effective_from_evidence: str | None = None
    effective_from_confidence: Literal["high", "medium", "low", "unresolved"] = "unresolved"
    effective_to: date | None = None
    effective_to_method: str | None = None
    effective_to_evidence: str | None = None
    effective_to_confidence: Literal["high", "medium", "low", "unresolved"] = "unresolved"
    validity_status: ValidityStatus = ValidityStatus.UNVERIFIED
    status_verified_at: datetime | None = None
    source_name: str = "local-laws-dataset"
    source_url: str | None = None
    source_path: str
    source_authority_level: Literal["official", "secondary", "unknown"] = "unknown"
    source_claimed_status: str = "current"
    supersedes_version_id: str | None = None
    amends_version_ids: list[str] = Field(default_factory=list)
    content_hash: str
    schema_version: str = SCHEMA_VERSION
    pipeline_version: str = PIPELINE_VERSION
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LawChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    law_family_id: str
    law_version_id: str
    title: str
    document_type: DocumentType
    authority: str | None = None
    authority_level: str | None = None
    jurisdiction: str = "CN"
    effective_from: date | None = None
    effective_from_method: str | None = None
    effective_from_confidence: Literal["high", "medium", "low", "unresolved"] = "unresolved"
    effective_to: date | None = None
    effective_to_method: str | None = None
    effective_to_confidence: Literal["high", "medium", "low", "unresolved"] = "unresolved"
    validity_status: ValidityStatus = ValidityStatus.UNVERIFIED
    source_path: str
    source_authority_level: Literal["official", "secondary", "unknown"] = "unknown"
    chunk_type: Literal["article", "amendment_item", "section"]
    article_no: str | None = None
    ordinal: int = Field(ge=1)
    structure_path: str = ""
    content: str = Field(min_length=1)
    embedding_text: str = Field(min_length=1)
    content_hash: str
    schema_version: str = SCHEMA_VERSION
    pipeline_version: str = PIPELINE_VERSION

    def qdrant_payload(self) -> dict:
        payload = self.model_dump(mode="json")
        payload.pop("embedding_text", None)
        return payload
