# LawAgent Agent Loop / Night Shift Skill
> 摘要：编排 Agent 从 task queue 自主领取任务并完整执行 0–18 条工作流。
> 摘要：每个任务必须创建 worksheet，持续落盘进度，使 Agent 中断后可由另一个 Agent 恢复。
> 摘要：循环包含真实应用运行、持续测试、四节点跨模型 review、文档自愈和专项审计。
> 摘要：结束前必须运行全量验证、写 session 反馈、提交全部产物并创建 worksheet 同名 tag。
> 摘要：工具或模型失败时保留证据、尝试恢复并在 worksheet 标记，不得虚构完成。
> 摘要：本 skill 服从 `AGENTS.md` 与 `AGENT_WORKFLOW.md`，不能降低其中任何强制步骤。

## Loop

1. 读取 `AGENTS.md` 和 `AGENT_WORKFLOW.md`。
2. 从 `TODOS.md` 领取任务并创建 worksheet。
3. 执行恢复、调研、调研 review、规划、规划 review。
4. 按纵向切片循环：实现、运行应用、测试、修复、自愈文档、保存 worksheet。
5. 执行实现 review、虚假信心审计、视觉回归、性能基准/profile、跨 commit 扫描。
6. 执行下班前全量验证与收尾 review。
7. 写反馈，提交工作，创建同名 tag，写回 commit/tag。
8. 更新 task queue；若仍有可领取任务，开始新 worksheet。

## 调度与保险丝

- 只领取调度器/TODOS 明确分配的任务；不得把任务私下转给另一个 Agent。
- 无能力、权限或必要上下文时，返回 `ESCALATED`、原因和已完成证据，由调度器决定 owner。
- 开始前登记 DAG、owner role/id、`maxSteps`、`maxTokenBudget` 和 handoff 上限；子任务消耗计入父任务。
- 默认最多 3 次 owner handoff；达到上限后只允许一次上下文合并与兜底重规划。
- 每任务最多一次自动重规划；再次循环、升级或无进展时停止并登记 Blocked/验证债务。
- 最近动作使用去敏规范化指纹检测重复；不得保存原始 PII 或用改写措辞规避循环检测。

## 中断恢复

每个切片后必须更新 worksheet 的已完成、命令结果、失败、当前运行状态和下一条可执行命令。新 Agent 只依赖仓库内 worksheet、handoff、提交与 tag 即可继续。
