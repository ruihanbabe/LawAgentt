# Knowledge 模块指引

## 职责

拥有检索查询、Evidence View、来源标识和可用知识上下文；不拥有 Qdrant、embedding 或其他外部实现。

## 修改前

阅读 [`ARCHITECTURE.md`](ARCHITECTURE.md)、[`../../docs/sources/SOURCE_POLICY.md`](../../docs/sources/SOURCE_POLICY.md)、`evidence_views.py` 与 `qdrant_tools.py`；外部配置变更还要读取 Infrastructure 指引。

## 不变量与 contract

- provenance、来源标识和法规版本信息不得丢失；Evidence 必须保持可追溯。
- Adapter、fixture 或 mock 不能被表述为真实数据健康或法律正确性的证据。
- 通过 Runtime 消费检索需求，通过 Infrastructure 使用外部能力；本模块不定义 Provider 实现。

## 修改后验证

运行 `PYTHONPATH=src python3 -m unittest tests.test_qdrant_runtime_tools tests.test_runtime_tools -v`；触及交付证据链时追加 `tests.test_delivery_gate_e2e`。详见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。
