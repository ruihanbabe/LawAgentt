import os
import re
import uuid
import traceback
from pathlib import Path
from typing import List, Dict, Any
from tqdm import tqdm
import sys

# ================= Qdrant & 模型配置 =================
from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams, SparseVectorParams, Distance, 
    PointStruct, PayloadSchemaType, OptimizersConfigDiff,
    SparseVector
)
from FlagEmbedding import BGEM3FlagModel


# ================= 配置区 =================
LOCAL_BGE_M3_PATH = "/root/agent/models/bge-m3" 
DATA_DIR = "/root/agent/data/laws"  # 包含多个子文件夹的根目录
QDRANT_HOST = "http://localhost:6333"
COLLECTION_NAME = "laws_collections"  # 单库 Collection
DISTANCE = Distance.COSINE
BATCH_SIZE = 128
EMBED_BATCH_SIZE = 32

# ================= 模型加载 =================
print(f"⏳ 正在加载本地 BGE-M3 模型: {LOCAL_BGE_M3_PATH} ...")
embedding_model = BGEM3FlagModel(
    LOCAL_BGE_M3_PATH,
    use_fp16=True,
    use_faiss=False,
    device='cuda'
)
print("✅ BGE-M3 加载完成！(GPU Mode)")

# ================= 数据解析类 =================
class LawDataParser:
    def __init__(self):
        self.cn_num_map = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,
                          '百':100,'千':1000,'零':0}

    def _cn_to_an(self, num_str: str) -> int:
        try:
            import cn2an
            return cn2an.cn2an(num_str, mode='smart')
        except:
            return self.cn_num_map.get(num_str, 0)

    def parse_law_file(self, file_path: str) -> List[Dict[str, Any]]:
        """
        解析单个 MD 文件。
        根据 <!-- INFO END --> 分割头部与正文，提取法律名、日期，并按条切分正文。
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        law_name = "未知法律"
        effect_date = ""
        info_end_pos = content.find('<!-- INFO END')
        
        # ============ 1. 提取头部元数据 ============
        if info_end_pos != -1:
            header = content[:info_end_pos]
            
            # 提取法律名：优先匹配《》，如果没有则匹配第一个 # 开头的标题
            match_law_book = re.search(r'《(.+?)》', header)
            if match_law_book:
                law_name = match_law_book.group(1)
            else:
                match_law_title = re.search(r'^#\s+(.+)', header, re.MULTILINE)
                if match_law_title:
                    # 去除可能带有的前后空格和书名号(兼容处理)
                    law_name = match_law_title.group(1).strip().replace('《', '').replace('》', '')
            
            # 提取施行日期：匹配 xxxx年xx月xx日 + 关键字(通过/施行/发布)
            match_date = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日)\s*(?:通过|施行|发布|修正)', header)
            if match_date:
                effect_date = match_date.group(1)

        # ============ 2. 提取正文并按条切分 ============
        main_content = content[info_end_pos + len('<!-- INFO END -->'):] if info_end_pos != -1 else content
        
        current_path = []
        articles_data = []
        current_article_num = None
        current_article_lines = []

        def save_current_article():
            if current_article_num is not None:
                full_text = "\n".join(current_article_lines).strip()
                if full_text:
                    articles_data.append({
                        "law_name": law_name,
                        "effect_date": effect_date,  # 冗余存入单库
                        "article_num": current_article_num,
                        "hierarchy": "/".join(current_path),
                        "content": full_text
                    })

        for line in main_content.split('\n'):
            line_strip = line.strip()
            if not line_strip:
                continue

            # 匹配层级标题 (如 ## 第一编 总则)
            header_match = re.match(r'^(#{1,6})\s+(第[一二三四五六七八九十百千]+[编章节部分组].*)', line_strip)
            if header_match:
                level = len(header_match.group(1))
                title = header_match.group(2).strip()
                current_path = current_path[:level-1]
                current_path.append(title)
                continue
                
            # 匹配法条 (如 第一条 xxxxx)
            article_match = re.match(r'^第([一二三四五六七八九十百千]+)条\s*(.*)', line_strip)
            if article_match:
                save_current_article() # 保存上一条
                num_str = article_match.group(1)
                first_line_text = article_match.group(2)
                current_article_num = self._cn_to_an(num_str)
                current_article_lines = [first_line_text] if first_line_text else []
                continue

            # 普通文本追加到当前条
            if current_article_num is not None:
                current_article_lines.append(line_strip)

        save_current_article() # 保存最后一条
        
        return articles_data

# ================= 向量批处理函数 =================
def get_embedding_batch(texts: List[str]) -> List[Dict[str, Any]]:
    output = embedding_model.encode(
        texts, 
        batch_size=EMBED_BATCH_SIZE,  
        return_dense=True, 
        return_sparse=True, 
        return_colbert_vecs=False
    )
    
    results = []
    for i in range(len(texts)):
        dense_vecs = output['dense_vecs'][i].tolist()
        
        sparse_indices = []
        sparse_values = []
        if output.get('sparse_vecs') is not None:
            sparse_mat = output['sparse_vecs'][i]
            if sparse_mat.nnz > 0:
                indices = sparse_mat.indices.tolist()
                values = sparse_mat.data.tolist()
                sorted_pairs = sorted(zip(indices, values), key=lambda x: x[0])
                sparse_indices = [p[0] for p in sorted_pairs]
                sparse_values = [p[1] for p in sorted_pairs]
        
        results.append({
            'dense_vecs': dense_vecs,
            'sparse_indices': sparse_indices,
            'sparse_values': sparse_values
        })
    
    return results

# ================= 主入库流程 =================
def run_law_ingestion(law_dir: str):
    print("=== 开始法规单库入库流程 ===")
    
    client = QdrantClient(url=QDRANT_HOST, check_compatibility=False)
    parser = LawDataParser()
    vector_dim = embedding_model.model.config.hidden_size
    
    # 1. 初始化单库 Collection
    try:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={"dense": VectorParams(size=vector_dim, distance=DISTANCE)},
            sparse_vectors_config={"text_sparse": SparseVectorParams()},
            optimizers_config=OptimizersConfigDiff(indexing_threshold=20000)
        )
        print(f"✅ Collection '{COLLECTION_NAME}' 创建成功")
    except Exception as e:
        print(f"⚠️  Collection 创建跳过 (可能已存在): {e}")

    # 2. 创建核心索引 (支撑架构设计的过滤与关联)
    try:
        client.create_payload_index(collection_name=COLLECTION_NAME, field_name="law_name", field_schema=PayloadSchemaType.KEYWORD)
        client.create_payload_index(collection_name=COLLECTION_NAME, field_name="article_num", field_schema=PayloadSchemaType.INTEGER)
        client.create_payload_index(collection_name=COLLECTION_NAME, field_name="effect_date", field_schema=PayloadSchemaType.KEYWORD)
        print("✅ Payload 索引创建成功")
    except Exception as e:
        print(f"⚠️  Payload 索引创建跳过: {e}")

    # 3. 递归遍历所有子文件夹找 md 文件
    md_files = list(Path(law_dir).rglob("*.md"))
    print(f"🔍 找到 {len(md_files)} 个法律 MD 文件。")

    total_articles = 0
    batch_texts, batch_payloads, batch_ids = [], [], []
    
    def flush_batch():
        nonlocal total_articles, batch_texts, batch_payloads, batch_ids
        if not batch_texts: return
        
        vectors_list = get_embedding_batch(batch_texts)
        points = []
        for i, vec_data in enumerate(vectors_list):
            point = PointStruct(
                id=batch_ids[i],
                vector={
                    "dense": vec_data['dense_vecs'],
                    "text_sparse": SparseVector(indices=vec_data['sparse_indices'], values=vec_data['sparse_values'])
                },
                payload=batch_payloads[i]
            )
            points.append(point)
        
        client.upsert(collection_name=COLLECTION_NAME, points=points)
        total_articles += len(points)
        batch_texts, batch_payloads, batch_ids = [], [], []

    for file_path in tqdm(md_files, desc="Processing Laws"):
        try:
            # 解析单个文件，直接返回法条列表
            articles = parser.parse_law_file(str(file_path))
            
            if not articles:
                continue

            # 批量处理该法律下的法条
            for article in articles:
                # 核心：构造用于 Embedding 的文本 (拼接 law_name 和 hierarchy 防语义丢失)
                if article['hierarchy']:
                    embed_text = f"{article['law_name']}, {article['hierarchy']}\n{article['content']}"
                else:
                    embed_text = f"{article['law_name']}\n{article['content']}"
                
                article_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{article['law_name']}_{article['article_num']}"))
                
                batch_texts.append(embed_text)
                batch_payloads.append(article) # payload 直接存单库 schema 字典
                batch_ids.append(article_uuid)
                
                if len(batch_texts) >= BATCH_SIZE:
                    flush_batch()
                    
        except Exception as e:
            print(f"❌ 处理文件 {file_path.name} 失败: {e}")
            traceback.print_exc()
    
    # 刷入最后一批残余数据
    flush_batch()
    print(f"✅ 入库完成！共入库法条数: {total_articles}")

# ================= Main 入口 =================
if __name__ == "__main__":
    run_law_ingestion(DATA_DIR)
