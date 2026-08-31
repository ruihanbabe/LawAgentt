# LawAgent System Design
> 摘要：定义求职展示型 LawAgent MVP 的模块、接口、数据流、状态、失败与部署边界。
> 摘要：首个真实纵向场景是中国大陆个人住宅租赁押金纠纷，通用性由 ScenarioPack 与 Harness 契约证明。
> 摘要：PolicyOrchestrator 独占全局状态转换权，Agent、模型和第三方 Agent SDK 只能完成局部授权任务。
> 摘要：WebUI、API、CLI 和开发者 Trace 面板消费统一应用契约；桌面端仅保留未来消费者边界。
> 摘要：Model Provider、Agent Backend、Tool、Source 与存储均通过独立 seam 接入，业务层不绑定具体 SDK。
> 摘要：本地已有TaskBoard/DeliveryGate/存储Adapter与测试；外部Qdrant、数据库、浏览器和性能仍须按当次环境核验。

## 1. 设计目标与约束

LawAgent 用一条可运行、可追溯、可评测的住宅押金咨询闭环证明 Agent Runtime 与 Harness Engineering。首版强调受控执行、证据门禁、成本路由、可恢复状态和可审计失败，不以微服务数量或高并发作为架构质量证明。

已确认约束：

- 单机模块化单体，目标同时处理 3–5 个咨询 Run；不承诺生产级 SLA。
- 纯中文文本咨询，不上传文件。
- 固定版本法规快照与案例库；不实现实时权威法规查询。
- 匿名会话，默认保存 7 天；用户可删除当前咨询。
- WebUI + API 为产品入口；CLI 用于评测、回放和诊断；Trace Viewer 位于 WebUI 开发模式。
- 轻量文书仅返回文字建议和草稿，不导出、不签名、不发送。

## 2. 顶层模块与依赖方向

```text
apps/web ─┐
apps/cli ─┼─> application contracts
future desktop ─┘         │
                           v
                 PolicyOrchestrator / Workflow
                           │
              ScenarioPack + domain state
                 │         │          │
                 v         v          v
           AgentBackend  ToolExecutor  Evidence/Delivery Gates
                 │         │          │
                 v         v          v
           ModelRouter   Adapters   Stores / Trace
```

依赖只能向内：应用壳、Provider SDK、Qdrant、数据库和第三方 Agent SDK 不得被领域模块反向依赖。

## 3. 深模块与 seam

| Module | 小接口 | 隐藏的主要复杂度 |
|---|---|---|
| `ConsultationApplication` | `submitMessage`、`getConsultation`、`deleteConsultation` | 归属校验、幂等、Run 创建、SSE 投影、删除编排 |
| `PolicyOrchestrator` | `decide(state, event, policyProfile)` | 权限、风险、预算、版本、重试、证据与 Review 门禁 |
| `ScenarioPack` | `qualify`、`assessSufficiency`、`planNext` | 场景边界、事实层级、问题策略、行动与 Artifact 规则 |
| `AgentBackend` | `execute(task, context, profile)` | SDK session、tool loop、stream、cancel、compaction |
| `ModelRouter` | `resolve(profile, runContext)` | Provider/Model 能力、成本、延迟、可用性与回退 |
| `ToolExecutor` | `execute(toolIntent, executionContext)` | 唯一工具调用入口；隐藏注册、权限、预算、门禁、执行、结果与 Trace |
| `EvidenceGateway` | `retrieve(plan)` | Qdrant 查询、rerank、DTO 归一化、PII 与来源等级 |
| `DeliveryGate` | `decide(candidate, checks, review)` | 引用、事实、金额、时效、安全和审计门槛 |

只有真实变化点建立 seam：Model Provider 至少有真实与 Fake/Replay Adapter；存储至少有开发与目标持久化 Adapter。其余假想扩展不提前暴露为公共接口。

## 4. ScenarioPack

