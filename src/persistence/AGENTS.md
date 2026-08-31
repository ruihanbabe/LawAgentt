# Persistence 模块指引

## 职责

拥有会话、画像和 Trace 的 repository contract，以及 TTL、删除和事务语义；提供内存实现与可替换 Adapter。

## 修改前

阅读 [`ARCHITECTURE.md`](ARCHITECTURE.md)、`storage.py`、`persistence_adapters.py`、[`../conversation/AGENTS.md`](../conversation/AGENTS.md) 与相关存储测试。

## 不变量与 contract

- Adapter 必须服从端口语义；数据库产品不能定义业务规则。
- 存储的历史、画像和 Trace 保持会话隔离、删除/TTL 语义和必要的脱敏边界。
- Conversation 经端口协调持久化；Runtime 不得直接依赖数据库客户端。

## 修改后验证

运行 `PYTHONPATH=src python3 -m unittest tests.test_persistence_adapters tests.test_runtime_storage tests.test_trace_operations tests.test_context_service -v`。触及真实 Adapter 时还需按根开发指南运行对应 service smoke；详见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。
