"""Scheduler 共享协议与确定性循环、转派及预算护栏。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from runtime.identifiers import new_id, utc_now
from runtime.taskboard import AgentRunBoard, BoardTask, EventType, TaskStatus
from safety.pii import PIIReviewer


class EscalationReasonCode(StrEnum):
    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"
    PERMISSION_MISMATCH = "PERMISSION_MISMATCH"
    CONTEXT_INSUFFICIENT = "CONTEXT_INSUFFICIENT"
    DEPENDENCY_BLOCKED = "DEPENDENCY_BLOCKED"
    POLICY_CONFLICT = "POLICY_CONFLICT"
    BUDGET_AT_RISK = "BUDGET_AT_RISK"
    OTHER = "OTHER"


class EscalationRequest(BaseModel):
    """只描述升级原因；刻意不包含目标角色或调度指令。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(default_factory=lambda: new_id("escalation"))
    task_id: str = Field(min_length=1)
    board_id: str = Field(min_length=1)
    origin_agent: str = Field(min_length=1)
    reason_code: EscalationReasonCode
    reason_detail: str = Field(min_length=1)
    related_artifact_ids: list[str] = Field(default_factory=list)
    attempted_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)


class TaskIntent(BaseModel):
    """描述所需能力，不指定具体 Agent 实例。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent_id: str = Field(default_factory=lambda: new_id("intent"))
    board_id: str = Field(min_length=1)
    required_capability: str = Field(min_length=1)
    priority: int = 0
    context_refs: list[str] = Field(default_factory=list)
    budget_hint: int | None = Field(default=None, ge=1)


class LoopReason(StrEnum):
    REPEATED_ACTION = "repeated_action"
    NO_PROGRESS = "no_progress"
    SHORT_CYCLE = "short_cycle"
    REPEATED_ERROR = "repeated_error"


class ActionObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    made_progress: bool
    error_code: str | None = None


class LoopDetection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    detected: bool = False
    reason: LoopReason | None = None
    fingerprint: str


_VOLATILE_KEYS = frozenset({
    "request_id", "run_id", "task_id", "board_id", "intent_id", "event_id",
    "artifact_id", "created_at", "updated_at", "timestamp", "random_id",
})
_ISO_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:[^\s]+")


def action_fingerprint(action: Mapping[str, Any]) -> str:
    """对去 PII、去易变 ID/时间且稳定排序后的动作计算 SHA256。"""

    reviewer = PIIReviewer()

    def normalize(value: Any, key: str | None = None) -> Any:
        if key in _VOLATILE_KEYS:
            return None
        if isinstance(value, Mapping):
            return {
                str(item_key): normalized
                for item_key in sorted(value, key=str)
                if (normalized := normalize(value[item_key], str(item_key))) is not None
            }
        if isinstance(value, (list, tuple)):
            return [normalize(item) for item in value]
        if isinstance(value, str):
            return reviewer.review(_ISO_TIMESTAMP.sub("[时间]", value)).text
        if isinstance(value, (bool, int, float)) or value is None:
            return value
        return str(value)

    payload = json.dumps(normalize(action), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LoopGuard:
    """阈值为 D18 指定的初始草案值，尚待真实负载校准。"""

    def __init__(self, window_size: int = 5, threshold: int = 3) -> None:
        self.window_size = window_size
        self.threshold = threshold
        self._history: list[ActionObservation] = []

    @property
    def history(self) -> tuple[ActionObservation, ...]:
        return tuple(self._history)

    def observe(
        self,
        action: Mapping[str, Any],
        *,
        made_progress: bool,
        error_code: str | None = None,
    ) -> LoopDetection:
        fingerprint = action_fingerprint(action)
        self._history.append(ActionObservation(
            fingerprint=fingerprint,
            made_progress=made_progress,
            error_code=error_code,
        ))
        recent = self._history[-self.window_size:]
        last = recent[-self.threshold:]
        if len(last) == self.threshold and len({item.fingerprint for item in last}) == 1:
            return LoopDetection(detected=True, reason=LoopReason.REPEATED_ACTION, fingerprint=fingerprint)
        if len(last) == self.threshold and all(not item.made_progress for item in last):
            return LoopDetection(detected=True, reason=LoopReason.NO_PROGRESS, fingerprint=fingerprint)
        if len(recent) >= 4 and recent[-1].fingerprint == recent[-3].fingerprint \
                and recent[-2].fingerprint == recent[-4].fingerprint:
            return LoopDetection(detected=True, reason=LoopReason.SHORT_CYCLE, fingerprint=fingerprint)
        if len(last) == self.threshold and error_code is not None \
                and all(item.error_code == error_code for item in last):
            return LoopDetection(detected=True, reason=LoopReason.REPEATED_ERROR, fingerprint=fingerprint)
        return LoopDetection(fingerprint=fingerprint)


class SchedulingBudget(BaseModel):
    """Node/Task/Run 三层只增不减的步数账本。"""

    model_config = ConfigDict(extra="forbid")

    max_node_steps: int = Field(default=3, ge=1)
    max_task_steps: int = Field(default=8, ge=1)
    max_run_steps: int = Field(default=32, ge=1)
    node_steps: dict[str, int] = Field(default_factory=dict)
    task_steps: dict[str, int] = Field(default_factory=dict)
    run_steps: int = Field(default=0, ge=0)

    def consume(self, *, node_id: str, task_id: str, amount: int = 1) -> bool:
        if amount < 1:
            raise ValueError("budget consumption must be positive")
        node_next = self.node_steps.get(node_id, 0) + amount
        task_next = self.task_steps.get(task_id, 0) + amount
        run_next = self.run_steps + amount
        if node_next > self.max_node_steps or task_next > self.max_task_steps or run_next > self.max_run_steps:
            return False
        self.node_steps[node_id] = node_next
        self.task_steps[task_id] = task_next
        self.run_steps = run_next
        return True


class HandoffGuard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_handoffs: int = Field(default=3, ge=1)
    handoff_count: int = Field(default=0, ge=0)
    fallback_replan_used: bool = False

    def next_action(self) -> Literal["handoff", "fallback_replan", "terminate"]:
        if self.handoff_count < self.max_handoffs:
            self.handoff_count += 1
            return "handoff"
        if not self.fallback_replan_used:
            self.fallback_replan_used = True
            return "fallback_replan"
        return "terminate"


def terminate_for_guard(
    board: AgentRunBoard,
    task: BoardTask,
    *,
    origin_agent: str,
    detail: str,
    release: Callable[[], None] | None = None,
) -> EscalationRequest:
    """把取消、终止事件、资源释放和控制权交回封装成单个同步操作。"""

    task.status = TaskStatus.CANCELLED
    task.failure_code = "scheduler_guard_triggered"
    task.updated_at = utc_now()
    request = EscalationRequest(
        task_id=task.task_id,
        board_id=board.run_id,
        origin_agent=origin_agent,
        reason_code=EscalationReasonCode.BUDGET_AT_RISK,
        reason_detail=detail,
        attempted_count=task.attempt_count,
    )
    board.append_event(
        EventType.BUDGET_EXHAUSTED,
        actor_type="scheduler_guard",
        actor_id="scheduler-guard-v0.1",
        task_id=task.task_id,
        payload={"escalation_request": request.model_dump(mode="json")},
    )
    if release is not None:
        try:
            release()
        except Exception:
            # 清理失败不能撤销已经落盘的终止状态，也不能重新进入执行路径。
            pass
    return request
