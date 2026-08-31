# WS-20260819-10 Standard Make Commands
> 摘要：把重复使用的 setup、test、lint、check、run 和外部服务命令收敛到根目录 Makefile。
> 摘要：Make 目标保持为现有 bin/scripts 的薄封装，不复制产品逻辑。
> 摘要：缺少 Ruff 时 lint 必须明确失败，不能用 compile 冒充静态检查。
> 摘要：check 当前只代表预检、compile 和本地测试，不代表真实服务、浏览器、视觉、性能或 Review。
> 摘要：Qdrant stop 不删除 volume，model-smoke 不自动补跑或隐藏 Provider 成本。
> 摘要：独立 Review、完整验证、commit 和同名 tag 仍是工作流债务。

## 目标清单

- 基础：`help`、`setup`、`status`、`run`、`health`。
- 质量：`compile`、`test`、`test-e2e`、`lint`、`check`、`verify`。
- 外部：`qdrant-up`、`qdrant-status`、`qdrant-down`、`model-smoke`。

## 验证

- `make help`、`make setup`、`make compile`：通过；预检正确报告 Qdrant unavailable。
- `make test-e2e`：2/2 通过，包含正常流与 Trace fail-closed。
- `make check`：compile 与 147/147 本地测试通过，并打印未覆盖债务。
- `make -n run`：确认 HOST/PORT/PYTHON 参数正确传入 `bin/run_app`。
- `make lint`：按预期因 Ruff 未安装以 code 2 明确阻塞。
- 外部服务和真实模型目标：本 session 不自动执行。

## 后续文档同步

- 从 `requirement.txt` 将已核验技术栈版本摘要加入 README。
- 明确区分当前环境版本、架构选择和未来待安装的质量工具，避免把环境中已有 LangGraph 误写为当前 Runtime。
