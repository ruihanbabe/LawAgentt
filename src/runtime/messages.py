from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from runtime.identifiers import new_id, utc_now


class AgentRole(StrEnum):
    ORCHESTRATOR = "orchestrator"
    SAFETY = "safety"
    INTAKE = "intake"
    RETRIEVAL = "retrieval"
    ANALYSIS = "analysis"
    DRAFTING = "drafting"
    REVIEW = "review"
    SCHEDULER = "scheduler"
    HUMAN = "human"
    SYSTEM = "system"


class MessageType(StrEnum):
    USER_PROBLEM = "user_problem"
    FACT_PROFILE = "fact_profile"
    RETRIEVAL_INTENT = "retrieval_intent"
    RETRIEVAL_RESULT = "retrieval_result"
    ANALYSIS_RESULT = "analysis_result"
    DRAFT_RESULT = "draft_result"
    REVIEW_RESULT = "review_result"
    CLARIFICATION_REQUEST = "clarification_request"
    RISK_RESULT = "risk_result"
    ERROR = "error"


class AgentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(default_factory=lambda: new_id("msg"))
    run_id: str = Field(min_length=1)
    case_id: str | None = None
    from_role: AgentRole
    to_role: AgentRole
    message_type: MessageType
    payload: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: object = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def human_messages_target_orchestrator(self) -> AgentMessage:
        if self.from_role == AgentRole.HUMAN and self.to_role != AgentRole.ORCHESTRATOR:
            raise ValueError("human messages must target orchestrator")
        if self.message_type == MessageType.ERROR and not self.warnings and "error_code" not in self.payload:
            raise ValueError("error messages require warnings or payload.error_code")
        return self
