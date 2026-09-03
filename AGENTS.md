# LawAgent Codex 入口

LawAgentt 是面向中国大陆住宅租赁押金纠纷的 Python 法律援助 Agent MVP，同时用于验证受证据约束的 Harness/Runtime 工程能力。

## 新会话启动

1. 阅读本文件、[`README.md`](README.md)、[`PROGRESS.md`](PROGRESS.md)；[`DECISIONS.md`](DECISIONS.md) 只浏览决策标题（`grep '^## '`）建立索引，具体条目在实现 Feature 时按「全局硬约束」的定点方式读取，不在启动阶段通读全文。
2. 运行 `git status --short --branch`，保护已有未提交修改。
3. 运行 `make status`；依赖齐备时再运行 `make check`。
4. 根据任务确定所属模块，先读取该目录的 `AGENTS.md`；再按其中指引读取局部 `ARCHITECTURE.md`、代码和测试。
5. 不默认扫描整个仓库或全部 Markdown；只读取与当前任务有关的文档和模块。

## 标准命令入口

```bash
make setup
make status
make check
make run
make health
```

完整命令以 `make help` 为准。`Makefile`、`bin/`、`.env.example` 与 `compose.yaml` 是运行和环境事实来源；Markdown 不能证明当前依赖、服务或外部系统状态。

## 全局硬约束

- Feature 按 `depends_on` 拓扑顺序选择；默认每次只激活一个 Feature，仅在满足 [`docs/development/DEVELOPMENT.md`](docs/development/DEVELOPMENT.md)「Feature 选择顺序与并行边界」列出的条件（互不依赖、独立分支、无共享文件重叠）时才允许多个 Feature 并行处于 `active`。当前 Feature（或并行组）未完成其必需验证（跨组件时含端到端验证）前，不得开始下一个不满足并行条件的 Feature，也不得顺带重构无关功能。
- 只读取和修改当前任务需要的文件，不做相邻重构；保留用户已有改动。
- **Runtime 层（`src/runtime/`、`src/conversation/` 等非 ScenarioPack 目录）禁止出现具体对象身份词汇**（"房东"/"用人单位"/"保险公司"等），包括代码变量名、Pydantic 字段名、错误兜底文案、日志/Trace 文案；测试 fixture 与 ScenarioPack 自身文件不受此约束。具体称谓只能通过 `ScenarioPack.party_labels()` 注入，渲染给用户时才替换为具体文案。提交前可用 `grep -rn "房东\|用人单位\|保险公司" src/runtime src/conversation` 做启发式排查（非穷举，新词需人工判断是否属于"具体对象身份"，不得因不在此列表就默认合规）。依据见 `DECISIONS.md` D28、D29。
- **实现任一 Feature 时禁止完整读取 [`DECISIONS.md`](DECISIONS.md)、[`docs/architecture/scenario-pack-and-streaming-design.md`](docs/architecture/scenario-pack-and-streaming-design.md)、[`docs/product/requirements.md`](docs/product/requirements.md) 三份文件的全文。** 正确做法：先读 [`docs/features.json`](docs/features.json) 中该 Feature 自己的条目，取出 `context_refs`；对 `context_refs.decisions` 的每个 ID 用 `grep '<!-- id: Dxx -->'` 定位标题行，只读该行到下一条 `## ` 之前；对 `architecture_sections` / `requirements_sections` 的每个章节号按 `## N.` / `### N.M` 标题定位，只读该节到下一个同级或更高级标题之前；有 `depends_on` 时额外只读被依赖 Feature 在 `docs/features.json` 里的条目（了解上游接口），不读其关联的 `context_refs` 内容。仅当调试明确怀疑"决策理解错误"、且定点读取仍无法确认时，才允许临时读整份文件排查；排查完成后按上述定点方式继续，不得把整份文件留在长期上下文。完整步骤见 [`docs/development/DEVELOPMENT.md`](docs/development/DEVELOPMENT.md)「每 Feature 的上下文投影」。
- Review 或诊断任务默认只报告，不自动修改。
- 不提交 `.env`、凭据、原始 PII、完整 Provider payload 或未脱敏 Trace。
- 连接远程服务器、调用真实模型或产生费用前，必须获得用户明确授权。
- 模型不得绕过 `ToolExecutor` 执行工具；最终回答不得绕过 `DeliveryGate` 交付。
- 只报告当前环境实际执行成功的验证；mock、语法编译和历史结果不是完整验收。
- 完成以项目 Harness 的外部验证证据为准，不以 agent 自评或“代码写完”代替；必需验证被阻塞时如实报告阻塞。
- 跨组件修改前必须遵守架构边界、数据所有权和依赖方向；稳定、可客观检测的约束应有自动检查，且失败信息说明何处违约、为何、如何修复。
- 重复、高风险且可客观检测的审查问题，应提升为带修复指引和防回归测试的自动检查；不强行自动化纯审美意见。
- 过时历史不留在工作树；仅在用户明确要求时从 Git 历史恢复。
- 验证分四级递进：语法/类型检查 → lint（已装配时为必经阶段）→ 单元测试（不连网络）→ 模块/系统层测试；每一级的自动修复尝试上限各为 3 次，四级独立计数、互不共享配额，某一级达到上限后必须停止自行尝试，不得跳级掩盖失败。
- 修复动作若改变了函数签名或接口，必须强制回退重跑更早的验证级别（语法/类型检查→lint→单元测试→模块/系统层测试），不由模型自行判断是否需要回退。
- `EscalationRequest` 统一覆盖两类触发场景，禁止各自发明格式：(i) 上述任一验证级别自动修复超过重试上限；(ii) 运行时角色/模块（如 Scheduler）判断自身能力或权限不匹配，见 [`src/runtime/AGENTS.md`](src/runtime/AGENTS.md)。两者都必须产出结构化 `EscalationRequest`（`reason_code`/`reason_detail`/`attempted_count`，定义见 [`docs/architecture/scenario-pack-and-streaming-design.md`](docs/architecture/scenario-pack-and-streaming-design.md) §9.1），不得无限重试、静默放弃或自行决定转派对象；详见 [`docs/development/DEVELOPMENT.md`](docs/development/DEVELOPMENT.md)「自动修复与升级上限」。

