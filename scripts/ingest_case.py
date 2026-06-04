import json
import sys
import re
import traceback
from pathlib import Path
from typing import Dict, Any, List
from tqdm import tqdm
import uuid

class BlackHole:
    def write(self, text):
        pass
    def flush(self):
        pass

# 1. 关闭标准输出（这会干掉 tqdm 进度条）
original_stdout = sys.stdout
sys.stdout = BlackHole()

# 2. 重新定义 print 函数，让它绕过黑洞，直接输出到终端
def print(*args, **kwargs):
    kwargs['file'] = original_stdout
    __builtins__.print(*args, **kwargs)

# Qdrant & Model Imports
from qdrant_client import QdrantClient, models
from qdrant_client.models import Distance, VectorParams, SparseVectorParams

# ================= 配置区 =================
LOCAL_BGE_M3_PATH = "/root/agent/models/bge-m3" 
DATA_DIR = "/root/agent/data/c3rd" 
QDRANT_HOST = "http://localhost:6333"
COLLECTION_NAME = "legal_cases_c3rd"
DISTANCE = Distance.COSINE
BATCH_SIZE = 128  # Qdrant上传批次
EMBED_BATCH_SIZE = 32  # 模型推理批次（根据显存调整）

# ================= 路径导入兼容 =================
current_file = Path(__file__).resolve().parent
sys.path.insert(0, str(current_file))

# ================= 模型加载 =================
print(f"正在加载本地 BGE-M3 模型: {LOCAL_BGE_M3_PATH} ...")
from FlagEmbedding import BGEM3FlagModel

# ✅ 强制使用CUDA (Docker内需有NVIDIA驱动)
embedding_model = BGEM3FlagModel(
    LOCAL_BGE_M3_PATH,
    use_fp16=True,      # GPU下fp16大幅加速
    use_faiss=False,
    device='cuda'       # 强制使用GPU
)
print("✅ BGE-M3 加载完成！(GPU Mode)")

