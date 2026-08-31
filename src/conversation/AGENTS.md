# Conversation 模块指引

## 职责

拥有单次交互生命周期：会话识别、历史与画像端口调用、输入 PII 处理、Runtime 调用及 Trace/结果持久化协调。不拥有 Runtime 的 Task/Artifact。

## 修改前

阅读 [`ARCHITECTURE.md`](ARCHITECTURE.md)、[`../../ARCHITECTURE.md`](../../ARCHITECTURE.md)、`harness.py`、Persistence 与 Safety 的局部指引。

## 不变量与 contract

- 会话边界稳定；保存历史、画像和 Trace 前执行要求的脱敏处理。
- Trace 未可靠持久化时不得交付候选回复；Runtime 可替换而交互生命周期不变。
- 仅经 Persistence 端口保存状态；向 Runtime 提供受控输入，不拥有其调度状态。

## 修改后验证

运行 `PYTHONPATH=src python3 -m unittest tests.test_taskboard_runtime tests.test_runtime_storage tests.test_trace_operations tests.test_http_e2e -v`。局部细节见 [`ARCHITECTURE.md`](ARCHITECTURE.md) 与 `src/persistence/AGENTS.md`。
