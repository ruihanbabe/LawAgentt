# LawAgent Minimum-Scenario MVP Acceptance Contract
> 摘要：定义租房押金最小场景从 Runtime、后端到浏览器的可执行验收矩阵。
> 摘要：验收以用户可观察结果、安全不变量和真实证据链为主，不以 mock 调用次数代替。
> 摘要：租房样例验证产品链路，至少一个非租赁样例验证通用机制未硬编码。
> 摘要：每个纵向切片均从真实 `/chat` 或最接近真实的 Runtime seam 运行，不能只在末尾做 E2E。
> 摘要：确定性指标、LLM proxy 和人工视觉/法律审阅分栏报告，不合并为单一分数。
> 摘要：总设计见 `docs/design/MVP_END_TO_END_DESIGN.md`，字段见 `docs/interfaces/API_CONTRACTS.md`。
> 摘要：2026-08-19 当前回归基线为130项测试；该数字随新增测试增长，不替代真实Qdrant、模型、浏览器和人工验收。

## 1. 完成门槛

完整 MVP 同时满足：当前回归基线及后续新增测试全部无回归（2026-08-19 为130项）；新增契约/单元/集成/E2E 测试通过；真实 Qdrant 法规与案例各至少一次命中；回答引用可回溯；证据不足路径可见；独立 Review 和 DeliveryGate 生效；浏览器完成四条关键路径；无原始 PII、内部异常或 raw payload 泄漏。

## 2. 必测用户场景

| ID | 输入/前置 | 预期 |
|---|---|---|
| MVP-01 | “房东不退我押金” | `ASK_CLARIFICATION`；询问高信息量事实，不给法律结论 |
| MVP-02 | 已退租交房；房东称墙面损坏扣押金；用户问能否追回 | `START_RETRIEVAL`，随后法规+案例检索 |
| MVP-03 | 用户回答“不知道房东具体扣了哪些费用” | 不重复同一问题；可先宽检索或明确有限状态 |
| MVP-04 | 信息完整、证据充分 | 条件化分析、引用、材料清单、行动建议、限制 |
| MVP-05 | 法规时间版本不明或来源冲突 | `LIMITED_ANSWER` 或 `CONSTRUCTIVE_ABSTENTION` |
| MVP-06 | 案例通道失败、法规成功 | 保留法规支持部分，披露案例检索失败，不伪装全成功 |
| MVP-07 | 模型输出缺字段/非法枚举 | 不进入下一阶段；修复一次后安全降级 |
| MVP-08 | 手机号、身份证或当事人姓名进入输入 | Agent/Trace/前端无原始敏感值 |
| MVP-09 | 非租赁问题：“商家拒绝退有质量问题的商品” | 使用同一充分性接口，未要求租赁专属固定字段 |
| MVP-10 | 浏览器中途断开 SSE | 服务端停止继续消费；无重复历史和悬挂交付 |

## 3. 按切片验收

### S1 信息充分性

- Schema 对额外字段、非法枚举、矛盾 action 拒绝。
- 事实候选不能进入确认事实。
- 追问 1–3 个且每个关联 gap。
- 多轮不重复已回答或无法提供的问题。
- 租赁与非租赁样例走同一 Agent/Node/Artifact 契约。
- `/chat` SSE 能看到 clarification 或进入下一阶段的可审计事件。

### S2 真实检索

- Tool 输入只来自白名单 slots。
- 案例/法规分别生成安全 EvidenceView；不出现 raw payload。
- 空结果、超时和单通道失败有稳定错误码。
- EvidenceBundle 记录 tool call、证据 ID、去重和 warnings。
- 至少一次在线 Qdrant smoke；fake client 单测不能替代。

### S3 证据门控与回答

- 每个关键 issue 有 assessment；每个实质性 claim 有 evidence ref。
- 历史法规不确定、案例元数据缺失和空 LegalBasis 均按既有数据契约处理。
- 引用不存在、时效不明或证据冲突时不能交付 supported answer。
- 最终内容包含事实边界、材料清单、行动建议和限制。

### S4 Review/Delivery

- Candidate 不可直接成为 `accepted_artifact_id`。
- 确定性 validator 失败会阻断。
- Review reject 只允许配置上限内重做。
- FinalResponse 可回溯 Candidate、Review 和 EvidenceBundle。
- supported、limited、constructive abstention与safe error四条SSE应用seam均有确定性验收；浏览器HTTP层仍须单独验证。

### S5 前端

- 正确显示理解、检索、证据评估、生成、审查、完成/有限状态。
- 追问与最终回答视觉上区分。
- 引用可读，不展示内部 ID、Agent 名称、Prompt 或置信度。
- `error`、断流、重复提交和窄屏均有可理解体验。

## 4. 测试层级

| 层级 | 必须证明 |
|---|---|
| 单元 | Schema、事实合并、追问去重、预算、路由、引用/时效 validator |
| 契约 | Artifact、Task 依赖、Tool、SSE envelope、错误码、版本拒绝 |
| 集成 | 模型适配器、TaskBoard、Qdrant adapters、Harness、存储端口 |
| E2E | `/chat` 从输入到 clarification/final/limited/error |
| 视觉 | 桌面和移动 viewport 的关键稳定状态 |
| 安全 | PII、Prompt 注入、raw payload、异常和内部 ID 泄漏 |
| 性能 | 首事件、首次有意义状态、首文本、总时延、检索和模型分段耗时 |

## 5. 前端人工验收清单

1. 输入 MVP-01，追问在一次流中完整出现且不会显示内部工具状态。
2. 补充事实运行 MVP-02，阶段顺序合理，页面持续响应。
3. 最终回答的法条/案例引用与正文关联清楚。
4. 模拟单通道失败，页面显示有限结果而不是空白或无限加载。
5. 模拟服务错误，显示安全中文文案并恢复可提交状态。
6. 刷新或重复提交不会把上一轮 chunk 重复拼接。
7. 390px 与桌面宽度下输入、状态、正文和引用均可操作。

## 6. 性能首版记录项

设计阶段不虚构阈值。首次真实 E2E 记录：输入长度、模型/Profile、检索 top-k、轮数、TTFE、首文本时间、总耗时、各 Agent/Tool 耗时、token/费用、CPU/RAM/GPU 峰值、失败率。得到 20 次固定夹具基线后，再由用户确认回归阈值。

## 7. 禁止的验收捷径

- 用 `assert mock.called` 证明业务完成。
- 绕过 `/chat`、Harness、PII、TaskBoard 或 DeliveryGate 的“E2E”。
- 用局部 qrels 或 RAGAS 代表法律正确率。
- 只测 supported answer，不测追问、有限回答、拒答和依赖故障。
- 用静态 HTML 截图替代真实 SSE 状态变化。
- 在没有 FinalResponse 时报告 Faithfulness 或引用完整率。
