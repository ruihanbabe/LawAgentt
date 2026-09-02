# Runtime 模块指引

## 职责

拥有 Run、Task、Artifact、Event、Trace、角色 Context、工具执行和回答候选，并调度协作角色；不拥有具体法律案件事实、外部 Provider 或最终交付决定。

## 修改前

阅读 [`ARCHITECTURE.md`](ARCHITECTURE.md)、[`../../ARCHITECTURE.md`](../../ARCHITECTURE.md)、相关模型定义与 `board_runtime.py`；按触及能力继续读取 Intake、Knowledge、Safety 的局部指引。

## 不变量与 contract

- Task、Artifact 和 Event 必须可追踪；角色只接收允许的最小 Context。
- 工具调用遵守权限和契约；具体 Agent 与 LLM 实现可替换，不能改变核心数据语义。
- Runtime 消费 Intake、Knowledge 与 Safety 的能力，不接管其数据 owner 或最终 DeliveryGate 决策。
- 角色/Scheduler 判断自身能力或权限不匹配时，必须产出 `EscalationRequest`（不得自行决定下一步调度或转派对象），Schema 定义见 [`../../docs/architecture/scenario-pack-and-streaming-design.md`](../../docs/architecture/scenario-pack-and-streaming-design.md) §9.1；跨角色复用同一份定义，禁止重新声明同名但字段不同的模型。Scheduler 的产出物类型只能是 `TaskIntent` 或 `EscalationRequest` 二选一，不存在第三种返回类型。

## 修改后验证

运行 `PYTHONPATH=src python3 -m unittest tests.test_taskboard_runtime tests.test_runtime_tools tests.test_context_service tests.test_agent_model_candidates -v`；触及模型、检索或交付时追加对应模块测试。详见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。
