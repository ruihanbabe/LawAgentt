# API 模块指引

## 职责

拥有 HTTP 请求 DTO、路由和 SSE transport；只将已校验的 HTTP 输入转换为交互请求，并将内部结果投影为稳定外部事件。不拥有法律事实、推理或持久化规则。

## 修改前

阅读 [`ARCHITECTURE.md`](ARCHITECTURE.md)、[`../../ARCHITECTURE.md`](../../ARCHITECTURE.md)、`sse.py` 和相关 API 测试。

## 不变量与 contract

- 外部请求与 SSE 协议保持兼容；transport 不泄露内部对象、未脱敏 Trace、密钥、路径或上游异常原文。
- API 只编排 transport，不将业务推理、会话持久化或安全决策移入路由。
- 调用 `ConversationHarness`，并将其安全失败投影为对客户端安全的响应。

## 修改后验证

运行 `PYTHONPATH=src python3 -m unittest tests.test_api_sse tests.test_http_e2e -v`；涉及 Trace/SSE 失败路径时追加 `tests.test_trace_operations` 与 `tests.test_delivery_gate_e2e`。详见 [`ARCHITECTURE.md`](ARCHITECTURE.md) 和根开发指南。
