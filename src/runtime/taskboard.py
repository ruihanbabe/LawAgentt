"""一轮对话的共享任务板、追加式事件与结构化产物契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from runtime.messages import AgentMessage, AgentRole
from intake.blackboard import MatterBlackboard
from runtime.model_provider import ModelBudget, ModelUsage
from safety.pii import PIIStatus
from runtime.identifiers import new_id, utc_now


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    LIMITED = "limited"
    FAILED = "failed"


class TaskStatus(StrEnum):
    OPEN = "open"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class ArtifactType(StrEnum):
    INTENT_DECISION = "intent_decision"
    USER_PROFILE_SNAPSHOT = "user_profile_snapshot"
    FACT_EXTRACTION = "fact_extraction"
    CASE_EVENT = "case_event"
    RETRIEVAL_PLAN = "retrieval_plan"
    RAG_EVIDENCE_BUNDLE = "rag_evidence_bundle"
    RISK_REVIEW = "risk_review"
    RESPONSE_CANDIDATE = "response_candidate"
    FINAL_RESPONSE = "final_response"
    CLARIFICATION_QUESTION = "clarification_question"
    SUFFICIENCY_ASSESSMENT = "sufficiency_assessment"
    ISSUE_ANALYSIS = "issue_analysis"
    REVIEW_RESULT = "review_result"


class EventType(StrEnum):
    RUN_CREATED = "run_created"
    INPUT_SANITIZED = "input_sanitized"
    CONTEXT_BUILT = "context_built"
    MODEL_CALLED = "model_called"
    MODEL_DEGRADED = "model_degraded"
    TASK_CREATED = "task_created"
    CLAIM_REQUESTED = "claim_requested"
    CLAIM_ACCEPTED = "claim_accepted"
    CLAIM_REJECTED = "claim_rejected"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    ARTIFACT_CREATED = "artifact_created"
    ARTIFACT_ACCEPTED = "artifact_accepted"
    MESSAGE_SENT = "message_sent"
    TASK_DEDUPLICATED = "task_deduplicated"
    NO_PROGRESS = "no_progress"
    BUDGET_EXHAUSTED = "budget_exhausted"
    DELIVERY_ACCEPTED = "delivery_accepted"
    DELIVERY_BLOCKED = "delivery_blocked"
    REPLAY_STARTED = "replay_started"
    RUN_COMPLETED = "run_completed"


class EventVisibility(StrEnum):
    USER = "user"
    ADMIN = "admin"
    DEVELOPER = "developer"


class BoardLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_rounds: int = Field(default=8, ge=1, le=100)
    max_total_claims: int = Field(default=16, ge=1, le=1_000)
    max_tasks: int = Field(default=32, ge=1, le=1_000)
    max_claims_per_agent: int = Field(default=4, ge=1, le=100)
    max_claims_per_agent_per_round: int = Field(default=1, ge=1, le=10)
    max_task_depth: int = Field(default=6, ge=0, le=20)
    max_children_per_task: int = Field(default=6, ge=1, le=100)
    max_no_progress_rounds: int = Field(default=2, ge=1, le=10)


class ClaimCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
    agent_role: AgentRole
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=500)


class BoardTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(default_factory=lambda: new_id("task"))
    run_id: str = Field(min_length=1)
    parent_task_id: str | None = None
    task_type: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    priority: int = Field(default=100, ge=0, le=1_000)
    status: TaskStatus = TaskStatus.OPEN
    required_capabilities: list[str] = Field(default_factory=list)
    created_by: AgentRole = AgentRole.ORCHESTRATOR
    depth: int = Field(default=0, ge=0)
    dependency_ids: list[str] = Field(default_factory=list)
    deduplication_key: str = Field(min_length=1)
    claim_candidates: list[ClaimCandidate] = Field(default_factory=list)
    claimed_by: str | None = None
    claim_count: int = Field(default=0, ge=0)
    attempt_count: int = Field(default=0, ge=0)
    input_artifact_ids: list[str] = Field(default_factory=list)
    output_artifact_ids: list[str] = Field(default_factory=list)
    failure_code: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(default_factory=lambda: new_id("artifact"))
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    artifact_type: ArtifactType
    schema_version: str = "artifact-v0.1"
    producer_agent: str = Field(min_length=1)
    content: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    source_artifact_ids: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    risk_level: str = "low"
    validation_status: str = "valid"
    review_status: str = "pending"
    created_at: datetime = Field(default_factory=utc_now)


class CollaborationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: new_id("event"))
    run_id: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    event_type: EventType
    actor_type: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    task_id: str | None = None
    artifact_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    visibility: EventVisibility = EventVisibility.DEVELOPER
    created_at: datetime = Field(default_factory=utc_now)


class AgentRunBoard(BaseModel):
    """当前运行状态投影；事件列表是该投影的追加式审计来源。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: new_id("run"))
    session_id: str | None = None
    pseudonymous_user_id: str | None = None
    runtime_profile: str = "taskboard-v0.1"
    status: RunStatus = RunStatus.RUNNING
    raw_input_ref: str | None = None
    sanitized_input: str = Field(min_length=1)
    pii_status: PIIStatus = PIIStatus.CLEAN
    current_message_id: str = Field(default_factory=lambda: new_id("message"))
    blackboard: MatterBlackboard = Field(
        default_factory=lambda: MatterBlackboard(session_id="anonymous")
    )
    round: int = Field(default=0, ge=0)
    total_claims: int = Field(default=0, ge=0)
    no_progress_rounds: int = Field(default=0, ge=0)
    limits: BoardLimits = Field(default_factory=BoardLimits)
    model_budget: ModelBudget = Field(default_factory=ModelBudget)
    model_usage: ModelUsage = Field(default_factory=ModelUsage)
    tasks: list[BoardTask] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    events: list[CollaborationEvent] = Field(default_factory=list)
    messages: list[AgentMessage] = Field(default_factory=list)
    accepted_artifact_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def accepted_artifact_must_exist(self) -> AgentRunBoard:
        if self.accepted_artifact_id and not any(
            item.artifact_id == self.accepted_artifact_id for item in self.artifacts
        ):
            raise ValueError("accepted_artifact_id must reference an artifact in this run")
        return self

    def append_event(
        self,
        event_type: EventType,
        *,
        actor_type: str,
        actor_id: str,
        task_id: str | None = None,
        artifact_id: str | None = None,
        payload: dict[str, Any] | None = None,
        visibility: EventVisibility = EventVisibility.DEVELOPER,
    ) -> CollaborationEvent:
        event = CollaborationEvent(
            run_id=self.run_id,
            sequence=len(self.events),
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            task_id=task_id,
            artifact_id=artifact_id,
            payload=payload or {},
            visibility=visibility,
        )
        self.events.append(event)
        self.updated_at = utc_now()
        return event

    def task(self, task_id: str) -> BoardTask:
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        raise KeyError(f"unknown task: {task_id}")

    def artifact(self, artifact_id: str) -> Artifact:
        for artifact in self.artifacts:
            if artifact.artifact_id == artifact_id:
                return artifact
        raise KeyError(f"unknown artifact: {artifact_id}")

    @property
    def open_tasks(self) -> list[BoardTask]:
        completed = {task.task_id for task in self.tasks if task.status == TaskStatus.COMPLETED}
        return sorted(
            [
                task
                for task in self.tasks
                if task.status == TaskStatus.OPEN and set(task.dependency_ids).issubset(completed)
            ],
            key=lambda task: (task.priority, task.created_at, task.task_id),
        )


