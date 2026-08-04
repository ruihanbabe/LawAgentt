from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from .messages import AgentRole
from .observations import Observation
from .state import RunState


class NodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    agent_role: AgentRole
    timeout_ms: int | None = Field(default=None, ge=1)
    max_retries: int = Field(default=0, ge=0)


class AgentNode(Protocol):
    config: NodeConfig

    def run(self, state: RunState) -> Observation:
        ...


class NodeRegistry:
    def __init__(self) -> None:
        self._nodes: dict[str, AgentNode] = {}

    def register(self, node: AgentNode) -> None:
        name = node.config.name
        if name in self._nodes:
            raise ValueError(f"node already registered: {name}")
        self._nodes[name] = node

    def get(self, name: str) -> AgentNode:
        try:
            return self._nodes[name]
        except KeyError as exc:
            raise KeyError(f"node is not registered: {name}") from exc

    def names(self) -> list[str]:
        return sorted(self._nodes)
