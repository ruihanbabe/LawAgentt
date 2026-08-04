from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from .messages import AgentRole
from .nodes import NodeRegistry
from .observations import Observation, ObservationStatus
from .patches import PatchOperation, PatchTarget, StatePatch
from .permissions import PermissionError, apply_authorized_patch
from .router import DefaultRouter, RouteDecision
from .state import FailureItem, FinalDecision, RunState, Stage, StopReason


class RuntimeError(ValueError):
    pass


@dataclass(slots=True)
class RuntimeResult:
    state: RunState
    observations: list[Observation]


class AgentRuntime:
    def __init__(self, registry: NodeRegistry, router: DefaultRouter | None = None) -> None:
        self.registry = registry
        self.router = router or DefaultRouter()

    def run(self, state: RunState) -> RuntimeResult:
        observations: list[Observation] = []
        decision = self.router.initial(state)
        self._apply_route_decision(state, decision)
        while state.stage not in {Stage.COMPLETED, Stage.FAILED}:
            if state.budget.exhausted():
                decision = self.router.route(state)
                self._apply_route_decision(state, decision)
                break
            node_name = state.next_node
            if not node_name:
                decision = self.router.route(state)
                self._apply_route_decision(state, decision)
                if decision.terminal:
                    break
                node_name = state.next_node
            observation = self._run_node(state, node_name)
            observations.append(observation)
            self._record_node_trace(state, observation)
            if observation.status == ObservationStatus.FAILED:
                self._record_failure(state, observation)
            else:
                try:
                    for patch in observation.state_patches:
                        apply_authorized_patch(state, patch)
                except PermissionError as exc:
                    failed = Observation(
                        node_name=observation.node_name,
                        agent_role=AgentRole.ORCHESTRATOR,
                        status=ObservationStatus.FAILED,
                        warnings=[str(exc)],
                        error_code="permission_denied",
                    )
                    observations.append(failed)
                    self._record_failure(state, failed)
                    self._apply_route_decision(
                        state,
                        RouteDecision(
                            stage=Stage.FAILED,
                            reason="permission_denied",
                            stop_reason=StopReason.TOOL_FAILURE,
                            final_decision=FinalDecision.FAILED,
                        ),
                    )
                    break
            state.budget.step_count += 1
            decision = self.router.route(state, observation)
            self._apply_route_decision(state, decision)
        return RuntimeResult(state=state, observations=observations)

    def _run_node(self, state: RunState, node_name: str) -> Observation:
        started = perf_counter()
        try:
            node = self.registry.get(node_name)
            observation = node.run(state)
        except Exception as exc:
            return Observation(
                node_name=node_name,
                agent_role=AgentRole.ORCHESTRATOR,
                status=ObservationStatus.FAILED,
                warnings=[str(exc)],
                error_code="node_execution_error",
                latency_ms=int((perf_counter() - started) * 1000),
            )
        if observation.node_name != node_name:
            raise RuntimeError(f"node returned mismatched observation name: {observation.node_name} != {node_name}")
        if observation.agent_role != node.config.agent_role:
            raise RuntimeError(f"node returned mismatched agent role: {observation.agent_role} != {node.config.agent_role}")
        if observation.latency_ms is None:
            observation.latency_ms = int((perf_counter() - started) * 1000)
        return observation

    def _record_node_trace(self, state: RunState, observation: Observation) -> None:
        state.add_trace(
            observation.node_name,
            input_summary=f"stage={state.stage.value}",
            output_summary=observation.status.value,
            route_reason=state.route_reason,
            latency_ms=observation.latency_ms,
            error_code=observation.error_code,
        )

    def _record_failure(self, state: RunState, observation: Observation) -> None:
        state.failures.append(
            FailureItem(
                node_name=observation.node_name,
                error_code=observation.error_code or "node_failed",
                message="; ".join(observation.warnings) or "node failed",
                retryable=False,
            )
        )

    def _apply_route_decision(self, state: RunState, decision: RouteDecision) -> None:
        payload = {
            "stage": decision.stage.value,
            "next_node": decision.next_node,
            "route_reason": decision.reason,
            "stop_reason": decision.stop_reason.value if decision.stop_reason else None,
            "final_decision": decision.final_decision.value if decision.final_decision else None,
        }
        patch = StatePatch(
            run_id=state.run_id,
            author_role=AgentRole.ORCHESTRATOR,
            target=PatchTarget.CONTROL,
            operation=PatchOperation.SET_CONTROL,
            payload=payload,
            reason=decision.reason,
        )
        apply_authorized_patch(state, patch)
