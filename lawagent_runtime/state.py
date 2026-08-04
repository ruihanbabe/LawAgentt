from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SCHEMA_VERSION = "run-state-v0.1"
RUNTIME_VERSION = "lawagent-runtime-v0.1"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class UserGoal(StrEnum):
    ASK_LAW = "ask_law"
    FIND_CASES = "find_cases"
    CALCULATE = "calculate"
    DRAFT_DOCUMENT = "draft_document"
    LAWYER_HANDOFF = "lawyer_handoff"
    UNKNOWN = "unknown"


class FactStatus(StrEnum):
    USER_STATED = "user_stated"
    SYSTEM_EXTRACTED = "system_extracted"
    USER_CONFIRMED = "user_confirmed"
    DOCUMENT_SUPPORTED = "document_supported"
    DISPUTED = "disputed"
    MISSING = "missing"


class IssueStatus(StrEnum):
    PENDING = "pending"
    RETRIEVING = "retrieving"
    PARTIALLY_SUPPORTED = "partially_supported"
    SUPPORTED = "supported"
    BLOCKED = "blocked"


class SourceType(StrEnum):
    STATUTE = "statute"
    CASE = "case"
    CALCULATION = "calculation"
    USER_FACT = "user_fact"


class ToolIntentStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    EXECUTED = "executed"
    FAILED = "failed"
    SKIPPED = "skipped"


class IntentCreator(StrEnum):
    PLANNER = "planner"
    REFINE_QUERY = "refine_query"
    ROUTER = "router"
    HUMAN = "human"


class AttemptStatus(StrEnum):
    SUCCESS = "success"
    EMPTY = "empty"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class EvidenceRelation(StrEnum):
    SUPPORTS = "supports"
    OPPOSES = "opposes"
    BACKGROUND = "background"
    UNCLEAR = "unclear"


class GapType(StrEnum):
    MISSING_FACT = "missing_fact"
    MISSING_STATUTE = "missing_statute"
    MISSING_CASE = "missing_case"
    STALE_LAW = "stale_law"
    UNVERIFIED_VALIDITY = "unverified_validity"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    LOW_CONFIDENCE = "low_confidence"
    EMPTY_RESULT = "empty_result"


class GapStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    WAIVED = "waived"
    BLOCKED = "blocked"


class Stage(StrEnum):
    INITIALIZED = "initialized"
    UNDERSTANDING = "understanding"
    PLANNING = "planning"
    RETRIEVING = "retrieving"
    RERANKING = "reranking"
    GRADING = "grading"
    REFINING = "refining"
    ANSWERING = "answering"
    CLARIFYING = "clarifying"
    ABSTAINING = "abstaining"
    COMPLETED = "completed"
    FAILED = "failed"


class FinalDecision(StrEnum):
    SUPPORTED_ANSWER = "supported_answer"
    LIMITED_ANSWER = "limited_answer"
    CLARIFICATION_NEEDED = "clarification_needed"
    CONSTRUCTIVE_ABSTENTION = "constructive_abstention"
    FAILED = "failed"


class StopReason(StrEnum):
    EVIDENCE_SUFFICIENT = "evidence_sufficient"
    MISSING_CRITICAL_FACTS = "missing_critical_facts"
    BUDGET_EXHAUSTED = "budget_exhausted"
    RISK_TOO_HIGH = "risk_too_high"
    TOOL_FAILURE = "tool_failure"
    NO_PROGRESS = "no_progress"
    USER_CANCELLED = "user_cancelled"


class FactItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: str = Field(default_factory=lambda: new_id("fact"))
    name: str = Field(min_length=1)
    value: str | int | float | bool | date | None = None
    source: str = Field(default="user_query", min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: FactStatus = FactStatus.SYSTEM_EXTRACTED


class LegalIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: str = Field(default_factory=lambda: new_id("issue"))
    title: str = Field(min_length=1)
    description: str = ""
    issue_type: str | None = None
    required_sources: list[SourceType] = Field(default_factory=list)
    status: IssueStatus = IssueStatus.PENDING
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    opposing_evidence_ids: list[str] = Field(default_factory=list)
    gap_ids: list[str] = Field(default_factory=list)


class ToolIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_id: str = Field(default_factory=lambda: new_id("intent"))
    issue_id: str | None = None
    tool_name: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    query_terms: list[str] = Field(default_factory=list)
    filters_as_slots: dict[str, str | int | float | bool | list[str] | None] = Field(default_factory=dict)
    priority: int = Field(default=100, ge=0)
    created_by: IntentCreator = IntentCreator.PLANNER
    status: ToolIntentStatus = ToolIntentStatus.PENDING


class RetrievalAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str = Field(default_factory=lambda: new_id("attempt"))
    intent_id: str | None = None
    issue_id: str | None = None
    tool_name: str = Field(min_length=1)
    normalized_query: str = ""
    applied_filters: dict[str, str | int | float | bool | list[str] | None] = Field(default_factory=dict)
    top_k: int = Field(default=10, ge=1, le=100)
    result_count: int = Field(default=0, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    status: AttemptStatus = AttemptStatus.SUCCESS
    error_code: str | None = None
    warnings: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    source_type: SourceType
    source_id: str
    parent_id: str | None = None
    title: str = ""
    citation_label: str = ""
    content_snippet: str = ""
    score: float | None = None
    rerank_score: float | None = None
    issue_ids: list[str] = Field(default_factory=list)
    supports: EvidenceRelation = EvidenceRelation.UNCLEAR
    authority_level: str | None = None
    validity_status: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    warnings: list[str] = Field(default_factory=list)

    @field_validator("score", "rerank_score")
    @classmethod
    def score_must_be_finite(cls, value: float | None) -> float | None:
        if value is not None and not -1.0 <= value <= 1.0:
            raise ValueError("score must be between -1.0 and 1.0")
        return value


class EvidenceGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gap_id: str = Field(default_factory=lambda: new_id("gap"))
    issue_id: str
    gap_type: GapType
    description: str = Field(min_length=1)
    severity: int = Field(default=2, ge=1, le=3)
    suggested_action: str | None = None
    suggested_tool: str | None = None
    suggested_query_terms: list[str] = Field(default_factory=list)
    status: GapStatus = GapStatus.OPEN


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_steps: int = Field(default=12, ge=1)
    step_count: int = Field(default=0, ge=0)
    max_retrieval_rounds: int = Field(default=3, ge=0)
    retrieval_round: int = Field(default=0, ge=0)
    token_budget: int | None = Field(default=None, ge=1)
    time_budget_ms: int | None = Field(default=None, ge=1)
    started_at: datetime = Field(default_factory=utc_now)
    deadline_at: datetime | None = None

    @model_validator(mode="after")
    def counts_cannot_exceed_limits(self) -> Budget:
        if self.step_count > self.max_steps:
            raise ValueError("step_count cannot exceed max_steps")
        if self.retrieval_round > self.max_retrieval_rounds:
            raise ValueError("retrieval_round cannot exceed max_retrieval_rounds")
        return self

    def exhausted(self, now: datetime | None = None) -> bool:
        current = now or utc_now()
        if self.step_count >= self.max_steps:
            return True
        if self.deadline_at is not None and current >= self.deadline_at:
            return True
        return False

    def retrieval_exhausted(self) -> bool:
        return self.retrieval_round >= self.max_retrieval_rounds


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_index: int = Field(ge=0)
    node_name: str = Field(min_length=1)
    input_summary: str = ""
    output_summary: str = ""
    route_reason: str | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class FailureItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    failure_id: str = Field(default_factory=lambda: new_id("failure"))
    node_name: str
    error_code: str
    message: str
    retryable: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class RunState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: new_id("run"))
    session_id: str | None = None
    case_id: str | None = None
    schema_version: str = SCHEMA_VERSION
    runtime_version: str = RUNTIME_VERSION
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    raw_query: str = Field(min_length=1)
    normalized_query: str = ""
    user_goal: UserGoal = UserGoal.UNKNOWN
    language: str = "zh-CN"
    jurisdiction: str = "CN"
    event_date: date | None = None

    facts: list[FactItem] = Field(default_factory=list)
    legal_issues: list[LegalIssue] = Field(default_factory=list)
    tool_intents: list[ToolIntent] = Field(default_factory=list)
    retrieval_attempts: list[RetrievalAttempt] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    evidence_gaps: list[EvidenceGap] = Field(default_factory=list)

    stage: Stage = Stage.INITIALIZED
    next_node: str | None = None
    route_reason: str | None = None
    budget: Budget = Field(default_factory=Budget)
    stop_reason: StopReason | None = None
    final_decision: FinalDecision | None = None
    failures: list[FailureItem] = Field(default_factory=list)
    trace: list[TraceEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def completed_runs_need_decision(self) -> RunState:
        if self.stage == Stage.COMPLETED and self.final_decision is None:
            raise ValueError("completed runs require final_decision")
        if self.stage == Stage.FAILED and self.stop_reason is None:
            raise ValueError("failed runs require stop_reason")
        return self

    @classmethod
    def start(
        cls,
        raw_query: str,
        *,
        session_id: str | None = None,
        case_id: str | None = None,
        jurisdiction: str = "CN",
        language: str = "zh-CN",
    ) -> RunState:
        normalized = " ".join(raw_query.split())
        return cls(
            raw_query=raw_query,
            normalized_query=normalized,
            session_id=session_id,
            case_id=case_id,
            jurisdiction=jurisdiction,
            language=language,
        )

    @property
    def open_gaps(self) -> list[EvidenceGap]:
        return [gap for gap in self.evidence_gaps if gap.status in {GapStatus.OPEN, GapStatus.IN_PROGRESS}]

    @property
    def missing_critical_facts(self) -> list[FactItem]:
        return [fact for fact in self.facts if fact.status == FactStatus.MISSING]

    def add_trace(
        self,
        node_name: str,
        *,
        input_summary: str = "",
        output_summary: str = "",
        route_reason: str | None = None,
        latency_ms: int | None = None,
        error_code: str | None = None,
    ) -> None:
        self.trace.append(
            TraceEvent(
                step_index=len(self.trace),
                node_name=node_name,
                input_summary=input_summary,
                output_summary=output_summary,
                route_reason=route_reason,
                latency_ms=latency_ms,
                error_code=error_code,
            )
        )
        self.updated_at = utc_now()

    def advance(
        self,
        *,
        stage: Stage,
        next_node: str | None = None,
        route_reason: str | None = None,
    ) -> None:
        self.stage = stage
        self.next_node = next_node
        self.route_reason = route_reason
        self.budget.step_count += 1
        self.updated_at = utc_now()

    def complete(self, decision: FinalDecision, stop_reason: StopReason) -> None:
        self.stage = Stage.COMPLETED
        self.next_node = None
        self.final_decision = decision
        self.stop_reason = stop_reason
        self.updated_at = utc_now()
