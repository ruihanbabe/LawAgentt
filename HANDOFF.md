# LawAgent Active Handoff
> 摘要：交接本地产品与架构重构后的当前状态、已确认决策、未核验事实和远程下一步。
> 摘要：住宅押金咨询已成为完整 MVP 纵向切片，用于证明通用 Runtime 与 Harness Engineering。
> 摘要：PRD、Feature、System Design、C4、API、Source、Testing、Performance、Coding 与 ADR 已建立正式边界。
> 摘要：当前已有源码、测试、Qdrant 数据和运行环境；多 Agent/RAG 最小链路已通过真实验证。
> 摘要：旧离线与规划 handoff 已完成迁移并删除；历史检索基线保存在正式测试文档。
> 摘要：统一DeliveryGate已加入日期半开区间、十段Schema和Trace fail-closed；Trace/Replay、存储Adapter及ASGI HTTP E2E已落地。

## 当前阶段

当前完成项、进行中工作和阻塞统一见根目录 `PROGRESS.md`；本文只保留接手上下文、环境事实与恢复步骤，避免重复维护进度副本。

唯一产品 Runtime 已收敛为 `AgentRunBoard + TaskBoardRuntime`。Safety、Understanding、Retrieval、Analysis、Response、Review 六角色、跨 Run MatterBlackboard、两轮追问和 ToolExecutor RAG 已接通。

六角色最小权限 ContextView 已由 ContextService 统一构建；GLM OpenAI 兼容 Adapter 与六个免费模型 Profile 已实现。`ModelGateway` 已通过 `StructuredModelRunner` 注入六角色：模型只生成结构化候选，确定性基线继续控制风险下限、事实确认、工具名、Evidence ID 与最终 Review。真实 GLM smoke 仍需要运行环境注入新 Key。

统一 `DeliveryGate` 已成为 Orchestrator 唯一交付入口，不再接受裸 `RESPONSE_CANDIDATE` 或无 Review 的 Final。v0.1 检查 Candidate→Review→Final provenance、Review 状态、响应与决策类型、Claim-Evidence 映射、Evidence Bundle 存在性、法规版本状态和 PII；失败时只生成确定性 `SAFE_ERROR`。成功与阻断两条 SSE 应用入口测试已通过。

v0.2 新增禁止胜诉/追回承诺、内部 run/task/artifact/model ID 泄漏和回答限制项结构检查；法规版本未确认时由 Analysis 产生 `constructive_abstention`，检索不可用时产生 `limited_answer`。成功、Gate阻断、有限回答、建设性拒答四条SSE应用 seam 均已有离线E2E。

本轮继续加入事件日期提取和法规 `[effectiveFrom,effectiveTo)` 判定、类型化十段
`FinalResponseContent`、Trace持久化失败禁止交付。开发模式提供脱敏Trace View、Replay和白名单故障注入；
Redis/PostgreSQL正式Adapter已实现并通过Fake客户端契约测试。HTTP流式测试统一改用
`httpx.AsyncClient + ASGITransport`，避免当前Starlette TestClient组合卡死。

## 已确认 MVP

- 用户：中国大陆个人住宅承租人；押金拒退、少退或拖延。
- 入口：匿名中文纯文本 Web 咨询；默认保存 7 天；用户可删除。
- 流程：准入 → 最多两轮追问 → 法规/案例 → 证据受限分析 → 材料/行动 → 用户主动文本式文书建议。
- 信源：固定法规快照 S2 + 案例 S3；模板 S4 预留；不实现实时 S1。
- 架构：单机模块化单体，3–5 并发 Run；Web/API、CLI、Dev Trace；桌面端延期。
- Harness：PolicyOrchestrator 全局控制；ScenarioPack 领域规则；ModelProvider 与 AgentBackend 分层；确定性 Delivery Gate。
- 调度保险丝：版本化 DAG；Scheduler 独占 owner/status；ownerRole + ownerId/epoch/lease；step/token 父子预算；Worker 只能 escalate；默认 3 次 handoff + 一次 fallback replan；去敏 SHA256 循环检测。
- 工具保险丝：模型只产出 ToolIntent；唯一 ToolExecutor 执行；每工具独立 Policy；读写分离；外部写 preview/dry-run + 一次性确认；RawToolResult 经 MessageReducer 压缩后才进入 Agent。
- 评测：30 条固定样例；硬门禁零串扰、零伪造引用、零 LLM 金额、零越权交付。

## 正式文档入口

- 产品：`docs/product/requirements.md`
- Feature：`docs/features/rental-deposit-consultation.md`
- 系统：`docs/design/SYSTEM_DESIGN.md`
- C4：`docs/architecture/lawagent-c4.md`
- 契约：`docs/interfaces/API_CONTRACTS.md`
- 信源：`docs/sources/SOURCE_POLICY.md`
- 决策：`docs/decisions/ADR-0001-mvp-runtime-and-application-surfaces.md`
- 调度决策：`docs/decisions/ADR-0002-orchestrated-task-ownership-and-loop-guards.md`
- 工具决策：`docs/decisions/ADR-0003-tool-execution-and-result-reduction.md`
- 测试/性能：`docs/testing/TESTING.md`、`PERFORMANCE.md`
- 第三方研究 Skill：`skills/research-agent-backends/SKILL.md`

## 已核验运行事实

FastAPI/SSE、TaskBoard Harness、Qdrant Adapter 与本地 BGE-M3 均曾实际运行；案例集合92,523点、法规集合66,147点均green，CPU真实RAG曾分别返回5条法规与5条案例并进入Evidence Bundle。2026-08-19 当前源码 `compileall` 通过，完整 unittest 为147/147。本轮Qdrant容器报告Started后端口仍不可达，Redis/PostgreSQL服务与浏览器引擎也不可用；这些外部验证未通过，不能用历史或Fake证据替代。

## 远程入口

`ssh root@111.127.52.27 -p 30277`。服务器由用户手动开启；不得自动连接、启动或执行付费任务。本文不保存凭据。

## 下一接手步骤

1. 不自动重跑完整六角色矩阵；现有真实结果为4角色成功、Safety/Review限流，用量2,395输入/4,595输出token。任何补跑先获用户确认并降低输出上限。
2. 先恢复Qdrant端口，再用一个固定输入做Qdrant+DeliveryGate组合验证；无需调用GLM。
3. Redis/PostgreSQL 客户端、Compose 服务与真实 TTL/事务 smoke 已完成；下一步将 Adapter 接入应用组装并验证重启恢复、7天TTL与删除级联。
4. 提供Playwright或浏览器二进制后跑Web提交、SSE消费和Trace Viewer浏览器E2E；当前仅ASGI HTTP通过。

## 保留与删除说明

- 已删除旧 `docs/design/lawagent-design-doc.md`，内容已迁入正式 System Design、API、Source 与 ADR。
- 两份旧 handoff 已删除：产品决策已进入正式文档，唯一历史检索数据已迁入 `docs/testing/RETRIEVAL_BASELINES.md`。
- `DEVELOPMENT.md` 已收敛为运行手册，不再保存架构副本和会话历史。