通用 Runtime 不包含固定法律问卷。每个场景包由类型化核心规则和版本化配置组成：

- manifest：目标用户、支持/排除边界、版本与风险；
- goal catalog：常见目标和结束条件；
- fact schema：候选事实、确认规则、依赖和分层充分性；
- question policy：优先级、合并、重复抑制和两轮预算；
- issue map：争点与所需事实/证据；
- source policy、retrieval profile、evidence thresholds；
- action catalog、artifact specs、evaluation suite。

核心规则、转换和校验使用有类型代码；文案和有限阈值可配置。配置不得表达任意代码、权限决定或不受控工具调用，且版本必须进入 Trace。

## 5. 押金咨询主流程

```text
匿名会话归属与幂等检查
→ 原始消息持久化与脱敏投影
→ 风险/范围筛查
→ 押金 ScenarioPack 准入与事实增量抽取
→ 信息不足：最多两轮合并追问，等待时释放全部运行资源
→ RetrievalPlan
→ 法规与案例并行检索、rerank、Evidence DTO 归一化
→ 证据充分性与缺口判断
→ CandidateResponseArtifact
→ 确定性 Validators + 独立 Review
→ DeliveryGate
→ FinalResponseArtifact 或有限回答
→ 用户主动请求时进入金额/文本式文书建议
```

等待用户回复时只保存 MatterState，不保持 Agent、Worker、数据库事务或 SSE 长连接。每轮是短生命周期 Run；SSE 在 `done`/`error` 后关闭。

## 6. 状态与核心对象

- `Conversation`、`Message`、`AnonymousSession`；
- `Matter`、`MatterState`、`FactCandidate`、`ConfirmedFact`、`MissingFact`；
- `Run`、`Task`、`Event`、`Checkpoint`；
- `RetrievalPlan`、`Evidence`、`EvidenceGap`、`Claim`；
- `CandidateResponseArtifact`、`ReviewResultArtifact`、`FinalResponseArtifact`；
- `CalculationArtifact`、`DocumentAdviceArtifact`。

候选事实不得自动升级为确认事实。所有状态更新使用 `stateVersion` 和幂等键；旧事件不得覆盖新状态。

### 6.1 调度 DAG 与节点状态

每个进入 Runtime 的复合任务先由 Planner 产生版本化 `TaskGraph`。图必须是有向无环图；节点依赖满足后才可进入 `READY`。运行中发现新证据或缺口时，只有 `PolicyOrchestrator` 可以追加/替换节点，并在提交新图版本前重新执行无环、权限、预算与可达性校验。Worker/Agent 不得自行创建后继任务或修改依赖。

节点状态使用单一枚举：

```text
PLANNED → READY → ASSIGNED → RUNNING
                         ├→ WAITING
                         ├→ SUCCEEDED
                         ├→ FAILED_RETRYABLE
                         ├→ FAILED_TERMINAL
                         ├→ ESCALATED
                         └→ CANCELLED
```

只有调度器可以执行 `READY → ASSIGNED`、改变 owner、重新排队、重规划或取消。Worker 只能报告运行结果、心跳、等待原因或 `EscalationRequest`。

合法转换由注册表穷举：`PLANNED→READY/CANCELLED`；`READY→ASSIGNED/CANCELLED`；`ASSIGNED→RUNNING/READY/CANCELLED`；`RUNNING→WAITING/SUCCEEDED/FAILED_RETRYABLE/FAILED_TERMINAL/ESCALATED/CANCELLED`；`WAITING→READY/CANCELLED`；`FAILED_RETRYABLE→READY/FAILED_TERMINAL`；`ESCALATED→READY/FAILED_TERMINAL`。终态 `SUCCEEDED/FAILED_TERMINAL/CANCELLED` 不得离开。任何其他转换返回 `INVALID_STATE_TRANSITION`。

### 6.2 owner、租约与禁止横向转派

