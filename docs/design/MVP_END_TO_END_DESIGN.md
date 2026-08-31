# LawAgent Minimum-Scenario MVP End-to-End Design
> 摘要：定义“房东不退租房押金”最小场景从输入、追问、检索、分析、审查到前端交付的完整工程流程。
> 摘要：场景用于验收，Runtime、Artifact 和充分性机制必须可复用于其他法律问题。
> 摘要：Orchestrator 是唯一全局状态推进者；Agent 只交付结构化 Artifact，Tool 只执行白名单原子能力。
> 摘要：任何实质性法律主张必须绑定法规或案例证据；证据不足时只能追问、有限回答或建设性拒答。
> 摘要：首轮实现复用现有 FastAPI、SSE、TaskBoard Runtime、Evidence DTO 和 Qdrant adapters。
> 摘要：本文是实现总入口；精确字段见 `docs/interfaces/API_CONTRACTS.md`，验收见 `docs/testing/MVP_ACCEPTANCE.md`。

## 1. 状态与范围

- 设计状态：`【已确认并开始实现】`。
- 当前代码事实：唯一TaskBoard Harness、六个受控Agent、跨Run MatterBlackboard、两轮充分性、ToolExecutor、ContextService、GLM Adapter/候选调用和统一DeliveryGate v0.2已接通；项目级`.env`配置可用。
- 当前缺口：实时Qdrant与Gate组合复验、事件日期半开区间、Trace失败门禁、完整十段响应、浏览器E2E和Redis/PostgreSQL Adapter。
- 本设计不包含：金额计算、附件解析、完整文书、外部发送、Redis/PostgreSQL 实装、多租户权限和人工律师接管。

## 2. 用户可见结果

一次请求最终只能交付下列结果之一：

| 结果 | 条件 | 用户可见内容 |
|---|---|---|
| `ASK_CLARIFICATION` | 进入检索仍缺少高价值事实 | 1–3 个不重复问题及提问原因 |
| `SUPPORTED_ANSWER` | 关键争点有适用且可引用证据 | 条件化分析、法条/案例引用、材料清单、行动建议、限制 |
| `LIMITED_ANSWER` | 仅部分争点有证据，或依赖降级 | 已支持部分、未解决缺口、补充材料和下一步 |
| `CONSTRUCTIVE_ABSTENTION` | 法域/时效/来源冲突或核心证据无法可靠解决 | 不下结论的原因、可执行补充清单和专业协助建议 |
| `SAFE_ERROR` | 模型、工具或运行时失败且无法安全恢复 | 不泄露内部异常的重试提示 |

`START_RETRIEVAL` 是内部转换，不作为本轮最终用户回复。

## 3. 端到端状态机

```text
RECEIVED
  -> INPUT_SANITIZED
  -> INTENT_ASSESSED
     -> 非法律/非援助：受控普通回复（不进入本 MVP）
     -> 法律援助：INFORMATION_ASSESSED
        -> ASK_CLARIFICATION -> WAITING_USER -> 新 run 重新评估
        -> START_RETRIEVAL -> RETRIEVAL_PLANNED
           -> EVIDENCE_RETRIEVED
           -> EVIDENCE_ASSESSED
              -> 有可修复证据缺口且预算允许：REFINED_RETRIEVAL
              -> 缺用户事实：ASK_CLARIFICATION
              -> 部分支持/无法支持：LIMITED 或 ABSTAIN
              -> 充分：RESPONSE_DRAFTED
                 -> RESPONSE_REVIEWED
                    -> 通过：DELIVERED
                    -> 可修复：REWORK（最多一次）
                    -> 不可修复：LIMITED 或 ABSTAIN
```

每次补检索必须绑定 `issue_id + gap_id`，并使用上一跳新证据或缺口；禁止同义改写式无限重试。

## 4. 最小纵向切片

| 切片 | 新增能力 | 真实入口验收 |
|---|---|---|
| S1 信息充分性 | 模型结构化评估、多轮事实合并、受控追问、`START_RETRIEVAL` | `/chat` 可完成追问与进入检索决定 |
| S2 真实检索 | RetrievalPlan、案例/法规并行检索、EvidenceBundle、空结果/失败路径 | SSE 展示检索阶段；Trace 可见证据 ID |
| S3 证据门控与回答 | EvidenceAssessment、候选回答、引用校验、材料和行动建议 | 能产出 supported/limited/abstain |
| S4 独立 Review | ReviewResult、DeliveryGate、一次重做上限 | 只有通过或降级后的 FinalResponse 可发送 |
| S5 前端验收 | 稳定 SSE 映射、状态提示、引用展示、错误/断流体验 | 浏览器完成成功、追问、有限回答和故障路径 |

每个切片独立测试、启动应用和从 `/chat` 验收；不得等 S5 才首次运行真实入口。

## 5. 模块职责

| 模块 | 输入 | 输出 | 禁止事项 |
|---|---|---|---|
| `ConversationHarness` | 原始消息、会话 ID | 脱敏输入、RunBoard、Trace | 把原始 PII 交给普通 Agent |
| `PolicyOrchestrator` | Board、Artifact、预算、策略 | 预注册 Task 和最终转换 | 开放式法律分析、直接生成答案 |
| `Intent/Sufficiency Agent` | 脱敏输入、已确认事实、已知缺口 | `InformationSufficiencyArtifact` | 确认事实真实性、生成 Qdrant filter |
| `RetrievalPlanning Agent` | 法律问题候选、事实、缺口 | `RetrievalPlanArtifact` | 任意工具名、任意数据库表达式 |
| `RetrievalAgent` | 已批准计划 | `RAGEvidenceBundleArtifact` | 接收或输出 raw payload |
| `EvidenceAssessment Agent` | EvidenceBundle、事实、事件时间 | `EvidenceAssessmentArtifact` | 凭模型记忆补法条、单独决定交付 |
| `ResponseAgent` | 已确认事实、通过门控的证据 | `CandidateResponseArtifact` | 直接写前端、无引用实质性主张 |
| `ReviewAgent` | Candidate、Evidence、政策摘要 | `ReviewResultArtifact` | 修改事实或悄悄降低安全标准 |
| `DeliveryGate` | validators + ReviewResult | `FinalResponseArtifact` 或降级任务 | 接受未验证 Candidate |

