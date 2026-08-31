# LawAgent Testing & Evaluation Plan
> 摘要：定义实现同步测试、30 条固定产品评测、E2E、引用/事实门禁、故障注入和虚假信心审计。
> 摘要：硬门禁是事实串扰、伪造引用、LLM 自行计算金额和越权交付为零，不能被平均分抵消。
> 摘要：业务、Agent 契约、RAG、法律证据、Review、性能和用户界面指标分开报告。
> 摘要：不完整 qrels、RAGAS 和 LLM Judge 不得包装为真实全库 Recall 或法律正确率。
> 摘要：每条固定样例必须产生可检查 Trace；失败样例单独报告原因与降级行为。
> 摘要：当前已有147项本地单元/契约/ASGI HTTP测试；真实模型、实时Qdrant、浏览器引擎、视觉和性能仍须分开验证。

## 1. 测试层级

- 单元/属性：状态转换、事实升级、有效期、金额、预算、引用和删除/TTL。
- 契约：API/SSE、ScenarioPack、ModelProvider、AgentBackend、Tool、Evidence、Artifact、Error。
- 集成：MessageStore、MatterStore、TraceStore、Qdrant、真实 Model Adapter、Replay。
- E2E：Web/API 从匿名会话到追问、检索、Review、交付、文书建议和删除。
- 视觉：回答十段结构、证据卡片、错误/降级、Trace 面板和窄屏状态。
- 恢复/故障：429/5xx、超时、取消、重复事件、旧 stateVersion、空检索、Trace 失败。
- 性能/成本：见 `PERFORMANCE.md`。

## 2. 固定 30 条 MVP 评测集

- 12 条正常押金咨询；
- 6 条信息不足和两轮追问；
- 4 条超出支持范围；
- 4 条证据为空、冲突或版本问题；
- 4 条安全、Prompt Injection、金额和状态隔离反例。

每条夹具包含：用户输入轮次、期望准入、关键事实/缺口、允许 Evidence 类型、禁止 Claim、预期降级、硬门禁与人工 rubric。不得把生产用户数据直接加入评测集。

## 3. 验收阈值

- 硬门禁：串扰、伪造引用、模型自行算金额、越权交付均为 0。
- 场景路由和结构化契约 ≥95%。
- 人工评审的证据支持与行动建议 ≥85%。
- 30/30 样例有完整、脱敏、可检查 Trace。
- 所有失败按类型单列，不只报告平均分。

## 4. Claim-Evidence 评测

分别验证引用存在、locator 正确、Evidence 是否支持 Claim、法规时间/法域是否匹配、案例是否被过度类推。确定性检查覆盖存在性与映射；人工或独立 Review 覆盖语义支持。

## 5. Model 选型评测

生成与 Review 模型使用相同固定样例比较：任务成功、Schema 合规、引用支持、遗漏/幻觉、Review 真阳性/误报、P50/P95、token 和单 Run 成本。具体 Provider/Model 只有通过该门后才能写入版本化 ModelProfile 与 ADR。

Review 不读取生成模型隐藏思维链。是否强制跨 Provider 由成本与独立性结果决定。

## 6. E2E 必测路径

1. 成功押金咨询与两轮内追问；
2. 两轮不足后有限回答；
3. 法规为空、案例为空、版本冲突；
4. Provider 超时与结构化输出无效；
5. Review/引用/Trace fail-closed；
6. 用户主动文书建议与模板源为空；
7. 匿名归属、重复提交、状态版本冲突和删除；
8. 3–5 并发 Matter 隔离与过载。

## 7. 调度、推诿与循环测试

### DAG 与 owner

- 拒绝含环、未知节点、不可达节点或未满足依赖却进入 `READY` 的 TaskGraph；
- 运行时追加节点必须产生新 graphVersion 并重新验证无环；
- 只有调度器可写 owner/status/dependency；Worker 伪造转派必须失败；
- owner lease 过期或 epoch 落后时，迟到结果不得修改状态；
- 并发抢占同一 READY 节点时最多一个 owner 获得有效租约。

### 预算

- maxSteps 与 maxTokenBudget 在 Node/Task/Run 单调累计；
- retry、拆 Node、handoff、fallback replan 均不能重置父预算；
- 到限时取消正在进行的模型/Tool，产生 `BUDGET_EXHAUSTED`，不再调用下游；
- token usage 缺失或 Provider 报告异常时采用保守记账并阻止预算逃逸。

### Escalation 与 handoff

- 不匹配 Agent 只能产生 `EscalationRequest`，不能指定/调用下一个 Agent；
- 普通 retry 不增加 handoff，owner 变化才增加；
- 第 3 次 handoff 触发一次 MergedTaskContext + FALLBACK_REPLAN；
- 合并上下文保留用户约束、Evidence/Artifact ID、失败原因、预算和 provenance；
- fallback 再次升级/循环时终止，不清零计数。

### 循环检测

