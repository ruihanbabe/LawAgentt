# Knowledge 模块

负责 `query/case context → retrieval → filtering → Evidence/KnowledgeContext`。拥有查询、Evidence View 和来源标识，不拥有 Qdrant 或 embedding 实现。provenance 不得丢失，Adapter 或 mock 不得被当作真实数据健康证据。知识实现位于本目录，embedding Adapter 位于 `src/infrastructure/embedder.py`。