## 6. 信息充分性规则

- 判断对象是 `sufficient_for_next_step=RETRIEVAL`，不是“案件信息完整”。
- 事实分为 `user_stated`、`system_extracted`、`user_confirmed`、`document_supported`、`disputed`；候选事实不得自动升级。
- 缺口按 `blocking/high/medium/low` 排序；每轮最多问 3 个，默认优先 1–2 个。
- 已回答、用户明确不知道、已拒绝回答或语义等价的问题不得重复。
- 追问达到轮次/时间/token 预算后，内部产生 `CLARIFICATION_BUDGET_EXHAUSTED`，由 Orchestrator 决定以可用信息开始宽检索或有限终止。
- 模型结构无效、置信度低于配置阈值或输出自相矛盾时，不得进入检索；允许一次结构修复，仍失败则安全降级。
- 租房押金的典型信息（退租/交还、押金约定、拒退/扣款理由、房屋损坏或欠费争议、时间与地点）只能作为模型参考和验收样例，不能成为通用 Runtime 的固定必填表。

## 7. 检索与证据门控

### 7.1 检索

- RetrievalPlan 至少包含 `issue_id`、目标、案例/法规 source type、query terms、结构化 filter slots、事件时间和期望证据类型。
- 案例和法规可并行执行；适配器复用现有 dense+sparse RRF，并只返回 `CaseEvidenceView` / `LawEvidenceView`。
- v0 产品重排使用已确认 Compact view；当前 BGE reranker 只作为低权重/可配置信号，不能覆盖 Hybrid 排名。
- 法规事件时间必须按 `[effective_from,effective_to)` 和有效性证据复核；本地历史完整文本不足时路由权威来源或降级。

### 7.2 EvidenceAssessment 最低维度

- `fact_coverage`：关键分析前提是否来自允许的事实状态。
- `issue_coverage`：每个关键争点是否有证据。
- `authority`：法规/案例来源是否可用于当前强度的主张。
- `temporal_validity`：事件时间与法规版本是否匹配。
- `jurisdiction_fit`：法域是否明确且适用。
- `consistency`：法条、案例和事实是否冲突。
- `citability`：每个实质性主张能否绑定 Evidence ID。

门控结果只能是 `sufficient`、`partial`、`needs_more_retrieval`、`needs_user_fact`、`unsafe_to_conclude`。

## 8. 回答与 Review

候选回答固定包含：问题概括、已知事实与假设、条件化初步分析、法条/案例引用、材料清单、下一步、限制与不确定性。引用必须先进入 EvidenceBundle；案例数据缺少法院、案号、日期和官方 URL 时必须坦诚，不得猜测。

确定性 Validators 至少检查：Artifact schema、引用存在性、引用覆盖、法规时效字段、禁止承诺语、内部 ID/PII 泄漏和结果类型一致性。ReviewAgent 独立检查法律适用、证据支持、遗漏风险和可理解性。DeliveryGate 仅在两者满足策略时接受 FinalResponse。

当前 v0.2 已实现 provenance、Review、response/decision、Claim-Evidence、Evidence存在性、法规版本状态、PII、禁止承诺、内部标识和limitations结构检查，并验证supported/limited/abstention/safe-error四条SSE路径。Trace持久化、完整十段响应以及事件日期落入法规半开有效期仍是下一版门禁范围；不得把v0.2称为全部产品门槛完成。

## 9. 多轮与持久化 v0

- 当前每条 `/chat` 创建新 run，以 `session_id=user_id` 关联历史。
- S1 允许从最近脱敏历史构造 `PriorConversationSummary`，但真正影响路由的事实仍须保留来源消息引用与确认状态。
- 用户回答追问后重新运行 Sufficiency，不恢复上次模型内部状态。
- 首版继续使用存储端口的内存实现；接口稳定后再接 Redis/PostgreSQL，不让基础设施阻塞 MVP。

## 10. 可观测性与安全

Trace 必须记录 run/task/artifact ID、状态转换原因、模型/Prompt/schema 版本、工具名、query 摘要、证据 ID、耗时、预算、错误码和降级原因；不得记录隐藏思维链、密钥、raw Qdrant payload 或未脱敏正文。

## 11. 实现顺序与完成定义

实现顺序严格为 S1→S2→S3→S4→S5。完整 MVP 完成必须同时满足：真实 `/chat` 入口、至少一次真实法规和案例检索、可追溯 EvidenceBundle、证据门控、独立 Review、FinalResponse、浏览器验收、失败/有限回答路径，以及 `docs/testing/MVP_ACCEPTANCE.md` 全部门槛。

## 12. 待用户确认

1. 追问每轮默认最多 2 个、硬上限 3 个，是否接受。
2. 追问预算耗尽时，允许在非高风险问题上以已有信息启动宽检索，还是一律有限终止。
3. Review 可修复失败最多重做 1 次，是否接受。
4. 前端第一版是否仅展示用户可理解的阶段状态，不展示 Agent 名称、内部 Task 和置信度。
