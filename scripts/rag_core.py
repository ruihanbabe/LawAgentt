import json
import asyncio
import logging
from typing import List, Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass, field
import numpy as np
import httpx
from FlagEmbedding import BGEM3FlagModel
from sentence_transformers import CrossEncoder
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, SparseVectorParams, PointStruct, SparseIndexParams

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ARTICLE_COLLECTION = "articles"
CASE_COLLECTION = "cases"

@dataclass
class RAGResult:
    id: str
    content: str
    score: float
    metadata: Dict[str, Any]
    source: str  # 'article' 或 'case'

class RAGEngine:
    def __init__(
    self,
    api_key: str,
    llm_url: str = "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    bge_model_name: str = "BAAI/bge-m3",
    cross_encoder_name: str = "BAAI/bge-reranker-base",
    rrf_k: int = 60,
    cache_dir: str = "/root/LawAgent/models/bge-m3"  # 修改为这个路径
):
        self.cache_dir = cache_dir  # 保存缓存目录
        # ... 其他初始化代码

        self.api_key = api_key
        self.llm_url = llm_url
        self.rrf_k = rrf_k
        
        # 1. 初始化 BGE-M3 (Dense + Sparse) - 确保加载到内存
        logger.info("正在加载 BGE-M3 模型...")
        # 在 RAGEngine.__init__ 方法中
        self.bge_m3 = BGEM3FlagModel(
        "/root/LawAgent/models/bge-m3",  # 直接指定本地路径
        use_fp16=True,
        device="cpu",
        trust_remote_code=True,
        local_files_only=True  # 保持这个参数
        )


        self.dense_dim = self.bge_m3.model.config.hidden_size # 1024
        
        # 2. 初始化 Cross-Encoder 精排模型
        logger.info("正在加载 Cross-Encoder 模型...")
        self.cross_encoder = CrossEncoder(cross_encoder_name)
        
        # 3. 初始化 Qdrant 内存模式 (用于Dense+Sparse混合检索)
        self.qdrant_client = QdrantClient(":memory:")
        
        # 4. 内存字典 (用于手写RRF时的原文/元数据提取，模拟Collection)
        self.in_memory_collections = {
            ARTICLE_COLLECTION: {},
            CASE_COLLECTION: {}
        }

    def build_collections_from_json(self, articles_path: str, cases_path: str):
        """预留的JSON路径转换建库接口"""
        logger.info(f"开始从 JSON 建库: {articles_path}, {cases_path}")
        
        with open(articles_path, 'r', encoding='utf-8') as f:
            articles_data = json.load(f)
        with open(cases_path, 'r', encoding='utf-8') as f:
            cases_data = json.load(f)
            
        self._build_article_collection(articles_data)
        self._build_case_collection(cases_data)
        logger.info("建库完成！")

    def _build_article_collection(self, data: List[Dict]):
        # 创建 Qdrant Collection (Dense + Sparse)
        self.qdrant_client.recreate_collection(
            collection_name=ARTICLE_COLLECTION,
            vectors_config=VectorParams(size=self.dense_dim, distance=Distance.COSINE),
            sparse_vectors_config={
                "sparse": SparseIndexParams()
            }
        )
        
        points = []
        for idx, item in enumerate(data):
            doc_id = item.get("id", f"art_{idx}")
            content = item.get("content", "")
            
            # 编码
            encoded = self.bge_m3.encode([content], return_dense=True, return_sparse=True)
            dense_vec = encoded['dense_vecs'][0].tolist()
            sparse_vec = encoded['lexical_weights'][0]
            
            # Qdrant Sparse 格式转换
            sparse_indices = [int(k) for k in sparse_vec.keys()]
            sparse_values = [float(v) for v in sparse_vec.values()]
            
            points.append(
                PointStruct(
                    id=idx,
                    vector={"dense": dense_vec, "sparse": SparseVector(indices=sparse_indices, values=sparse_values)},
                    payload={"doc_id": doc_id}
                )
            )
            
            # 存入内存字典
            self.in_memory_collections[ARTICLE_COLLECTION][doc_id] = {
                "content": content,
                "metadata": {
                    "law_name": item.get("law_name"),
                    "article_number": item.get("article_number"),
                    "amount": item.get("amount")
                }
            }
            
        self.qdrant_client.upsert(collection_name=ARTICLE_COLLECTION, points=points)

    def _build_case_collection(self, data: List[Dict]):
        self.qdrant_client.recreate_collection(
            collection_name=CASE_COLLECTION,
            vectors_config=VectorParams(size=self.dense_dim, distance=Distance.COSINE),
            sparse_vectors_config={
                "sparse": SparseIndexParams()
            }
        )
        
        points = []
        for idx, item in enumerate(data):
            doc_id = item.get("id", f"case_{idx}")
            # 案例用 content + summary 拼接作为检索文本
            content = item.get("content", "")
            summary = item.get("summary", "")
            combined_text = f"{content}\n总结：{summary}"
            
            encoded = self.bge_m3.encode([combined_text], return_dense=True, return_sparse=True)
            dense_vec = encoded['dense_vecs'][0].tolist()
            sparse_vec = encoded['lexical_weights'][0]
            
            sparse_indices = [int(k) for k in sparse_vec.keys()]
            sparse_values = [float(v) for v in sparse_vec.values()]
            
            points.append(
                PointStruct(
                    id=idx,
                    vector={"dense": dense_vec, "sparse": SparseVector(indices=sparse_indices, values=sparse_values)},
                    payload={"doc_id": doc_id}
                )
            )
            
            self.in_memory_collections[CASE_COLLECTION][doc_id] = {
                "content": combined_text,
                "metadata": {
                    "case_id": item.get("case_id"),
                    "case_type": item.get("case_type"),
                    "claim_amount": item.get("claim_amount")
                }
            }
            
        self.qdrant_client.upsert(collection_name=CASE_COLLECTION, points=points)

    # ================= 预留接口 =================
    def rewrite_query(self, query: str, **kwargs) -> str:
        """Query重写/扩写函数接口"""
        # TODO: 接入LLM进行意图识别、关键词扩写
        return query

    def expand_query(self, query: str, max_expansions: int = 3) -> List[str]:
        """Query扩写函数接口"""
        # TODO: 返回多个同义词/领域词改写的查询
        return [query]
    # ==========================================

    def _hybrid_search(self, query: str, top_k: int = 10) -> Dict[str, List[RAGResult]]:
        """BGE-M3 Dense + Sparse 检索"""
        rewritten_query = self.rewrite_query(query)
        
        encoded = self.bge_m3.encode([rewritten_query], return_dense=True, return_sparse=True)
        dense_vec = encoded['dense_vecs'][0].tolist()
        sparse_vec = encoded['lexical_weights'][0]
        sparse_indices = [int(k) for k in sparse_vec.keys()]
        sparse_values = [float(v) for v in sparse_vec.values()]
        
        results_dict = {}
        for coll_name in [ARTICLE_COLLECTION, CASE_COLLECTION]:
            # Qdrant 混合检索：Dense 和 Sparse 各自检索
            dense_results = self.qdrant_client.search(
                collection_name=coll_name,
                query_vector=("dense", dense_vec),
                limit=top_k
            )
            sparse_results = self.qdrant_client.search(
                collection_name=coll_name,
                query_vector=("sparse", SparseVector(indices=sparse_indices, values=sparse_values)),
                limit=top_k
            )
            
            # 转换为 RAGResult 列表
            dense_rags = [
                RAGResult(
                    id=res.payload['doc_id'],
                    content=self.in_memory_collections[coll_name][res.payload['doc_id']]['content'],
                    score=res.score,
                    metadata=self.in_memory_collections[coll_name][res.payload['doc_id']]['metadata'],
                    source=coll_name
                ) for res in dense_results if res.payload['doc_id'] in self.in_memory_collections[coll_name]
            ]
            
            sparse_rags = [
                RAGResult(
                    id=res.payload['doc_id'],
                    content=self.in_memory_collections[coll_name][res.payload['doc_id']]['content'],
                    score=res.score,
                    metadata=self.in_memory_collections[coll_name][res.payload['doc_id']]['metadata'],
                    source=coll_name
                ) for res in sparse_results if res.payload['doc_id'] in self.in_memory_collections[coll_name]
            ]
            
            results_dict[coll_name] = [dense_rags, sparse_rags]
            
        return results_dict

    def _reciprocal_rank_fusion(self, results_lists: List[List[RAGResult]], k: int = 60) -> List[RAGResult]:
        """手写内存版 RRF 融合排序，不调用任何外部库的RRF"""
        rrf_scores = {}
        
        for rank_list in results_lists:
            for rank, result in enumerate(rank_list):
                if result.id not in rrf_scores:
                    rrf_scores[result.id] = {
                        "score": 0.0,
                        "content": result.content,
                        "metadata": result.metadata,
                        "source": result.source
                    }
                # RRF 核心公式: 1 / (k + rank + 1)  (rank从0开始，所以+1)
                rrf_scores[result.id]["score"] += 1.0 / (k + rank + 1)
                
        # 按融合后的分数降序排序
        sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x]["score"], reverse=True)
        
        return [
            RAGResult(
                id=rid,
                content=rrf_scores[rid]["content"],
                score=rrf_scores[rid]["score"],
                metadata=rrf_scores[rid]["metadata"],
                source=rrf_scores[rid]["source"]
            ) for rid in sorted_ids
        ]

    def _cross_encoder_rerank(self, query: str, results: List[RAGResult], top_n: int = 5) -> List[RAGResult]:
        """Cross-Encoder 精排"""
        if not results:
            return []
            
        pairs = [[query, res.content] for res in results]
        scores = self.cross_encoder.predict(pairs)
        
        for i, score in enumerate(scores):
            results[i].score = float(score)
            
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_n]

    def _build_context(self, results: List[RAGResult]) -> str:
        """将检索结果拼接为 LLM 的上下文"""
        context_str = ""
        for res in results:
            if res.source == ARTICLE_COLLECTION:
                context_str += f"【相关法条】(法律:{res.metadata.get('law_name')}, 条款:{res.metadata.get('article_number')})\n{res.content}\n\n"
            elif res.source == CASE_COLLECTION:
                context_str += f"【相关案例】(案号:{res.metadata.get('case_id')}, 案由:{res.metadata.get('case_type')})\n{res.content}\n\n"
        return context_str

    async def _call_llm_stream(self, messages: List[dict]) -> AsyncGenerator[dict, None]:
        """调用大模型外部 API 并进行流式返回 (整合了异常处理和流式碎片清洗)"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        payload = {
            "model": "glm-4-flash",
            "messages": messages,
            "stream": True
        }

        raw_content = ""
        async with httpx.AsyncClient() as client:
            try:
                async with client.stream("POST", self.llm_url, headers=headers, json=payload, timeout=10) as res:
                    res.raise_for_status()
                    async for line in res.aiter_lines():
                        if line and line.startswith("data: "):
                            data_str = line[len("data: "):]
                            if data_str == "[DONE]":
                                break
                            try:
                                data_json = json.loads(data_str)
                                content_piece = data_json["choices"][0]["delta"].get("content", "")
                                raw_content += content_piece
                                if content_piece:
                                    yield {"type": "chunk", "content": content_piece}
                            except json.JSONDecodeError:
                                pass
            except httpx.HTTPStatusError as e:
                yield {"type": "error", "content": f"LLM API请求失败: {e.response.status_code}"}
            except Exception as e:
                yield {"type": "error", "content": f"网络或流式异常: {str(e)}"}
                
        yield {"type": "done", "content": raw_content}

    def _sliding_window_context_manager(self, full_history: List[Dict], window_size: int = 20) -> List[Dict]:
        """滑动窗口上下文管理"""
        if len(full_history) <= window_size:
            return full_history
        history_conversation = [msg for msg in full_history if msg["role"] in ["user", "assistant"]]
        sliding_history = history_conversation[-window_size:]
        return [full_history[0]] + sliding_history

    async def ask_stream(self, question: str, chat_history: List[dict]) -> AsyncGenerator[dict, None]:
        """RAG 核心流式问答接口"""
        # 1. 混合检索 (Dense + Sparse)
        hybrid_results = self._hybrid_search(question, top_k=10)
        
        # 2. 手写 RRF 融合预选集排序
        rrf_results_articles = self._reciprocal_rank_fusion(hybrid_results[ARTICLE_COLLECTION], k=self.rrf_k)
        rrf_results_cases = self._reciprocal_rank_fusion(hybrid_results[CASE_COLLECTION], k=self.rrf_k)
        
        # 取RRF后的 top 15 送入精排
        candidates = (rrf_results_articles[:8] + rrf_results_cases[:7])
        
        # 3. Cross-Encoder 精排
        final_results = self._cross_encoder_rerank(question, candidates, top_n=5)
        
        # 4. 构建 Context
        context = self._build_context(final_results)
        
        # 5. 组装 Prompt 和 History
        system_prompt = f"你是一个专业的法律文献智能助手。请根据以下检索到的法律文献信息回答用户问题，如果文献中没有提及，请合理推断并说明。\n\n【检索到的法律文献上下文】：\n{context}"
        
        history_with_system = [{"role": "system", "content": system_prompt}] + chat_history
        managed_history = self._sliding_window_context_manager(history_with_system, window_size=20)
        
        # 6. 调用 LLM 流式生成
        async for chunk in self._call_llm_stream(managed_history):
            yield chunk
