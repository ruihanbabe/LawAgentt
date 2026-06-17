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
COLLECTION_NAME = "cases_collections"
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
                        # ================= 构建用于Embedding的文本 =================
            parts = []
            
            # ✅ 优化1：标签融合进自然语言，摒弃机器格式，贴近法官写作习惯
            if merged_tags:
                tags_str = "，".join(merged_tags)
                # 模拟法官在文书开头的案由归纳（最核心的语义锚点）
                parts.append(f"本案系{tags_str}纠纷。")
            
            # ✅ 优化2：优先提取“核心匹配区”，保持原生法律文书语感
            # 原告诉称（案件事实来源，保持原汁原味）
            if accusation_text:
                parts.append(f"原告诉称：{accusation_text}")
            
            # 争议焦点
            dispute = key_facts.get('dispute', '')
            if dispute:
                parts.append(f"争议焦点：{dispute}")
                
            # 法院查明（客观事实）
            court_findings = key_facts.get('court_findings', '')
            if court_findings:
                parts.append(f"经审理查明：{court_findings}")

            # ✅ 优化3：把降维后的法条“自然地”缝回文书
            # 之前硬拼"裁判依据法规："是灾难，但现在完全不拼又丢失了强特征
            # 模拟判决书"本院认为，依照《XXX法》第X条，判决如下："的语境
            if ref_laws:
                laws_str = "，".join(ref_laws)
                if result_text:
                    parts.append(f"本院认为，依照{laws_str}，判决如下：{result_text}")
                else:
                    parts.append(f"本院认为，依照{laws_str}。")
            elif result_text:
                parts.append(f"判决结果：{result_text}")
            
            # 兜底逻辑
            if not parts:
                full_reason = raw_data.get("JudgeReason", "")
                parts.append(full_reason if full_reason else "本案详情缺失")
            
            full_text = "\n".join(parts)

            
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
        batch_size=EMBED_BATCH_SIZE,  
        return_dense=True, 
        return_sparse=True, 
        return_colbert_vecs=False
    )
    
    results = []
    for i in range(len(texts)):
        # 1. 处理 Dense 向量
        dense_vecs = output['dense_vecs'][i].tolist()
        
        # 2. 处理 Sparse 向量 (直接从 lexical_weights 提取字典，转为 indices 和 values)
        sparse_indices = []
        sparse_values = []
        lexical_weights = output['lexical_weights'][i] # M3直接返回字典 {token_id: weight}
        
        if lexical_weights:
            # 按词汇ID排序，保证顺序一致性
            sorted_items = sorted(lexical_weights.items(), key=lambda x: x[0])
            sparse_indices = [int(k) for k, v in sorted_items]
            sparse_values = [float(v) for k, v in sorted_items]
        
        results.append({
            'dense_vecs': dense_vecs,
            'sparse_indices': sparse_indices,
            'sparse_values': sparse_values
        })
    
    return results


