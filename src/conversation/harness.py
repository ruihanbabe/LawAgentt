"""SSE/API 之前的消息处理、PII、安全运行配置选择与内存 Trace 存储。"""

from __future__ import annotations

from dataclasses import dataclass

from intake.blackboard import MatterBlackboard
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
)
from runtime.taskboard import (
    AgentRunBoard,
    AgentRunTrace,
    Artifact,
    ArtifactType,
    EventType,
    EventVisibility,
    RunStatus,
)
from runtime.identifiers import new_id
from runtime.tools import ToolExecutor
from runtime.model_provider import ModelGateway


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


class ConversationHarness:
    def __init__(
        self,
        registry: RuntimeRegistry,
        *,
        reviewer: PIIReviewer | None = None,
        default_profile: str = "taskboard-v0.1",
        profile_store: UserProfileStore | None = None,
        conversation_repository: ConversationRepository | None = None,
    ) -> None:
        self.registry = registry
        self.reviewer = reviewer or PIIReviewer()
        self.default_profile = default_profile
        self.profile_store = profile_store or InMemoryUserProfileStore()
        self.conversation_repository = conversation_repository or InMemoryConversationRepository()
        self.run_store: dict[str, AgentRunBoard] = {}
        self.trace_store: dict[str, AgentRunTrace] = {}

    def handle(
        self,
        text: str,
        *,
        session_id: str | None = None,
        pseudonymous_user_id: str | None = None,
        runtime_profile: str | None = None,
        replay_of_run_id: str | None = None,
    ) -> HarnessResult:
        review = self.reviewer.review(text, policy=PIIPolicy.MASK)
        session_key = session_id or new_id("session")
        blackboard = self.conversation_repository.get_blackboard(session_key)
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
        self.conversation_repository.create_run(board)
        self.conversation_repository.append_history(
            HistoryMessage(
                session_id=session_key,
                run_id=board.run_id,
                role="user",
                content=board.sanitized_input,
                pii_status=board.pii_status,
            )
        )
        runtime = self.registry.get(board.runtime_profile)
        root_task = runtime.create_root_task(board)
        stored_profile = None
        if pseudonymous_user_id:
            stored_profile = self.profile_store.get(pseudonymous_user_id)
            if stored_profile is None:
                stored_profile = self.profile_store.upsert(
                    UserProfile(pseudonymous_user_id=pseudonymous_user_id)
                )
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
        runtime.run(
            board,
            history=self.conversation_repository.list_history(session_key, limit=6),
        )
        board.blackboard.advance_version()
        self.conversation_repository.save_blackboard(board.blackboard)
        trace = AgentRunTrace.from_board(board)
        try:
            self.conversation_repository.save_trace(trace)
        except Exception as exc:
            board.status = RunStatus.FAILED
            board.accepted_artifact_id = None
            raise TracePersistenceError("TRACE_PERSISTENCE_FAILED") from exc

        # 只有审计 Trace 已持久化后，才允许把回复发布到会话历史和调用方。
        self.run_store[board.run_id] = board
        self.trace_store[board.run_id] = trace
        for message in board.messages:
            self.conversation_repository.append_agent_message(message)
        if board.accepted_artifact_id:
            accepted = board.artifact(board.accepted_artifact_id)
            response = str(accepted.content.get("response") or "").strip()
            if response:
                self.conversation_repository.append_history(
                    HistoryMessage(
                        session_id=session_key,
                        run_id=board.run_id,
                        role="assistant",
                        content=response,
                        artifact_id=accepted.artifact_id,
                    )
                )
        return HarnessResult(board=board)


def build_default_harness(
    tool_executor: ToolExecutor | None = None,
    model_gateway: ModelGateway | None = None,
) -> ConversationHarness:
    registry = RuntimeRegistry()
    registry.register(
        "taskboard-v0.1",
        TaskBoardRuntime(build_default_agents(tool_executor, model_gateway)),
    )
    return ConversationHarness(registry)
