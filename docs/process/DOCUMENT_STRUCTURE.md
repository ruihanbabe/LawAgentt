# LawAgent Documentation & Skills Path Map
> 摘要：记录 LawAgent Agentic 工作流全部固定文档、动态文档和 skills 的目标存放路径。
> 摘要：本文件只定义目录、文件主题、生成方式和职责，不记录未经远程仓库核验的项目事实。
> 摘要：固定文档随远程启动包上传；Feature、ADR 和 Worksheet 按开发过程持续生成。
> 摘要：`AGENTS.md` 是统一检索入口，本文件是文件路径和目录结构的唯一清单。
> 摘要：旧 handoff 在信息完成核验与迁移前保留原件，不直接删除或覆盖。
> 摘要：远程服务器接入后再补充真实源码路径、运行命令、工具配置和实现状态。

## 1. 仓库根目录

以下路径均相对于远程项目仓库根目录。

```text
<repository-root>/
├── AGENTS.md
├── README.md
├── Makefile
├── AGENT_WORKFLOW.md
├── PROGRESS.md
├── HANDOFF.md
├── TODOS.md
├── docs/
│   ├── product/
│   │   └── requirements.md
│   ├── features/
│   │   ├── rental-deposit-consultation.md
│   │   └── <feature-name>.md
│   ├── design/
│   │   └── SYSTEM_DESIGN.md
│   ├── interfaces/
│   │   └── API_CONTRACTS.md
│   ├── sources/
│   │   └── SOURCE_POLICY.md
│   ├── decisions/
│   │   └── ADR-<number>-<decision-name>.md
│   ├── testing/
│   │   ├── TESTING.md
│   │   └── PERFORMANCE.md
│   ├── review/
│   │   └── REVIEW_GUIDE.md
│   ├── engineering/
│   │   ├── CODING_CONVENTIONS.md
│   │   └── AGENT_TOOLS.md
│   ├── project/
│   │   └── worksheets/
│   │       └── <worksheet-id>.md
│   └── process/
│       ├── DOCUMENT_STRUCTURE.md
│       └── SESSION_FEEDBACK.md
├── skills/
│   ├── agent-loop/
│   │   └── SKILL.md
│   ├── feature-development/
│   │   └── SKILL.md
│   ├── agent-review/
│   │   └── SKILL.md
│   ├── test-confidence-audit/
│   │   └── SKILL.md
│   ├── visual-regression/
│   │   └── SKILL.md
│   ├── performance-benchmark/
│   │   └── SKILL.md
│   ├── handoff-maintainer/
│   │   └── SKILL.md
│   └── research-agent-backends/
│       └── SKILL.md
├── bin/
└── tools/
```

## 2. 固定文档路径

固定文档属于远程启动包。路径确定后保持稳定，避免 Agent 因重命名失去路由。

| 路径 | 主题 |
|---|---|
| `README.md` | 新会话五问入口；项目、组织、运行、验证和进度路由 |
| `Makefile` | setup、run、test、lint、check、外部服务和 smoke 的标准操作入口 |
| `AGENTS.md` | Agent 工作流入口；路由文档、skills、工具和检索关键词 |
| `AGENT_WORKFLOW.md` | 用户定义的 0–18 条标准 Agentic 开发流程 |
| `PROGRESS.md` | 当前进度唯一总览：已完成、正在做、阻塞与最近验证 |
| `docs/process/DOCUMENT_STRUCTURE.md` | 全部文档、skills 和工具目录的路径清单 |
| `docs/product/requirements.md` | 产品目标、范围、用户需求、业务规则和验收标准 |
| `docs/design/SYSTEM_DESIGN.md` | 总体架构、模块职责、数据流、状态和失败路径 |
| `docs/interfaces/API_CONTRACTS.md` | REST、SSE、Agent、Tool、Artifact、Event 和 DTO 契约 |
| `docs/sources/SOURCE_POLICY.md` | 信源等级、数据版本、Evidence 用途、引用与远程核验规则 |
| `docs/testing/TESTING.md` | 测试原则、测试分类、E2E、清单和虚假信心审计 |
| `docs/testing/RETRIEVAL_BASELINES.md` | 历史检索基线、数据快照和指标解释边界 |
| `docs/testing/PERFORMANCE.md` | 性能指标、自动基准、回归阈值和 profile 规则 |
| `docs/review/REVIEW_GUIDE.md` | 四阶段跨模型、跨 Persona review 规则 |
| `docs/engineering/CODING_CONVENTIONS.md` | 项目编码规范及应下沉到 linter 的规则 |
| `docs/engineering/AGENT_TOOLS.md` | `bin/`、`tools/` 脚本制作和统一调用规范 |
| `HANDOFF.md` | 接手上下文、环境恢复、远程入口和下一恢复步骤 |
| `TODOS.md` | Agent 可读取和领取的任务队列 |
| `docs/process/SESSION_FEEDBACK.md` | 各 session 的工作流反馈和改进记录 |

