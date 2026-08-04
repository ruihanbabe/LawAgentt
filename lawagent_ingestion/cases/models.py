from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


SCHEMA_VERSION = "cases-v0.1"
PIPELINE_VERSION = "cases-ingest-v0.1"


class LegalBasisItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    law: str = ""
    terms: str = ""


class PartyItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = ""
    role: str = ""
    entity_type: str | None = None


class CaseDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    case_version_id: str
    title: str
    case_type: str | None = None
    procedure: str | None = None
    case_causes: list[str] = Field(default_factory=list)
    category_l1: str | None = None
    category_l2: str | None = None
    keywords: list[str] = Field(default_factory=list)
    case_record: str = ""
    claims_and_facts: str = ""
    judge_reason: str = ""
    judge_result: str = ""
    legal_basis: list[LegalBasisItem] = Field(default_factory=list)
    parties: list[PartyItem] = Field(default_factory=list)
    court: str | None = None
    case_number: str | None = None
    judgment_date: str | None = None
    jurisdiction: str = "CN"
    source_paths: list[str] = Field(default_factory=list)
    source_count: int = Field(ge=1)
    source_authority_level: str = "unknown"
    content_hash: str
    schema_version: str = SCHEMA_VERSION
    pipeline_version: str = PIPELINE_VERSION


class CaseRetrievalPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point_id: str
    case_id: str
    case_version_id: str
    title: str
    case_type: str | None = None
    procedure: str | None = None
    case_causes: list[str] = Field(default_factory=list)
    category_l1: str | None = None
    category_l2: str | None = None
    keywords: list[str] = Field(default_factory=list)
    jurisdiction: str = "CN"
    source_count: int = Field(ge=1)
    retrieval_text: str = Field(min_length=1)
    case_record: str = ""
    claims_and_facts: str = ""
    judge_reason: str = ""
    judge_result: str = ""
    legal_basis: list[LegalBasisItem] = Field(default_factory=list)
    content_hash: str
    schema_version: str = SCHEMA_VERSION
    pipeline_version: str = PIPELINE_VERSION

    def qdrant_payload(self) -> dict:
        payload = self.model_dump(mode="json")
        payload.pop("retrieval_text", None)
        return payload

