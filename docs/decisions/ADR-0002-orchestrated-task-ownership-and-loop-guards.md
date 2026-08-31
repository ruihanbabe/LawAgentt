# ADR-0002: Orchestrated Task Ownership, Budgets and Loop Guards
> 摘要：决定所有复合 Agent 任务由调度器维护版本化 DAG，并独占 owner、依赖和状态转换权。
> 摘要：owner 分为能力角色与带租约的执行实例；Worker 不得横向转派，只能结构化 escalate。
> 摘要：Node、Task、Run 采用单调累计 step/token 预算，重试、handoff 和 replan 不得重置。
> 摘要：默认最多 3 次 owner handoff，到限后只允许一次上下文合并与兜底重规划。
> 摘要：循环检测采用去敏规范化 ActionRecord SHA256、五条窗口三连、无进展三连和短周期规则。
> 摘要：本决策是规划契约，具体阈值须经远程真实负载和误报评测校准，但不得取消硬保险丝。

## 状态

Accepted for planning；implementation unverified。

## 问题

多 Agent 如果可以自行转派、重置上下文或无限调用工具，会出现责任不清、互相推诿、预算逃逸、重复行动和不可审计终止。单纯依赖 Prompt 要求“不要循环”不足以构成安全约束。

## 决策

1. Planner 产生版本化 DAG；运行时只能由 PolicyOrchestrator 变更并重新验环。
2. `ownerRole` 描述能力，`ownerId` 描述当前租约 Worker，`ownerEpoch` 阻止迟到写入。
3. Worker 不得横向调用/转派其他 Agent；不匹配时只返回 `EscalationRequest`。
4. Node/Task/Run 都有 `maxSteps` 与 `maxTokenBudget`；使用量向父级汇总且不可重置。
5. 默认 `maxHandoffs=3`；到限后合并上下文并仅允许一次 fallback replan，再失败即终止或有限回答。
6. 对去敏规范化 ActionRecord 做 SHA256。用户提出的“最近五条 Tool/Assistant 窗口连续三次一致”作为硬中断；另加无进展动作三连、周期 1/2 与相同错误结果三连。
7. 循环触发时取消执行、释放资源、记录 Trace，并限制每 Task 最多一次自动重规划。

## 为什么不直接 hash 原始消息

原始文本包含 PII，且时间戳、随机 ID、自然语言改写会造成假阴性；可预测敏感文本的裸 SHA256 也可能被字典猜测。规范化动作记录只保留调度所需的类别、hash 与进展指标，既稳定又减少敏感暴露。

## 为什么静态 DAG 不够

检索和 Review 可能暴露新证据缺口，因此允许调度器动态扩图；但 Worker 不能动态派单，每次扩图都必须形成新版本并验证无环、预算、权限和可达性。

## 后果

- 优点：单一责任源、可审计、可取消、预算可证明、避免 Agent 推诿。
- 代价：调度器更复杂；需要租约、指纹规范化、进展定义和误报测试。
- 风险：阈值过低可能误杀合法迭代；以 state/Artifact/Evidence 增量区分合法重复，并通过固定 workload 校准。

## 验证

以 `TESTING.md` 的 DAG、owner、预算、escalation 和 loop 测试为门禁；性能基准报告调度开销、handoff/loop 命中及误报。远程实现前不得声称完成。

