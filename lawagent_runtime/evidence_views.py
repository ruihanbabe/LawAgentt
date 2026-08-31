from __future__ import annotations

import math
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .pii import PIIPolicy, PIIReviewer, PIIStatus


class LegalBasisView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    law: str = ""
    terms: str = ""


class CaseEvidenceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["case"] = "case"
    case_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    case_causes: list[str] = Field(default_factory=list)
    category_l1: str | None = None
    category_l2: str | None = None
    fact_snippet: str = ""
    reasoning_snippet: str = ""
    result_summary: str = ""
    legal_basis: list[LegalBasisView] = Field(default_factory=list)
    score: float | None = None
    source_count: int = Field(default=1, ge=1)
    pii_status: PIIStatus = PIIStatus.CLEAN
    warnings: list[str] = Field(default_factory=list)

    @field_validator("score")
    @classmethod
    def score_is_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("score must be finite")
        return value


class LawEvidenceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["law"] = "law"
    chunk_id: str = Field(min_length=1)
    law_family_id: str = Field(min_length=1)
    law_version_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    article_no: str | None = None
    content: str = Field(min_length=1)
    effective_from: date | None = None
    effective_to: date | None = None
    validity_status: str = "unverified"
    score: float | None = None
    pii_status: PIIStatus = PIIStatus.CLEAN
    warnings: list[str] = Field(default_factory=list)

    @field_validator("score")
    @classmethod
    def score_is_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("score must be finite")
        return value


def _truncate(value: str, max_chars: int, field_name: str) -> tuple[str, str | None]:
    if len(value) <= max_chars:
        return value, None
    return value[:max_chars].rstrip() + "…", f"truncated:{field_name}:{len(value)}>{max_chars}"


def build_case_evidence_view(
    payload: dict[str, Any],
    *,
    score: float | None = None,
    party_names: list[str] | None = None,
    reviewer: PIIReviewer | None = None,
    policy: PIIPolicy = PIIPolicy.MASK,
    max_chars_per_field: int = 1200,
) -> CaseEvidenceView:
    pii_reviewer = reviewer or PIIReviewer()
    warnings: list[str] = []
    statuses: list[PIIStatus] = []
    blocked_count = 0

    def safe_text(field_name: str, fallback: str = "") -> str:
        nonlocal blocked_count
        reviewed = pii_reviewer.review(payload.get(field_name), party_names=party_names, policy=policy)
        statuses.append(reviewed.status)
        warnings.extend(f"{field_name}:{warning}" for warning in reviewed.warnings)
        if reviewed.blocked:
            blocked_count += 1
            return fallback
        truncated, warning = _truncate(reviewed.text, max_chars_per_field, field_name)
        if warning:
            warnings.append(warning)
        return truncated

    title = safe_text("title", "[标题因敏感信息被阻断]") or "[无标题]"
    fact_source = "claims_and_facts" if payload.get("claims_and_facts") else "case_record"
    fact_snippet = safe_text(fact_source)
    reasoning = safe_text("judge_reason")
    result = safe_text("judge_result")
    if blocked_count:
        pii_status = PIIStatus.REVIEW_REQUIRED
    elif PIIStatus.MASKED in statuses:
        pii_status = PIIStatus.MASKED
    else:
        pii_status = PIIStatus.CLEAN

    legal_basis = [
        LegalBasisView(law=str(item.get("law") or ""), terms=str(item.get("terms") or ""))
        for item in (payload.get("legal_basis") or [])
        if isinstance(item, dict)
    ]
    return CaseEvidenceView(
        case_id=str(payload.get("case_id") or ""),
        title=title,
        case_causes=[str(value) for value in (payload.get("case_causes") or [])],
        category_l1=payload.get("category_l1"),
        category_l2=payload.get("category_l2"),
        fact_snippet=fact_snippet,
        reasoning_snippet=reasoning,
        result_summary=result,
        legal_basis=legal_basis,
        score=score,
        source_count=max(1, int(payload.get("source_count") or 1)),
        pii_status=pii_status,
        warnings=warnings,
    )


def build_law_evidence_view(
    payload: dict[str, Any],
    *,
    score: float | None = None,
    reviewer: PIIReviewer | None = None,
    max_chars: int = 4000,
) -> LawEvidenceView:
    reviewed = (reviewer or PIIReviewer()).review(payload.get("content"), policy=PIIPolicy.MASK)
    content, truncation_warning = _truncate(reviewed.text, max_chars, "content")
    warnings = list(reviewed.warnings)
    if truncation_warning:
        warnings.append(truncation_warning)
    return LawEvidenceView(
        chunk_id=str(payload.get("chunk_id") or ""),
        law_family_id=str(payload.get("law_family_id") or ""),
        law_version_id=str(payload.get("law_version_id") or ""),
        title=str(payload.get("title") or ""),
        article_no=str(payload["article_no"]) if payload.get("article_no") is not None else None,
        content=content,
        effective_from=payload.get("effective_from"),
        effective_to=payload.get("effective_to"),
        validity_status=str(payload.get("validity_status") or "unverified"),
        score=score,
        pii_status=reviewed.status,
        warnings=warnings,
    )
