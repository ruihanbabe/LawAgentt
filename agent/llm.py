from langchain_openai import ChatOpenAI
import os

llm = ChatOpenAI(
    model=os.getenv("QWEN_MODEL", "qwen-plus"),
    base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    api_key=os.getenv("QWEN_API_KEY", "sk-ws-H.REXMLXY.cwkN.MEUCIQCCY2IKh1RnG6Lks8NN8wH7DXHHKIAJDhkkEdk22garoQIgTtjgY5Y02dYjcr6VwvJX7YNwitWPS0Ocibq7skihTaA"),
    streaming=True,
    temperature=0.1,
)