- 规范化去除时间戳、随机 ID、措辞差异并稳定排序；相同行为产生相同指纹；
- 原始 PII 不进入 ActionRecord 或指纹输入快照；
- 五条动作窗口连续 3 次相同触发硬中断；
- 无状态/Artifact/Evidence 增量的动作三连触发；
- ABAB 短周期与相同错误结果三连触发；
- 合法重复但状态持续推进不得误报；
- 触发后验证取消、资源释放、Trace、最多一次 replan 和最终 fail-safe。

## 8. ToolExecutor、写门禁与 Reducer 测试

### 选择与执行隔离

- 模型输出 ToolIntent 后，断言 Adapter 尚未执行；只有 ToolExecutor 可触发实现调用；
- AgentBackend 自带 tool loop、Node、UI 或 Adapter 旁路执行应被架构/契约测试阻止；
- 未注册工具、版本不匹配、Schema 非法、owner epoch 过期或 CapabilityGrant 无效时零副作用。

### 独立 ToolPolicy

- 每个工具缺少 timeout、权限、operationClass、sideEffect、幂等或结果上限时注册失败；
- 单工具超时、重试、并发、速率、成本和大小限制互不串用；
- 超时/取消后释放连接和进程，迟到结果不得写入有效状态；
- 非幂等写操作不得自动重试；幂等键重复只产生一次副作用。

### 读写与确认

- READ 凭据/Adapter 无法调用 WRITE；MVP 所有外部 WRITE 默认拒绝；
- 写工具先生成 ExecutionPreview，未确认时零副作用；
- 无原生 dry-run 时必须显示 `isAuthoritativeDryRun=false`；
- ConfirmationGrant 只能消费一次，并绑定 intent、参数、目标版本、owner epoch 和过期时间；
- 确认后参数或目标变化、过期、重放和 TOCTOU 均被拒绝；
- 内部受控状态写不弹用户确认，但仍验证权限、幂等、版本和 Trace。

### MessageReducer

- RawToolResult 在压缩前保存，ToolResultView 可通过 rawResultId 回溯；
- 超大、重复、部分失败和含 Prompt Injection 的结果均按策略压缩/隔离；
- 金额、日期、法条/案例 locator、Evidence ID、版本、错误、来源和截断标志保持不变；
- `isLossy`、omittedFieldClasses、reducer/version 和压缩比准确；
- Reducer 模型失败/超预算时返回安全截断或结构化错误，不把原始超大结果直接交给 Agent。

## 9. 虚假信心禁令

- 只断言 mock 调用；测试复制实现；宽松 snapshot；E2E 绕过入口/存储/检索；
- 用局部 qrels 解释真实全库 Recall；用 LLM Judge 解释法律正确率；
- 用 fixture 模板冒充可信来源；用 Replay 成功冒充真实 Provider 成功；
- 只测成功，不测证据缺口、版本冲突、权限、TTL 和故障。

审计问题：错误实现是否会让测试失败；是否走过所声称 seam；断言是否对应用户行为；反例是否足够；缓存/重试是否掩盖失败。

## 10. 当前命令与基线

| 层级 | 命令 | 状态 |
|---|---|---|
| compile | `/root/miniconda3/envs/agent/bin/python -m compileall -q lawagent_runtime tests` | 2026-08-19通过 |
| unit/contract/ASGI HTTP | `/root/miniconda3/envs/agent/bin/python -m unittest discover -s tests -v` | 2026-08-19：147/147通过，0.32秒，零真实模型调用 |
| GLM six-role smoke | `/root/miniconda3/envs/agent/bin/python scripts/smoke_glm_six_roles.py --output <report.json>` | Blocked：`.env` Key字段为空 |
| format/lint | 待建立统一入口 | Blocked：工具未建立 |
| integration/Qdrant/model | 历史真实Qdrant smoke已有证据；本轮容器端口不可达；GLM按用户要求未重跑 | Blocked（外部环境） |
| integration/Redis/PostgreSQL | `make services-smoke` | 真实 Redis TTL/删除与 PostgreSQL schema/事务/读写/清理通过 |
| HTTP E2E | `tests/test_http_e2e.py`，使用`httpx.ASGITransport`避免Starlette TestClient流式卡死 | 正常完成/Trace故障两路通过 |
| browser/visual | 环境无Playwright、Selenium或浏览器二进制 | Blocked（未用HTTP测试冒充浏览器） |
| evaluation | 待核验 | Blocked |
| core verification | `bin/verify_all` | 可执行 compile/unittest 并报告完整验收债务 |
| standard local check | `make check` | 预检 + compile + 147项本地测试；不包含外部/视觉/性能/Review |
| full product verification | 尚未建立 | Blocked：真实模型/Qdrant、浏览器、视觉、性能、Review、30条评测 |

147项测试主要覆盖单元、契约、SSE和进程内ASGI HTTP；不得据此声称真实Provider、实时检索、浏览器用户路径或法律质量已经验收。
