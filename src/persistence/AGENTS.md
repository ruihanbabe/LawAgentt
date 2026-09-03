# Persistence 模块指引

## 职责

拥有会话、画像和 Trace 的 repository contract，以及 TTL、删除和事务语义；提供内存实现与可替换 Adapter。

## 修改前

阅读 [`ARCHITECTURE.md`](ARCHITECTURE.md)、`storage.py`、`persistence_adapters.py`、[`../conversation/AGENTS.md`](../conversation/AGENTS.md) 与相关存储测试。

## 不变量与 contract

- Adapter 必须服从端口语义；数据库产品不能定义业务规则。
- 存储的历史、画像和 Trace 保持会话隔离、删除/TTL 语义和必要的脱敏边界。
- Conversation 经端口协调持久化；Runtime 不得直接依赖数据库客户端。
- Trace 复用池（F22）沉淀只能来自通过 `DeliveryGate` 校验的 Run，且不得存原始用户陈述文本；范例记录允许被检索作为辅助上下文，但本模块不得提供任何把范例池内容标记/返回为 `Evidence` 的读取路径。完整设计见 [`../../docs/architecture/scenario-pack-and-streaming-design.md`](../../docs/architecture/scenario-pack-and-streaming-design.md) §11，决策依据见 `DECISIONS.md` D32。

## 修改后验证

运行 `PYTHONPATH=src python3 -m unittest tests.test_persistence_adapters tests.test_runtime_storage tests.test_trace_operations tests.test_context_service -v`。触及真实 Adapter 时还需按根开发指南运行对应 service smoke；详见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。
