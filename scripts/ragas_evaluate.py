#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import numpy as np

# ================= 新版导入 (RAGAS 0.2.x + LangChain 0.3.x) =================
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI
from ragas import evaluate
from ragas.dataset_schema import SingleTurnSample  # 新版数据结构
from ragas.metrics import Faithfulness, AnswerRelevancy, LLMContextRecall
from datasets import Dataset

# ================= 配置区 =================
LOCAL_BGE_M3_PATH = "/root/agent/models/bge-m3"
QWEN_API_KEY = "sk-ws-H.REXMLXY.cwkN.MEUCIQCCY2IKh1RnG6Lks8NN8wH7DXHHKIAJDhkkEdk22garoQIgTtjgY5Y02dYjcr6VwvJX7YNwitWPS0Ocibq7skihTaA"  # ← 请替换
QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
TESTSET_PATH = "/root/agent/data/test_queries.jsonl"

# ================= 1. Embedding (直接用官方 HuggingFace 接口) =================
print("⏳ 加载本地检索模型 BGE-M3...")
ragas_embeddings = HuggingFaceEmbeddings(
    model_name=LOCAL_BGE_M3_PATH,
    model_kwargs={"device": "cuda"},
    encode_kwargs={"normalize_embeddings": True}
)
print("✅ BGE-M3 加载完成")

# ================= 2. LLM =================
judge_llm = ChatOpenAI(
    model="qwen-plus",
    temperature=0.1,
    base_url=QWEN_BASE_URL,
    api_key=QWEN_API_KEY
)

# ================= 3. 你的 RAG 生成逻辑 =================
def generate_rag_response(query_text):
    """
    替换为你自己项目里的检索和生成代码！
    """
    # 🔽↓↓ 替换为你的真实代码 ↓↓
    answer = "这是大模型根据案件生成的回答。"
    contexts = ["这是检索到的相关法条或先例判决上下文。"]
    return answer, contexts

# ================= 4. 加载测试集 =================
def load_and_prepare_data():
    print(f"📖 正在从 {TESTSET_PATH} 加载测试集...")
    with open(TESTSET_PATH, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    questions, answers, contexts, ground_truths = [], [], [], []

    print("🚀 开始对测试集进行 RAG 推理...")
    for item in raw_data:
        q = item.get("query_text", "")
        gt = item.get("reference_answer", "")
        if not q or not gt:
            continue
        ans, ctx = generate_rag_response(q)
        questions.append(q)
        answers.append(ans)
        contexts.append(ctx)
        ground_truths.append(gt)

    print(f"✅ 成功准备了 {len(questions)} 条评估数据")
    return {
        "question": questions,
        "answer": answers,
        "contexts": contexts,
        "ground_truth": ground_truths
    }

# ================= 5. 主程序 =================
if __name__ == "__main__":
    eval_data = load_and_prepare_data()
    eval_dataset = Dataset.from_dict(eval_data)

    # 新版 RAGAS: 用类实例代替字符串
    metrics = [
        Faithfulness(),
        AnswerRelevancy(),
    ]

    print("\n🔥 开始 RAGAS 评估 (这可能需要几分钟)...")
    try:
        result = evaluate(
            dataset=eval_dataset,
            metrics=metrics,
            llm=judge_llm,
            embeddings=ragas_embeddings,
        )

        # 新版 result 直接是一个 DataFrame-like 对象
        print("\n" + "="*50)
        print("📊 RAGAS 评估报告")
        print("="*50)
        
        # 提取分数
        scores = result.to_pandas() if hasattr(result, 'to_pandas') else result
        faith_score = float(scores['faithfulness'].mean())
        relevancy_score = float(scores['answer_relevancy'].mean())

        print(f"Faithfulness (忠实度/抗幻觉): {faith_score:.4f}")
        print(f"Answer Relevancy (答案相关性): {relevancy_score:.4f}")

        # 保存结果
        output_file = "/root/agent/data/ragas_evaluation_results.json"
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump({
                "faithfulness": faith_score,
                "answer_relevancy": relevancy_score,
                "sample_size": len(eval_data["question"]),
                "evaluation_llm": "qwen-plus"
            }, f, indent=4, ensure_ascii=False)

        print(f"\n详细结果已保存至: {output_file}")

    except Exception as e:
        print(f"\n❌ 评估过程中发生错误: {str(e)}")
        import traceback
        traceback.print_exc()
