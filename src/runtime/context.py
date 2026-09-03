"""按角色构建最小、可审计且不可变的模型上下文视图。"""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from runtime.messages import AgentRole
from runtime.identifiers import new_id
from runtime.memory import MemoryService
from runtime.tools import ToolExecutor
from scenario_pack import RentalDepositScenarioPack, ScenarioPack
from runtime.taskboard import AgentRunBoard, Artifact, ArtifactType, BoardTask, EventType


CONTEXT_POLICY_VERSION = "context-policy-v0.1"


class ContextSourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: str
    source_id: str
    source_version: str | None = None
    content_hash: str
    classification: str = "internal"


class ContextHistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: str
    role: str
    content: str


class ContextArtifactView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str
    artifact_type: ArtifactType
    content: dict[str, Any]
    evidence_refs: tuple[str, ...] = ()
    validation_status: str
    review_status: str


class FactContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    confirmed: dict[str, str] = Field(default_factory=dict)
    candidates: dict[str, str] = Field(default_factory=dict)
    disputed_keys: tuple[str, ...] = ()
    missing_keys: tuple[str, ...] = ()
    unknown_to_user_keys: tuple[str, ...] = ()


class AgentContextView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    context_id: str = Field(default_factory=lambda: new_id("context"))
    run_id: str
    task_id: str
    matter_id: str
    role: AgentRole
    objective: str
    current_message: str | None = None
    facts: FactContext = Field(default_factory=FactContext)
    history: tuple[ContextHistoryMessage, ...] = ()
    artifacts: tuple[ContextArtifactView, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    auxiliary_examples: tuple[dict[str, Any], ...] = ()
    scenario_id: str = "rental-deposit-v0.1"
    prompt_version: str
    policy_version: str = CONTEXT_POLICY_VERSION
    allowed_tool_names: tuple[str, ...] = ()
    source_refs: tuple[ContextSourceRef, ...] = ()
    is_truncated: bool = False
    omitted_sections: tuple[str, ...] = ()
    content_hash: str


class ContextRolePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    include_current_message: bool
    include_confirmed_facts: bool = False
    include_candidate_facts: bool = False
    include_disputes: bool = False
    include_missing_facts: bool = False
    history_limit: int = Field(default=0, ge=0, le=20)
    allowed_artifact_types: frozenset[ArtifactType] = frozenset()
    include_source_chain: bool = False
    allowed_tool_names: tuple[str, ...] = ()
    prompt_version: str


ROLE_CONTEXT_POLICIES: dict[AgentRole, ContextRolePolicy] = {
    AgentRole.SAFETY: ContextRolePolicy(
        include_current_message=True,
        history_limit=2,
        allowed_artifact_types=frozenset({ArtifactType.USER_PROFILE_SNAPSHOT}),
        prompt_version="safety-glm-v0.1",
    ),
    AgentRole.INTAKE: ContextRolePolicy(
        include_current_message=True,
        include_confirmed_facts=True,
        include_candidate_facts=True,
        include_disputes=True,
        include_missing_facts=True,
        history_limit=6,
        allowed_artifact_types=frozenset({ArtifactType.RISK_REVIEW, ArtifactType.USER_PROFILE_SNAPSHOT}),
        prompt_version="understanding-glm-v0.1",
    ),
    AgentRole.RETRIEVAL: ContextRolePolicy(
        include_current_message=False,
        include_confirmed_facts=True,
        include_candidate_facts=True,
        include_disputes=True,
        include_missing_facts=True,
        allowed_artifact_types=frozenset({ArtifactType.SUFFICIENCY_ASSESSMENT}),
        allowed_tool_names=("search_statutes", "search_cases"),
        prompt_version="retrieval-glm-v0.1",
    ),
    AgentRole.ANALYSIS: ContextRolePolicy(
        include_current_message=False,
        include_confirmed_facts=True,
        include_candidate_facts=True,
        include_disputes=True,
        include_missing_facts=True,
        allowed_artifact_types=frozenset({ArtifactType.RAG_EVIDENCE_BUNDLE}),
        prompt_version="analysis-glm-v0.1",
    ),
    AgentRole.DRAFTING: ContextRolePolicy(
        include_current_message=False,
        include_confirmed_facts=True,
        include_disputes=True,
        include_missing_facts=True,
        allowed_artifact_types=frozenset({ArtifactType.SUFFICIENCY_ASSESSMENT, ArtifactType.ISSUE_ANALYSIS}),
        prompt_version="response-glm-v0.1",
    ),
    AgentRole.REVIEW: ContextRolePolicy(
        include_current_message=True,
        include_confirmed_facts=True,
        include_candidate_facts=True,
        include_disputes=True,
        include_missing_facts=True,
        history_limit=6,
        allowed_artifact_types=frozenset({
            ArtifactType.RESPONSE_CANDIDATE,
            ArtifactType.ISSUE_ANALYSIS,
            ArtifactType.RAG_EVIDENCE_BUNDLE,
            ArtifactType.SUFFICIENCY_ASSESSMENT,
            ArtifactType.RISK_REVIEW,
            ArtifactType.RETRIEVAL_PLAN,
            ArtifactType.TASK_INTENT,
            ArtifactType.ESCALATION_REQUEST,
        }),
        include_source_chain=True,
        prompt_version="review-glm-v0.1",
    ),
    AgentRole.SCHEDULER: ContextRolePolicy(
        include_current_message=False,
        include_confirmed_facts=True,
        include_candidate_facts=True,
        include_disputes=True,
        include_missing_facts=True,
        allowed_artifact_types=frozenset({
            ArtifactType.SUFFICIENCY_ASSESSMENT,
            ArtifactType.RAG_EVIDENCE_BUNDLE,
            ArtifactType.ISSUE_ANALYSIS,
            ArtifactType.REVIEW_RESULT,
            ArtifactType.ESCALATION_REQUEST,
        }),
        include_source_chain=True,
        prompt_version="scheduler-glm-v0.1",
    ),
}


class ContextService:
    """只从显式输入构建 ContextView；Agent 不自行读取 Store。"""

    def __init__(
        self,
        *,
        max_chars: int = 24_000,
        scenario_id: str = "rental-deposit-v0.1",
        memory_service: MemoryService | None = None,
        tool_executor: ToolExecutor | None = None,
        scenario_pack: ScenarioPack | None = None,
    ) -> None:
        if max_chars < 1:
            raise ValueError("max_chars must be positive")
        if not scenario_id:
            raise ValueError("scenario_id must not be empty")
        self.max_chars = max_chars
        self.scenario_id = scenario_id
        self.memory_service = memory_service
        self.tool_executor = tool_executor
        self.scenario_pack = scenario_pack or RentalDepositScenarioPack()

    def build(
        self,
        *,
        role: AgentRole,
        task: BoardTask,
        board: AgentRunBoard,
        history: list[Any] | None = None,
    ) -> AgentContextView:
        policy = ROLE_CONTEXT_POLICIES.get(role)
        if policy is None:
            raise ValueError(f"role has no context policy: {role.value}")
        if task.run_id != board.run_id:
            raise ValueError("task and board run_id mismatch")

        refs: list[ContextSourceRef] = []
        current_message = board.sanitized_input if policy.include_current_message else None
        if current_message is not None:
            refs.append(_source_ref("message", board.current_message_id, current_message, "sanitized"))

        facts = FactContext(
            confirmed=dict(board.blackboard.confirmed_facts) if policy.include_confirmed_facts else {},
            candidates=dict(board.blackboard.candidate_facts) if policy.include_candidate_facts else {},
            disputed_keys=tuple(board.blackboard.disputed_fact_keys) if policy.include_disputes else (),
            missing_keys=tuple(board.blackboard.sufficiency.missing_fact_keys) if policy.include_missing_facts else (),
            unknown_to_user_keys=(
                tuple(board.blackboard.sufficiency.unknown_to_user_fact_keys)
                if policy.include_missing_facts else ()
            ),
        )
        if any((facts.confirmed, facts.candidates, facts.disputed_keys, facts.missing_keys)):
            refs.append(_source_ref(
                "matter_blackboard",
                board.blackboard.matter_id,
                facts.model_dump(mode="json"),
                "sanitized",
                str(board.blackboard.state_version),
            ))

        managed_history = (
            list(self.memory_service.read(board.session_id or "", limit=policy.history_limit))
            if self.memory_service is not None and board.session_id else list(history or [])
        )
        selected_history = managed_history[-policy.history_limit:] if policy.history_limit else []
        history_views = tuple(
            ContextHistoryMessage(message_id=item.message_id, role=item.role, content=item.content)
            for item in selected_history
        )
        refs.extend(
            _source_ref("history_message", item.message_id, item.content, "sanitized")
            for item in history_views
        )

        artifact_ids = list(task.input_artifact_ids)
        has_evidence_input = any(
            board.artifact(artifact_id).artifact_type == ArtifactType.RAG_EVIDENCE_BUNDLE
            for artifact_id in artifact_ids
        )
        if (
            self.tool_executor is not None
            and role in {AgentRole.ANALYSIS, AgentRole.REVIEW}
            and not has_evidence_input
        ):
            existing_fill = next((
                item for item in board.artifacts
                if item.task_id == task.task_id
                and item.artifact_type == ArtifactType.RAG_EVIDENCE_BUNDLE
                and item.producer_agent == "context-service-v0.1"
            ), None)
            fill = existing_fill or self._retrieve_context_hole(board, task)
            if fill.artifact_id not in artifact_ids:
                artifact_ids.append(fill.artifact_id)
        if policy.include_source_chain:
            cursor = 0
            while cursor < len(artifact_ids):
                artifact = board.artifact(artifact_ids[cursor])
                for source_id in artifact.source_artifact_ids:
                    if source_id not in artifact_ids:
                        artifact_ids.append(source_id)
                cursor += 1

        artifacts: list[ContextArtifactView] = []
        for artifact_id in artifact_ids:
            artifact = board.artifact(artifact_id)
            if artifact.artifact_type not in policy.allowed_artifact_types:
                continue
            artifacts.append(_artifact_view(artifact))
            refs.append(_source_ref(
                "artifact", artifact.artifact_id, artifacts[-1].model_dump(mode="json"),
                "sanitized", artifact.schema_version,
            ))

        payload = {
            "run_id": board.run_id,
            "task_id": task.task_id,
            "matter_id": board.blackboard.matter_id,
            "role": role.value,
            "objective": task.objective,
            "current_message": current_message,
            "facts": facts.model_dump(mode="json"),
            "history": [item.model_dump(mode="json") for item in history_views],
            "artifacts": [item.model_dump(mode="json") for item in artifacts],
            "evidence_ids": list(dict.fromkeys(ref for item in artifacts for ref in item.evidence_refs)),
            "auxiliary_examples": [],
            "scenario_id": self.scenario_id,
            "prompt_version": policy.prompt_version,
            "policy_version": CONTEXT_POLICY_VERSION,
            "allowed_tool_names": list(policy.allowed_tool_names),
        }
        omitted: list[str] = []
        if len(_canonical_json(payload)) > self.max_chars and payload["history"]:
            payload["history"] = []
            history_views = ()
            refs = [item for item in refs if item.source_type != "history_message"]
            omitted.append("history")
        if len(_canonical_json(payload)) > self.max_chars:
            raise ValueError("required context exceeds max_chars")

        return AgentContextView(
            run_id=board.run_id,
            task_id=task.task_id,
            matter_id=board.blackboard.matter_id,
            role=role,
            objective=task.objective,
            current_message=current_message,
            facts=facts,
            history=history_views,
            artifacts=tuple(artifacts),
            evidence_ids=tuple(payload["evidence_ids"]),
            auxiliary_examples=(),
            scenario_id=self.scenario_id,
            prompt_version=policy.prompt_version,
            allowed_tool_names=policy.allowed_tool_names,
            source_refs=tuple(refs),
            is_truncated=bool(omitted),
            omitted_sections=tuple(omitted),
            content_hash=_hash(payload),
        )

    def _retrieve_context_hole(self, board: AgentRunBoard, task: BoardTask) -> Artifact:
        query_parts = [self.scenario_pack.retrieval_query_prefix().strip()]
        query_parts.extend(str(value).strip() for value in board.blackboard.confirmed_facts.values())
        query = " ".join(part for part in query_parts if part)[:1_000]
        results: list[dict[str, Any]] = []
        evidence_refs: list[str] = []
        for tool_name in ("search_statutes", "search_cases"):
            result = self.tool_executor.execute(tool_name, {"query": query, "top_k": 5})
            item_refs = [
                f"law:{item.chunk_id}" if hasattr(item, "chunk_id") else f"case:{item.case_id}"
                for item in result.items
            ]
            evidence_refs.extend(item_refs)
            results.append({
                "tool_name": result.tool_name,
                "status": result.status.value,
                "items": [item.model_dump(mode="json") for item in result.items],
                "evidence_refs": item_refs,
                "warnings": list(result.warnings),
                "latency_ms": result.latency_ms,
                "trace_id": result.trace_id,
            })
        unique_refs = list(dict.fromkeys(evidence_refs))
        for evidence_id in unique_refs:
            if evidence_id not in board.blackboard.evidence_ids:
                board.blackboard.evidence_ids.append(evidence_id)
        artifact = Artifact(
            run_id=board.run_id,
            task_id=task.task_id,
            artifact_type=ArtifactType.RAG_EVIDENCE_BUNDLE,
            producer_agent="context-service-v0.1",
            evidence_refs=unique_refs,
            content={
                "results": results,
                "warnings": [warning for result in results for warning in result["warnings"]],
                "evidence_count": len(unique_refs),
                "is_sufficient": bool(unique_refs),
                "retrieval_reason": "context_hole",
            },
            validation_status="valid" if unique_refs else "partial",
        )
        board.artifacts.append(artifact)
        board.append_event(
            EventType.ARTIFACT_CREATED,
            actor_type="context_service",
            actor_id="context-service-v0.1",
            task_id=task.task_id,
            artifact_id=artifact.artifact_id,
            payload={"artifact_type": artifact.artifact_type.value, "reason": "context_hole"},
        )
        return artifact


def _artifact_view(artifact: Artifact) -> ContextArtifactView:
    content = dict(artifact.content)
    if artifact.artifact_type == ArtifactType.USER_PROFILE_SNAPSHOT:
        content.pop("pseudonymous_user_id", None)
    return ContextArtifactView(
        artifact_id=artifact.artifact_id,
        artifact_type=artifact.artifact_type,
        content=content,
        evidence_refs=tuple(artifact.evidence_refs),
        validation_status=artifact.validation_status,
        review_status=artifact.review_status,
    )


def _source_ref(
    source_type: str,
    source_id: str,
    content: Any,
    classification: str,
    source_version: str | None = None,
) -> ContextSourceRef:
    return ContextSourceRef(
        source_type=source_type,
        source_id=source_id,
        source_version=source_version,
        content_hash=_hash(content),
        classification=classification,
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()
