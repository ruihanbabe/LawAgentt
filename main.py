"""LawAgent 的 FastAPI 入口。"""

import json
import os
from html import escape
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

import api.sse as sse_api
from api.sse import ChatInput, build_chat_stream
from api.session_auth import InMemoryTokenBindingStore
from persistence.storage import FaultInjectingConversationRepository
from persistence.trace_tools import trace_view


PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_INDEX = PROJECT_ROOT / "web" / "index.html"

app = FastAPI(
    title="LawAgent API",
    description="法律检索问答 Agent 的最小 Web 与 SSE 接口。",
    version="0.1.0",
)
session_auth_store = InMemoryTokenBindingStore()


class FaultInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal[
        "create_run", "get_blackboard", "save_blackboard", "append_history",
        "append_agent_message", "save_trace", "list_history", "get_trace",
    ]
    count: int = Field(default=1, ge=1, le=100)


def require_dev_access(x_lawagent_dev_token: str | None = Header(default=None)) -> None:
    if os.getenv("LAWAGENT_DEV_MODE", "false").lower() not in {"1", "true", "yes"}:
        raise HTTPException(status_code=404, detail="not found")
    expected = os.getenv("LAWAGENT_DEV_TOKEN")
    if expected and x_lawagent_dev_token != expected:
        raise HTTPException(status_code=403, detail="forbidden")


@app.get("/", response_class=FileResponse, summary="打开最小问答页面")
async def index() -> FileResponse:
    """返回不依赖前端构建工具的单页入口。"""

    return FileResponse(FRONTEND_INDEX, media_type="text/html; charset=utf-8")


@app.post(
    "/chat",
    response_class=StreamingResponse,
    summary="提交法律问题并接收 SSE 流",
    responses={
        200: {
            "description": (
                "SSE 事件流。事件类型包括 chunk、tool_call、tool_result、done、error；"
                "最后发送 data: [DONE]。"
            ),
            "content": {"text/event-stream": {}},
        },
        422: {"description": "请求参数校验失败。"},
    },
)
async def stream_ai(req: ChatInput, request: Request) -> StreamingResponse:
    """流式回答用户问题。

    参数：
    - ``text``：当前问题，去除首尾空白后长度为 1--8,000。
    - ``user_id``：前端生成的会话用户标识，用于区分内存中的对话历史。
    - ``context``：可选历史消息；首版只接受 ``user``/``assistant`` 角色。

    返回值采用 ``text/event-stream``，每条 ``data`` 为 JSON；流结束标记为
    ``data: [DONE]``。
    """

    if not session_auth_store.authenticate_or_bind(req.user_id, req.token):
        raise HTTPException(status_code=403, detail="invalid session credentials")
    return StreamingResponse(
        build_chat_stream(req=req, request=request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/health", summary="服务健康检查")
async def health() -> dict[str, str]:
    """只检查 Web 进程，不触发模型、Qdrant 或 GPU 初始化。"""

    return {"status": "ok"}


@app.get("/api/dev/runs/{run_id}/trace", dependencies=[], summary="查看脱敏 Trace")
async def get_trace(
    run_id: str,
    x_lawagent_dev_token: str | None = Header(default=None),
) -> dict:
    require_dev_access(x_lawagent_dev_token)
    trace = await sse_api.conversation_harness.get_trace(run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    return trace_view(trace)


@app.get("/dev/traces/{run_id}", response_class=HTMLResponse, summary="打开 Trace Viewer")
async def trace_viewer(
    run_id: str,
    x_lawagent_dev_token: str | None = Header(default=None),
) -> HTMLResponse:
    require_dev_access(x_lawagent_dev_token)
    token = json.dumps(x_lawagent_dev_token or "")
    safe_run_id = escape(run_id)
    trace_url = json.dumps(f"/api/dev/runs/{run_id}/trace")
    html = f"""<!doctype html><meta charset=utf-8><title>LawAgent Trace</title>
<style>body{{font:14px system-ui;margin:2rem;max-width:1100px}}pre{{white-space:pre-wrap}}</style>
<h1>Trace {safe_run_id}</h1><pre id=trace>Loading…</pre><script>
fetch({trace_url},{{headers:{{'X-LawAgent-Dev-Token':{token}}}}})
.then(r=>r.json()).then(x=>trace.textContent=JSON.stringify(x,null,2))
.catch(e=>trace.textContent=String(e));</script>"""
    return HTMLResponse(html)


@app.post("/api/dev/runs/{run_id}/replay", summary="按已持久化输入重放")
async def replay_trace(
    run_id: str,
    x_lawagent_dev_token: str | None = Header(default=None),
) -> dict[str, str]:
    require_dev_access(x_lawagent_dev_token)
    harness = sse_api.conversation_harness
    trace = await harness.get_trace(run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    result = await harness.handle_async(
        trace.sanitized_input,
        session_id=None,
        pseudonymous_user_id=trace.pseudonymous_user_id,
        runtime_profile=trace.runtime_profile,
        replay_of_run_id=run_id,
    )
    return {"source_run_id": run_id, "replay_run_id": result.board.run_id}


@app.post("/api/dev/faults", summary="注入一次性持久化故障")
async def inject_fault(
    fault: FaultInput,
    x_lawagent_dev_token: str | None = Header(default=None),
) -> dict[str, str | int]:
    require_dev_access(x_lawagent_dev_token)
    harness = sse_api.conversation_harness
    repository = harness.conversation_repository
    if not isinstance(repository, FaultInjectingConversationRepository):
        repository = FaultInjectingConversationRepository(repository)
        harness.conversation_repository = repository
    repository.inject(fault.operation, count=fault.count)
    return {"operation": fault.operation, "count": fault.count}
