# LawAgent Standard Agentic Workflow
> 摘要：这是每个 session 强制加载的标准工作流，逐项实现用户给出的 0–18 条开发方法。
> 摘要：流程覆盖恢复上下文、调研、规划、实现、真实运行、测试、跨模型 review、提交和反馈。
> 摘要：Agent 必须边实现边运行应用、边写针对性测试，不能把验证集中推迟到最后。
> 摘要：调研、规划、实现和收尾四个关键节点均由不同模型与多个 Persona 交叉 review。
> 摘要：每次 session 使用 worksheet 可恢复地记录工作，并随 commit 创建同名 git tag。
> 摘要：下班前必须执行包括测试、性能、review、虚假信心审计和全面扫描在内的全量验证。

## Phase 1：恢复与领取任务

1. 按 `AGENTS.md` 固定顺序加载需求、技术说明、handoff、worksheet 和 task queue。
2. 若是项目中途接手，先把 `HANDOFF.md` 中的当前状态、已做决策、运行方法、风险和下一步同步到新 worksheet。
3. 从 `TODOS.md` 领取任务，为 session 创建唯一 worksheet ID。
4. 检查最近 commits、未提交变更、当前应用运行状态和已有测试基线。
5. 建立本 session 的需求、非范围、验收、验证清单和恢复点。

## Phase 2：调研与调研 Review

1. 查阅对应系统的自愈文档、代码、测试、工具和历史 worksheet。
2. 实际复现当前行为或问题，记录命令和输出。
3. 通过统一 `agent_review` 入口请求不同模型 review 调研完整性。
4. 使用领域专家、安全、性能、维护性、代码质量和 AI 坏味道 Persona 补充盲区。
5. 修订调研结论和系统文档后，才进入规划。

## Phase 3：规划与规划 Review

1. 需求文档写清问题、范围、用户路径和验收标准。
2. 技术说明写清模块、接口、数据流、失败分支、迁移、测试和性能方案。
3. 将计划拆为能持续运行应用和验证的纵向切片。
4. 由不同模型及相关 Persona review 规划；解决或登记全部 finding。
5. 更新 worksheet 后开始实现。

## Phase 4：实现、运行与持续测试

对每个纵向切片重复：

1. 编写或更新针对性测试。
2. 实现最小切片。
3. 实际启动应用并从真实入口执行该功能。
4. 运行针对性单元、契约、集成和 E2E 测试。
5. 发现问题立即修复并重跑，不等到 session 末尾。
6. 涉及界面时生成截图，执行自动视觉对比和 Agent 视觉 review。
7. 涉及性能时运行基准；发现变化时使用 profile 工具定位并保存对比结果。
8. 同步更新需求、技术说明、自愈文档、worksheet 和 task queue。

实现与测试必须一起进入同一提交范围。

## Phase 5：pre-commit 清洁循环

1. 运行格式化器、自定义 linter 和 pre-commit hooks。
2. 对可机械修复的问题使用 `--fix` 并重新验证。
3. 对无法机械修复的问题，通过统一脚本调用配置的便宜 LLM（例如 Composer 或 Sonnet）修复。
4. 对 LLM 产生的改动重新运行 linter、测试和应用验证，直到输出干净代码。
5. linter 能稳定表达的 coding convention 必须从文档下沉到规则。

具体 hook、模型和命令在源码接入后写入工具文档；不可用时 worksheet 必须标出该强制步骤未完成。

## Phase 6：实现 Review

通过不同模型执行跨 Agent review，并至少覆盖：

- 可维护性；
- 代码质量；
- 安全与隐私；
- 性能；
- AI 坏味道；
- 中国法律领域风险；
- 测试真实性和验收覆盖。

修复 finding 后必须重新运行相关应用路径和测试。

## Phase 7：专项审计

1. 虚假信心测试审计：寻找没有真正验证所声称行为的测试并直接修复。
2. 跨 commit 扫描：审查最近 commits 的组合效果，寻找单个 diff 中不明显的问题。
3. 视觉回归：确认截图差异符合需求，产物随工作提交或至少上传 PR。
4. 性能回归：与基线比较并对下降做 profile。
5. 系统文档自愈：将新事实和 review 结论回写到对应文档。

## Phase 8：下班前全量验证

必须执行：

1. 所有格式化、linter、pre-commit；
2. 全部单元、契约、集成和 E2E 测试；
3. 全部视觉回归；
4. 自动性能基准与需要的 profile；
5. 虚假信心测试审计；
6. 跨 Agent、跨模型收尾 review；
7. 最近 commits 的全面扫描；
8. 应用真实入口最终 smoke；
9. 文档、worksheet、task queue 和反馈一致性检查。

## Phase 9：提交、Tag 与反馈

1. 在 worksheet 记录所有命令、结果、finding、修复、剩余风险和恢复点。
2. 自动生成本 session 反馈，写入 `docs/process/SESSION_FEEDBACK.md`。
3. 将实现、测试、截图/性能产物、文档、worksheet 和反馈一起提交。
4. 创建与 worksheet ID 同名的 annotated git tag。
5. 把 commit SHA 和 tag 写回 worksheet；如需追加记录，再提交该更新。
6. 定期在交互 session 中汇总反馈，修改 `AGENTS.md`、本工作流、linter 和工具。

## Night Shift / Agent Loop

自主运行由 `skills/agent-loop/SKILL.md` 编排：循环领取 task queue、建立 worksheet、执行上述 Phase、持续落盘、失败后可交接，并在结束前完成 Phase 8–9。该 skill 不得绕开任何 review、测试或文档步骤。

## Agent 调度、预算与防推诿

适用于自动开发任务和产品 Runtime Agent：

1. 调度器将复合任务拆为可验证 DAG；只有调度器分配 owner、修改依赖、重排或取消。
2. owner 同时记录能力角色与具体执行实例；实例使用租约/epoch，过期 owner 不得继续写结果。
3. Agent 收到不属于其能力、权限或上下文的任务时，不得私下转派；返回结构化 `ESCALATED` 给调度器。
4. 单 Node/Task/Run 设置 `maxSteps` 与 `maxTokenBudget`；重试、拆分、handoff 或重规划不重置父预算。
5. 调度器记录 handoff；默认达到 3 次后只允许一次上下文合并与兜底重规划，再失败则终止、阻塞或有限交付。
6. 最近 Tool/Assistant 动作经去敏规范化后计算 SHA256；五条窗口连续三次一致、无进展动作三连或短周期重复时强制取消并重规划。
7. 每个 Task 最多自动重规划一次；不得用“重新规划”逃避预算、review finding 或完成标准。
8. 所有升级、预算耗尽、循环、owner 变化、上下文合并和终止原因写入 worksheet/Trace。
