"""
法条检索 & 案例检索工具。
把 embedder 和 qdrant 的初始化换成你实际的配置。
核心约束：入参 str，返回 str（格式化后的检索结果）。
"""
from langchain_core.tools import tool
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer
import json
import os
from langchain_community.embeddings import SentenceTransformerEmbeddings  # 或者你之前用的方式
# ━━━━━━━━━━━━━━━━━━━━ 初始化（改成你的实际配置） ━━━━━━━━━━━━━━━━━━━━
embedder = SentenceTransformer("/root/agent/models/bge-m3")  # 本地 BGE-M3

qdrant = QdrantClient(
    host=os.getenv("QDRANT_HOST", "localhost"),
    port=int(os.getenv("QDRANT_PORT", 6333)),
)

LAWS_COLLECTION = "laws_collection"
CASES_COLLECTION = "cases_collection"
TOP_K = 5

@tool
def search_laws(query: str) -> str:
    """检索法律条文库，返回相关法条原文。当需要查找具体法律条款时使用此工具。"""
    query_vector = embedder.embed_query(query)
    
    # 使用 query_points 替代已废弃的 search
    results = qdrant.query_points(
        collection_name="law_collection",  # 换成你实际的 collection 名称
        query=query_vector,
        limit=5
    )
    
    # 解析结果
    output = []
    for point in results.points:
        payload = point.payload
        output.append(
            f"【法条】{payload.get('title', '未知')} 第{payload.get('article', '未知')}条\n"
            f"内容: {payload.get('content', '未知')}\n"
            f"相似度: {point.score:.4f}"
        )
    
    return "\n\n".join(output) if output else "未检索到相关法条"


@tool
def search_cases(query: str) -> str:
    """检索法院裁判案例库，返回相似案例。当需要查找真实法院判决案例时使用此工具。"""
    query_vector = embedder.embed_query(query)
    
    results = qdrant.query_points(
        collection_name="case_collection",  # 换成你实际的 collection 名称
        query=query_vector,
        limit=5
    )
    
    output = []
    for point in results.points:
        payload = point.payload
        output.append(
            f"【案例】{payload.get('case_name', '未知')}\n"
            f"案号: {payload.get('case_number', '未知')}\n"
            f"裁判要旨: {payload.get('content', '未知')}\n"
            f"相似度: {point.score:.4f}"
        )
    
    return "\n\n".join(output) if output else "未检索到相关案例"
