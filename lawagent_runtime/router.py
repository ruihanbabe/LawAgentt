from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .observations import Observation, ObservationStatus
from .state import FinalDecision, IssueStatus, RunState, Stage, StopReason


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    next_node: str | None = None
    stage: Stage
    reason: str = Field(min_length=1)
    stop_reason: StopReason | None = None
    final_decision: FinalDecision | None = None

    @property
    def terminal(self) -> bool:
        return self.final_decision is not None


class DefaultRouter:
    def __init__(
        self,
        *,
        intake_node: str = "intake",
        plan_node: str = "plan",
        retrieve_node: str = "retrieve",
        refine_node: str = "refine",
        clarify_node: str = "clarify",
        answer_node: str = "answer",
        abstain_node: str = "abstain",
    ) -> None:
        self.intake_node = intake_node
        self.plan_node = plan_node
        self.retrieve_node = retrieve_node
        self.refine_node = refine_node
        self.clarify_node = clarify_node
        self.answer_node = answer_node
        self.abstain_node = abstain_node

    def initial(self, state: RunState) -> RouteDecision:
        if state.next_node:
            return RouteDecision(next_node=state.next_node, stage=state.stage, reason="state_next_node")
        return RouteDecision(next_node=self.intake_node, stage=Stage.UNDERSTANDING, reason="start_with_intake")

    def route(self, state: RunState, observation: Observation | None = None) -> RouteDecision:
        if state.stage in {Stage.COMPLETED, Stage.FAILED}:
            return RouteDecision(
                stage=state.stage,
                reason="already_terminal",
                stop_reason=state.stop_reason,
                final_decision=state.final_decision or FinalDecision.FAILED,
            )
        if observation and observation.status == ObservationStatus.FAILED:
            return RouteDecision(
                stage=Stage.FAILED,
                reason=f"node_failed:{observation.node_name}",
                stop_reason=StopReason.TOOL_FAILURE,
                final_decision=FinalDecision.FAILED,
            )
        if state.budget.exhausted():
            return self._budget_exhausted_decision(state)
        if observation and observation.node_name == self.answer_node:
            decision = FinalDecision.SUPPORTED_ANSWER if state.evidence_items else FinalDecision.LIMITED_ANSWER
            return RouteDecision(
                stage=Stage.COMPLETED,
                reason="answer_node_completed",
                stop_reason=StopReason.EVIDENCE_SUFFICIENT,
                final_decision=decision,
            )
        if observation and observation.node_name == self.clarify_node:
            return RouteDecision(
                stage=Stage.COMPLETED,
                reason="clarification_delivered",
                stop_reason=StopReason.MISSING_CRITICAL_FACTS,
                final_decision=FinalDecision.CLARIFICATION_NEEDED,
            )
        if observation and observation.node_name == self.abstain_node:
            return RouteDecision(
                stage=Stage.COMPLETED,
                reason="abstention_delivered",
                stop_reason=state.stop_reason or StopReason.RISK_TOO_HIGH,
                final_decision=FinalDecision.CONSTRUCTIVE_ABSTENTION,
            )
        if state.missing_critical_facts:
            return RouteDecision(next_node=self.clarify_node, stage=Stage.CLARIFYING, reason="missing_critical_facts")
        if not state.legal_issues:
            return RouteDecision(next_node=self.plan_node, stage=Stage.PLANNING, reason="no_legal_issues")
        if self._all_issues_supported(state):
            return RouteDecision(next_node=self.answer_node, stage=Stage.ANSWERING, reason="all_issues_supported")
        if state.open_gaps:
            if state.budget.retrieval_exhausted():
                return RouteDecision(next_node=self.answer_node, stage=Stage.ANSWERING, reason="retrieval_budget_exhausted")
            return RouteDecision(next_node=self.refine_node, stage=Stage.REFINING, reason="open_evidence_gaps")
        if not state.evidence_items:
            return RouteDecision(next_node=self.retrieve_node, stage=Stage.RETRIEVING, reason="no_evidence")
        return RouteDecision(next_node=self.answer_node, stage=Stage.ANSWERING, reason="evidence_available")

    def _budget_exhausted_decision(self, state: RunState) -> RouteDecision:
        if state.evidence_items:
            return RouteDecision(
                stage=Stage.COMPLETED,
                reason="budget_exhausted_with_evidence",
                stop_reason=StopReason.BUDGET_EXHAUSTED,
                final_decision=FinalDecision.LIMITED_ANSWER,
            )
        return RouteDecision(
            stage=Stage.COMPLETED,
            reason="budget_exhausted_without_evidence",
            stop_reason=StopReason.BUDGET_EXHAUSTED,
            final_decision=FinalDecision.CONSTRUCTIVE_ABSTENTION,
        )

    def _all_issues_supported(self, state: RunState) -> bool:
        if not state.legal_issues:
            return False
        return all(issue.status == IssueStatus.SUPPORTED for issue in state.legal_issues)
