from langchain_openai import ChatOpenAI
import os

llm = ChatOpenAI(
    model=os.getenv("QWEN_MODEL", "qwen-plus"),
    base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    api_key=os.environ["QWEN_API_KEY"],
    streaming=True,
    temperature=0.1,
)
