# LawAgent Application, Runtime & Tool Contracts
> 摘要：定义 Web、CLI、Runtime、ScenarioPack、Model、Agent Backend、Tool、Evidence、Artifact 和错误接口。
> 摘要：契约优先且难以误用；应用层只消费本文件定义的应用契约，不依赖 Provider SDK 或 raw Qdrant payload。
> 摘要：所有外部输入和第三方响应在 seam 处校验，内部模块依赖有类型对象与稳定错误语义。
> 摘要：全局状态转换、权限、金额、引用存在性和交付裁决由确定性代码控制，LLM 只返回候选结构化结果。
> 摘要：字段仍是目标契约；当前源码已实现其中的TaskBoard、Context、ModelGateway、ToolExecutor与最小SSE子集，不能把部分实现视为完整API验收。
> 摘要：当前源码已实现日期/引用/结构门禁、十段响应、Trace fail-closed及开发态Trace/Replay/故障接口；其余REST仍是目标契约。

## 1. 通用约定

- JSON 字段使用 `camelCase`，枚举值使用 `UPPER_SNAKE_CASE`。
- ID 在代码中使用不同 branded/nominal 类型，禁止混用 Session、Conversation、Matter、Run、Artifact 和 Evidence ID。
- 时间使用带时区 ISO 8601 UTC；法规有效期使用 `[effectiveFrom, effectiveTo)`。
- 客户端提供 `Idempotency-Key`；状态修改携带 `expectedStateVersion`。
- 所有错误使用同一 Envelope；不得以 HTTP 200 包装业务失败。
- 第三方返回、模型结构化输出、Qdrant payload 和配置均视为不可信输入。

## 2. REST 资源

### 2.1 匿名会话

```text
POST   /api/sessions
DELETE /api/sessions/current
```

创建会话返回一次性 Session Token 与 `expiresAt`。服务端只保存 Token Hash。删除操作幂等，并触发咨询数据删除流程。

### 2.2 咨询与消息

```text
POST   /api/consultations
GET    /api/consultations/{consultationId}
DELETE /api/consultations/{consultationId}
POST   /api/consultations/{consultationId}/messages
GET    /api/consultations/{consultationId}/events?after=<cursor>
POST   /api/consultations/{consultationId}/document-advice
```

首版不提供咨询列表，避免匿名 Token 枚举和无必要分页接口。`document-advice` 必须由用户主动调用。

### 2.3 开发者 Trace

```text
GET /api/dev/runs/{runId}/trace
POST /api/dev/runs/{runId}/replay
POST /api/dev/faults
```

仅 `LAWAGENT_DEV_MODE=true` 时可用；配置 `LAWAGENT_DEV_TOKEN` 后必须携带
`X-LawAgent-Dev-Token`。生产配置默认以404隐藏。Trace View 不包含输入、消息或Artifact正文；
故障注入仅接受存储端口操作枚举和有界次数，不接受任意代码。

## 3. 消息提交

```text
SubmitMessageInput {
  consultationId: ConsultationId
  clientMessageId: string
  expectedStateVersion: integer
  text: string
}

SubmitMessageAccepted {
  runId: RunId
  acceptedStateVersion: integer
  eventCursor: string
}
```

文本大小、编码、归属和重复提交在入口校验。相同 `clientMessageId` 与幂等键必须返回同一逻辑结果。

## 4. 事件流

SSE/Event 统一 Envelope：

```text
RunEvent {
  eventId: EventId
  runId: RunId
  sequence: integer
  occurredAt: timestamp
  type: RUN_STARTED | STATUS_CHANGED | QUESTION_READY |
        EVIDENCE_READY | RESPONSE_READY | DEGRADED | DONE | ERROR
  payload: discriminated union
  traceId: TraceId
}
```

事件至少一次送达，客户端按 `eventId`/`sequence` 去重。`DONE` 或 `ERROR` 后连接关闭；等待用户回复不保持 SSE。

