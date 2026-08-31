"""聊天请求模型、历史管理和 SSE 流处理。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Annotated, Literal

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


logger = logging.getLogger(__name__)

from conversation.harness import TracePersistenceError, build_default_harness
from infrastructure.glm_provider import build_glm_gateway_from_env
from infrastructure.env import load_project_env
from knowledge.qdrant_tools import LazyRuntimeToolExecutor


def build_configured_harness():
    load_project_env()
    model_gateway = None
    if os.getenv("LAWAGENT_GLM_ENABLED", "false").lower() in {"1", "true", "yes"}:
        model_gateway = build_glm_gateway_from_env()
    if os.getenv("LAWAGENT_RAG_ENABLED", "false").lower() not in {"1", "true", "yes"}:
        return build_default_harness(model_gateway=model_gateway)
    executor = LazyRuntimeToolExecutor(
        qdrant_url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
        model_path=Path(os.getenv("EMBEDDING_MODEL_PATH", "models/bge-m3")),
        device=os.getenv("DEVICE", "auto"),
        cases_collection=os.getenv("CASES_COLLECTION", "cases_collection"),
        laws_collection=os.getenv("LAWS_COLLECTION", "laws_collection"),
    )
    return build_default_harness(executor, model_gateway)


conversation_harness = build_configured_harness()

ChatText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8_000)]
UserId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]


class ContextMessage(BaseModel):
    """由前端显式提交的一条历史消息。"""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"] = Field(description="消息角色。")
    content: ChatText = Field(description="消息正文。")


class ChatInput(BaseModel):
    """``POST /chat`` 的请求体。"""

    model_config = ConfigDict(extra="forbid")

    text: ChatText = Field(description="用户当前提问文本。")
    user_id: UserId = Field(description="会话用户标识，用于隔离内存对话历史。")
    context: list[ContextMessage] | None = Field(
        default=None,
        max_length=20,
        description="可选对话上下文，最多20条；服务端历史仍会应用滑动窗口。",
    )

    @field_validator("context")
    @classmethod
    def reject_duplicate_current_question(
        cls, value: list[ContextMessage] | None
    ) -> list[ContextMessage] | None:
        # 上下文只表示之前的消息，当前问题必须始终通过 text 单独传入。
        return value


# 用来存储对话历史的全局变量。首版仅适合单进程 Demo；后续由案件状态存储替换。
history_store: dict[str, list[dict[str, str]]] = {}


# 滑动窗口上下文管理器实现
def sliding_window_context_manager(
    full_history: list[dict[str, str]], window_size: int
) -> list[dict[str, str]]:
    """保留最近 ``window_size`` 条用户/助手消息，不修改调用方列表。"""

    if window_size <= 0:
        return []
    history_conversation = [
        message
        for message in full_history
        if message.get("role") in {"user", "assistant"}
    ]
    return list(history_conversation[-window_size:])


def encode_sse(payload: dict[str, str] | str) -> str:
    """把一个协议事件编码成完整 SSE data frame。"""

    if isinstance(payload, str):
        return f"data: {payload}\n\n"
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def iter_agent_events(
    messages: list[dict[str, str]],
    *,
    session_id: str | None = None,
    pseudonymous_user_id: str | None = None,
) -> AsyncIterator[dict[str, str]]:
    """执行自研共享任务板 Runtime，并转换为前端稳定事件。"""

    current_question = next(
        (message["content"] for message in reversed(messages) if message["role"] == "user"),
        "",
    )
    result = conversation_harness.handle(
        current_question,
        session_id=session_id,
        pseudonymous_user_id=pseudonymous_user_id,
    )
    board = result.board

    yield {"type": "run_started", "content": board.run_id}
    for task in board.tasks:
        event_type = "tool_call" if task.task_type == "retrieve_context" else "status_changed"
        yield {"type": event_type, "content": f"{task.task_type}:{task.status.value}"}
    for event in board.events:
        if event.event_type.value == "task_completed" and event.task_id:
            completed_task = board.task(event.task_id)
            if completed_task.task_type == "retrieve_context":
                yield {"type": "tool_result", "content": event.event_type.value}

    # 第一切片的回答由确定性安全 Agent 产生；后续真实生成模型仍沿用 chunk 协议。
    response = result.response
    for start in range(0, len(response), 24):
        yield {"type": "chunk", "content": response[start : start + 24]}


async def build_chat_stream(req: ChatInput, request: Request) -> AsyncGenerator[str, None]:
    """执行一次聊天并产出已经编码的 SSE frame。"""

    stored_history = history_store.setdefault(req.user_id, [])
    if req.context is not None:
        # 前端显式上下文只用于本次请求，不覆盖服务端已有历史。
        request_history = [message.model_dump() for message in req.context]
    else:
        request_history = sliding_window_context_manager(stored_history, window_size=20)

    request_history.append({"role": "user", "content": req.text})
    full_content = ""

    # stream_generator只负责处理网络流和yield碎片，以实现复用。
    try:
        async for event in iter_agent_events(
            request_history,
            session_id=req.user_id,
            pseudonymous_user_id=req.user_id,
        ):
            # 客户端断开连接后停止继续消费上游流。
            if await request.is_disconnected():
                logger.info("客户端已断开连接，停止生成")
                return

            if event["type"] == "chunk":
                full_content += event["content"]
            yield encode_sse(event)

        if full_content:
            stored_history.extend(
                [
                    {"role": "user", "content": req.text},
                    {"role": "assistant", "content": full_content},
                ]
            )
            # 确保 full_response 在流式结束时，准确写入对应用户的历史里。
            history_store[req.user_id] = sliding_window_context_manager(
                stored_history, window_size=20
            )

        yield encode_sse({"type": "done", "content": full_content})
    except asyncio.CancelledError:
        # 无论正常结束还是异常断开，都必须停止后台生成。
        raise
    except TracePersistenceError:
        logger.error("Trace持久化失败，已阻断本轮交付")
        yield encode_sse({"type": "error", "content": "服务暂时不可用，请稍后重试。"})
    except Exception:
        logger.exception("Agent 流式输出异常")
        # 不把密钥、路径或上游异常原文发送给浏览器。
        yield encode_sse({"type": "error", "content": "服务暂时不可用，请稍后重试。"})
    finally:
        yield encode_sse("[DONE]")
