"""SSE/API 之前的消息处理、PII、安全运行配置选择与内存 Trace 存储。"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from intake.blackboard import MatterBlackboard, SufficiencyConfig
from runtime.board_runtime import (
    AnalysisAgent,
    ResponseAgent,
    RetrievalAgent,
    ReviewAgent,
    SafetyAgent,
    TaskBoardRuntime,
    UnderstandingAgent,
    build_default_agents,
)
from safety.pii import PIIPolicy, PIIReviewer
from persistence.storage import (
    ConversationRepository,
    HistoryMessage,
    InMemoryConversationRepository,
    InMemoryUserProfileStore,
    UserProfile,
    UserProfileStore,
    InMemoryTraceReusePool,
    TraceReuseClaimItem,
    TraceReuseExample,
    TraceReusePool,
)
from persistence.trace_reuse_tools import TraceReuseSearchAdapter
from runtime.taskboard import (
    AgentRunBoard,
    AgentRunTrace,
    Artifact,
    ArtifactType,
    EventType,
    EventVisibility,
    CollaborationEvent,
    RunStatus,
)
from runtime.identifiers import new_id
from runtime.tools import ToolExecutor, ToolPermission, ToolRegistry
from runtime.model_provider import ModelGateway
from runtime.context import ContextService
from runtime.memory import MemoryService
from scenario_pack import RentalDepositScenarioPack, ScenarioPack


class TracePersistenceError(RuntimeError):
    """Trace 未可靠落盘；调用方不得交付本轮候选回复。"""


class RuntimeRegistry:
    def __init__(self) -> None:
        self._runtimes: dict[str, TaskBoardRuntime] = {}

    def register(self, profile: str, runtime: TaskBoardRuntime) -> None:
        if profile in self._runtimes:
            raise ValueError(f"runtime profile already registered: {profile}")
        self._runtimes[profile] = runtime

    def get(self, profile: str) -> TaskBoardRuntime:
        try:
            return self._runtimes[profile]
        except KeyError as exc:
            raise KeyError(f"unknown runtime profile: {profile}") from exc


@dataclass(slots=True)
class HarnessResult:
    board: AgentRunBoard

    @property
    def response(self) -> str:
        if not self.board.accepted_artifact_id:
            return "当前运行没有产生可采纳回复。"
        artifact = self.board.artifact(self.board.accepted_artifact_id)
        return str(artifact.content.get("response") or "当前运行没有产生可采纳回复。")


@dataclass(slots=True)
class PreparedRun:
    board: AgentRunBoard
    runtime: TaskBoardRuntime
    history: list[object]


class ConversationHarness:
    def __init__(
        self,
        registry: RuntimeRegistry,
        *,
        reviewer: PIIReviewer | None = None,
        default_profile: str = "taskboard-v0.1",
        profile_store: UserProfileStore | None = None,
        conversation_repository: ConversationRepository | None = None,
        memory_service: MemoryService | None = None,
        trace_reuse_pool: TraceReusePool | None = None,
    ) -> None:
        self.registry = registry
        self.reviewer = reviewer or PIIReviewer()
        self.default_profile = default_profile
        self.profile_store = profile_store or InMemoryUserProfileStore()
        self.conversation_repository = conversation_repository or InMemoryConversationRepository()
        self.memory_service = memory_service
        self.trace_reuse_pool = trace_reuse_pool or InMemoryTraceReusePool()
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self.run_store: dict[str, AgentRunBoard] = {}
        self.trace_store: dict[str, AgentRunTrace] = {}

    async def prepare(
        self,
        text: str,
        *,
        session_id: str | None = None,
        pseudonymous_user_id: str | None = None,
        runtime_profile: str | None = None,
        replay_of_run_id: str | None = None,
        event_sink: Callable[[CollaborationEvent], None] | None = None,
    ) -> PreparedRun:
        review = self.reviewer.review(text, policy=PIIPolicy.MASK)
        session_key = session_id or new_id("session")
        blackboard = await _maybe_await(self.conversation_repository.get_blackboard(session_key))
        if blackboard is None:
            blackboard = MatterBlackboard(session_id=session_key)
        board = AgentRunBoard(
            session_id=session_key,
            pseudonymous_user_id=pseudonymous_user_id,
            runtime_profile=runtime_profile or self.default_profile,
            sanitized_input=review.text,
            pii_status=review.status,
            blackboard=blackboard,
        )
        board.blackboard.message_ids.append(board.current_message_id)
        board._event_sink = event_sink
        board.append_event(
            EventType.RUN_CREATED,
            actor_type="harness",
            actor_id="conversation-harness",
            payload={"runtime_profile": board.runtime_profile},
            visibility=EventVisibility.ADMIN,
        )
        board.append_event(
            EventType.INPUT_SANITIZED,
            actor_type="harness",
            actor_id="pii-reviewer",
            payload={
                "pii_status": review.status.value,
                "detection_kinds": [item.kind for item in review.detections],
                "warnings": review.warnings,
            },
            visibility=EventVisibility.ADMIN,
        )
        if replay_of_run_id:
            board.append_event(
                EventType.REPLAY_STARTED,
                actor_type="harness",
                actor_id="conversation-harness",
                payload={"source_run_id": replay_of_run_id},
                visibility=EventVisibility.ADMIN,
            )
        await _maybe_await(self.conversation_repository.create_run(board))
        await _maybe_await(self.conversation_repository.append_history(
            HistoryMessage(
                session_id=session_key,
                run_id=board.run_id,
                role="user",
                content=board.sanitized_input,
                pii_status=board.pii_status,
            )
        ))
        runtime = self.registry.get(board.runtime_profile)
        root_task = runtime.create_root_task(board)
        stored_profile = None
        if pseudonymous_user_id:
            stored_profile = await _maybe_await(self.profile_store.get(pseudonymous_user_id))
            if stored_profile is None:
                stored_profile = await _maybe_await(self.profile_store.upsert(
                    UserProfile(pseudonymous_user_id=pseudonymous_user_id)
                ))
        profile_artifact = Artifact(
            run_id=board.run_id,
            task_id=root_task.task_id,
            artifact_type=ArtifactType.USER_PROFILE_SNAPSHOT,
            producer_agent="conversation-harness",
            content={
                "language": "zh-CN",
                "pseudonymous_user_id": pseudonymous_user_id,
                "jurisdiction": stored_profile.jurisdiction if stored_profile else None,
                "explanation_preference": stored_profile.explanation_preference if stored_profile else None,
                "consent_flags": stored_profile.consent_flags if stored_profile else {},
                "profile_version": stored_profile.version if stored_profile else None,
            },
            confidence=1.0,
            review_status="system_generated",
        )
        board.artifacts.append(profile_artifact)
        root_task.input_artifact_ids.append(profile_artifact.artifact_id)
        board.append_event(
            EventType.ARTIFACT_CREATED,
            actor_type="harness",
            actor_id="conversation-harness",
            task_id=root_task.task_id,
            artifact_id=profile_artifact.artifact_id,
            payload={"artifact_type": profile_artifact.artifact_type.value},
            visibility=EventVisibility.ADMIN,
        )
        history = await _maybe_await(
            self.conversation_repository.list_history(session_key, limit=6)
        )
        if self.memory_service is not None:
            self.memory_service.replace(session_key, history)
        return PreparedRun(board=board, runtime=runtime, history=list(history))

    async def finalize(self, prepared: PreparedRun) -> HarnessResult:
        board = prepared.board
        session_key = board.session_id or ""
        board.blackboard.advance_version()
        await _maybe_await(self.conversation_repository.save_blackboard(board.blackboard))
        trace = AgentRunTrace.from_board(board)
        try:
            await _maybe_await(self.conversation_repository.save_trace(trace))
        except Exception as exc:
            board.status = RunStatus.FAILED
            board.accepted_artifact_id = None
            raise TracePersistenceError("TRACE_PERSISTENCE_FAILED") from exc

        # 只有审计 Trace 已持久化后，才允许把回复发布到会话历史和调用方。
        self.run_store[board.run_id] = board
        self.trace_store[board.run_id] = trace
        for message in board.messages:
            await _maybe_await(self.conversation_repository.append_agent_message(message))
        if board.accepted_artifact_id:
            accepted = board.artifact(board.accepted_artifact_id)
            response = str(accepted.content.get("response") or "").strip()
            if response:
                await _maybe_await(self.conversation_repository.append_history(
                    HistoryMessage(
                        session_id=session_key,
                        run_id=board.run_id,
                        role="assistant",
                        content=response,
                        artifact_id=accepted.artifact_id,
                    )
                ))
                if self.memory_service is not None:
                    self.memory_service.write(
                        session_key, role="assistant", content=response,
                        message_id=accepted.artifact_id,
                    )
            if any(event.event_type == EventType.DELIVERY_ACCEPTED for event in board.events):
                example = self._trace_reuse_example(prepared, accepted)
                background = asyncio.create_task(
                    _save_trace_reuse_example(self.trace_reuse_pool, example)
                )
                self._background_tasks.add(background)
                background.add_done_callback(self._background_task_done)
        return HarnessResult(board=board)

    def _trace_reuse_example(self, prepared: PreparedRun, accepted: Artifact) -> TraceReuseExample:
        facts = {
            key: self.reviewer.review(value, policy=PIIPolicy.MASK).text
            for key, value in prepared.board.blackboard.confirmed_facts.items()
        }
        sections = accepted.content.get("sections") or {}
        claim_items = tuple(
            TraceReuseClaimItem(
                item_key=str(item["item_key"]),
                applicability=str(item["applicability"]),
                evidence_ids=tuple(str(value) for value in item.get("evidence_ids", [])),
            )
            for item in sections.get("amount_items", [])
            if isinstance(item, dict) and item.get("item_key") and item.get("applicability")
        )
        return TraceReuseExample(
            run_id=prepared.board.run_id,
            session_id=prepared.board.session_id or "anonymous",
            contributor_user_id=prepared.board.pseudonymous_user_id,
            scenario_id=prepared.runtime.context_service.scenario_id,
            confirmed_facts_summary=facts,
            claim_items=claim_items,
            action_template_condition_key=accepted.content.get("action_template_condition_key"),
            created_at=prepared.board.created_at,
        )

    def _background_task_done(self, task: asyncio.Task[Any]) -> None:
        self._background_tasks.discard(task)
        if not task.cancelled():
            task.exception()

    async def drain_background_tasks(self) -> None:
        if self._background_tasks:
            await asyncio.gather(*tuple(self._background_tasks), return_exceptions=True)

    async def delete_trace_reuse_for_user(self, pseudonymous_user_id: str) -> int:
        return int(await _maybe_await(
            self.trace_reuse_pool.delete_examples_by_user(pseudonymous_user_id)
        ))

    async def handle_async(
        self,
        text: str,
        *,
        session_id: str | None = None,
        pseudonymous_user_id: str | None = None,
        runtime_profile: str | None = None,
        replay_of_run_id: str | None = None,
        event_sink: Callable[[CollaborationEvent], None] | None = None,
    ) -> HarnessResult:
        prepared = await self.prepare(
            text,
            session_id=session_id,
            pseudonymous_user_id=pseudonymous_user_id,
            runtime_profile=runtime_profile,
            replay_of_run_id=replay_of_run_id,
            event_sink=event_sink,
        )
        await asyncio.to_thread(
            prepared.runtime.run,
            prepared.board,
            history=prepared.history,
            event_sink=event_sink,
        )
        return await self.finalize(prepared)

    def handle(self, text: str, **kwargs: Any) -> HarnessResult:
        """同步兼容入口；异步 API 必须调用 :meth:`handle_async`。"""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.handle_async(text, **kwargs))
        raise RuntimeError("handle() cannot run inside an event loop; await handle_async()")

    async def get_trace(self, run_id: str) -> AgentRunTrace | None:
        return await _maybe_await(self.conversation_repository.get_trace(run_id))


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def _save_trace_reuse_example(
    pool: TraceReusePool, example: TraceReuseExample
) -> None:
    await _maybe_await(pool.save_example(example))


def build_default_harness(
    tool_executor: ToolExecutor | None = None,
    model_gateway: ModelGateway | None = None,
    scenario_pack: ScenarioPack | None = None,
    sufficiency_config: SufficiencyConfig | None = None,
) -> ConversationHarness:
    pack = scenario_pack or RentalDepositScenarioPack()
    memory_service = MemoryService()
    trace_reuse_pool = InMemoryTraceReusePool()
    reuse_registry = ToolRegistry()
    reuse_registry.register(TraceReuseSearchAdapter(trace_reuse_pool))
    reuse_executor = ToolExecutor(
        reuse_registry,
        {ToolPermission.SEARCH_TRACE_EXAMPLES},
    )
    registry = RuntimeRegistry()
    registry.register(
        "taskboard-v0.1",
        TaskBoardRuntime(
            build_default_agents(
                tool_executor,
                model_gateway,
                pack,
                sufficiency_config,
                reuse_executor,
            ),
            context_service=ContextService(
                scenario_id=pack.scenario_id,
                memory_service=memory_service,
                tool_executor=tool_executor,
                scenario_pack=pack,
            ),
        ),
    )
    return ConversationHarness(
        registry,
        memory_service=memory_service,
        trace_reuse_pool=trace_reuse_pool,
    )
