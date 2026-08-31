# LawAgent Agentic Workflow Router
> 摘要：本文件严格路由用户定义的 0–18 条 Agentic 开发工作流，不自行删减流程环节。
> 摘要：所有 session 必须加载标准工作流、需求、技术说明、handoff、worksheet 和任务队列。
> 摘要：所有系统文档都是自愈文档；代码变化、运行发现和 review 结论必须同步回写。
> 摘要：Agent 必须实际运行应用，边实现边测试，并在关键节点接受跨模型、跨 Persona review。
> 摘要：测试体系必须覆盖 E2E、虚假信心审计、视觉回归、性能基准与性能分析。
> 摘要：每个 session 都要留下 worksheet、反馈、commit 关联和同名 git tag，支持其他 Agent 接手。

## 0. 本文件的职责：路由器

进入仓库后，Agent 必须先读取本文件，再根据任务读取正确的 skill、文档与工具。不得跳过被路由的强制文档。

### 每个 session 的固定加载顺序

1. `README.md`：用唯一入口回答项目五问，并运行 `bin/project_status`。
2. `AGENT_WORKFLOW.md`：用户定义的标准开发流。
3. `docs/process/DOCUMENT_STRUCTURE.md`：文档、skills 和工具的路径清单。
4. `docs/product/requirements.md`：需求与验收。
5. `docs/design/SYSTEM_DESIGN.md`：技术说明与系统设计。
6. `PROGRESS.md`：当前已完成、正在做和阻塞总览。
7. `HANDOFF.md`：项目中途接手与环境恢复信息。
8. `docs/project/STATUS.md`：当前 session worksheet 与历史证据。
9. `TODOS.md`：Agent task queue。
10. 按任务继续读取下表的专项文档。

### 任务路由

| 任务 | 必读文档 / skill / 工具 |
|---|---|
| 查找文档、skills 和工具路径 | `docs/process/DOCUMENT_STRUCTURE.md` |
| 需求分析与规划 | `docs/product/requirements.md`、`docs/review/REVIEW_GUIDE.md` |
| 架构、接口与实现 | `docs/design/SYSTEM_DESIGN.md`、`docs/interfaces/API_CONTRACTS.md`、`docs/engineering/CODING_CONVENTIONS.md` |
| 信源、数据与证据 | `docs/sources/SOURCE_POLICY.md` |
| 第三方 Agent Runtime 调研 | `skills/research-agent-backends/SKILL.md` |
| 测试与验收 | `docs/testing/TESTING.md` |
| Review | `docs/review/REVIEW_GUIDE.md`、`bin/agent_review` 或等价统一入口 |
| 性能工作 | `docs/testing/PERFORMANCE.md` |
| 自动/夜班运行 | `skills/agent-loop/SKILL.md` |
| 脚本制作 | `docs/engineering/AGENT_TOOLS.md`、`tools/`、`bin/` |
| session 收尾 | `docs/project/STATUS.md`、`docs/process/SESSION_FEEDBACK.md` |

如果表中的目录、skill 或脚本尚不存在，当前任务必须把它作为明确的工作流缺口记录到 worksheet 和 `TODOS.md`；不得假装已经执行。

## 1. 自愈文档规则

所有系统文档必须持续更新。每份可路由文档的前 7 行必须包含标题与详细摘要，使 Agent 可通过 `rg` 找到正确文档。Agent 发现以下任一情况时，必须在同一工作中更新文档：

- 代码行为与文档不一致；
- 新增或改变模块、接口、命令、测试、失败模式、性能特征；
- review 找到跨系统问题；
- 实际运行暴露新的环境要求或恢复步骤；
- worksheet 中的临时知识已成为长期规则。

## 2. 0–18 条强制索引

| 编号 | 强制要求 | 仓库落点 |
|---:|---|---|
| 0 | AGENTS 路由 skill、文档、工具 | 本文件 |
| 1 | 定制标准工作流，每个 session 引入 | `AGENT_WORKFLOW.md` |
| 2 | 每个系统自愈文档，前 7 行可 grep 摘要 | 本节及所有系统文档 |
| 3 | 始终实际运行应用，边做边测边修 | `AGENT_WORKFLOW.md`、`TESTING.md` |
| 4 | E2E、测试写法、反例、全测试清单；实现同步提交测试 | `docs/testing/TESTING.md` |
| 5 | pre-commit 自定义 linter，优先 `--fix`，否则调用便宜 LLM 修复 | `AGENT_WORKFLOW.md`、待建 hook/脚本 |
| 6 | 调研、规划、实现、收尾跨 Agent/跨模型 Persona review | `docs/review/REVIEW_GUIDE.md`、`bin/agent_review` |
| 7 | 每 session worksheet 随工作提交并创建同名 git tag | `docs/project/STATUS.md` |
| 8 | session 结束自动反馈并随工作提交，定期消化 | `docs/process/SESSION_FEEDBACK.md` |
| 9 | `tools/`/`bin/` 脚本库及脚本制作说明 | `docs/engineering/AGENT_TOOLS.md` |
| 10 | 定期扫描最近 commits，跨 commit 找问题 | `AGENT_WORKFLOW.md`、review 工具 |
| 11 | coding conventions，尽量下沉 linter | `docs/engineering/CODING_CONVENTIONS.md` |
| 12 | agent loop / night shift skill | `skills/agent-loop/SKILL.md` |
| 13 | Agent 可访问 task queue | `TODOS.md` |
| 14 | 定期“虚假信心测试审计”并修复 | `docs/testing/TESTING.md` |
| 15 | 截图视觉回归，工具与 Agent 视觉 review，提交或上传 PR | `docs/testing/TESTING.md` |
| 16 | 自动性能基准，发现回退 | `docs/testing/PERFORMANCE.md` |
| 17 | 性能分析工具、对比输出与 profile | `docs/testing/PERFORMANCE.md`、`tools/` |
| 18 | 下班前全量验证：全部测试、性能、Agent review、全面扫描 | `AGENT_WORKFLOW.md` |

## 3. 执行约束

- 上述 0–18 条是本仓库协作流程的来源，不允许 Agent 自行精简。
- 上传的需求、技术说明和 handoff 可重写、拆分；拆分后必须保留来源映射与未迁移信息。
- 每个关键节点必须调用不同模型做 review；同一模型不得 review 自己的工作。
- worksheet、反馈、实现、测试和自愈文档必须与工作一起提交。
- worksheet 对应的 git tag 必须在 session 提交完成后创建，并把 commit/tag 写回 worksheet。
- 外部工具、权限或模型不可用时，记录为未完成的强制步骤，不能用自查冒充。

## 4. 完成定义

只有工作流对应步骤全部完成，真实应用运行、针对性测试、E2E、相关视觉/性能验证、跨模型 review、虚假信心审计、全量验证、自愈文档、worksheet、反馈、commit 和 tag 均有证据时，session 才能标记完成。无法执行的条目必须明确标为阻塞或验证债务。