class AgentRunTrace(BaseModel):
    """供管理员和开发者查询/导出的单轮审计包。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    session_id: str | None = None
    pseudonymous_user_id: str | None = None
    runtime_profile: str
    status: RunStatus
    sanitized_input: str
    pii_status: PIIStatus
    model_budget: ModelBudget
    model_usage: ModelUsage
    tasks: list[BoardTask]
    events: list[CollaborationEvent]
    artifacts: list[Artifact]
    messages: list[AgentMessage]
    accepted_artifact_id: str | None = None
    created_at: datetime
    completed_at: datetime

    @classmethod
    def from_board(cls, board: AgentRunBoard) -> AgentRunTrace:
        # 深拷贝，避免后台审计读取时被后续内存状态修改污染。
        return cls(
            run_id=board.run_id,
            session_id=board.session_id,
            pseudonymous_user_id=board.pseudonymous_user_id,
            runtime_profile=board.runtime_profile,
            status=board.status,
            sanitized_input=board.sanitized_input,
            pii_status=board.pii_status,
            model_budget=board.model_budget.model_copy(deep=True),
            model_usage=board.model_usage.model_copy(deep=True),
            tasks=[item.model_copy(deep=True) for item in board.tasks],
            events=[item.model_copy(deep=True) for item in board.events],
            artifacts=[item.model_copy(deep=True) for item in board.artifacts],
            messages=[item.model_copy(deep=True) for item in board.messages],
            accepted_artifact_id=board.accepted_artifact_id,
            created_at=board.created_at,
            completed_at=board.updated_at,
        )
