from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .messages import AgentMessage, AgentRole
from .state import (
    EvidenceGap,
    EvidenceItem,
    FactItem,
    FailureItem,
    FinalDecision,
    LegalIssue,
    RetrievalAttempt,
    RunState,
    Stage,
    StopReason,
    ToolIntent,
    new_id,
    utc_now,
)


class PatchOperation(StrEnum):
    APPEND = "append"
    SET_CONTROL = "set_control"


class PatchTarget(StrEnum):
    FACTS = "facts"
    LEGAL_ISSUES = "legal_issues"
    TOOL_INTENTS = "tool_intents"
    RETRIEVAL_ATTEMPTS = "retrieval_attempts"
    EVIDENCE_ITEMS = "evidence_items"
    EVIDENCE_GAPS = "evidence_gaps"
    FAILURES = "failures"
    CONTROL = "control"


class PatchError(ValueError):
    pass


class StatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patch_id: str = Field(default_factory=lambda: new_id("patch"))
    run_id: str = Field(min_length=1)
    author_role: AgentRole
    target: PatchTarget
    operation: PatchOperation
    payload: dict[str, Any]
    reason: str = Field(min_length=1)
    source_message_id: str | None = None
    created_at: object = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def operation_matches_target(self) -> StatePatch:
        if self.operation == PatchOperation.SET_CONTROL and self.target != PatchTarget.CONTROL:
            raise ValueError("set_control operation can only target control")
        if self.operation == PatchOperation.APPEND and self.target == PatchTarget.CONTROL:
            raise ValueError("control target requires set_control operation")
        return self

    @classmethod
    def from_message(
        cls,
        message: AgentMessage,
        *,
        target: PatchTarget,
        operation: PatchOperation,
        payload: dict[str, Any],
        reason: str,
    ) -> StatePatch:
        return cls(
            run_id=message.run_id,
            author_role=message.from_role,
            target=target,
            operation=operation,
            payload=payload,
            reason=reason,
            source_message_id=message.message_id,
        )


def apply_state_patch(state: RunState, patch: StatePatch) -> None:
    if state.run_id != patch.run_id:
        raise PatchError("patch run_id does not match state run_id")
    if patch.operation == PatchOperation.APPEND:
        item = _build_append_item(patch)
        getattr(state, patch.target.value).append(item)
    elif patch.operation == PatchOperation.SET_CONTROL:
        _apply_control_patch(state, patch)
    else:
        raise PatchError(f"unsupported patch operation: {patch.operation}")
    state.add_trace(
        "apply_state_patch",
        input_summary=f"{patch.author_role.value}:{patch.operation.value}:{patch.target.value}",
        output_summary=patch.reason,
        route_reason=f"patch_id={patch.patch_id}",
    )
    state.updated_at = utc_now()


def _build_append_item(patch: StatePatch) -> BaseModel:
    model_by_target: dict[PatchTarget, type[BaseModel]] = {
        PatchTarget.FACTS: FactItem,
        PatchTarget.LEGAL_ISSUES: LegalIssue,
        PatchTarget.TOOL_INTENTS: ToolIntent,
        PatchTarget.RETRIEVAL_ATTEMPTS: RetrievalAttempt,
        PatchTarget.EVIDENCE_ITEMS: EvidenceItem,
        PatchTarget.EVIDENCE_GAPS: EvidenceGap,
        PatchTarget.FAILURES: FailureItem,
    }
    model = model_by_target.get(patch.target)
    if model is None:
        raise PatchError(f"append is not supported for target: {patch.target}")
    return model.model_validate(patch.payload)


def _apply_control_patch(state: RunState, patch: StatePatch) -> None:
    allowed = {"stage", "next_node", "route_reason", "stop_reason", "final_decision"}
    unknown = set(patch.payload) - allowed
    if unknown:
        raise PatchError(f"unsupported control fields: {sorted(unknown)}")
    if "stage" in patch.payload:
        state.stage = Stage(patch.payload["stage"])
    if "next_node" in patch.payload:
        state.next_node = patch.payload["next_node"]
    if "route_reason" in patch.payload:
        state.route_reason = patch.payload["route_reason"]
    if "stop_reason" in patch.payload and patch.payload["stop_reason"] is not None:
        state.stop_reason = StopReason(patch.payload["stop_reason"])
    if "final_decision" in patch.payload and patch.payload["final_decision"] is not None:
        state.final_decision = FinalDecision(patch.payload["final_decision"])
