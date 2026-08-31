"""跨多轮咨询共享的最小 Matter Blackboard。"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from runtime.identifiers import new_id, utc_now


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SufficiencyDecision(StrEnum):
    ASK_CLARIFICATION = "ask_clarification"
    START_RETRIEVAL = "start_retrieval"
    DELIVER_LIMITED_RESPONSE = "deliver_limited_response"


class RiskAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: str = Field(default_factory=lambda: new_id("risk"))
    assessed_through_message_id: str
    level: RiskLevel = RiskLevel.LOW
    signal_types: list[str] = Field(default_factory=list)
    recommended_action: str = "continue"
    created_at: datetime = Field(default_factory=utc_now)


class SufficiencyState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clarification_round: int = Field(default=0, ge=0, le=2)
    max_clarification_rounds: int = 2
    missing_fact_keys: list[str] = Field(default_factory=list)
    asked_question_keys: list[str] = Field(default_factory=list)
    unknown_to_user_fact_keys: list[str] = Field(default_factory=list)
    decision: SufficiencyDecision = SufficiencyDecision.ASK_CLARIFICATION


class MatterBlackboard(BaseModel):
    """PostgreSQL 事实源的运行时投影；当前由内存仓储模拟。"""

    model_config = ConfigDict(extra="forbid")

    matter_id: str = Field(default_factory=lambda: new_id("matter"))
    session_id: str
    state_version: int = Field(default=0, ge=0)
    message_ids: list[str] = Field(default_factory=list)
    confirmed_facts: dict[str, str] = Field(default_factory=dict)
    candidate_facts: dict[str, str] = Field(default_factory=dict)
    disputed_fact_keys: list[str] = Field(default_factory=list)
    event_date: date | None = None
    risk_assessments: list[RiskAssessment] = Field(default_factory=list)
    sufficiency: SufficiencyState = Field(default_factory=SufficiencyState)
    evidence_ids: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)

    def advance_version(self) -> None:
        self.state_version += 1
        self.updated_at = utc_now()
