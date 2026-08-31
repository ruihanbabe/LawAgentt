from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PIIPolicy(StrEnum):
    MASK = "mask"
    BLOCK = "block"


class PIIStatus(StrEnum):
    CLEAN = "clean"
    MASKED = "masked"
    REVIEW_REQUIRED = "review_required"


class PIIDetection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    count: int = Field(ge=1)


class PIIReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    status: PIIStatus
    blocked: bool = False
    detections: list[PIIDetection] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PIIReviewer:
    _patterns = (
        ("id_card", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), "[身份证号]"),
        ("credit_code", re.compile(r"(?<![0-9A-Z])[0-9A-HJ-NPQRTUWXY]{18}(?![0-9A-Z])"), "[统一社会信用代码]"),
        ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[手机号]"),
        ("bank_card", re.compile(r"(?<!\d)\d{16,19}(?!\d)"), "[银行卡号]"),
        ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[邮箱]"),
    )

    def review(
        self,
        text: str | None,
        *,
        party_names: list[str] | None = None,
        policy: PIIPolicy = PIIPolicy.MASK,
    ) -> PIIReview:
        value = str(text or "")
        detections: list[PIIDetection] = []
        warnings: list[str] = []

        if "[Missing]" in value:
            count = value.count("[Missing]")
            value = value.replace("[Missing]", "[角色未标注的当事人]")
            warnings.append(f"normalized_missing_party_role:{count}")

        for name in sorted(set(party_names or []), key=len, reverse=True):
            if len(name) < 2:
                continue
            count = value.count(name)
            if count:
                detections.append(PIIDetection(kind="party_name", count=count))
                value = value.replace(name, "[当事人]")

        for kind, pattern, replacement in self._patterns:
            value, count = pattern.subn(replacement, value)
            if count:
                detections.append(PIIDetection(kind=kind, count=count))

        if detections and policy == PIIPolicy.BLOCK:
            return PIIReview(
                text="",
                status=PIIStatus.REVIEW_REQUIRED,
                blocked=True,
                detections=detections,
                warnings=[*warnings, "pii_blocked"],
            )
        if detections or warnings:
            return PIIReview(text=value, status=PIIStatus.MASKED, detections=detections, warnings=warnings)
        return PIIReview(text=value, status=PIIStatus.CLEAN)