def run_ingestion():
    print("=== 开始优化后的入库流程 ===")
    
    data_path = Path(DATA_DIR)
    if not data_path.exists():
        print(f"【错误】数据目录 {data_path.absolute()} 不存在！")
        return

    json_files = list(data_path.glob("*.json"))
    print(f"在 {DATA_DIR} 中找到 {len(json_files)} 个 JSON 文件。")
    if not json_files: return

    client = QdrantClient(url=QDRANT_HOST, check_compatibility=False)
    cleaner = DataCleaner()
    
    test_queries = [] 
    vector_dim = embedding_model.model.config.hidden_size
    
    # 初始化 Collection 和索引 (保持不变)
    try:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={"dense": VectorParams(size=vector_dim, distance=DISTANCE)},
            sparse_vectors_config={"sparse": SparseVectorParams()},
            optimizers_config=models.OptimizersConfigDiff(indexing_threshold=20000)
        )
        print(f"✅ Collection '{COLLECTION_NAME}' 创建成功")
    except Exception as e:
        print(f"⚠️  Collection 创建跳过 (可能已存在): {e}")

    try:
        client.create_payload_index(collection_name=COLLECTION_NAME, field_name="case_cause", field_schema=models.PayloadSchemaType.KEYWORD)
        client.create_payload_index(collection_name=COLLECTION_NAME, field_name="tags", field_schema=models.PayloadSchemaType.KEYWORD)
        client.create_payload_index(collection_name=COLLECTION_NAME, field_name="ref_laws", field_schema=models.PayloadSchemaType.KEYWORD)
        client.create_payload_index(collection_name=COLLECTION_NAME, field_name="amounts.amount", field_schema=models.PayloadSchemaType.FLOAT)
        print("✅ Payload 索引创建成功")
    except Exception as e:
        print(f"⚠️  Payload 索引创建跳过 (可能已存在): {e}")

    total_count = 0
    batch_texts, batch_payloads, batch_ids = [], [], []
    
    def flush_batch():
        nonlocal total_count, batch_texts, batch_payloads, batch_ids
        if not batch_texts: return
        
        vectors_list = get_embedding_batch(batch_texts)
        points = []
        for i, vec_data in enumerate(vectors_list):
            point = models.PointStruct(
                id=batch_ids[i],
                vector={
                    "dense": vec_data['dense_vecs'],
                    "sparse": models.SparseVector(indices=vec_data['sparse_indices'], values=vec_data['sparse_values'])
                },
                payload={
                    "case_id": batch_payloads[i]["case_id"],
                    "case_cause": batch_payloads[i]["case_cause"],
                    "tags": batch_payloads[i]["tags"],
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
        
        client.upsert(collection_name=COLLECTION_NAME, points=points)
        total_count += len(points)
        batch_texts, batch_payloads, batch_ids = [], [], []

    for file_path in tqdm(json_files, desc="Processing Files"):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data_dict = json.load(f)
                
                # ✅ 1. 提取 query_case 和 ctxs
                query_case = data_dict.get("query_case")
                gt_indices = data_dict.get("gt_idx", [])
                ctxs = data_dict.get("ctxs", {})
                
                if not query_case or not ctxs:
                    print(f"⚠️ 文件 {file_path.name} 缺少 query_case 或 ctxs，跳过")
                    continue

                current_query_info = None
                
                # ✅ 2. 优先处理并入库 Query Case
                query_case_id = query_case.get('CaseId', 'unknown')
                query_raw_str = f"{file_path.stem}_{query_case_id}"
                query_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, query_raw_str))
                
                query_payload = cleaner.clean_single_case(query_uuid, query_case)
                
                q_vec = get_embedding_batch([query_payload["full_text"]])[0]
                q_point = models.PointStruct(
                    id=query_uuid,
                    vector={
                        "dense": q_vec['dense_vecs'],
                        "sparse": models.SparseVector(indices=q_vec['sparse_indices'], values=q_vec['sparse_values'])
                    },
                    payload={
                        "case_id": query_payload["case_id"],
                        "case_cause": query_payload["case_cause"],
                        "tags": query_payload["tags"],
                        "case_type": query_payload["case_type"],
                        "case_proc": query_payload["case_proc"],
                        "title": query_payload["title"],
                        "parties": query_payload["parties"],
                        "key_facts": query_payload["key_facts"],
                        "initial_evidence_issue": query_payload["initial_evidence_issue"],
                        "ref_laws": query_payload["ref_laws"],
                        "amounts": query_payload["amounts"],
                        "full_text": query_payload["full_text"],
                    }
                )
                client.upsert(collection_name=COLLECTION_NAME, points=[q_point])
                total_count += 1
                
                # 暂存 query 信息
                current_query_info = {
                    "query_id": query_uuid,
                    "query_text": query_payload["full_text"],
                    "gt_indices": gt_indices,
                    "ref_laws": query_payload.get("ref_laws", []),
                    "reference_answer": query_case.get("JudgeReason", "")
                }

                # ✅ 3. 处理普通 Case (从 ctxs 字典提取)，维护 UUID 列表
                # 核心：用字典推导式按数字顺序 0, 1, 2... 提取，保证和 gt_idx 对齐
                sorted_ctx_keys = sorted([int(k) for k in ctxs.keys()])
                
                # 预分配一个足够大的列表，索引即为 ctxs 的 key
                file_case_uuid_map = {}

                for ctx_idx in sorted_ctx_keys:
                    raw_case = ctxs[str(ctx_idx)]
                    case_id = raw_case.get('CaseId', 'unknown')
                    raw_id_str = f"{file_path.stem}_{case_id}"
                    final_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, raw_id_str))
                    
                    try:
                        payload_data = cleaner.clean_single_case(str(final_id), raw_case)
                        
                        batch_texts.append(payload_data["full_text"])
                        batch_payloads.append(payload_data)
                        batch_ids.append(final_id)
                        
                        # ✅ 核心：将 UUID 放入对应的索引位置
                        file_case_uuid_map[ctx_idx] = final_id
                        
                        if len(batch_texts) >= BATCH_SIZE:
                            flush_batch()
                    
                    except Exception as e:
                        print(f"❌ 处理案例失败，文件: {file_path.name}, ctx_idx: {ctx_idx}, 案例ID: {case_id}, 错误: {e}")
                        file_case_uuid_map[ctx_idx] = None

                # ✅ 4. 文件遍历结束，根据 gt_idx 延迟赋值
                if current_query_info and file_case_uuid_map:
                    mapped_gt_case_ids = []
                    # gt_idx 是绝对索引 (如 12, 94)，直接按图索骥
                    for idx in current_query_info["gt_indices"]:
                        uuid_val = file_case_uuid_map.get(idx)
                        if uuid_val is not None:
                            mapped_gt_case_ids.append(uuid_val)
                        else:
                            # 如果在字典里找不到，或者值为 None，说明该索引的案例处理失败了
                            print(f"⚠️ 警告: 文件 {file_path.name} 的 gt_idx {idx} 未成功处理或不存在")
                    test_queries.append({
                        "query_id": current_query_info["query_id"],
                        "query_text": current_query_info["query_text"],
                        "ground_truth_case_ids": mapped_gt_case_ids,
                        "ground_truth_law_ids": current_query_info["ref_laws"],
                        "reference_answer": current_query_info["reference_answer"]
                    })

        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析失败 {file_path.name}: {e}")
        except Exception as e:
            print(f"❌ 处理文件 {file_path.name} 时发生未知错误: {e}")
            traceback.print_exc()
    
    flush_batch()

    # --- 5. 保存测试集 ---
    if test_queries:
        test_file = Path(DATA_DIR).parent / "test_queries.jsonl"
        with open(test_file, "w", encoding="utf-8") as f:
            for item in test_queries:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"✅ 测试集已保存到: {test_file} (共 {len(test_queries)} 条)")
    else:
        print("⚠️ 未提取到任何测试集数据，请检查 JSON 文件是否包含 query 和 gt_idx 字段。")
    
    print(f"=== 入库完成！总共处理 {total_count} 条案例 ===")

if __name__ == "__main__":
    run_ingestion()

