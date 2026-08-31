# LawAgent Performance & Cost Plan
> 摘要：定义少量并发 MVP 的延迟、资源、成本、容量和回归评测，不宣称生产级 SLA。
> 摘要：目标容量为单实例同时 3–5 个咨询 Run；重点验证状态隔离、资源释放、超时和有界过载。
> 摘要：模型、Embedding/Reranker、Qdrant、存储和 SSE 分段计时，避免只看端到端总数。
> 摘要：每个 Node 与 Run 记录 token、估算费用、模型路由、重试和降级，支持生成/Review 成本选型。
> 摘要：固定环境、数据、模型、并发、预热和样本量后才建立阈值；回归必须通过 profile 定位。
> 摘要：本地无运行环境，所有数值基线与命令目前待远程测量。

## 1. 容量契约

- 单实例同时 3–5 个 Run；等待用户回复不占 Worker、模型、事务或 SSE。
- 超出上限采用有界排队或 429/503 快速拒绝，禁止无界积压。
- API 请求结束后释放模型流、GPU/CPU 任务、数据库连接和 SSE。

## 2. 指标

- 每 Node 与端到端 P50/P95/P99；首事件、首 token、总时长；
- LLM 调用次数、输入/输出 token、Provider/Model、重试和估算成本；
- dense、sparse、hybrid、rerank 和 Evidence 归一化耗时；
- CPU、RAM、GPU/显存、连接池、网络与 payload 大小；
- 失败率、过载拒绝率、空结果率、取消成功率与资源泄漏；
- 单轮、两轮澄清和完整咨询成本分解。
- 每 Run/Task/Node 的 step、token、tool、handoff 和 replan 消耗；
- READY 等待、owner 分配、租约续期、上下文合并与循环检测开销；
- `handoffCount` 到限率、`LOOP_DETECTED` 率、误报率和兜底成功率。
- 每工具 timeout/queue/execute/retry/reduction 分段耗时、并发与限流拒绝率；
- RawToolResult 大小、ToolResultView 大小、压缩比、Reducer token/成本、lossy/截断率；
- dry-run/preview、确认等待（与执行延迟分开）和 CapabilityGrant 校验开销。

## 3. 标准 workload

- 固定 30 条产品评测集中的代表子集；
- 单 Run 冷/热启动；3 与 5 并发；重复提交；取消；Provider 超时；rerank 降级；
- 等待用户回复前后资源快照，证明非活跃 Matter 不占执行资源。
- 含 DAG fan-out/fan-in、租约过期、3 次 handoff、重复动作与 ABAB 循环的合成 workload；验证预算到限时资源及时释放。
- 含小/大/超限 ToolResult、Reducer 失败、Tool timeout、限流、确认过期与 TOCTOU 的 workload；验证零旁路副作用。

## 4. Model 成本选型

按 `ModelProfile` 比较候选 Provider/Model，而不是全局选一个模型。分别为事实抽取、检索规划、法律分析、生成和 Review 记录质量/成本 Pareto 前沿。Review 可分层：确定性检查始终执行，普通输出低成本 Review，证据冲突或高影响输出升级。

## 5. 基准与 Profile

结果记录 commit、worksheet、数据/索引/模型/配置版本、硬件、预热、样本、统计量、失败和与基线差异。先测量再设阈值；阈值变化必须有 ADR 或 worksheet 证据。

回归流程：相同夹具复现 → 分离应用/模型/检索/存储/网络 → 保存 profiler 原始与摘要 → 优化 → 重跑正确性与全量测试。

## 6. 待远程填写

- 标准硬件与容器；固定 ModelProfile；基线阈值；benchmark/profile 命令；产物目录；CI 触发方式。