- `ownerRole` 表示节点所需能力，例如 retrieval、generation、review；
- `ownerId` 表示当前获分配的具体 Worker/Agent 实例，不表示永久业务归属；
- `ownerEpoch` 与 `leaseExpiresAt` 防止旧 owner 在重分配后继续写结果；
- 所有结果必须携带当前 epoch，过期结果被拒绝并进入 Trace；
- Worker 收到能力、权限或上下文不匹配的任务时，不得调用另一个 Agent 或直接转交；只返回 `ESCALATED` 与结构化原因，由调度器决定下一 owner。

### 6.3 step、token 与 handoff 预算

预算同时存在于 Run、Task 和 Node，子层消耗计入父层，禁止通过拆分节点或重规划重置：

- `maxSteps`：一次 Agent 推理、一次 Tool 调用或一次调度器认可的状态动作各计一步；
- `maxTokenBudget`：所有模型输入与输出 token 总和；
- 实现时同时支持 `maxToolCalls`、`maxWallClockMs` 和 `maxCost`，作为补充保险丝。

任何硬预算耗尽时，当前执行立即停止并返回 `BUDGET_EXHAUSTED`。调度器只能生成有限结果、请求用户输入或进入一次兜底重规划；不得静默扩大预算。

`handoffCount` 只统计调度器因 `ESCALATED` 改变 owner 的次数，普通 retry 不计入。默认 `maxHandoffs = 3`。达到上限后：

1. 冻结原 DAG 与已完成 Artifact；
2. 生成带来源映射的压缩 `MergedTaskContext`，不得丢失用户约束、证据 ID、失败原因和预算消耗；
3. 进入一次 `FALLBACK_REPLAN`；
4. 兜底仍失败、再次升级或无进展时转 `FAILED_TERMINAL`/有限回答，不重新清零 handoff。

上下文合并优先使用确定性结构化裁剪；若调用模型进行压缩，该调用计入原 Task/Run 的 step、token、时间与成本预算，不得建立独立“免费预算”。

### 6.4 循环与无进展检测

每一步生成不含原始 PII 的规范化 `ActionRecord`：节点/角色、动作类型或工具名、规范化参数 hash、结果类别、状态版本前后、Artifact/Evidence 增量和预算增量。使用稳定键排序、去除时间戳/随机 ID/自然语言措辞后计算 SHA256。

保留用户提出的硬规则：对最近五条 Tool/Assistant `ActionRecord` 计算窗口指纹；连续三个窗口指纹一致时，立即中断当前执行并进入重规划。

为避免滚动窗口规则漏掉“文本变化但没有进展”或 ABAB 循环，同时增加：

- 同一动作指纹在无 `stateVersion`、Artifact 或 Evidence 增量时连续出现 3 次；
- 最近记录出现重复周期 1 或 2，且完成两个周期仍无进展；
- 相同错误/工具结果被重复消费 3 次。

触发后记录 `LOOP_DETECTED`、匹配规则和指纹，不记录原始敏感内容；取消当前模型/工具，释放资源。每个 Task 最多自动重规划一次，重规划后再次触发则终止或有限回答。

## 7. Model Provider 与 Agent Backend

两层必须区分：

- `ModelProvider`：模型请求、结构化输出、流式响应、token、模型级错误；Anthropic/OpenAI 等属于此层。
- `AgentBackend`：session、agent loop、工具事件、取消、压缩；Pi Agent SDK、Claude Agent SDK 或自研 loop 属于此层。

Node/Agent 只声明 `ModelProfile`，例如 `fast_structured`、`retrieval_planner`、`legal_reasoning`、`grounded_generation`、`independent_review`。`ModelRouter` 用显式策略表解析为 Provider/Model；具体生成与 Review 模型在开发阶段按质量、延迟和成本评测确定。

第三方 Agent SDK 不得推进全局 Matter 状态或绕过 ToolExecutor、Trace、PolicyOrchestrator 和 DeliveryGate。

## 8. ToolIntent、ToolExecutor 与结果压缩

