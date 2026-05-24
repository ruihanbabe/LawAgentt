from fastapi import FastAPI, Request
from pydantic import BaseModel, Field
from typing import List, AsyncGenerator, Optional
import json
import httpx
from fastapi.responses import StreamingResponse
import asyncio 

from scripts.rag_core import RAGEngine

# ================= 1. 配置区 =================
API_KEY = "70fe14b65a3a4855b2a4599301ea6daa.AnYV4wySH1ISRaXw"
URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

# 🌟🌟 在这里写入您的 JSON 数据路径 🌟🌟
ARTICLES_JSON_PATH = "./data/chinese-laws.json"
CASES_JSON_PATH = "./data/chinese-cases.json"

# ================= 2. 初始化 RAG 引擎 & 建库 =================
rag_engine = RAGEngine(api_key=API_KEY, llm_url=URL)

# 🌟🌟 在这里触发 JSON 导入并构建 Collection 🌟🌟
# 这一步会读取 JSON，调用 BGE-M3 生成向量，存入 Qdrant 内存库，并存入内存字典
rag_engine.build_collections_from_json(
    articles_path=ARTICLES_JSON_PATH, 
    cases_path=CASES_JSON_PATH
)

# ================= 3. FastAPI 辅助函数 =================
# 滑动窗口上下文管理器实现
def sliding_window_context_manager(full_history: List[dict], window_size: int) -> List[dict]:
    if len(full_history) <= window_size:
        return full_history
    else:
        history_conversation = [msg for msg in full_history if msg["role"] in ["user", "assistant"]]
        sliding_history = history_conversation[-window_size:]
        return [full_history[0]] + sliding_history

# 智能清洗器, 对只需要json数据的特殊用户使用
async def clean_json_stream(raw_stream: AsyncGenerator[str, None]) -> AsyncGenerator[dict, None]:
    bracket_count = 0
    state = "WAITING"
    json_buffer = ""
    
    async for chunk_dict in raw_stream:
        if not isinstance(chunk_dict, dict) or chunk_dict.get("type") != "chunk":
            yield chunk_dict
            continue
        # 注意：这里要遍历 chunk_dict 里的 content 字符串
        for char in chunk_dict.get("content", ""):
            if state == "WAITING":
                if char == '{':
                    bracket_count += 1
                    state = "JSON"
                    json_buffer += char
            elif state == "JSON":
                json_buffer += char
                if char == '{':
                    bracket_count += 1
                elif char == '}':
                    bracket_count -= 1
                    if bracket_count == 0:
                        state = "Done"
                        break
            elif state == "Done":
                break
                
        if json_buffer:
            yield {"type": "chunk", "content": json_buffer}

# ================= 4. FastAPI 路由 =================
app = FastAPI()

class AIResult(BaseModel):
    answer: str

class ChatInput(BaseModel):
    text: str = Field(..., description="用户当前提问文本")
    user_id: str = Field(..., description="用户ID，用于区分不同用户的对话历史")
    context: Optional[List[dict]] = Field(default=None, description="可选的对话历史上下文")

history_store = {}

@app.post("/chat")
async def stream_ai(req: ChatInput, request: Request):
    if req.user_id not in history_store:
        history_store[req.user_id] = []
    
    chat_history = history_store[req.user_id]
    chat_history = sliding_window_context_manager(chat_history, window_size=20) 
    
    chat_history.append({"role": "user", "content": req.text})
    
    # 直接调用 RAG 引擎的流式接口
    stream_answer = rag_engine.ask_stream(question=req.text, chat_history=chat_history)
    
    async def stream_generator():
        async def disconnect_guard():
            while True:
                if await request.is_disconnected():
                    print("客户端已断开连接，停止生成")
                    break
                await asyncio.sleep(0.1)
                
        disconnect_watcher = asyncio.create_task(disconnect_guard())
        
        try:
            async for chunk in stream_answer:
                if disconnect_watcher.done():
                    break
                    
                if isinstance(chunk, dict) and chunk.get("type") == "chunk" and "content" in chunk:
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                    
                elif isinstance(chunk, dict) and chunk.get("type") == "done":
                    full_content = chunk["content"]
                    if not full_content:
                        yield f"data: [ERROR] LLM返回了空内容\n\n"
                        yield "data: [DONE]\n\n"
                        break 
                    try:
                        validated_result = AIResult.model_validate({"answer": full_content})
                        print("校验通过:", validated_result)
                        chat_history.append({"role": "assistant", "content": full_content})
                    except Exception as validation_error:
                        print(f"🔥 校验失败原因: {validation_error}")
                        yield f"data: [ERROR] JSON解析失败\n\n"
                    
                    yield "data: [DONE]\n\n"
                    
                elif isinstance(chunk, dict) and chunk.get("type") == "error":
                    # 捕获 RAG 内部抛出的异常 (如 LLM API 断流)
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                    
        except Exception as e:
            print(f"生成器异常结束: {e}")
            yield f"data: [ERROR] 生成器异常结束\n\n"
        finally:
            if not disconnect_watcher.done():
                disconnect_watcher.cancel()

    return StreamingResponse(stream_generator(), media_type="text/event-stream")
