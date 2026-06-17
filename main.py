"""
FastAPI SSE 入口 - LangGraph Agent 版本
改造要点：
  1. 核心从直接调 LLM 换成 LangGraph graph.astream_events
  2. SSE 事件新增 tool_call / tool_result 类型，前端可展示 Agent 思考过程
  3. 保留原有 disconnect_guard / 滑动窗口 / 历史管理
"""
from fastapi import FastAPI, Request
from pydantic import BaseModel, Field
from typing import List, Optional
import json
import asyncio
from fastapi.responses import StreamingResponse

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from agent.graph import graph

app = FastAPI()


# ━━━━━━━━━━━━━━━━━━━━ 数据模型 ━━━━━━━━━━━━━━━━━━━━
class ChatInput(BaseModel):
    text: str = Field(..., description="用户当前提问文本")
    user_id: str = Field(..., description="用户ID")
    context: Optional[List[dict]] = Field(default=None, description="可选上下文")


# ━━━━━━━━━━━━━━━━━━━━ 对话历史管理 ━━━━━━━━━━━━━━━━━━━━
history_store = {}

SYSTEM_PROMPT = """你是一个专业的法律AI助手。你可以使用以下工具来回答用户的法律问题：

1. search_laws(query): 检索法律条文库，返回相关法条原文
2. search_cases(query): 检索法院裁判案例库，返回相似案例

回答规则：
- 先判断是否需要检索工具，需要时调用对应工具
- 基于检索到的法条和案例回答，标注引用来源（法条名称+条号）
- 如果检索结果不足以回答，明确告知"基于当前检索结果无法确定"
- 不要编造法条或案例
- 回答简洁专业，先给结论再附依据"""


def convert_history(history: list[dict]) -> list:
    """
    dict 格式对话历史 -> LangChain Message 对象列表。
    system prompt 占位——实际 system prompt 在 agent_node 中动态注入。
    """
    messages = [SystemMessage(content="placeholder")]
    
    for msg in history:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))
    return messages


def sliding_window_context_manager(full_history: list[dict], window_size: int) -> list[dict]:
    if len(full_history) <= window_size:
        return full_history
    history_conversation = [msg for msg in full_history if msg["role"] in ["user", "assistant"]]
    sliding_history = history_conversation[-window_size:]
    return [full_history[0]] + sliding_history


# ━━━━━━━━━━━━━━━━━━━━ SSE 流式接口 ━━━━━━━━━━━━━━━━━━━━
@app.post("/chat")
async def stream_ai(req: ChatInput, request: Request):
    if req.user_id not in history_store:
        history_store[req.user_id] = []

    chat_history = history_store[req.user_id]
    chat_history = sliding_window_context_manager(chat_history, window_size=20)
    chat_history.append({"role": "user", "content": req.text})

    messages = convert_history(chat_history)

    async def stream_generator():
        async def disconnect_guard():
            while True:
                if await request.is_disconnected():
                    print("客户端已断开连接，停止生成")
                    break
                await asyncio.sleep(0.1)
        disconnect_watcher = asyncio.create_task(disconnect_guard())

        try:
            full_content = ""

            async for event in graph.astream_events(
                {"messages": messages},
                version="v2",
            ):
                if disconnect_watcher.done():
                    break

                kind = event["event"]

                # ── LLM token 流式输出 ──
                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if chunk.content:
                        full_content += chunk.content
                        yield f"data: {json.dumps({'type': 'chunk', 'content': chunk.content}, ensure_ascii=False)}\n\n"

                # ── 工具调用开始 ──
                elif kind == "on_tool_start":
                    tool_name = event.get("name", "unknown")
                    yield f"data: {json.dumps({'type': 'tool_call', 'content': tool_name}, ensure_ascii=False)}\n\n"

                # ── 工具调用结束 ──
                elif kind == "on_tool_end":
                    output = event["data"].get("output", "")
                    if hasattr(output, "content"):
                        output_str = str(output.content)[:500]
                    else:
                        output_str = str(output)[:500]
                    yield f"data: {json.dumps({'type': 'tool_result', 'content': output_str}, ensure_ascii=False)}\n\n"

            # ── 流结束 ──
            if full_content:
                chat_history.append({"role": "assistant", "content": full_content})
            yield f"data: {json.dumps({'type': 'done', 'content': full_content}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as e:
            print(f"Agent 流式输出异常: {e}")
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            if not disconnect_watcher.done():
                disconnect_watcher.cancel()

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@app.get("/health")
async def health():
    return {"status": "ok"}
