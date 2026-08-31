from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .messages import AgentMessage, AgentRole, MessageType
from .nodes import NodeConfig
from .observations import Observation, ObservationStatus
from .state import RunState, ToolIntent, ToolIntentStatus
from .tools import ToolExecutor, ToolResult, ToolResultStatus, tool_result_to_state_patches


@dataclass(slots=True)
class RetrievalToolNode:
    executor: ToolExecutor
    name: str = "retrieve"

    @property
    def config(self) -> NodeConfig:
        return NodeConfig(name=self.name, agent_role=AgentRole.RETRIEVAL)

    def run(self, state: RunState) -> Observation:
        intent = _next_tool_intent(state)
        if intent is None:
            return Observation(
                node_name=self.name,
                agent_role=AgentRole.RETRIEVAL,
                status=ObservationStatus.SKIPPED,
                warnings=["no_pending_tool_intent"],
            )
        arguments = _arguments_from_intent(intent)
        result = self.executor.execute(intent.tool_name, arguments)
        patches = tool_result_to_state_patches(
            result,
            run_id=state.run_id,
            intent_id=intent.intent_id,
            issue_id=intent.issue_id,
        )
        message = AgentMessage(
            run_id=state.run_id,
            case_id=state.case_id,
            from_role=AgentRole.RETRIEVAL,
            to_role=AgentRole.ORCHESTRATOR,
            message_type=MessageType.RETRIEVAL_RESULT,
            payload={
                "intent_id": intent.intent_id,
                "tool_name": result.tool_name,
                "status": result.status.value,
                "result_count": len(result.items),
                "trace_id": result.trace_id,
            },
            warnings=result.warnings,
        )
        return Observation(
            node_name=self.name,
            agent_role=AgentRole.RETRIEVAL,
            status=_observation_status(result),
            message=message,
            state_patches=patches,
            warnings=result.warnings,
            error_code=_tool_error_code(result),
            latency_ms=result.latency_ms,
        )


def _next_tool_intent(state: RunState) -> ToolIntent | None:
    runnable = [
        intent for intent in state.tool_intents
        if intent.status in {ToolIntentStatus.PENDING, ToolIntentStatus.APPROVED}
    ]
    if not runnable:
        return None
    return sorted(runnable, key=lambda item: (item.priority, item.intent_id))[0]


def _arguments_from_intent(intent: ToolIntent) -> dict[str, Any]:
    arguments = dict(intent.filters_as_slots)
    if "query" not in arguments or not str(arguments.get("query") or "").strip():
        query = " ".join(intent.query_terms).strip() or intent.objective
        arguments["query"] = query
    return arguments


def _observation_status(result: ToolResult) -> ObservationStatus:
    if result.status == ToolResultStatus.SUCCESS:
        return ObservationStatus.SUCCESS
    if result.status == ToolResultStatus.EMPTY:
        return ObservationStatus.EMPTY
    if result.status in {ToolResultStatus.PARTIAL, ToolResultStatus.BLOCKED, ToolResultStatus.FAILED}:
        return ObservationStatus.PARTIAL
    return ObservationStatus.FAILED


def _tool_error_code(result: ToolResult) -> str | None:
    value = result.metadata.get("error_code")
    if isinstance(value, str):
        return value
    return None