## 多 Agent 协作（Codex 与 Claude Code 同时开发时）

- 建议分工：Claude Code 优先承担独立、依赖简单的 Feature；Codex 专注强耦合核心链路。具体名单随 `docs/features.json` 更新，以当前 `depends_on` 图为准，不固定绑定某几个 Feature id。
- 两者同时对同一仓库操作时，必须满足 [`docs/development/DEVELOPMENT.md`](docs/development/DEVELOPMENT.md)「Feature 选择顺序与并行边界」的并行条件（互不依赖、独立分支、无共享文件重叠），并在合并前各自跑完三层验证。
- 任一方发现某 Feature 卡住需要重新规划时，升级给用户决定，不由 Codex/Claude Code 自行决定转派方向。

## 顶层文档与模块入口

- 系统架构、模块边界和依赖方向：[`ARCHITECTURE.md`](ARCHITECTURE.md)
- 开发命令、验证层级与 Feature 状态规则：[`docs/development/DEVELOPMENT.md`](docs/development/DEVELOPMENT.md)
- 产品目标与范围（含 2026-09-01 可行性复核定稿章节 §14–§21）：[`docs/product/requirements.md`](docs/product/requirements.md)
- ScenarioPack、Scheduler、EscalationRequest/TaskIntent 架构设计：[`docs/architecture/scenario-pack-and-streaming-design.md`](docs/architecture/scenario-pack-and-streaming-design.md)
- 信源与证据约束：[`docs/sources/SOURCE_POLICY.md`](docs/sources/SOURCE_POLICY.md)
- 当前状态、阻塞和下一步：[`PROGRESS.md`](PROGRESS.md)
- 当前设计约束：[`DECISIONS.md`](DECISIONS.md)
- 文档写作与记录规则：[`DOCUMENT-WRITING.md`](DOCUMENT-WRITING.md)
- Feature 清单：[`docs/features.json`](docs/features.json)
- 交接缺口与待办追踪：[`ISSUE-TRACKING.md`](ISSUE-TRACKING.md)

进入以下模块前，必须先读取其局部指引：

- HTTP 与 SSE：[`src/api/AGENTS.md`](src/api/AGENTS.md)
- 交互生命周期与会话：[`src/conversation/AGENTS.md`](src/conversation/AGENTS.md)
- 任务板、角色与工具：[`src/runtime/AGENTS.md`](src/runtime/AGENTS.md)
- 案件事实与充分性：[`src/intake/AGENTS.md`](src/intake/AGENTS.md)
- 检索与 Evidence：[`src/knowledge/AGENTS.md`](src/knowledge/AGENTS.md)
- 交付安全与 PII：[`src/safety/AGENTS.md`](src/safety/AGENTS.md)
- 会话、画像与 Trace 存储：[`src/persistence/AGENTS.md`](src/persistence/AGENTS.md)
- 环境与外部 Provider：[`src/infrastructure/AGENTS.md`](src/infrastructure/AGENTS.md)

若任务不属于上述模块，先以 `ARCHITECTURE.md` 确认 owner；边界不明确时不要擅自创建新模块或局部 `AGENTS.md`。
