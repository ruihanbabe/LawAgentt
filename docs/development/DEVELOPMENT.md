# LawAgent 开发指南

## 标准命令

```bash
make setup
make check
make run
make health
```

当前命令以 `make help` 为准。`Makefile` 和 `bin/` 是权威入口，不在文档中复制其实现。

`make setup` 只检查解释器并在缺少 `.env` 时复制安全模板，不安装 Python 依赖。`make status` 只检查项目入口和本地解释器；服务状态使用对应的 `services-status` 或 `qdrant-status` 命令。

## 环境

- 将 `.env.example` 复制为 `.env`，密钥不得进入 Git。
- 进程环境变量优先于 `.env`。
- 当前代码要求 Python 3.11 或更高版本。默认使用 `python3`；需要指定解释器时，通过 `PYTHON` 或 `LAWAGENT_PYTHON` 覆盖。
- `LAWAGENT_GLM_ENABLED=true` 开启 GLM Provider。
- `LAWAGENT_RAG_ENABLED=true` 开启懒加载 Qdrant 检索。
- 服务镜像和拓扑以 `compose.yaml` 为准。
- `requirement.txt` 是人工环境记录，不是锁文件。

## 可选服务

```bash
make services-up
make services-status
make services-smoke
make services-down
```

持久化 smoke 会连接真实 Redis/PostgreSQL；默认应用仍使用内存 Adapter。

## 可选模型验证

`make model-smoke` 会调用真实模型。执行前必须获得用户明确授权，并确认凭据和潜在费用。

## 验证边界

`make check` 只执行离线语法编译和当前测试。lint/type-check 尚未纳入门禁；它也不证明真实 GLM、Qdrant、Redis/PostgreSQL 应用接入、浏览器行为、性能或法律质量。

## Feature / Task 分层

Feature 是 Harness 和项目进度层的最小可独立验收单元，不是 Agent 内部 task decomposition 的最小步骤。Harness 管理 **WHAT + DONE**：Feature 描述目标行为，verification 定义完成标准；Codex 管理 **HOW**，并根据当前仓库状态自行拆解 implementation tasks。

功能清单使用 [`docs/features.json`](../features.json)，当前实例保持空列表。每个项目必须具备 `id`、`behavior`、`verification`、`state` 和 `evidence` 五个字段：

```json
{
  "id": "F03",
  "behavior": "<可观测的目标行为>",
  "verification": {
    "static": "<静态检查命令>",
    "runtime": "<运行时行为验证命令>",
    "system": "<系统级流程确认命令>"
  },
  "state": "planned",
  "evidence": {
    "static": null,
    "runtime": null,
    "system": null
  }
}
```

### 完成定义与终止校验

代码完成不等于 Feature 完成。Feature 只有在下列三层验证均成功、并由 Harness 根据执行证据判定时，才能变为 `passing`；Agent 的自我评价、编译成功或部分测试不是完成证据。验证必须按顺序执行：上一层失败、未执行或被阻塞时，不得进入下一层，也不得宣称完成。核心行为未通过这些校验前，不得开展顺便重构、风格整理或性能优化。

1. **静态层**：语法、编译与已配置的静态分析。当前至少使用 `make compile`；如果 lint 已装配，同时运行 `make lint`。
2. **运行时层**：测试执行、应用启动/就绪信号、关键路径与必要副作用的验证。根据 Feature 选择当前可执行的 `make test`、`make run` + `make health`、或相关 service smoke。
3. **系统层**：端到端、集成或用户场景模拟，确认组件协作后仍满足 `behavior`。例如 HTTP 端到端验证可使用 `make test-e2e`；需真实服务、模型或浏览器的 Feature 还必须执行其对应的实环境流程。

每一层的 `verification` 必须是 Harness 可执行的命令或脚本入口，而 `evidence` 必须记录实际结果、运行时信号和证据位置/提交。应观察的信号包括：进程已启动并就绪，关键路径执行成功，数据库写入、文件操作等副作用正确，以及临时资源已清理（当 Feature 涉及该信号时）。

状态只能是 `planned`、`active`、`verifying`、`passing` 或 `blocked`。每次仅一项可处于 `active` 或 `verifying`。Harness 选择下一个 `planned` 项后将其置为 `active`；Agent 只能提交该项的 verification 请求，不得自行修改 `state`、`evidence` 或将其标记为 `passing`。Harness 按 `static` → `runtime` → `system` 执行 `verification`：仅当三层均通过时写入可追溯 `evidence` 并转为 `passing`；任一层失败时保留该层的失败证据、停止后续层级并转为 `blocked`。失败信息必须包含失败命令/信号、观察到的结果、可疑原因和下一步修复建议；不可只记录“测试失败”。

功能项以一次会话可完成为粒度校准：“用户可以将商品添加至购物车”是合适的 Feature；“实现购物车”过粗，“创建 Cart 模型的 `name` 字段”过细。创建文件、实现函数、增加字段等 implementation steps 不应机械提升为 Feature；只有当该步骤本身具有独立业务价值和独立验收标准时，才可作为 Feature。

以上是开发 orchestration 契约；当前 `ConversationHarness` 尚未实现对 `docs/features.json` 的读取、验证和状态写回，因此不得将此规则表述为已自动执行。待实现该能力时，具体数据格式、scheduler 和 validator 行为应进一步下沉到对应代码模块附近的 `README.md`。