## 5. ScenarioPack 接口

```text
ScenarioPack {
  manifest(): ScenarioManifest
  qualify(input: QualificationInput): QualificationResult
  assessSufficiency(input: SufficiencyInput): SufficiencyResult
  planNext(input: PlanningInput): NextAction
  artifactSpec(kind: ArtifactKind): ArtifactSpec
}
```

`NextAction` 只允许注册动作，例如 `ASK_CLARIFICATION`、`START_RETRIEVAL`、`DELIVER_LIMITED_RESPONSE`、`OFFER_DOCUMENT_ADVICE`。ScenarioPack 不执行工具、不调用模型、不直接修改全局状态。

## 6. 事实与充分性

```text
FactCandidate {
  factId, factType, value, sourceMessageId,
  extractionConfidence, confirmationStatus
}

SufficiencyResult {
  stage: QUALIFICATION | RETRIEVAL | ANALYSIS | CALCULATION | DOCUMENT_ADVICE
  isSufficient: boolean
  missingFacts: MissingFact[]
  proposedQuestions: ClarificationQuestion[]
  nextAction: NextAction
  assessmentConfidence: number
}
```

`confirmationStatus` 至少区分 `USER_STATED`、`USER_CONFIRMED`、`INFERRED_CANDIDATE`、`DISPUTED`。候选事实不得被 Agent 自动升级。

## 7. Model 与 Agent Backend

### 7.1 调度图、所有权与预算

```text
TaskGraph {
  graphId: TaskGraphId
  graphVersion: integer
  runId: RunId
  nodes: TaskNode[]
  edges: DependencyEdge[]
  fallbackReplanUsed: boolean
}

TaskNode {
  nodeId: NodeId
  nodeType: registered NodeType
  status: PLANNED | READY | ASSIGNED | RUNNING | WAITING |
          SUCCEEDED | FAILED_RETRYABLE | FAILED_TERMINAL |
          ESCALATED | CANCELLED
  ownerRole: AgentRole
  ownerId?: WorkerId
  ownerEpoch: integer
  leaseExpiresAt?: timestamp
  budget: ExecutionBudget
  usage: ExecutionUsage
  handoffCount: integer
  maxHandoffs: integer = 3
  replanCount: integer
}

ExecutionBudget {
  maxSteps: integer
  maxTokenBudget: integer
  maxToolCalls?: integer
  maxWallClockMs?: integer
  maxCost?: decimal
}
```

`ownerId` 是调度器授予当前租约的具体执行实例；`ownerRole` 是能力要求。只有调度器可以写 owner、epoch、状态和 DAG。预算使用单调累计计数，Node → Task → Run 汇总；retry、escalate、handoff、replan 不得重置。

合法状态转换：

```text
PLANNED -> READY | CANCELLED
READY -> ASSIGNED | CANCELLED
ASSIGNED -> RUNNING | READY | CANCELLED
RUNNING -> WAITING | SUCCEEDED | FAILED_RETRYABLE |
           FAILED_TERMINAL | ESCALATED | CANCELLED
WAITING -> READY | CANCELLED
FAILED_RETRYABLE -> READY | FAILED_TERMINAL
ESCALATED -> READY | FAILED_TERMINAL
```

`SUCCEEDED`、`FAILED_TERMINAL`、`CANCELLED` 是不可离开的终态。重新进入 `READY` 只能由调度器执行并生成新的 owner epoch。

```text
EscalationRequest {
  nodeId, ownerId, ownerEpoch
  reasonCode: CAPABILITY_MISMATCH | PERMISSION_MISMATCH |
              CONTEXT_INSUFFICIENT | DEPENDENCY_BLOCKED |
              POLICY_CONFLICT | BUDGET_AT_RISK | OTHER
  safeSummary: string
  missingCapabilities: string[]
  contextRefs: Id[]
}
```

