# LawAgent Agent Tools & Scripts Guide
> 摘要：定义 Agent 在 `tools/` 与 `bin/` 中创建、使用和维护脚本的方法。
> 摘要：脚本用于隐藏不同 Agent、测试、视觉和性能工具的调用差异，提供统一入口。
> 摘要：核心目标包括 `agent_review`、全量验证、视觉回归、性能基准、profile 和 commit 扫描。
> 摘要：Agent 遇到重复操作时应补充脚本和文档，使后续 Agent 无需重新学习底层调用方式。
> 摘要：脚本必须可审计、可失败、可复现，并有自己的测试或 smoke 验证。
> 摘要：当前已有五问预检、应用启动和核心验证入口；review、visual、benchmark等完整验证入口仍未创建。

## 目录职责

- `bin/`：供 Agent 和开发者直接调用的稳定统一入口。
- `tools/`：脚本实现、辅助模块、配置和测试。

## 必备统一入口

- `bin/agent_review`：屏蔽 Codex、Claude、Cursor 等调用差异，支持模型与 Persona。
- `bin/verify_all`：执行下班前全量验证。
- `bin/test_confidence_audit`：执行虚假信心测试审计。
- `bin/visual_regression`：生成、对比并 review 截图。
- `bin/benchmark`：运行基准并与基线比较。
- `bin/profile`：执行针对性 profile 并输出对比报告。
- `bin/review_commits`：跨最近 commits 扫描问题。
- `bin/validate_task_graph`：验证 DAG、状态转换、owner lease、父子预算与 handoff/replan 上限。
- `bin/detect_agent_loop`：对去敏规范化 ActionRecord 执行窗口、无进展和短周期循环检测。
- `bin/validate_tool_registry`：检查每工具 Schema、读写/副作用、timeout、权限、重试/幂等、并发/限流、大小、数据、沙箱、dry-run、确认和 Reducer 配置完整性。

上述校验项当前仍是强制待建入口；已有源码不代表这些脚本已经实现，不得用文档描述或零散手工命令冒充统一入口。

## 当前可用命令

- 标准开发入口：`make help`、`make setup`、`make run`、`make test`、`make check`、`make verify`
- 可选外部入口：`make qdrant-up`、`make qdrant-status`、`make qdrant-down`、`make model-smoke`
- 五问/环境预检：`bin/project_status`
- 启动 Web/API：`bin/run_app`
- 核心验证与缺口报告：`bin/verify_all`
- 编译检查：`/root/miniconda3/envs/agent/bin/python -m compileall -q lawagent_runtime tests`
- 单元/契约测试：`/root/miniconda3/envs/agent/bin/python -m unittest discover -s tests -v`

`Makefile` 是人类与新会话的标准命令入口，目标保持为 `bin/` 或 `scripts/` 的薄封装。`make lint` 在 Ruff 未安装时明确失败，不用 compile 冒充 lint；`make check` 当前只包含 status、compile 和147项本地测试，并明确报告未覆盖债务。真实Qdrant产品E2E、视觉、性能和Review仍无统一实现入口。

## 制作规则

脚本应提供 `--help`；显式输入输出；失败返回非零；保存机器可读结果与人类摘要；避免依赖 Agent 记住隐式环境；敏感信息只从批准的环境或密钥系统读取；新增脚本同步更新本文件、workflow 与测试。Agent 发现高频手工步骤时应优先把它收敛成统一入口。
