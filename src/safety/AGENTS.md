# Safety 模块指引

## 职责

拥有风险判断、交付约束和最终安全决策，将输入、上下文或回答候选判定为允许、限制或阻断。

## 修改前

阅读 [`ARCHITECTURE.md`](ARCHITECTURE.md)、`delivery_gate.py`、`pii.py`、`law_validity.py`，以及 Runtime 与 Knowledge 的局部指引。

## 不变量与 contract

- 证据、Review、法规有效期、PII 和回答结构门禁必须 fail closed，不能由 LLM 绕过。
- DeliveryGate 是最终交付决定者；Runtime 可产出候选，但不能自行批准交付。
- Safety 消费 Evidence，不拥有检索实现；安全失败不得泄露内部详情。

## 修改后验证

运行 `PYTHONPATH=src python3 -m unittest tests.test_delivery_gate tests.test_delivery_gate_e2e tests.test_runtime_tools -v`。PII 或法规有效期改动必须覆盖对应失败路径；详见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。
