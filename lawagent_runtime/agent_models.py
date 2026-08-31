"""六角色共用的结构化模型候选调用 seam。"""

from __future__ import annotations

from typing import Any, Protocol

from .context import AgentContextView
from .model_provider import ModelGateway, ModelProfile, ModelRequest
from .taskboard import AgentRunBoard, BoardTask, EventType, EventVisibility


class CandidateGenerator(Protocol):
    def generate(
        self,
        *,
        board: AgentRunBoard,
        task: BoardTask,
        context: AgentContextView,
        profile: ModelProfile,
        system_prompt: str,
        response_schema: dict[str, Any],
    ) -> dict[str, Any] | None: ...


class StructuredModelRunner:
    """模型仅返回候选；错误、预算与 Trace 由 Gateway/Runner 集中处理。"""

    def __init__(self, gateway: ModelGateway) -> None:
        self.gateway = gateway

    def generate(
        self,
        *,
        board: AgentRunBoard,
        task: BoardTask,
        context: AgentContextView,
        profile: ModelProfile,
        system_prompt: str,
        response_schema: dict[str, Any],
    ) -> dict[str, Any] | None:
        result = self.gateway.generate(
            ModelRequest(
                run_id=board.run_id,
                task_id=task.task_id,
                agent_id=task.claimed_by or context.role.value,
                profile=profile,
                system_prompt=system_prompt,
                user_prompt=task.objective,
                context=context.model_dump(mode="json", exclude={"source_refs"}),
                response_schema=response_schema,
            ),
            budget=board.model_budget,
            usage=board.model_usage,
        )
        if result.error is not None:
            board.append_event(
                EventType.MODEL_DEGRADED,
                actor_type="model_gateway",
                actor_id="model-gateway-v0.1",
                task_id=task.task_id,
                payload={
                    "profile": profile.value,
                    "error_code": result.error.code.value,
                    "retryable": result.error.retryable,
                    "safe_message": result.error.message,
                },
                visibility=EventVisibility.DEVELOPER,
            )
            return None
        response = result.response
        assert response is not None
        board.append_event(
            EventType.MODEL_CALLED,
            actor_type="model_gateway",
            actor_id=response.provider,
            task_id=task.task_id,
            payload={
                "profile": response.profile.value,
                "model": response.model,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cost_usd": response.cost_usd,
                "latency_ms": response.latency_ms,
            },
            visibility=EventVisibility.DEVELOPER,
        )
        return response.structured_output
