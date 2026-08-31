# LawAgent Coding Conventions
> 摘要：定义 LawAgent 深模块、依赖方向、类型、错误、Agent、Tool、证据、隐私和测试编码规则。
> 摘要：应用层只消费契约；Provider SDK、Qdrant payload 和存储实现不得泄漏到领域或 UI。
> 摘要：PolicyOrchestrator 独占全局状态转换，LLM 不决定权限、金额、SQL/filter 或最终交付。
> 摘要：候选事实、确认事实、Evidence、Claim 和 Artifact 使用不同类型与存储语义。
> 摘要：错误、重试、降级、幂等、版本和预算必须显式且可观测，禁止无界 Agent loop。
> 摘要：可机械执行的规则应下沉到 formatter、linter、Schema 与 pre-commit；工具链待远程核验。

## 1. 模块与依赖

- 使用 Module、Interface、Implementation、Seam、Adapter、Depth、Leverage、Locality 术语。
- 模块接口小而完整，隐藏复杂实现；调用方与测试跨同一 seam。
- 依赖向内：apps → application → domain/policy → ports；adapters 实现 ports。
- Provider/Agent SDK、数据库、Qdrant、Web 框架类型不得进入核心类型或应用响应。
- 一个假想 Adapter 不证明 seam；只有真实变化、隔离外部 SDK 或测试替换需要时建立。
- 依赖注入；领域逻辑返回结果，副作用由 Adapter 承担。

## 2. 类型与状态

- ID 使用名义类型；输入与输出类型分离；变体使用可穷举 discriminated union。
- 禁止巨型可变 Context；Node 只接收最小授权视图。
- FactCandidate、ConfirmedFact、Evidence、Claim、CandidateArtifact、FinalArtifact 不得复用同一弱类型字典。
- 状态修改携带 expectedStateVersion、幂等键和来源事件；旧事件不得覆盖新状态。
- 配置与 Prompt/Scenario/ModelProfile 全部版本化并进入 Trace。
- TaskGraph、TaskNode、Assignment、Lease、Budget、Usage、Escalation 和 LoopDetection 使用独立类型；禁止用自由文本或共享字典表达调度状态。
- Node 状态转换必须穷举且由调度器单点执行；Worker 不得直接改状态、依赖、owner 或 handoff 计数。
- `ownerRole` 表示能力，`ownerId` 表示当前租约实例；所有写结果操作校验 `ownerEpoch`。

## 3. Agent、Model 与 Tool

- Agent 只完成局部语义任务并返回 Schema 校验后的候选结果。
- Node 声明 ModelProfile，不硬编码 Provider/Model；Provider SDK 只在 Adapter。
- LLM 不生成 SQL、Qdrant Filter、凭据、任意工具名、权限决定或全局转换。
- ToolExecutor 统一执行白名单、Schema、权限、预算、超时、取消、错误包装和 Trace。
- Pi/Claude Agent SDK 等 AgentBackend 不可成为 MatterState 的事实源。
- Agent/Worker 不得横向转派、生成新任务或调用其他 Agent；任务不匹配时只返回结构化 `EscalationRequest`。
- 模型只能返回 `ToolIntent`；禁止在 AgentBackend、Node、UI 或 Adapter 中直接执行工具。所有实现调用必须经过唯一 `ToolExecutor`。
- 每个 ToolDefinition 独立声明超时、重试、幂等、并发/速率、大小、成本、数据等级、网络/文件范围、沙箱、审计、dry-run、确认和补偿策略；不得依赖全局默认掩盖缺项。
- CapabilityGrant 与 ConfirmationGrant 是短期、一次性、绑定参数 hash/owner epoch/数据范围的能力令牌；不得把长期凭据或 Grant 放进模型上下文。
- 查询与命令使用不同接口和最小权限凭据；读 Adapter 不得暴露写方法。
- 外部副作用写必须先 preview/dry-run 并经确认；确认后参数、目标版本或 owner 变化必须重新确认。
- Tool 原始结果与给 Agent 的 ToolResultView 分离；MessageReducer 不得覆盖原始 Artifact。
- Reducer 优先确定性压缩，语义摘要计入预算；金额、日期、locator、Evidence ID、版本、错误、来源和截断标志不得被压缩掉。

## 4. 法律证据与确定性规则

- 外部/raw 数据先校验、归一化、分级、脱敏为 Evidence DTO。
- 每个实质性 Claim 绑定 Evidence ID；案例不得替代法规证明一般规则。
- 法规版本使用 family/version ID 与半开有效期，不只用法名+条号。
- 金额、日期、期限、上限、舍入和公式用确定性代码及边界测试。
- 不推断缺失法院、案号、日期、URL、权威等级或模板来源。

## 5. 错误与并发

- 错误类型包含稳定 code、retryable、degradable、partialResult 和安全消息。
- 不吞异常、不把失败伪装为空结果、不静默降低证据/权限/Review/Trace 门槛。
- 所有重试有上限、退避、幂等和事件；所有队列有界；所有执行可取消并释放资源。
- Trace 持久化失败时法律分析 fail closed。
- `maxSteps`、`maxTokenBudget` 等使用父子单调累计预算；重试、拆分、handoff 和 replan 不得创建新预算逃逸。
- `handoffCount` 只由调度器增加，默认上限 3；到限后只允许一次兜底重规划，再失败即终止/有限回答。
- 循环指纹只使用去敏规范化动作，不 hash 或持久化原始 PII；规范化算法版本必须写入 Trace。
- SHA256 窗口规则之外必须检测无状态进展的动作三连和短周期，避免自然语言变化绕过检测。

## 6. 隐私与日志

- Agent 默认读取脱敏投影；原始 PII 不进入日志、Trace、测试 fixture 或错误响应。
- Token、密钥、完整 Prompt 和隐藏思维链禁止记录。
- 删除与 7 天 TTL 是领域可观察行为，必须通过测试，不只依赖运维约定。

## 7. API 与兼容性

- JSON camelCase；枚举 UPPER_SNAKE_CASE；统一 ErrorEnvelope。
- 外部入口和第三方响应在 seam 校验，内部不重复防御性解析。
- 公开契约优先增加可选字段；删除/改型需要迁移、弃用和 ADR。
- SSE 事件有稳定序列、去重和终止语义。

## 8. 测试与文档

- 实现与单元/契约/E2E 同切片提交；mock 调用次数不是验收。
- 新模块、错误、命令、性能和失败发现同步更新相应自愈文档。
- 稳定可机械判断的约定迁入 linter/pre-commit，文档只保留原因和例外。
