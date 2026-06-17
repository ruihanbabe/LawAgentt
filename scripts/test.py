import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from qdrant_client import QdrantClient
from qdrant_client.models import SparseVector, Filter, FieldCondition, MatchAny, MatchValue
from FlagEmbedding import BGEM3FlagModel
from tqdm import tqdm
import numpy as np
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch


# ================= 配置区 =================
QDRANT_HOST = "http://localhost:6333"
CASE_COLLECTION_NAME = "cases_collections"  # 你的案例库 Collection 名称
TEST_DATA_PATH = "/root/agent/data/test_queries.jsonl" # 测试集路径
TOP_K_VALUES = [3,5,10]
LOCAL_BGE_M3_PATH = "/root/agent/models/bge-m3"  # BGE-M3 模型路径
LOCAL_RERANKER_PATH = "/root/agent/models/bge-reranker-v2-m3"  # Reranker 模型路径

# ================= 模型加载 =================
print(f"⏳ 正在加载本地 BGE-M3 模型: {LOCAL_BGE_M3_PATH} ...")
embedding_model = BGEM3FlagModel(
    LOCAL_BGE_M3_PATH,
    use_fp16=True,
    use_faiss=False,
    device='cuda'
)
print("✅ BGE-M3 加载完成！(GPU Mode)")

print(f"🔄 正在加载 Reranker 模型: {LOCAL_RERANKER_PATH} ...")
reranker_tokenizer = AutoTokenizer.from_pretrained(LOCAL_RERANKER_PATH)
reranker_model = AutoModelForSequenceClassification.from_pretrained(LOCAL_RERANKER_PATH).half().eval().cuda()
print("✅ Reranker 模型加载完成！")


