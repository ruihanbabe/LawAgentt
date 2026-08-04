from __future__ import annotations

from dataclasses import dataclass

from .messages import AgentRole
from .patches import PatchOperation, PatchTarget, StatePatch, apply_state_patch
from .state import FactStatus, RunState


class PermissionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PatchPermission:
    operation: PatchOperation
    target: PatchTarget


ROLE_PERMISSIONS: dict[AgentRole, set[PatchPermission]] = {
    AgentRole.INTAKE: {
        PatchPermission(PatchOperation.APPEND, PatchTarget.FACTS),
        PatchPermission(PatchOperation.APPEND, PatchTarget.LEGAL_ISSUES),
        PatchPermission(PatchOperation.APPEND, PatchTarget.EVIDENCE_GAPS),
    },
    AgentRole.RETRIEVAL: {
        PatchPermission(PatchOperation.APPEND, PatchTarget.TOOL_INTENTS),
        PatchPermission(PatchOperation.APPEND, PatchTarget.RETRIEVAL_ATTEMPTS),
        PatchPermission(PatchOperation.APPEND, PatchTarget.EVIDENCE_ITEMS),
        PatchPermission(PatchOperation.APPEND, PatchTarget.EVIDENCE_GAPS),
    },
    AgentRole.ANALYSIS: {
        PatchPermission(PatchOperation.APPEND, PatchTarget.LEGAL_ISSUES),
        PatchPermission(PatchOperation.APPEND, PatchTarget.EVIDENCE_GAPS),
    },
    AgentRole.DRAFTING: {
        PatchPermission(PatchOperation.APPEND, PatchTarget.EVIDENCE_GAPS),
    },
    AgentRole.REVIEW: {
        PatchPermission(PatchOperation.APPEND, PatchTarget.EVIDENCE_GAPS),
        PatchPermission(PatchOperation.APPEND, PatchTarget.FAILURES),
    },
    AgentRole.ORCHESTRATOR: {
        PatchPermission(PatchOperation.APPEND, PatchTarget.FAILURES),
        PatchPermission(PatchOperation.SET_CONTROL, PatchTarget.CONTROL),
    },
    AgentRole.HUMAN: set(),
    AgentRole.SYSTEM: {
        PatchPermission(PatchOperation.APPEND, PatchTarget.FAILURES),
    },
}


def assert_patch_allowed(patch: StatePatch) -> None:
    permission = PatchPermission(patch.operation, patch.target)
    if permission not in ROLE_PERMISSIONS.get(patch.author_role, set()):
        raise PermissionError(f"{patch.author_role.value} cannot {patch.operation.value} {patch.target.value}")
    if patch.author_role != AgentRole.INTAKE and patch.target == PatchTarget.FACTS:
        raise PermissionError("only intake can append facts")
    if patch.target == PatchTarget.FACTS:
        status = patch.payload.get("status")
        if status in {FactStatus.USER_CONFIRMED.value, FactStatus.DOCUMENT_SUPPORTED.value}:
            raise PermissionError("facts cannot be confirmed by agent patch in v0")


def apply_authorized_patch(state: RunState, patch: StatePatch) -> None:
    assert_patch_allowed(patch)
    apply_state_patch(state, patch)
