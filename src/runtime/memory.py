"""确定性的会话记忆存储、压缩和淘汰策略。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from runtime.identifiers import new_id


class MemoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: str = Field(default_factory=lambda: new_id("memory"))
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8_000)


def sliding_window_context_manager(
    full_history: Sequence[Mapping[str, str]], window_size: int
) -> list[dict[str, str]]:
    """传输无关的滑动窗口规则；过滤非对话角色且不修改调用方数据。"""

    if window_size <= 0:
        return []
    conversation = [
        {"role": str(message.get("role")), "content": str(message.get("content", ""))}
        for message in full_history
        if message.get("role") in {"user", "assistant"} and str(message.get("content", "")).strip()
    ]
    return conversation[-window_size:]


class MemoryService:
    """写入时完成确定性压缩和窗口淘汰；读取端不再做二次判断。"""

    def __init__(self, *, window_size: int = 20, max_message_chars: int = 8_000) -> None:
        if window_size < 1 or max_message_chars < 1:
            raise ValueError("memory limits must be positive")
        self.window_size = window_size
        self.max_message_chars = min(max_message_chars, 8_000)
        self._sessions: dict[str, list[MemoryRecord]] = {}

    def write(self, session_id: str, *, role: str, content: str, message_id: str | None = None) -> None:
        normalized = " ".join(str(content).split())[:self.max_message_chars]
        if role not in {"user", "assistant"} or not normalized:
            return
        record = MemoryRecord(
            message_id=message_id or new_id("memory"),
            role=role,
            content=normalized,
        )
        records = self._sessions.setdefault(session_id, [])
        records.append(record)
        if len(records) > self.window_size:
            del records[:-self.window_size]

    def replace(self, session_id: str, history: Sequence[Any]) -> None:
        records: list[MemoryRecord] = []
        for item in history:
            if isinstance(item, Mapping):
                role, content = item.get("role"), item.get("content")
                message_id = item.get("message_id")
            else:
                role, content = getattr(item, "role", None), getattr(item, "content", None)
                message_id = getattr(item, "message_id", None)
            if role in {"user", "assistant"} and str(content or "").strip():
                records.append(MemoryRecord(
                    message_id=str(message_id or new_id("memory")),
                    role=role,
                    content=" ".join(str(content).split())[:self.max_message_chars],
                ))
        self._sessions[session_id] = records[-self.window_size:]

    def read(self, session_id: str, *, limit: int | None = None) -> tuple[MemoryRecord, ...]:
        records = self._sessions.get(session_id, [])
        selected = records[-limit:] if limit is not None else records
        return tuple(item.model_copy(deep=True) for item in selected)

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
