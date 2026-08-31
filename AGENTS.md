# LawAgent Codex 入口

LawAgentt 是面向中国大陆住宅租赁押金纠纷的 Python 法律援助 Agent MVP，同时用于验证受证据约束的 Harness/Runtime 工程能力。

## 新会话启动

1. 阅读本文件、[`README.md`](README.md)、[`PROGRESS.md`](PROGRESS.md) 与 [`DECISIONS.md`](DECISIONS.md)。
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

- 每次只激活一个 Feature；当前 Feature 未完成其必需验证（跨组件时含端到端验证）前，不得开始下一个，也不得顺带重构无关功能。
- 只读取和修改当前任务需要的文件，不做相邻重构；保留用户已有改动。
- Review 或诊断任务默认只报告，不自动修改。
- 不提交 `.env`、凭据、原始 PII、完整 Provider payload 或未脱敏 Trace。
- 连接远程服务器、调用真实模型或产生费用前，必须获得用户明确授权。
- 模型不得绕过 `ToolExecutor` 执行工具；最终回答不得绕过 `DeliveryGate` 交付。
- 只报告当前环境实际执行成功的验证；mock、语法编译和历史结果不是完整验收。
- 完成以项目 Harness 的外部验证证据为准，不以 agent 自评或“代码写完”代替；必需验证被阻塞时如实报告阻塞。
- 跨组件修改前必须遵守架构边界、数据所有权和依赖方向；稳定、可客观检测的约束应有自动检查，且失败信息说明何处违约、为何、如何修复。
- 重复、高风险且可客观检测的审查问题，应提升为带修复指引和防回归测试的自动检查；不强行自动化纯审美意见。
- 过时历史不留在工作树；仅在用户明确要求时从 Git 历史恢复。

## 顶层文档与模块入口

- 系统架构、模块边界和依赖方向：[`ARCHITECTURE.md`](ARCHITECTURE.md)
- 开发命令、验证层级与 Feature 状态规则：[`docs/development/DEVELOPMENT.md`](docs/development/DEVELOPMENT.md)
- 产品目标与范围：[`docs/product/requirements.md`](docs/product/requirements.md)
- 信源与证据约束：[`docs/sources/SOURCE_POLICY.md`](docs/sources/SOURCE_POLICY.md)
- 当前状态、阻塞和下一步：[`PROGRESS.md`](PROGRESS.md)
- 当前设计约束：[`DECISIONS.md`](DECISIONS.md)
- 文档写作与记录规则：[`DOCUMENT-WRITING.md`](DOCUMENT-WRITING.md)
- Feature 清单：[`docs/features.json`](docs/features.json)

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