## 3. 动态文档路径

这些文档不预先填入未经核验的内容，在远程开发过程中按需创建。

| 路径模板 | 生成单位 | 主题 |
|---|---|---|
| `docs/features/<feature-name>.md` | 每项功能一份 | 功能说明、范围、输入输出、业务规则、失败分支和验收 |

当前首个 Feature：`docs/features/rental-deposit-consultation.md`。
| `docs/decisions/ADR-<number>-<decision-name>.md` | 每项重要决策一份 | 背景、决策、备选方案、原因和后果 |
| `docs/project/worksheets/<worksheet-id>.md` | 每个 session 一份 | 目标、进度、命令、测试、review、风险和恢复点 |

### 命名约定

- Feature：小写 kebab-case，例如 `document-to-case.md`。
- ADR：四位递增编号加小写 kebab-case，例如 `ADR-0001-runtime-architecture.md`。
- Worksheet：`WS-YYYYMMDD-NN-short-name.md`，例如 `WS-20260811-01-agentic-workflow.md`。

## 4. Skills 路径

| 路径 | 主题 |
|---|---|
| `skills/agent-loop/SKILL.md` | 自主循环和 night shift 编排 |
| `skills/feature-development/SKILL.md` | 根据 Feature Spec 实现纵向功能切片 |
| `skills/agent-review/SKILL.md` | 跨模型、跨 Persona review |
| `skills/test-confidence-audit/SKILL.md` | 虚假信心测试审计与修复 |
| `skills/visual-regression/SKILL.md` | 截图生成、对比和 Agent 视觉 review |
| `skills/performance-benchmark/SKILL.md` | 自动性能基准、回归检测和 profile |
| `skills/handoff-maintainer/SKILL.md` | Handoff、Worksheet、TODO 和反馈自愈 |
| `skills/research-agent-backends/SKILL.md` | 调研 Pi、Claude Agent SDK、Craft Agents 等并形成采用 ADR |

## 5. 工具路径

| 路径 | 主题 |
|---|---|
| `bin/` | Agent 和开发者直接调用的稳定统一入口 |
| `tools/` | `bin/` 背后的脚本实现、辅助模块、配置和测试 |

具体脚本名称和实现方式等远程工具链核验后，再写入 `docs/engineering/AGENT_TOOLS.md`。

## 6. Handoff 与历史迁移

- `PROGRESS.md` 是唯一当前进度总览；`HANDOFF.md` 是唯一动态交接入口。
- 旧离线和规划 handoff 已在 2026-08-19 完成迁移后删除。
- 历史运行事实进入 worksheet 或专项基线文档，不再创建巨型新对话交接包。

## 7. 上传远程服务器时的路径原则

将上述文件和目录复制到远程项目的仓库根目录，并保持相对路径不变。上传后先核验远程已有同名文件和未提交改动，再进行合并；不得直接覆盖远程已有的 `AGENTS.md`、需求、设计、测试或 handoff 内容。