# ================= 数据清洗类 =================
class DataCleaner:
    def __init__(self):
        # 金额正则：匹配 X万元 / X万 / X元 / X,XXX元
        self.amount_pattern_wan = re.compile(r"(\d+\.?\d*)\s*万\s*[元块]?")
        self.amount_pattern_yuan = re.compile(r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*元")
        # 法条正则：匹配 "第X条"
        self.law_article_pattern = re.compile(r"第[一二三四五六七八九十百千\d]+条")

    def _extract_key_facts(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        facts = {"dispute": "", "court_findings": "", "evidence_issue": False}
        judge_reason = raw_data.get("JudgeReason", "")
        judge_result = raw_data.get("JudgeResult", "")
        
        if "争议焦点" in judge_reason:
            match = re.search(r'争议焦点[：:](.*?)(。|$)', judge_reason)
            if match: facts["dispute"] = match.group(1).strip()
            else:
                idx = judge_reason.find("争议焦点")
                facts["dispute"] = judge_reason[idx:idx+50] + "..."
        
        if "本院查明" in judge_reason or "经审理查明" in judge_reason:
            findings = re.search(r'(本院查明|经审理查明)(.*?)(。|本院认为)', judge_reason, re.DOTALL)
            if findings: facts["court_findings"] = findings.group(2).strip()
            else: facts["court_findings"] = judge_reason[:200]
        
        evidence_keywords = ["举证不能", "未能提供证据", "不予采信", "举证责任", "证据不足"]
        if any(kw in judge_result or kw in judge_reason for kw in evidence_keywords):
            facts["evidence_issue"] = True
        return facts

    def _extract_amounts(self, text: str) -> List[Dict[str, Any]]:
        """暴力提取金额，并截取上下文保留中间计算逻辑"""
        if not text:
            return []
            
        amounts = []
        # 1. 提取"万"级别的金额
        for match in self.amount_pattern_wan.finditer(text):
            try:
                val = float(match.group(1)) * 10000
                # 截取前后各15个字符作为上下文供后续Agent分析
                start = max(0, match.start() - 15)
                end = min(len(text), match.end() + 15)
                context = text[start:end].replace("\n", " ")
                amounts.append({"amount": val, "context": context})
            except ValueError:
                continue
                
        # 2. 提取"元"级别的金额 (排除前面已经匹配过的"万")
        for match in self.amount_pattern_yuan.finditer(text):
            start_pos = match.start()
            prefix = text[max(0, start_pos - 5):start_pos]
            if "万" not in prefix:
                try:
                    val = float(match.group(1).replace(",", ""))
                    start = max(0, match.start() - 15)
                    end = min(len(text), match.end() + 15)
                    context = text[start:end].replace("\n", " ")
                    amounts.append({"amount": val, "context": context})
                except ValueError:
                    continue
                    
        return amounts

    def _clean_legal_basis(self, legal_basis_list: List[Dict]) -> List[str]:
        """法条引用降维去重：只保留到条，合并同条下的款项"""
        if not legal_basis_list:
            return []
            
        unique_laws = set()
        for item in legal_basis_list:
            law_name = item.get("law", "")
            terms = item.get("terms", "")
            match = self.law_article_pattern.search(terms)
            if match:
                core_term = match.group(0)
                unique_laws.add(f"{law_name} {core_term}")
            else:
                unique_laws.add(f"{law_name} {terms}".strip())
                
        return list(unique_laws)

    def _extract_keywords_payload(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """提取并合并类别与关键词，形成统一的标签体系"""
        case_cause = raw_data.get("CaseCause", [])
        category = raw_data.get("Category", [])
        keywords = raw_data.get("Keywords", [])
        
        cat_1 = category[0].get("cat_1", "") if category else ""
        cat_2 = category[0].get("cat_2", "") if category else ""
        
        # === 核心：合并去重，保持层级顺序 ===
        # 顺序：cat_1 -> cat_2 -> case_cause -> keywords (从宏观到微观)
        merged_tags = []
        if cat_1: merged_tags.append(cat_1)
        if cat_2 and cat_2 not in merged_tags: merged_tags.append(cat_2)
        
        for cause in case_cause:
            if cause and cause not in merged_tags: merged_tags.append(cause)
            
        for kw in keywords:
            if kw and kw not in merged_tags: merged_tags.append(kw)
            
        return {
            # 保留拆分字段供极度精确的过滤使用 (可选)
            "case_cause": case_cause, 
            "tags": merged_tags  # 统一合并后的标签，用于Sparse和通用过滤
        }


    def clean_single_case(self, case_id: str, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            # 原始字段提取
            case_type = raw_data.get("CaseType", "未知案件类型")
            case_proc = raw_data.get("CaseProc", "未知审理程序")
            title = raw_data.get("Case", "无标题")
            parties = [{"name": p.get("NameText", ""), "role": p.get("Prop", "")} for p in raw_data.get("Parties", [])]
            key_facts = self._extract_key_facts(raw_data)
            
            # === 核心新增：提取并合并类别关键词 ===
            keyword_payload = self._extract_keywords_payload(raw_data)
            merged_tags = keyword_payload["tags"] # 使用合并后的统一标签列表
            
            # === 核心新增：法条降维去重 ===
            ref_laws = self._clean_legal_basis(raw_data.get("LegalBasis", []))
            
            # === 核心新增：金额提取 (同时扫描诉求和结果) ===
            accusation_text = raw_data.get("JudgeAccusation", "")
            result_text = raw_data.get("JudgeResult", "")
            amounts = self._extract_amounts(accusation_text) + self._extract_amounts(result_text)
            
            # ================= 构建用于Embedding的文本 =================
            parts = []
            
            # ✅ 优化1：使用合并后的 tags，采用更自然的语言模板
            # 摒弃 "分类:xx-xx, 关键词:xx" 这种机器格式，减少连接词对稀疏向量的干扰
            if merged_tags:
                tags_str = "，".join(merged_tags)
                parts.append(f"本案核心标签包括：{tags_str}。")
            
            # ✅ 优化2：将降维后的法条也拼接入文本，增强法律依据的语义和稀疏特征
            if ref_laws:
                laws_str = "，".join(ref_laws)
                parts.append(f"裁判依据法规：{laws_str}。")
            
            # 拼接核心事实
            parts.append(f"争议焦点：{key_facts.get('dispute', '未明确陈述')}")
            parts.append(f"法院查明事实：{key_facts.get('court_findings', raw_data.get('JudgeReason', ''))}")
            if result_text: parts.append(f"判决结果：{result_text}")
            
            full_text = "\n\n".join(parts)
            
            return {
                "case_id": case_id, 
                "case_type": case_type,
                "case_proc": case_proc, 
                "title": title, 
                "full_text": full_text,
                "parties": parties, 
                "key_facts": key_facts,
                "initial_evidence_issue": key_facts.get("evidence_issue", False),
                
                # === 返回字段优化 ===
                # 原来的 category_l1, l2, keywords 统统替换为 merged_tags
                "case_cause": keyword_payload["case_cause"], # 保留原始案由，用于最精确的过滤
                "tags": merged_tags,                         # 统一合并标签，用于Sparse和通用过滤
                "ref_laws": ref_laws,
                "amounts": amounts
            }
        except Exception as e:
            # 异常处理也需同步更新字段名
            return {
                "case_id": case_id, "case_cause": ["清洗失败"], "case_type": "清洗失败",
                "case_proc": "清洗失败", "title": "清洗失败", "full_text": "清洗失败",
                "parties": [], "key_facts": {"dispute": "", "court_findings": "", "evidence_issue": False},
                "initial_evidence_issue": False,
                "tags": [], "ref_laws": [], "amounts": []
            }


def extract_all_cases(data):
    cases = []
    if isinstance(data, dict):
        if 'CaseId' in data: cases.append(data)
        else:
            for value in data.values(): cases.extend(extract_all_cases(value))
    elif isinstance(data, list):
        for item in data: cases.extend(extract_all_cases(item))
    return cases


def get_embedding_batch(texts: List[str]) -> List[Dict[str, Any]]:
    """批量生成 BGE-M3 的 dense 和 sparse 向量"""
    output = embedding_model.encode(
        texts, 
        batch_size=EMBED_BATCH_SIZE,  # 使用模型内部批次
        return_dense=True, 
        return_sparse=True, 
        return_colbert_vecs=False
    )
    
    results = []
    for i in range(len(texts)):
        # 处理 Dense 向量
        dense_vecs = output['dense_vecs'][i].tolist()
        
        # 处理 Sparse 向量
        sparse_indices = []
        sparse_values = []
        if output.get('sparse_vecs') is not None:
            sparse_mat = output['sparse_vecs'][i]
            if sparse_mat.nnz > 0:
                indices = sparse_mat.indices.tolist()
                values = sparse_mat.data.tolist()
                # 按索引排序
                sorted_pairs = sorted(zip(indices, values), key=lambda x: x[0])
                sparse_indices = [p[0] for p in sorted_pairs]
                sparse_values = [p[1] for p in sorted_pairs]
        
        results.append({
            'dense_vecs': dense_vecs,
            'sparse_indices': sparse_indices,
            'sparse_values': sparse_values
        })
    
    return results

def run_ingestion():
    print("=== 开始优化后的入库流程 ===")
    
    # 1. 检查目录
    data_path = Path(DATA_DIR)
    if not data_path.exists():
        print(f"【错误】数据目录 {data_path.absolute()} 不存在！")
        return

    # 2. 解析 JSON 文件
    json_files = list(data_path.glob("*.json"))
    print(f"在 {DATA_DIR} 中找到 {len(json_files)} 个 JSON 文件。")
    
    if not json_files:
        print("未找到文件，请检查路径。")
        return

    client = QdrantClient(url=QDRANT_HOST, check_compatibility=False)
    cleaner = DataCleaner()
    
    test_queries = []
    vector_dim = embedding_model.model.config.hidden_size
    
    # 3. 初始化 Collection (增加 Payload 索引配置)
    try:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={"dense": VectorParams(size=vector_dim, distance=DISTANCE)},
            sparse_vectors_config={"text_sparse": SparseVectorParams()},
            optimizers_config=models.OptimizersConfigDiff(indexing_threshold=20000)
        )
        print(f"✅ Collection '{COLLECTION_NAME}' 创建成功")
    except Exception as e:
        print(f"⚠️  Collection 创建跳过 (可能已存在): {e}")

    # 为新增的过滤字段创建 Payload 索引
    try:
        # 1. 案由索引：保留原始案由数组，用于最精准的案由硬匹配过滤
        client.create_payload_index(
            collection_name=COLLECTION_NAME, 
            field_name="case_cause", 
            field_schema=models.PayloadSchemaType.KEYWORD
        )
        
        # 2. 合并标签索引：替代原来的 category_l1, l2, keywords，用于通用标签过滤和Sparse辅助
        client.create_payload_index(
            collection_name=COLLECTION_NAME, 
            field_name="tags", 
            field_schema=models.PayloadSchemaType.KEYWORD
        )
        
        # 3. 法条引用索引：用于跨库关联时的精准匹配
        client.create_payload_index(
            collection_name=COLLECTION_NAME, 
            field_name="ref_laws", 
            field_schema=models.PayloadSchemaType.KEYWORD
        )
        
        # 4. 金额索引：支持范围查询 (例如查询金额大于10万的案例)
        # 注意：由于 amounts 是一个对象数组，Qdrant 支持 amounts.amount 的嵌套索引
        client.create_payload_index(
            collection_name=COLLECTION_NAME, 
            field_name="amounts.amount", 
            field_schema=models.PayloadSchemaType.FLOAT
        )
        
        print("✅ Payload 索引创建成功")


    except Exception as e:
        print(f"⚠️  Payload 索引创建跳过 (可能已存在): {e}")

    # 4. 开始流式处理
    total_count = 0
    with open("failed_files.txt", "a", encoding="utf-8") as failed_files_log:
        
        # 批量化所需的数据结构
        batch_texts = []      # 待向量化的文本
        batch_payloads = []   # 预处理的payload
        batch_ids = []        # 预生成的ID
        
        for file_path in tqdm(json_files, desc="Processing Files"):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data_dict = json.load(f)
                    
                    if "query" in data_dict and "gt_idx" in data_dict:
                        test_queries.append({
                            "file": file_path.name,
                            "query": data_dict["query"],
                            "gt_idx": data_dict["gt_idx"]
                        })
                    
                    all_cases = extract_all_cases(data_dict)
                    print(f"文件 {file_path.name} 中找到 {len(all_cases)} 个案例。")
                    
                    for raw_case in all_cases:
                        case_id = raw_case.get('CaseId', 'unknown')
                        raw_id_str = f"{file_path.stem}_{case_id}"
                        final_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, raw_id_str))
                        
                        try:
                            # 预处理payload，但不立即计算向量
                            payload_data = cleaner.clean_single_case(str(final_id), raw_case)
                            
                            # 将文本、payload和ID添加到批次列表
                            batch_texts.append(payload_data["full_text"])
                            batch_payloads.append(payload_data)
                            batch_ids.append(final_id)
                            
                            # 当攒够一批时（比如128条），统一处理
                            if len(batch_texts) >= BATCH_SIZE:
                                # 批量计算向量
                                vectors_list = get_embedding_batch(batch_texts)
                                
                                # 构造PointStruct列表
                                points = []
                                for i, vec_data in enumerate(vectors_list):
                                    point = models.PointStruct(
                                        id=batch_ids[i],
                                        vector={
                                            "dense": vec_data['dense_vecs'],
                                            "text_sparse": models.SparseVector(
                                                indices=vec_data['sparse_indices'],
                                                values=vec_data['sparse_values']
                                            )
                                        },
                                        payload={
                                            "case_id": batch_payloads[i]["case_id"],
                                            "case_cause": batch_payloads[i]["case_cause"], # 保留
                                            "tags": batch_payloads[i]["tags"],             # 替换原有的 category 和 keywords
                                            "case_type": batch_payloads[i]["case_type"],
                                            "case_proc": batch_payloads[i]["case_proc"],
                                            "title": batch_payloads[i]["title"],
                                            "parties": batch_payloads[i]["parties"],
                                            "key_facts": batch_payloads[i]["key_facts"],
                                            "initial_evidence_issue": batch_payloads[i]["initial_evidence_issue"],
                                            "ref_laws": batch_payloads[i]["ref_laws"],
                                            "amounts": batch_payloads[i]["amounts"],
                                            "full_text": batch_payloads[i]["full_text"],
                                        }
                                    )
                                    points.append(point)
                                
                                # 批量上传
                                client.upsert(
                                    collection_name=COLLECTION_NAME,
                                    points=points
                                )
                                total_count += len(points)
                                
                                # 清空批次列表，准备下一批
                                batch_texts = []
                                batch_payloads = []
                                batch_ids = []
                        
                        except Exception as e:
                            print(f"❌ 处理案例失败，文件: {file_path.name}, 案例ID: {case_id}, 错误: {e}")
                            traceback.print_exc()
                            failed_files_log.write(f"CASE_ERROR|{file_path.name}|{case_id}|{e}\n")
                            continue

            except json.JSONDecodeError as e:
                print(f"❌ JSON 解析失败 {file_path.name}: {e}")
                failed_files_log.write(f"JSON_ERROR|{file_path.name}|{e}\n")
            except Exception as e:
                print(f"❌ 处理文件 {file_path.name} 时发生未知错误: {e}")
                traceback.print_exc()
                continue
        
        # 处理最后剩余不足BATCH_SIZE的数据
        if batch_texts:
            vectors_list = get_embedding_batch(batch_texts)
            points = []
            for i, vec_data in enumerate(vectors_list):
                point = models.PointStruct(
                    id=batch_ids[i],
                    vector={
                        "dense": vec_data['dense_vecs'],
                        "text_sparse": models.SparseVector(
                            indices=vec_data['sparse_indices'],
                            values=vec_data['sparse_values']
                        )
                    },
                    payload={
                        "case_id": batch_payloads[i]["case_id"],
                        "case_cause": batch_payloads[i]["case_cause"], # 保留
                        "tags": batch_payloads[i]["tags"],             # 替换原有的 category 和 keywords
                        "case_type": batch_payloads[i]["case_type"],
                        "case_proc": batch_payloads[i]["case_proc"],
                        "title": batch_payloads[i]["title"],
                        "parties": batch_payloads[i]["parties"],
                        "key_facts": batch_payloads[i]["key_facts"],
                        "initial_evidence_issue": batch_payloads[i]["initial_evidence_issue"],
                        "ref_laws": batch_payloads[i]["ref_laws"],
                        "amounts": batch_payloads[i]["amounts"],
                        "full_text": batch_payloads[i]["full_text"],
                    }   
                )
                points.append(point)
            
            client.upsert(
                collection_name=COLLECTION_NAME,
                points=points
            )
            total_count += len(points)

    # --- 5. 保存测试集 ---
    if test_queries:
        test_file = Path(DATA_DIR).parent / "test_queries.jsonl"
        with open(test_file, "w", encoding="utf-8") as f:
            for item in test_queries:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"✅ 测试集已保存到: {test_file} (共 {len(test_queries)} 条)")
    
    print(f"=== 入库完成！总共处理 {total_count} 条案例 ===")
    print(f"失败的文件已记录到: failed_files.txt")

if __name__ == "__main__":
    run_ingestion()

