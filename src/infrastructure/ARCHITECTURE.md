# Infrastructure 模块

负责 GLM、Qdrant、embedding、Redis、PostgreSQL 等可替换外部实现。它不定义核心业务规则；凭据不得进入代码或 Trace，外部失败不得伪装成功。当前实现分布在 `glm_provider.py`、`qdrant_tools.py`、`persistence_adapters.py` 和 embedding Adapter。
