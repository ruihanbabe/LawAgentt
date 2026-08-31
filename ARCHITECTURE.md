# LawAgent 当前架构

本文是当前有效系统架构的顶层事实来源。它描述稳定职责、数据所有权、关键语义变化、约束和依赖方向；产品目标不等于当前实现，具体代码事实仍以代码为准。

## 请求链路

```text
HTTP POST /chat
  → API：校验请求并建立 SSE transport
  → Conversation：加载会话/画像、处理 PII、建立一次交互
  → Runtime：创建 Run/Task，调度六类角色并产出 Artifact/Event
      → Intake（当前为 Runtime 内部能力）：原始陈述 → 案件事实与信息缺口
      → Knowledge（当前为 Runtime 内部能力）：查询 → Evidence
      → Safety（当前跨 Runtime 与 DeliveryGate）：风险/候选回答 → 允许或安全失败
  → DeliveryGate：回答候选 → 可交付回答或安全错误
  → Conversation：保存 Trace 与结果
  → API：投影为 SSE 响应
```

## 一级逻辑模块

这些是依据业务职责、数据所有权、语义变化、invariants 和可替换实现识别出的逻辑边界。表中的“部分成立”表示职责已存在，但尚未形成独立代码包；不得据此虚构不存在的 `src/` 目录。

| 模块 | 状态与当前代码落点 | 职责与数据所有权 | 关键语义变化 | 必须维护的 invariants | 主要依赖 |
|---|---|---|---|---|---|
| API | 已成立：[`src/api/ARCHITECTURE.md`](src/api/ARCHITECTURE.md)、`src/api/sse.py` | 拥有 HTTP 请求 DTO、路由和 SSE transport；不拥有法律事实或推理状态 | HTTP 输入 → 已校验交互请求；内部事件 → SSE | transport 不泄露内部对象或未脱敏 Trace；业务推理不进入路由 | Conversation、配置组装 |
| Conversation | 已成立：[`src/conversation/ARCHITECTURE.md`](src/conversation/ARCHITECTURE.md)、`src/conversation/harness.py` | 拥有一次用户交互生命周期、会话历史/画像端口使用、PII 处理和 Trace 持久化协调 | 请求 + 会话状态 → Runtime 调用；Runtime 结果 → 已持久化交互结果 | 会话边界稳定；保存前执行脱敏；Runtime 可替换而生命周期不变 | Runtime、Persistence、API |
| Runtime | 已成立：[`src/runtime/ARCHITECTURE.md`](src/runtime/ARCHITECTURE.md) | 拥有 Run、Task、Artifact、Event、Trace、角色上下文和协作执行状态 | Run → Task/Artifact/Event → 回答候选 | 任务/产物可追踪；角色只接收允许的 Context；工具按权限与契约执行；具体 Agent/LLM 可替换 | Conversation、Knowledge、Safety、Provider 端口 |
| Intake | 部分成立：[`src/intake/ARCHITECTURE.md`](src/intake/ARCHITECTURE.md) | 当前拥有案件事实、信息缺口、确认程度和充分性状态；尚无独立应用边界 | 原始陈述 → 提取事实/缺口 → 澄清或可继续处理状态 | 未确认信息不能升级为已确认事实；信息不足必须可见 | Runtime；未来可独立于具体 Understanding Agent |
| Safety | 部分成立：[`src/safety/ARCHITECTURE.md`](src/safety/ARCHITECTURE.md) | 拥有风险判断、交付约束和最终安全决策；当前前置与后置检查分散 | 输入/上下文/回答候选 → 风险与约束 → 允许、限制或安全失败 | 证据、Review、法规有效期、PII、回答结构等门禁必须 fail closed；不能由 LLM 绕过 | Runtime、Knowledge、Conversation |
| Knowledge | 部分成立：[`src/knowledge/ARCHITECTURE.md`](src/knowledge/ARCHITECTURE.md) | 拥有检索查询、Evidence View 和可用知识上下文；不拥有向量数据库实现 | 查询/案件上下文 → 检索结果 → 受约束 Evidence | 来源与证据标识不能丢失；mock/Adapter 不能证明真实数据健康或法律正确性 | Runtime、Infrastructure；信源规则见 `docs/sources/SOURCE_POLICY.md` |
| Persistence | 已成立：[`src/persistence/ARCHITECTURE.md`](src/persistence/ARCHITECTURE.md) | 拥有会话、画像和 Trace 的存储 contract，以及删除、TTL、事务语义 | 内存运行状态 → 可保存/恢复的记录 | Adapter 必须服从端口语义；数据库产品不能定义业务规则；默认应用仍使用内存实现 | Conversation、Infrastructure |
| Infrastructure | 已成立：[`src/infrastructure/ARCHITECTURE.md`](src/infrastructure/ARCHITECTURE.md) | 提供 LLM、Qdrant、embedding、Redis、PostgreSQL 等可替换外部实现 | 核心端口调用 → Provider/服务调用 → 规范化结果 | 凭据不进入代码和 Trace；外部失败不能伪装成功；实现可替换且不改变核心数据语义 | 各核心端口、`.env.example`、`compose.yaml` |
| Domain | 暂缓 | 尚未识别出应脱离数据 owner、同时被多个模块稳定拥有的独立领域概念 | 暂无独立转换 | 禁止演化为 `shared/common/utils`；共享次数不能覆盖数据 owner | 待租赁特定逻辑与 Runtime 分离后再判断 |

## 依赖方向

```text
API → Conversation → Runtime
                    ├→ Intake
                    ├→ Knowledge → Infrastructure
                    └→ Safety
Conversation → Persistence → Infrastructure
Safety → Knowledge（只消费证据，不拥有检索实现）
```

核心职责依赖端口，不依赖 GLM、Qdrant、Redis 或 PostgreSQL 等具体产品。当前部分 Adapter 与核心代码仍位于同一 Python 包，这是待收敛的物理结构，不代表允许反转职责所有权。

## 当前物理结构边界

- `src/` 按稳定职责同时放置模块知识与实现代码。
- 原 `api/`、`lawagent_runtime/` 和 `lawagent_ingestion/` 已完成迁移并移除空目录。
- Intake 代码已归入 `src/intake/`；Domain 因缺少稳定 owner 不创建目录。

## 修改导航

| 修改目标 | 首先阅读 |
|---|---|
| HTTP、SSE、路由 | 本文的 API 行、`api/` 代码、`tests/test_api_sse.py`、`tests/test_http_e2e.py` |
| 会话生命周期、历史、Trace | 本文的 Conversation/Persistence 行、`harness.py`、`storage.py`、相关测试 |
| TaskBoard、角色、Context、工具 | 本文的 Runtime 行、`src/runtime/` 和 Runtime 测试 |
| 事实、澄清、充分性 | 本文的 Intake 行、`blackboard.py`、Understanding 相关实现与测试 |
| 检索、Evidence、法规来源 | 本文的 Knowledge 行、`docs/sources/SOURCE_POLICY.md`、Qdrant 测试 |
| DeliveryGate、PII、法规有效期 | 本文的 Safety 行、相关实现和 DeliveryGate 测试 |
| 环境与外部服务 | `docs/development/DEVELOPMENT.md`、`.env.example`、`compose.yaml`、Provider/Adapter 测试 |

## 历史与当前事实

仓库不维护历史归档区。已删除的 ADR、worksheet、旧 Runtime、evaluation 和 ingestion 历史不得作为当前实现指导；需要回溯时由用户明确指定 Git revision。当前状态见 `PROGRESS.md`，运行与验证命令以 `Makefile` 为准。
