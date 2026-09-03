"""用户画像、会话消息和运行 Trace 的持久化端口。

本模块定义端口并提供内存适配器；Redis/PostgreSQL正式实现位于
``persistence_adapters.py``，由应用组装层注入Harness，领域Runtime不依赖数据库客户端。
"""

from __future__ import annotations

from collections.abc import Awaitable
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from runtime.messages import AgentMessage
from intake.blackboard import MatterBlackboard
from safety.pii import PIIStatus
from runtime.identifiers import new_id, utc_now
from runtime.taskboard import AgentRunBoard, AgentRunTrace


class UserProfile(BaseModel):
    """适合存入 Redis 的最小、可撤销用户画像。"""

    model_config = ConfigDict(extra="forbid")

    pseudonymous_user_id: str = Field(min_length=1)
    language: str = "zh-CN"
    jurisdiction: str | None = None
    explanation_preference: str | None = None
    confirmed_case_ids: list[str] = Field(default_factory=list)
    consent_flags: dict[str, bool] = Field(default_factory=dict)
    version: int = Field(default=1, ge=1)
    updated_at: datetime = Field(default_factory=utc_now)


class HistoryMessage(BaseModel):
    """适合存入 PostgreSQL 的脱敏用户/助手历史消息。"""

    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(default_factory=lambda: new_id("history"))
    session_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1)
    pii_status: PIIStatus = PIIStatus.CLEAN
    artifact_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class TraceReuseClaimItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    item_key: str = Field(min_length=1)
    applicability: Literal["applicable", "not_applicable", "uncertain"]
    evidence_ids: tuple[str, ...] = ()


