# LawAgent Task Queue
> 摘要：按纵向切片维护远程核验、MVP 实现、评测、工具和治理任务。
> 摘要：Ready 任务必须无需新增产品决策；所有实现任务先运行真实应用并留下测试与 Trace 证据。
> 摘要：当前 P0 是恢复真实Qdrant服务后验证已扩展的DeliveryGate，并补真实存储与浏览器引擎验证。
> 摘要：任务状态使用 Inbox、Needs Decision、Ready、In Progress、Blocked、Done。
> 摘要：完成必须包含应用、测试、Review、文档、worksheet、commit 和同名 tag 证据。
> 摘要：外部权限、模型或工具不可用时登记验证债务，不用自查冒充。

| ID | 状态 | P | 任务 | 验收标准 | Worksheet |
|---|---|---:|---|---|---|
| DOC-002 | In Progress | P0 | 初始化 MVP 产品与架构文档 | 正式文档齐全、冲突扫描通过、Review/债务记录 | WS-20260815-01-mvp-product-architecture |
| DOC-003 | In Progress | P0 | 定义 Agent 调度、owner、预算、escalation 与循环保险丝 | System/API/ADR/Test/Workflow 一致，阈值与降级明确 | WS-20260819-01-agent-loop-guards |
| DOC-004 | In Progress | P0 | 定义 ToolExecutor、读写确认与 MessageReducer | 唯一执行入口、独立 ToolPolicy、Grant/Preview/Reducer 契约和测试一致 | WS-20260819-01-agent-loop-guards |
| DOC-005 | In Progress | P0 | 同步源码进度与状态文档 | Handoff/Status/Worksheet/TODO/测试工具文档与119项基线一致；Review/commit/tag债务明确 | WS-20260819-04-progress-sync |
| DOC-006 | In Progress | P0 | 仓库收敛为五问 System of Record | 五问入口、预检/运行/验证命令、旧 handoff 迁移与核心测试通过；Review/commit/tag待完成 | WS-20260819-07-repository-system-of-record |
| DOC-007 | In Progress | P0 | 根目录统一项目进度入口 | PROGRESS明确已完成/进行中/阻塞，其他动态文档职责不重叠；Review/commit/tag待完成 | WS-20260819-09-root-progress |
| GOV-005 | In Progress | P1 | 根目录标准 Make 命令 | setup/test/lint/check/run/服务命令可发现且如实失败；Review/commit/tag待完成 | WS-20260819-10-standard-make-commands |
| REMOTE-001 | Done | P0 | 核验代码、运行、数据和 Qdrant | 98项测试、真实API、集合与RAG smoke | WS-20260819-02-multi-agent-mvp |
| SLICE-001 | In Progress | P0 | 匿名文本准入、事实状态与两轮追问 | 核心链路完成；幂等键/并发版本冲突待补 | WS-20260819-02-multi-agent-mvp |
| SLICE-002 | In Progress | P0 | 法规/案例检索与安全 Evidence DTO | ToolExecutor与真实RAG完成；空结果/超时故障注入待补 | WS-20260819-02-multi-agent-mvp |
| CTX-001 | In Progress | P0 | 六角色最小权限 ContextView 与 ContextService | 角色白名单、来源审计、裁剪、provenance和模型候选消费已完成；真实GLM smoke待补 | WS-20260819-03-context-glm |
| SLICE-003 | In Progress | P0 | Claim、生成、Review 与 Delivery Gate | 日期半开区间、十段响应、四路SSE与Trace fail-closed完成；真实Qdrant待恢复 | WS-20260819-08-platform-completion |
| SLICE-004 | In Progress | P1 | Dev Trace Viewer、Replay 与故障注入 | 实现和HTTP契约通过；浏览器视觉与生产隔离复核待补 | WS-20260819-08-platform-completion |
| SLICE-005 | Blocked | P1 | 金额工具与文本式文书建议 | 确定性计算、用户授权、模板空状态、文字输出 | 待建 |
| SLICE-006 | In Progress | P0 | 完成事件日期、类型化回答、Trace/Replay、存储与HTTP/Qdrant E2E | 代码及147项离线验证完成；真实Qdrant/Redis/PostgreSQL、浏览器、Review和Git收尾待补 | WS-20260819-08-platform-completion |
| STORE-001 | In Progress | P0 | 安装并验证真实 Redis/PostgreSQL | 客户端、容器、TTL/事务 smoke 完成；应用组装与重启/删除级联E2E待补 | WS-20260819-11-persistence-services |
| MODEL-001 | In Progress | P1 | GLM 免费模型 Profile 路由和角色接入 | Adapter、六Profile、角色调用及质量矩阵脚本完成；环境缺Key，真实smoke待跑 | WS-20260819-05-delivery-gate-glm |
| EVAL-001 | Blocked | P1 | 建立 30 条固定评测集 | 分类齐全、硬门禁、人工 rubric、30/30 Trace | 待建 |
| SDK-001 | Ready | P1 | 比较现有 Runtime、Pi、Claude Agent SDK | 使用 research skill 产出矩阵、可运行证据和 ADR | 待建 |
| GOV-001 | Blocked | P2 | 建立 verify/review/lint/benchmark 工具入口 | 统一命令可执行并有自身测试 | 待建 |
| GOV-002 | Blocked | P1 | 实现 TaskGraph 与 Agent Loop Guard 工具 | DAG/租约/预算/handoff/指纹规则通过契约、并发和故障测试 | 待建 |
| GOV-003 | Blocked | P1 | 实现 Tool Registry 校验、写门禁与 Result Reducer | 无旁路调用；每工具 Policy 完整；确认/TOCTOU/压缩保真测试通过 | 待建 |
| GOV-004 | Ready | P2 | 补齐文档声明但缺失的 workflow skills | 建立并验证 handoff-maintainer 等目录清单声明的 skills，或修正文档清单 | WS-20260819-04-progress-sync |

阻塞说明：真实模型按用户要求不重复消耗；真实Qdrant端口、Redis/PostgreSQL服务和浏览器引擎当前不可用，但不阻塞确定性 Harness 继续开发。
