# Intake 模块指引

## 职责

拥有案件事实、信息缺口、确认状态和充分性判断，将原始陈述演化为可继续处理或需澄清的案件状态。Understanding 角色仍由 Runtime 调度。

## 修改前

阅读 [`ARCHITECTURE.md`](ARCHITECTURE.md)、`blackboard.py`、[`../runtime/AGENTS.md`](../runtime/AGENTS.md) 和相关 Understanding 测试。

## 不变量与 contract

- 未确认信息不得升级为已确认事实；信息不足和澄清需求必须保持可见。
- Intake 维护事实状态，不接管 Runtime 调度、检索实现或最终安全决策。
- 对 Runtime 暴露稳定的案件状态，避免引入租赁场景以外的隐式业务规则。

## 修改后验证

运行 `PYTHONPATH=src python3 -m unittest tests.test_agent_model_candidates tests.test_taskboard_runtime -v`；变更影响案件状态跨轮保存时追加 `tests.test_runtime_storage`。详见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。
