"""用户可见十段 FinalResponse 的类型化契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


FinalDecision = Literal[
    "clarification_needed",
    "intent_confirmation_needed",
    "supported_answer",
    "limited_answer",
    "constructive_abstention",
    "safe_error",
]


class ResponseClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2_000)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)


class AmountFrameworkItem(BaseModel):
    """需要用户结合材料二次确认的金额项目框架，不包含最终金额。"""

    model_config = ConfigDict(extra="forbid")

    item_key: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=100)
    relief_kind: Literal["monetary", "non_monetary", "disputed_catchall"]
    applicability: Literal["applicable", "not_applicable", "uncertain"]
    legal_basis_hint: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(default_factory=list)
    calculation_logic: str = Field(min_length=1, max_length=500)
    requires_user_confirmation: bool = True

    @model_validator(mode="after")
    def grounded_when_relevant(self) -> AmountFrameworkItem:
        if self.applicability in {"applicable", "uncertain"} and not self.evidence_ids:
            raise ValueError("applicable or uncertain claim item requires evidence_ids")
        return self


class FinalResponseSections(BaseModel):
    """固定结构；暂时为空的段仍显式存在，避免结构随模型漂移。"""

    model_config = ConfigDict(extra="forbid")

    current_situation: list[str] = Field(default_factory=list)
    preliminary_assessment: list[str] = Field(default_factory=list)
    safety_guidance: list[str] = Field(default_factory=list)
    counterparty_position_analysis: list[str] = Field(default_factory=list)
    statutes: list[str] = Field(default_factory=list)
    similar_cases: list[str] = Field(default_factory=list)
    amount_items: list[AmountFrameworkItem] = Field(default_factory=list)
    disputed_items: list[AmountFrameworkItem] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)
    low_cost_communication: list[str] = Field(default_factory=list)
    formal_notice: list[str] = Field(default_factory=list)
    other_remedies: list[str] = Field(default_factory=list)
    document_draft_points: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class FinalResponseContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: str = Field(min_length=1, max_length=20_000)
    decision: FinalDecision
    confirmed_facts: dict[str, str] = Field(default_factory=dict)
    unresolved_facts: list[str] = Field(default_factory=list)
    claims: list[ResponseClaim] = Field(default_factory=list)
    sections: FinalResponseSections
    citation_map: dict[str, list[str]] = Field(default_factory=dict)
    source_snapshot_versions: list[str] = Field(default_factory=list)
    action_template_condition_key: str | None = None
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def decision_invariants(self) -> FinalResponseContent:
        if self.decision == "supported_answer" and not self.claims:
            raise ValueError("supported_answer requires claims")
        if self.decision in {"limited_answer", "constructive_abstention", "safe_error"} and self.claims:
            raise ValueError(f"{self.decision} must not contain claims")
        if self.decision in {"supported_answer", "limited_answer", "constructive_abstention"}:
            if not self.limitations or not self.sections.limitations:
                raise ValueError(f"{self.decision} requires limitations")
        claim_ids = {f"claim:{index}" for index, _ in enumerate(self.claims)}
        if set(self.citation_map) != claim_ids:
            raise ValueError("citation_map must have exactly one entry per claim")
        for index, claim in enumerate(self.claims):
            if self.citation_map[f"claim:{index}"] != claim.evidence_ids:
                raise ValueError("citation_map must match claim evidence_ids")
        return self


def safe_error_content(message: str) -> FinalResponseContent:
    return FinalResponseContent(
        response=message,
        decision="safe_error",
        sections=FinalResponseSections(limitations=["本次运行未通过确定性交付门禁。"]),
        limitations=["本次运行未通过确定性交付门禁。"],
    )