Worker 只能返回 `EscalationRequest`，不得指定新 owner 或直接调用另一个 Agent。调度器接收后增加 `handoffCount`；达到 `maxHandoffs` 时创建一次 `MergedTaskContext` 并进入 `FALLBACK_REPLAN`，之后不得清零计数。

`MergedTaskContext` 生成消耗原 Task/Run 预算；若剩余预算不足以安全合并，则直接终止/有限回答，不得另开预算。

### 7.2 ActionRecord 与循环中断

```text
ActionRecord {
  nodeId, ownerRole, actionKind, toolName?
  normalizedArgumentHash?, resultClass
  stateVersionBefore, stateVersionAfter
  artifactDeltaCount, evidenceDeltaCount
  stepDelta, tokenDelta
  actionFingerprint: sha256
}

LoopDetectionResult {
  isLoop: boolean
  rule: WINDOW_REPEAT_3 | ACTION_REPEAT_3 |
        PERIOD_1_OR_2 | ERROR_RESULT_REPEAT_3 | NONE
  fingerprintRefs: string[]
}
```

`actionFingerprint` 基于去 PII、去时间戳/随机 ID、稳定排序后的规范化动作 JSON；不得直接 hash 原始用户或 Assistant 文本。Runtime 保存最近至少五条 Tool/Assistant 动作记录。五条窗口指纹连续三次相同是强制中断条件；状态无进展的动作三连、短周期和错误结果三连同样触发。

触发时 Runtime 必须原子执行：取消当前调用、将节点标记为 `ESCALATED` 或 `FAILED_TERMINAL`、写入 `LOOP_DETECTED` Event、释放租约与资源，并把控制权交回调度器。一个 Task 只允许一次自动重规划。

### 7.3 Model 与 Backend 接口

```text
ModelProvider.generate(ModelRequest) -> ModelResponse | ModelError
AgentBackend.execute(AgentTask, AgentContext, ModelProfile) -> AgentResult | AgentError
ModelRouter.resolve(ModelProfile, RunContext) -> ResolvedModel
```

`ModelProfile` 描述能力、最大成本、最大延迟、结构化输出和回退策略，不暴露给 ScenarioPack 具体 Provider 名称。模型输出必须通过 Schema 校验后才能形成候选 Artifact。

`ModelError` 至少区分 `RATE_LIMITED`、`TIMEOUT`、`UNAVAILABLE`、`INVALID_RESPONSE`、`CONTEXT_LIMIT`、`POLICY_BLOCKED`、`CANCELLED`。

## 8. Tool 契约

```text
ToolDefinition {
  name, version, inputSchema, outputSchema
  operationClass: READ | WRITE
  sideEffectLevel: NONE | INTERNAL_REVERSIBLE |
                   EXTERNAL_REVERSIBLE | EXTERNAL_IRREVERSIBLE
  requiredCapability, requiredDataAccess
  timeoutMs, retryPolicy, idempotency
  concurrencyLimit, rateLimit, maxInputBytes, maxResultBytes
  costClass, dataClassification
  networkAllowlist[], filesystemAllowlist[]
  sandboxProfile, cachePolicy, auditLevel
  supportsDryRun, confirmationPolicy
  isCancellable, compensationPolicy?
}

ToolIntent {
  intentId, toolName, toolVersion, arguments, argumentsHash, purpose
  matterId, runId, nodeId, ownerId, ownerEpoch
  requestedOperationClass
}

CapabilityGrant {
  grantId, sessionId, matterId, runId, nodeId
  ownerId, ownerEpoch, toolName, toolVersion
  argumentsHash, allowedOperationClass, allowedDataScope
  expiresAt, nonce, signature
}

ExecutionPreview {
  previewId, intentId, toolName, argumentsHash, targetVersion?
  describedEffects[], warnings[], estimatedCost?
  isAuthoritativeDryRun: boolean
  expiresAt
}

ConfirmationGrant {
  confirmationId, previewId, intentId
  toolName, argumentsHash, targetVersion?
  confirmedBy, expiresAt, nonce, signature
}

RawToolResult {
  rawResultId, intentId, toolName, toolVersion
  outputArtifactRef?, error?, provenance
  contentHash, schemaVersion, sizeBytes
  isPartial, isTruncated, timing, usage
}

ToolResultView {
  rawResultId, resultClass, structuredContent
  evidenceRefs[], error?, provenance, limitations[]
  reducerName, reducerVersion
  originalSize, reducedSize
  isLossy, omittedFieldClasses[], isTruncated
}
```