### 8.1 选择与执行分离

模型或 Agent 只能输出候选 `ToolIntent`，包括工具名、版本、结构化参数和业务目的；该输出不代表授权，也不能直接触达 Tool Adapter。确定性 `ToolExecutor` 是唯一执行入口，依次完成：

```text
ToolIntent
→ Schema/注册表校验
→ Policy、预算、owner epoch 与能力令牌校验
→ 读写/副作用分类
→ dry-run 或确认门禁
→ 并发、限流、超时、重试与幂等控制
→ Tool Adapter 执行
→ 原始结果持久化
→ MessageReducer 生成受限 ToolResultView
→ Trace/Event
```

AgentBackend 自带的自动 tool loop 必须关闭或接管其执行 hook，使所有调用经过 LawAgent ToolExecutor。Adapter、UI、Worker 和模型均不得旁路执行。

### 8.2 每工具独立配置

每个工具的版本化 `ToolPolicy` 至少声明：输入/输出 Schema、`READ/WRITE` 与副作用等级、超时、最大重试、幂等语义、并发上限、速率限制、step/token/cost 预算影响、最大输入/结果大小、数据分类、网络域名/文件路径允许列表、沙箱要求、缓存策略、审计级别、dry-run 能力、确认策略、可取消性和补偿/回滚能力。

所谓权限 token 是由 PolicyOrchestrator 签发的短期 `CapabilityGrant`，绑定 session/matter/run/node/owner epoch、tool、参数 hash、允许动作、数据范围、过期时间和单次 nonce。它不是暴露给模型的长期 API Key；ToolExecutor 消费后即失效。

### 8.3 读写分离与写门禁

- 查询与命令使用不同 ToolDefinition、Adapter 方法和最小权限凭据；读权限不能升级为写。
- 外部、不可逆或高影响写操作默认 `DENY`；进入未来范围时必须先 dry-run 生成 `ExecutionPreview`。
- 有原生 dry-run 的工具调用真实 dry-run；没有时只做本地计划/参数/影响预览，必须明确 `isAuthoritativeDryRun=false`，不得假装上游已验证。
- 用户二次确认产生一次性 `ConfirmationGrant`，绑定 preview/tool/参数/目标/预期版本 hash 与过期时间。执行前重新校验授权和目标版本，防止确认后参数变化或 TOCTOU。
- 任意参数、目标、权限、owner epoch 或 preview hash 变化都会使确认失效；重试不得复用已消费令牌。
- 内部 Message/Trace/Matter/Artifact 持久化属于受 Orchestrator 管理的系统状态写入，不逐次请求用户确认，但仍需权限、幂等、版本和审计。MVP 明确禁止代表用户执行对外写操作。

### 8.4 ToolResult 与 MessageReducer

Tool Adapter 返回的原始结果先按保留策略写入受控 `RawToolResult`/Artifact Store，并记录内容 hash、工具/Schema 版本、查询参数 hash、来源、时间、截断和错误。模型只接收 `MessageReducer` 生成的有界 `ToolResultView`。

Reducer 优先执行确定性解析、字段选择、去重、分块和硬上限；只有确需语义摘要时才调用模型，该调用计入原 Task/Run 预算并使用低权限 Profile。Reducer 不得丢失或改写：错误/部分失败、权限/来源、金额、日期、法条/案例 locator、Evidence ID、版本、置信度和截断标志。

`ToolResultView` 必须带原始 Artifact 引用、reducer/version、input/output token/字符数、lossy 标志与遗漏字段类别。来自外部工具的指令性文本按不可信数据处理，不得提升为系统指令。压缩失败时返回结构化错误或安全截断视图，不把原始超大结果直接塞入模型上下文。

## 9. 数据、隐私与保留

