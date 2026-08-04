from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .messages import AgentMessage, AgentRole
from .patches import StatePatch


class ObservationStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    EMPTY = "empty"
    FAILED = "failed"
    SKIPPED = "skipped"


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_name: str = Field(min_length=1)
    agent_role: AgentRole
    status: ObservationStatus
    message: AgentMessage | None = None
    state_patches: list[StatePatch] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)
