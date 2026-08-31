# LawAgent Historical Retrieval Baselines
> 摘要：保留旧开发说明和离线 handoff 中仍有复现价值的检索基线与解释边界。
> 摘要：这些结果是历史运行证据，不代表当前在线状态，也不代表法律正确率。
> 摘要：案例 qrels 只覆盖同源 JSON 的已知正例，开放全库指标只能用于回归诊断。
> 摘要：当前集合数量和在线 smoke 以信源文档、当前 worksheet 与实际命令为准。
> 摘要：Compact reranker 历史默认融合权重为 Hybrid 0.75 / reranker 0.25。
> 摘要：重新评测必须保存版本、manifest、命令、失败项和机器可读结果。

## 数据快照

- 案例：1,146 条 query/template；92,523 条排除 query 泄漏后的语料；13,096 条局部 qrels。
- 法规：v0.2，使用 `law_family_id` / `law_version_id` 和半开有效期 `[effective_from, effective_to)`。
- 向量：BGE-M3 dense 1,024 维与 sparse lexical weights。
- 案例缺少稳定法院、案号、裁判日期、官方 URL 与权威等级时不得猜测。

历史记录同时出现法规 66,147 与 66,448 两个数量：前者是后续在线集合记录，后者是早期入库记录。新报告必须重新查询集合并记录 manifest。

## 开放全库 Case-to-Case（1,146 条）

| 方法 | HitRate@10 | Recall@10 | MRR@10 | NDCG@10 |
|---|---:|---:|---:|---:|
| Dense | 0.4974 | 0.2219 | 0.4217 | 0.2958 |
| Sparse | 0.4843 | 0.2225 | 0.4194 | 0.2964 |
| Hybrid RRF | 0.5166 | 0.2307 | 0.4319 | 0.3061 |
| 旧 Full reranker | 0.5061 | 0.2098 | 0.3943 | 0.2758 |

34.21% query 的 Hybrid Top-50 没有局部 gold。上述结果是 known-positive diagnostic，不得解释为真实全库 Recall。

## 99/100 候选闭集

| 方法 | Recall@10 |
|---|---:|
| Dense | 0.6546 |
| BGE Sparse | 0.5939 |
| Hybrid | 0.6503 |
| 等权结构标签 | 0.8108 |
| Hybrid + Structural | 0.7676 |
| Top-20 reranker | 0.7963 |

闭集可用于排序回归，但不能外推到真实口语查询。

## 法规回调与 RAGAS

历史 LegalBasis 回调中，案例回调覆盖约 59.23%，直接加回调约 59.41%；大量旧法不得自动映射为民法典。

RAGAS 仅作为 LLM proxy。曾有 75 项临时校准，56 项成功，19 项因 Provider 429 失败；临时目录结果不作为正式基线。后续必须与确定性指标分栏，并报告失败、token、成本和样本规模。

## 复现入口

入口位于 `scripts/evaluate_cases_closed_pool_v1.py`、`evaluate_joint_retrieval_v1.py`、`evaluate_reranker_grid_v1.py`、`rerank_compact_cache_v1.py` 和 `evaluate_ragas_retrieval_v1.py`。正式结果写入版本化 `data/evaluation/results/`。