- 原始消息进入独立 `MessageStore`；Agent 默认读取脱敏投影。
- Trace 记录 ID、脱敏摘要、版本、状态转换和调用元数据，不复制完整原文、原始 PII、密钥或隐藏思维链。
- Fact/Evidence/Artifact 保留来源 ID。
- 匿名 Session Token 只允许访问绑定咨询；服务端仅保存 Token Hash。
- 原始消息、Matter、可识别 Artifact 与关联 Trace 默认 TTL 7 天；用户删除后访问立即失效。
- 用户案件内容不得写回公共法规、案例、Prompt 或 Skill 资产。

TTL 执行、删除级联和备份删除语义在存储 Adapter 确定后形成 ADR 与故障测试。

当前实现提供两个正式端口适配器：Redis保存最小匿名画像并使用有界TTL、版本递增和删除；
PostgreSQL以参数化SQL保存Run、Blackboard、History、AgentMessage和Trace。客户端/连接工厂由组装层注入，
领域Runtime不导入具体数据库SDK。Trace必须先成功持久化，Harness才可发布助手历史和返回接受产物。

## 10. 错误、降级与交付

错误必须包含稳定代码、可重试性、可降级性、部分结果和用户安全消息。主要规则：

- 两轮后仍不足：已知事实、缺失项和一般建议；
- 法规为空：不交付确定法律结论；案例为空：可基于法规有限分析；
- 法规版本冲突：展示冲突并要求权威复核；
- rerank 失败：可使用 Hybrid 原始排序并标记降级；
- 生成失败：只返回安全结构化摘要；Review 失败：不交付开放式法律分析；
- 引用校验失败：删除主张或重做；金额缺输入：不估算；模板源为空：只给必要项；
- 过载：快速返回可重试错误；Trace 持久化失败：法律分析 fail closed。
- owner/租约冲突：拒绝旧 epoch 写入并由调度器重新判定；禁止 Worker 私下转派；
- budget、handoff 或 loop 上限：取消当前执行，最多一次兜底重规划，之后终止或有限回答。
- ToolIntent 未授权、令牌过期、确认不匹配或写操作未确认：不得执行，返回稳定门禁错误；
- Tool 超时/结果过大/Reducer 失败：保留原始审计引用，按工具策略重试、截断或降级，不向模型透传不受控结果。

## 11. 部署与容量

- 单机模块化单体；API 与受控执行可同进程起步。
- 不预引入 Kafka/NATS/Kubernetes；数据库任务表或受控进程内执行足够。
- 同时 3–5 个 Run；超出上限明确拒绝或有界排队。
- 必须验证并行 Matter 隔离、重复提交幂等、超时/取消和请求结束后的模型、GPU、连接释放。

## 12. 应用表面

- WebUI：咨询、追问、证据卡片、行动建议、文字文书建议。
- API：唯一正式应用入口与稳定错误语义。
- CLI：评测、Replay、故障注入和诊断。
- Trace Viewer：开发模式下读取脱敏 Trace View，不是独立应用。
- 桌面端和管理后台：Future，只消费既有应用契约。

当前Trace Viewer、Replay和白名单存储故障注入只在`LAWAGENT_DEV_MODE=true`开放；生产默认404隐藏，
可再用独立开发Token保护。Replay创建新Run并记录源Run ID，不复用原会话Blackboard的可变状态。

## 13. 第三方项目采用策略

- Craft Agents：分层参照，不复制目录。
- Pi/Claude Agent SDK：AgentBackend 候选，形成能力矩阵与 ADR。
- 每项能力选择直接采用、Adapter 包装、借鉴自研或 MVP 不需要。
- LawAgent 始终保有领域 Workflow、权限、证据和交付控制权。

## 14. 待远程核验

- 历史 FastAPI、Runtime、Taskboard、SSE、Qdrant Adapter 和测试的真实代码状态；
- Qdrant collections、数据版本、Schema、manifest 与在线 smoke；
- 可用 Model Provider、凭据、成本与结构化输出能力；
- PostgreSQL/内存存储现状、真实运行命令、依赖和性能基线。