# ================= 评测器类 =================
class CaseRetrievalEvaluator:
    def __init__(self, client: QdrantClient, collection_name: str, model: BGEM3FlagModel):
        self.client = client
        self.collection_name = collection_name
        self.model = model

    def _encode_query(self, query_text: str, boost_tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        将查询文本编码为 dense + sparse 向量
        🔥 方法一：隐式融入（查询扩展）- 将标签以高权重文本形式融入向量计算
        """
        # ========== 方法一：查询扩展 ==========
        if boost_tags:
            # 用强烈的语气将标签拼接到查询文本中，迫使模型关注这些核心词
            tags_str = " ".join(boost_tags)
            enhanced_text = f"【核心标签】: {tags_str}。具体案情: {query_text}"
        else:
            enhanced_text = query_text

        # 使用增强后的文本进行编码
        output = self.model.encode(
            [enhanced_text],  # 🔥 传入增强后的文本
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False
        )
        
        dense_vec = output['dense_vecs'][0].tolist()
        
        sparse_indices = []
        sparse_values = []
        if output.get('sparse_vecs') is not None:
            sparse_mat = output['sparse_vecs'][0]
            if sparse_mat.nnz > 0:
                indices = sparse_mat.indices.tolist()
                values = sparse_mat.data.tolist()
                sorted_pairs = sorted(zip(indices, values), key=lambda x: x[0])
                sparse_indices = [p[0] for p in sorted_pairs]
                sparse_values = [p[1] for p in sorted_pairs]
                
        sparse_dict = dict(zip(sparse_indices, sparse_values))
        return {
            'dense': dense_vec,
            'sparse': sparse_dict
        }

    def _build_filter(self, case_cause: Optional[str] = None, tags: Optional[List[str]] = None) -> Optional[Filter]:
        """
        🔥 方法二：显式过滤 - 构建 Qdrant 的 Filter 条件
        基于 case_cause 和 tags 字段进行过滤
        """
        conditions = []
        
        # 过滤 case_cause 字段（精确匹配）
        if case_cause:
            conditions.append(
                FieldCondition(
                    key="case_cause",  # 对应你入库时的 payload 字段名
                    match=MatchValue(value=case_cause)
                )
            )
        
        # 过滤 tags 字段（包含任意一个即可）
        if tags:
            conditions.append(
                FieldCondition(
                    key="tags",  # 对应你入库时的 payload 字段名
                    match=MatchAny(any=tags)
                )
            )
        
        if conditions:
            return Filter(must=conditions)
        return None

    def evaluate_single_query_rerank(
        self, 
        query_text: str, 
        ground_truth_ids: List[str], 
        k_values: List[int], 
        rrf_k: int = 60,
        boost_tags: Optional[List[str]] = None,
        filter_case_cause: Optional[str] = None,
        filter_tags: Optional[List[str]] = None
    ) -> tuple:
        """
        混合检索 Top20 + Reranker 重排评估，同时返回调试信息
        🔥 支持方法一（boost_tags）和方法二（filter_case_cause, filter_tags）
        """
        # 1. 编码（应用方法一：如果有 boost_tags，查询文本会被增强）
        vec_data = self._encode_query(query_text, boost_tags=boost_tags)
        candidate_k = 20  

        # 2. 构建过滤条件（应用方法二）
        query_filter = self._build_filter(case_cause=filter_case_cause, tags=filter_tags)
        
        # ========== 1. Dense 检索 Top-20 ==========
        dense_results = self.client.query_points(
            collection_name=self.collection_name,
            query=vec_data['dense'],
            using="dense",
            limit=candidate_k,
            with_payload=True,
            query_filter=query_filter  # 🔥 应用过滤
        )
        
        # ========== 2. Sparse 检索 Top-20 ==========
        sparse_results = self.client.query_points(
            collection_name=self.collection_name,
            query=SparseVector(
                indices=list(vec_data['sparse'].keys()),
                values=list(vec_data['sparse'].values())
            ),
            using="sparse",
            limit=candidate_k,
            with_payload=True,
            query_filter=query_filter  # 🔥 应用过滤
        )
        
        # ========== 3. RRF 融合 ==========
        rrf_scores = {}
        candidate_payloads = {}  
        
        for rank, point in enumerate(dense_results.points, start=1):
            pid = str(point.id)
            rrf_scores[pid] = rrf_scores.get(pid, 0.0) + 1.0 / (rrf_k + rank)
            if pid not in candidate_payloads:
                candidate_payloads[pid] = point.payload
        
        for rank, point in enumerate(sparse_results.points, start=1):
            pid = str(point.id)
            rrf_scores[pid] = rrf_scores.get(pid, 0.0) + 1.0 / (rrf_k + rank)
            if pid not in candidate_payloads:
                candidate_payloads[pid] = point.payload
        
        fused_ids = [pid for pid, score in sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)][:candidate_k]
        
        # ========== 4. Reranker 重排 ==========
        pairs = []  
        valid_ids = []  
        
        for pid in fused_ids:
            payload = candidate_payloads.get(pid, {})
            full_text = payload.get("full_text", "")
            
            if full_text and full_text != "清洗失败":
                # 🔥 首尾截断法：保留开头事实 + 结尾判决，跳过中间冗长的举证质证
                head_len = 200  
                tail_len = 200  
                
                if len(full_text) > head_len + tail_len:
                    doc_text = full_text[:head_len] + "......" + full_text[-tail_len:]
                else:
                    doc_text = full_text 
                
                pairs.append([query_text, doc_text])  # Reranker 必须用原始 query
                valid_ids.append(pid)
        
        if not pairs:
            reranked_ids = fused_ids
        else:
            with torch.no_grad():
                inputs = reranker_tokenizer(
                    pairs, 
                    padding=True, 
                    truncation=True, 
                    max_length=512, 
                    return_tensors='pt'
                ).to(reranker_model.device)
                
                scores = reranker_model(**inputs).logits.squeeze(-1)
                rerank_scores = torch.sigmoid(scores).cpu().tolist()
                if isinstance(rerank_scores, float):
                    rerank_scores = [rerank_scores]
            
            scored_pairs = list(zip(valid_ids, rerank_scores))
            scored_pairs.sort(key=lambda x: x[1], reverse=True)
            reranked_ids = [pid for pid, score in scored_pairs]

        # ========== 5. 计算指标 & 收集调试信息 ==========
        metrics = {}
        gt_set = set(ground_truth_ids)
        
        for k in k_values:
            top_k_ids = reranked_ids[:k]
            hits = len(set(top_k_ids) & gt_set)
            
            metrics[f"recall@{k}"] = hits / len(ground_truth_ids) if ground_truth_ids else 0
            metrics[f"precision@{k}"] = hits / k if k > 0 else 0
            
            mrr_k = 0.0
            for rank, doc_id in enumerate(top_k_ids, start=1):
                if doc_id in gt_set:
                    mrr_k = 1.0 / rank
                    break
            metrics[f"mrr@{k}"] = mrr_k
            
            dcg = 0.0
            for rank, doc_id in enumerate(top_k_ids, start=1):
                if doc_id in gt_set:
                    dcg += 1.0 / np.log2(rank + 1)
                    
            ideal_hits = min(len(ground_truth_ids), k)
            idcg = 0.0
            for rank in range(1, ideal_hits + 1):
                idcg += 1.0 / np.log2(rank + 1)
                
            metrics[f"ndcg@{k}"] = dcg / idcg if idcg > 0 else 0.0

        # 🔥 新增：收集调试信息，用于写入 JSON
        debug_info = {
            "query_text": query_text,
            "rag_results": [],
            "ground_truth": [],
            "filter_conditions": {
                "boost_tags": boost_tags,
                "filter_case_cause": filter_case_cause,
                "filter_tags": filter_tags
            }
        }
        
        # 收集 RAG 检索结果（取前 10 条看看即可）
        for i, pid in enumerate(reranked_ids[:10]):
            payload = candidate_payloads.get(pid, {})
            is_hit = pid in gt_set
            debug_info["rag_results"].append({
                "rank": i + 1,
                "case_id": pid,
                "is_ground_truth": is_hit,
                "full_text": payload.get("full_text", "无文本内容"),
                "case_cause": payload.get("case_cause", ""),
                "tags": payload.get("tags", [])
            })
            
        # 收集 Ground Truth 原文（看看本该搜出来的长啥样）
        for gt_id in ground_truth_ids:
            if gt_id in candidate_payloads:
                text = candidate_payloads[gt_id].get("full_text", "无文本内容")
                gt_payload = candidate_payloads[gt_id]
            else:
                try:
                    resp = self.client.retrieve(self.collection_name, ids=[gt_id], with_payload=True)
                    gt_payload = resp[0].payload if resp else {}
                    text = gt_payload.get("full_text", "无文本内容")
                except:
                    text = "检索异常"
                    gt_payload = {}
            
            debug_info["ground_truth"].append({
                "case_id": gt_id,
                "full_text": text,
                "case_cause": gt_payload.get("case_cause", ""),
                "tags": gt_payload.get("tags", [])
            })

        return metrics, debug_info

    def evaluate_dataset(
        self, 
        test_data_path: str, 
        k_values: List[int], 
        output_json_path: str = "rag_debug_results.json",
        boost_tags: Optional[List[str]] = None,
        filter_case_cause: Optional[str] = None,
        filter_tags: Optional[List[str]] = None
    ) -> Dict[str, float]:
        """评估整个测试集，计算平均指标，并将详细结果写入 JSON"""
        total_metrics = {f"recall@{k}": 0.0 for k in k_values}
        total_metrics.update({f"precision@{k}": 0.0 for k in k_values})
        total_metrics.update({f"mrr@{k}": 0.0 for k in k_values})
        total_metrics.update({f"ndcg@{k}": 0.0 for k in k_values})
        
        query_count = 0
        all_debug_infos = []  # 🔥 收集所有 Query 的调试信息
        
        with open(test_data_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        for line in tqdm(lines, desc="评估并收集数据中"):
            item = json.loads(line)
            query_text = item["query_text"]
            gt_ids = item["ground_truth_case_ids"]
            
            if not gt_ids:
                continue
            
            # 🔥 接收返回的调试信息，传入过滤条件
            single_metrics, debug_info = self.evaluate_single_query_rerank(
                query_text, 
                gt_ids, 
                k_values,
                boost_tags=boost_tags,
                filter_case_cause=filter_case_cause,
                filter_tags=filter_tags
            )
            
            for key, value in single_metrics.items():
                total_metrics[key] += value
            
            all_debug_infos.append(debug_info)
            query_count += 1
        
        # 计算平均值
        avg_metrics = {key: val / query_count for key, val in total_metrics.items()}
        avg_metrics["query_count"] = query_count
        
        # 🔥 将调试信息写入 JSON 文件
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(all_debug_infos, f, ensure_ascii=False, indent=4)
        print(f"\n✅ 详细检索结果已写入: {output_json_path}")
        
        return avg_metrics


# ================= 运行测试 =================
if __name__ == "__main__":
    # 1. 初始化客户端
    client = QdrantClient(url=QDRANT_HOST, check_compatibility=False)
    
    # 2. 初始化评测器
    evaluator = CaseRetrievalEvaluator(client, CASE_COLLECTION_NAME, embedding_model)
    
    # 3. 运行评估
    print(f"🚀 开始评估案例库检索能力 (Collection: {CASE_COLLECTION_NAME})...")
    output_file = "/root/agent/data/rag_badcase_analysis.json"
    
    # 🔥 测试标签增强和过滤的效果
    # 假设你通过某种方式从 query 中提取出了这些标签
    experimental_boost_tags = ["劳动争议", "劳动合同"]  # 方法一：查询扩展
    experimental_filter_case_cause = "劳动争议"  # 方法二：精确过滤案由
    experimental_filter_tags = ["未签劳动合同", "双倍工资"]  # 方法二：包含任意标签
    
    results = evaluator.evaluate_dataset(
        TEST_DATA_PATH, 
        TOP_K_VALUES, 
        output_json_path=output_file,
        boost_tags=None,  # 方法一
        filter_case_cause=None,  # 方法二
        filter_tags=None  # 方法二
    )
    
    # 4. 打印结果
    print("\n" + "="*40)
    print("📊 案例库检索评估报告")
    print("="*40)
    print(f"评估样本数: {results.pop('query_count')}")
    for metric, value in results.items():
        print(f"{metric}: {value:.4f}")
