# LawAgent 当前进度

## 当前状态

- 工作树：`.gitignore` 有一项未提交修改，修改前须保留并核对其意图。
- 推送：提交尚未推送。SSH 网络解析曾指向私网地址；恢复公网解析后需重新配置 GitHub SSH 密钥并推送。

## Git 检查点

- 当前检查点：`c9d2b7a refactor: reorganize runtime by domain boundaries`。
- 检查点内容：删除旧 Runtime、evaluation、ingestion 和历史文档；按领域边界迁移到 `src/`；收敛顶层入口和命令。
- 远程状态：本地 `main` 比 `origin/main` 领先 1 个提交，尚未推送。
- 完整检查点历史：`git log --oneline --decorate`；不要在 Markdown 中复制 commit 历史。

## 验证记录

| 时间 | 命令或范围 | 结果 | 边界 | 失败原因 | 修复动作 |
|---|---|---|---|---|---|
| 2026-08-31 | `make compile PYTHON=python3.11` | 通过 | 仅验证语法编译 | — | — |
| 2026-08-31 | `PYTHONPATH=src python3.11 -m unittest tests.test_env -v` | 3/3 通过 | 仅环境解析测试 | — | — |
| 2026-08-31 | `make test PYTHON=python3.11` | 阻塞 | 缺少 `pydantic`、`fastapi`、`httpx` 等项目依赖 | 依赖未安装，本地环境不可复现 | 待建立可复现依赖定义/锁文件后重跑（见「当前重点」P0） |
| 2026-08-31 | `make lint` | 阻塞 | Ruff 未安装 | Lint 工具未纳入依赖 | 待加入 lint 工具并纳入 `make check`（见「当前重点」P2） |
| 2026-08-31 | `git diff --check` | 通过 | 仅空白与补丁格式检查 | — | — |

新增记录必须同时填写「失败原因」与「修复动作」两列；`阻塞`/`失败` 结果不得留空这两列。跨 Feature 的自动修复达到单阶段 3 次上限后，在此表标注升级报告位置（`EscalationRequest`，见 [`docs/architecture/scenario-pack-and-streaming-design.md`](docs/architecture/scenario-pack-and-streaming-design.md) §9.1），不得继续自行重试。

## 已实现

- FastAPI Web/SSE 聊天入口和健康检查。
- Conversation Harness：Runtime 选择、历史/画像端口、PII 处理和 Trace 持久化。
- TaskBoard Runtime：Safety、Understanding、Retrieval、Analysis、Response、Review 六类角色。
- Matter Blackboard、角色化 Context、结构化模型候选和确定性回退。
- Tool Registry/Executor，以及可选 Qdrant 案例/法规 Adapter。
- DeliveryGate：证据、Review、法规有效期、PII 和回答结构门禁。
- 开发态 Trace、Replay 和故障注入接口。
- 默认内存存储，以及 Redis/PostgreSQL Adapter。

## 部分实现

- 当前行为主要针对租赁押金场景。
- Redis/PostgreSQL 尚未接入默认应用组装。
- 当前环境尚未重新验证真实 GLM、Qdrant 数据和服务健康。
- Intake、Safety、Knowledge、Persistence 和 Infrastructure 职责已有实现，但尚未全部形成独立物理模块。

## 未实现

- 没有依赖锁文件和可在本地完整复现的项目环境。
- 当前没有 ingestion/evaluation 包、固定产品评测集、浏览器 E2E、性能基线、金额计算器、文书生成或 MCP 集成。
- `docs/features.json` 已定义 Feature 清单与三层终止校验契约，但 `ConversationHarness` 尚未实现清单读取、验证执行或状态写回；不得将其视为已自动门禁。

## 当前重点

| 优先级 | 任务 | 完成证据 |
|---:|---|---|
| P0 | 建立可复现的 Python 依赖定义并运行当前全部测试 | 依赖文件/锁文件、干净环境安装和完整测试输出 |
| P0 | 在目标服务器重新验证当前应用 | 同一 revision 的 Git 状态、启动、`/health`、`/chat` 和环境报告 |
| P0 | 重新验证 Qdrant 集合及 Runtime → Evidence → DeliveryGate 链路 | 当前 Schema/版本、有限 smoke 和失败路径证据 |
| P1 | 决定并实现 Redis/PostgreSQL 默认应用接入 | 显式配置、重启恢复、TTL/删除行为和集成测试 |
| P1 | 分离租赁押金特定逻辑与可复用 TaskBoard 机制 | 小而稳定的接口、租赁与非租赁行为测试 |
| P1 | 产品契约重新确认后再建立固定 MVP 评测集 | 版本化 fixture、确定性门禁、Trace 覆盖和指标边界 |
| P2 | 加入 lint/type-check 并纳入 `make check` | 可复现配置和当前代码树零错误输出 |

## 交接下一步

1. 完成 GitHub SSH 密钥配置，确认 `git ls-remote origin` 可用后推送 `c9d2b7a`。
2. 核对 `.gitignore` 中删除 `chroma_db/` 忽略规则的意图，再决定是否提交。
3. 建立可复现依赖定义，在干净 Python 3.11 环境运行完整测试和 lint。

## 阻塞

- 本地 Python 3.11 环境缺少 `pydantic`、`fastapi`、`httpx` 和 Ruff，无法运行全部测试或 lint；语法编译已通过。
- 当前没有可复现依赖定义，不能通过临时安装证明新环境可复现。
- 真实 GLM、Qdrant 和持久化服务状态尚未在当前代码版本重新验证。

任何状态改为“已实现”前，都必须在目标服务器的同一代码版本上重新验证。真实模型调用、远程服务器访问和付费工作必须获得用户明确授权。