class TraceReuseExample(BaseModel):
    """通过门禁的 Run 摘要；不含原始陈述且不具备 Evidence 身份。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    example_id: str = Field(default_factory=lambda: new_id("example"))
    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    contributor_user_id: str | None = None
    scenario_id: str = Field(min_length=1)
    confirmed_facts_summary: dict[str, str] = Field(default_factory=dict)
    claim_items: tuple[TraceReuseClaimItem, ...] = ()
    action_template_condition_key: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


@runtime_checkable
class TraceReusePool(Protocol):
    def save_example(self, example: TraceReuseExample) -> None | Awaitable[None]: ...

    def search_examples(
        self, scenario_id: str, facts: dict[str, str], *, limit: int = 5
    ) -> list[TraceReuseExample] | Awaitable[list[TraceReuseExample]]: ...

    def delete_examples_by_user(self, contributor_user_id: str) -> int | Awaitable[int]: ...


class InMemoryTraceReusePool:
    def __init__(self) -> None:
        self.examples: dict[str, TraceReuseExample] = {}

    def save_example(self, example: TraceReuseExample) -> None:
        self.examples[example.example_id] = example.model_copy(deep=True)

    def search_examples(
        self, scenario_id: str, facts: dict[str, str], *, limit: int = 5
    ) -> list[TraceReuseExample]:
        if limit < 1:
            return []
        query_pairs = set(facts.items())
        candidates = [item for item in self.examples.values() if item.scenario_id == scenario_id]
        candidates.sort(
            key=lambda item: (
                -len(query_pairs & set(item.confirmed_facts_summary.items())),
                -item.created_at.timestamp(),
                item.example_id,
            )
        )
        return [item.model_copy(deep=True) for item in candidates[:limit]]

    def delete_examples_by_user(self, contributor_user_id: str) -> int:
        selected = [
            key for key, item in self.examples.items()
            if item.contributor_user_id == contributor_user_id
        ]
        for key in selected:
            del self.examples[key]
        return len(selected)


@runtime_checkable
class UserProfileStore(Protocol):
    """Redis 适配器需要实现的端口。"""

    def get(self, pseudonymous_user_id: str) -> UserProfile | None | Awaitable[UserProfile | None]: ...

    def upsert(self, profile: UserProfile) -> UserProfile | Awaitable[UserProfile]: ...

    def delete(self, pseudonymous_user_id: str) -> bool | Awaitable[bool]: ...


@runtime_checkable
class ConversationRepository(Protocol):
    """PostgreSQL 适配器需要实现的会话、消息和 Trace 端口。"""

    def create_run(self, board: AgentRunBoard) -> None | Awaitable[None]: ...

    def get_blackboard(
        self, session_id: str
    ) -> MatterBlackboard | None | Awaitable[MatterBlackboard | None]: ...

    def save_blackboard(self, blackboard: MatterBlackboard) -> None | Awaitable[None]: ...

    def append_history(self, message: HistoryMessage) -> None | Awaitable[None]: ...

    def append_agent_message(self, message: AgentMessage) -> None | Awaitable[None]: ...

    def save_trace(self, trace: AgentRunTrace) -> None | Awaitable[None]: ...

    def list_history(
        self, session_id: str, *, limit: int = 20
    ) -> list[HistoryMessage] | Awaitable[list[HistoryMessage]]: ...

    def get_trace(
        self, run_id: str
    ) -> AgentRunTrace | None | Awaitable[AgentRunTrace | None]: ...


class InMemoryUserProfileStore:
    """开发期 Redis 替身；读写均深拷贝，避免共享可变对象。"""

    def __init__(self) -> None:
        self._profiles: dict[str, UserProfile] = {}

    def get(self, pseudonymous_user_id: str) -> UserProfile | None:
        profile = self._profiles.get(pseudonymous_user_id)
        return profile.model_copy(deep=True) if profile else None

    def upsert(self, profile: UserProfile) -> UserProfile:
        current = self._profiles.get(profile.pseudonymous_user_id)
        stored = profile.model_copy(
            update={
                "version": (current.version + 1) if current else profile.version,
                "updated_at": utc_now(),
            },
            deep=True,
        )
        self._profiles[stored.pseudonymous_user_id] = stored
        return stored.model_copy(deep=True)

    def delete(self, pseudonymous_user_id: str) -> bool:
        return self._profiles.pop(pseudonymous_user_id, None) is not None


class InMemoryConversationRepository:
    """开发期 PostgreSQL 替身。"""

    def __init__(self) -> None:
        self.runs: dict[str, AgentRunBoard] = {}
        self.history: list[HistoryMessage] = []
        self.agent_messages: list[AgentMessage] = []
        self.traces: dict[str, AgentRunTrace] = {}
        self.blackboards: dict[str, MatterBlackboard] = {}

    def create_run(self, board: AgentRunBoard) -> None:
        if board.run_id in self.runs:
            raise ValueError(f"run already exists: {board.run_id}")
        self.runs[board.run_id] = board.model_copy(deep=True)

    def get_blackboard(self, session_id: str) -> MatterBlackboard | None:
        blackboard = self.blackboards.get(session_id)
        return blackboard.model_copy(deep=True) if blackboard else None

    def save_blackboard(self, blackboard: MatterBlackboard) -> None:
        self.blackboards[blackboard.session_id] = blackboard.model_copy(deep=True)

    def append_history(self, message: HistoryMessage) -> None:
        self.history.append(message.model_copy(deep=True))

    def append_agent_message(self, message: AgentMessage) -> None:
        self.agent_messages.append(message.model_copy(deep=True))

    def save_trace(self, trace: AgentRunTrace) -> None:
        self.traces[trace.run_id] = trace.model_copy(deep=True)

    def list_history(self, session_id: str, *, limit: int = 20) -> list[HistoryMessage]:
        if limit < 1:
            return []
        matches = [item for item in self.history if item.session_id == session_id]
        return [item.model_copy(deep=True) for item in matches[-limit:]]

    def get_trace(self, run_id: str) -> AgentRunTrace | None:
        trace = self.traces.get(run_id)
        return trace.model_copy(deep=True) if trace else None


class FaultInjectingConversationRepository:
    """测试/开发环境的一次性故障注入包装器，不接受任意代码执行。"""

    ALLOWED_OPERATIONS = frozenset({
        "create_run", "get_blackboard", "save_blackboard", "append_history",
        "append_agent_message", "save_trace", "list_history", "get_trace",
    })

    def __init__(self, inner: ConversationRepository) -> None:
        self.inner = inner
        self._remaining: dict[str, int] = {}

    def inject(self, operation: str, *, count: int = 1) -> None:
        if operation not in self.ALLOWED_OPERATIONS:
            raise ValueError(f"unsupported fault operation: {operation}")
        if count < 1 or count > 100:
            raise ValueError("fault count must be between 1 and 100")
        self._remaining[operation] = count

    def clear(self) -> None:
        self._remaining.clear()

    def _before(self, operation: str) -> None:
        remaining = self._remaining.get(operation, 0)
        if remaining:
            if remaining == 1:
                self._remaining.pop(operation, None)
            else:
                self._remaining[operation] = remaining - 1
            raise RuntimeError(f"injected storage fault: {operation}")

    def create_run(self, board: AgentRunBoard) -> None:
        self._before("create_run")
        self.inner.create_run(board)

    def get_blackboard(self, session_id: str) -> MatterBlackboard | None:
        self._before("get_blackboard")
        return self.inner.get_blackboard(session_id)

    def save_blackboard(self, blackboard: MatterBlackboard) -> None:
        self._before("save_blackboard")
        self.inner.save_blackboard(blackboard)

    def append_history(self, message: HistoryMessage) -> None:
        self._before("append_history")
        self.inner.append_history(message)

    def append_agent_message(self, message: AgentMessage) -> None:
        self._before("append_agent_message")
        self.inner.append_agent_message(message)

    def save_trace(self, trace: AgentRunTrace) -> None:
        self._before("save_trace")
        self.inner.save_trace(trace)

    def list_history(self, session_id: str, *, limit: int = 20) -> list[HistoryMessage]:
        self._before("list_history")
        return self.inner.list_history(session_id, limit=limit)

    def get_trace(self, run_id: str) -> AgentRunTrace | None:
        self._before("get_trace")
        return self.inner.get_trace(run_id)