LLM 只能产生候选 `ToolIntent`；不得持有 `CapabilityGrant`、`ConfirmationGrant`、API Key 或直接调用 Adapter。`ToolExecutor.execute(intent, executionContext)` 是唯一实现入口，负责注册表、Schema、owner epoch、能力令牌、预算、读写门禁、dry-run/确认、限流、超时、重试、幂等、取消、执行、结果持久化、Reducer 与 Trace。

查询和命令必须使用不同 ToolDefinition/Adapter 方法和最小权限凭据。`WRITE` 且具有外部副作用的工具需要有效 preview 与一次性确认；参数、目标版本、owner epoch 或权限变化会使确认失效。没有原生 dry-run 时，preview 必须标记 `isAuthoritativeDryRun=false`。

内部 Message/Matter/Artifact/Trace 持久化不要求逐次用户确认，但必须由 Orchestrator 授权并通过版本、幂等和审计约束。MVP 不允许代表用户执行外部写操作。

原始结果先保存为 `RawToolResult`，Agent 只接收 `MessageReducer.reduce(rawResultRef, reductionPolicy) -> ToolResultView`。Reducer 优先确定性处理；语义摘要计入原 Task/Run 模型预算。金额、日期、Evidence/locator、版本、错误、部分失败、来源和截断信息不得被省略或改写。外部结果中的指令文本始终是不可信数据。

首版工具：`searchStatutes`、`searchCases`、`fetchEvidence`、`calculateClaimItems`、`getTemplateReference`、`validateCitations`、`redactPii`。

## 9. Source 与 Evidence

```text
EvidenceView {
  evidenceId, sourceType, trustLevel,
  sourceRecordId, title, excerpt, locator,
  effectiveFrom?, effectiveTo?, snapshotVersion,
  retrievedAt, limitations, contentHash
}
```

`CaseEvidenceView` 额外包含相似点/差异点候选与已知数据缺陷；`LawEvidenceView` 包含 `lawFamilyId`、`lawVersionId` 和效力区间；`TemplateEvidenceView` 包含发布机构、来源 URL、核验状态和适用范围。

Agent 与 UI 不接收 raw Qdrant payload。Evidence Adapter 必须屏蔽不稳定、缺失或不可用字段。

## 10. Claim、回答与引用

```text
Claim {
  claimId, text, claimType, evidenceIds[], confidence, limitations[]
}

CandidateResponseArtifact {
  confirmedFacts, unresolvedFacts, claims,
  statuteEvidence, caseEvidence, materialChecklist,
  nextActions, calculation?, documentAdvice?, limitations
}

FinalResponseArtifact {
  response, decision,
  confirmedFacts, unresolvedFacts, claims,
  sections: {
    currentSituation, preliminaryAssessment, landlordReasonAnalysis,
    statutes, similarCases, materials, lowCostCommunication,
    formalNotice, otherRemedies, limitations
  },
  citationMap, sourceSnapshotVersions, limitations
}
```

每个实质性 Claim 必须绑定 Evidence ID。案例不得单独证明一般法律规则。引用校验失败的 Claim 必须删除或重做。
当前Python内部字段使用snake_case；API完成统一camelCase迁移前不得混用或假称已满足通用约定。
`supported_answer`必须有Claim且citationMap逐项精确匹配；limited/abstention/safe-error不得携带Claim。
受时间约束的法规Claim还必须有事件日期，且日期满足`effectiveFrom <= eventDate < effectiveTo`；开放终点视为无上界。

## 11. 确定性金额工具

```text
ClaimCalculationInput {
  confirmedInputs: MoneyInput[]
  ruleVersion: string
  requestedItems: ClaimItemType[]
}

CalculationArtifact {
  inputs, formulas, lineItems, total,
  missingInputs, ruleVersion, warnings
}
```

LLM 只提出候选项目和解释结果。工具缺少必要输入时返回 `missingInputs`，不得估算或以模型输出替代。

## 12. 文本式文书建议

```text
DocumentAdviceRequest {
  matterId, documentKind, expectedStateVersion, userAuthorized: true
}

DocumentAdviceArtifact {
  templateEvidenceIds[], requiredItems[],
  recommendedItems[], optionalItems[], missingItems[],
  claimCalculationId?, textDraft?, limitations[]
}
```

缺失信息使用显式占位符。无合格模板来源时返回 `TEMPLATE_SOURCE_UNAVAILABLE`，仍可给通用必要项检查，但不产生虚假引用。

## 13. Review 与 Delivery

```text
ReviewResultArtifact {
  decision: PASS | REVISE | LIMITED | BLOCK
  findings: ReviewFinding[]
  modelProfile?, deterministicChecks[]
}

DeliveryDecision = DELIVER | REGENERATE | LIMITED_RESPONSE | ASK | BLOCK
```

Review 模型不读取隐藏思维链。DeliveryGate 综合确定性检查与 Review，但最终裁决不由 LLM 作出。

当前运行时事件增加 `DELIVERY_ACCEPTED` 与 `DELIVERY_BLOCKED`。阻断时 Gate 生成固定 `safe_error` FinalResponse，原始失败码只进入管理员/开发 Trace，不进入用户正文；Orchestrator 不再接受裸 Candidate 或无有效 Review provenance 的 Final。

## 14. 统一错误 Envelope

```text
ErrorEnvelope {
  error: {
    code: string
    message: string
    retryable: boolean
    retryAfterMs?: integer
    details?: SafeErrorDetail
    traceId: TraceId
  }
}
```

HTTP 语义：400 格式错误；401 缺少/无效会话；403 无权访问；404 不存在；409 幂等、状态版本、owner epoch 或 lease 冲突；422 语义/DAG 校验失败；429 过载、限流或预算耗尽；503 依赖不可用；500 未分类内部错误。内部堆栈、Prompt、PII 和 Provider 原始错误不得返回客户端。

内部稳定错误码至少包括：`INVALID_TASK_GRAPH`、`INVALID_STATE_TRANSITION`、`STALE_OWNER_EPOCH`、`OWNER_LEASE_EXPIRED`、`ESCALATION_LIMIT_REACHED`、`BUDGET_EXHAUSTED`、`LOOP_DETECTED`、`FALLBACK_REPLAN_EXHAUSTED`、`TOOL_INTENT_INVALID`、`CAPABILITY_GRANT_INVALID`、`WRITE_CONFIRMATION_REQUIRED`、`CONFIRMATION_STALE`、`TOOL_TIMEOUT`、`TOOL_RESULT_TOO_LARGE`、`TOOL_REDUCTION_FAILED`。

## 15. 契约验证清单

- 每个入口均有类型化输入、输出和错误；
- 外部响应在 Adapter seam 校验；
- 事件顺序、重复和终止语义有契约测试；
- Provider 与 Fake/Replay Adapter 运行同一契约测试；
- API、CLI 和 WebUI 使用相同应用契约；
- 删除、TTL、并发冲突和 Fail-closed 有明确测试；
- 所有字段变更遵循增加优先，破坏性变更必须迁移与 ADR。
