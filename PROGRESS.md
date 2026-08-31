# LawAgent Current Progress
> 摘要：这是根目录唯一的项目进度总览，回答“已完成、正在做、被什么阻塞”。
> 摘要：这里只保存当前快照，不保存逐 session 历史；历史证据在 `docs/project/STATUS.md` 和 worksheets。
> 摘要：任务的 owner、优先级和验收标准以 `TODOS.md` 为准，接手步骤与环境恢复以 `HANDOFF.md` 为准。
> 摘要：状态必须由代码、命令输出、测试报告或明确用户决定支持，不能由旧 handoff 推断。
> 摘要：2026-08-19 当前离线基线是 compileall 与 147/147 unittest 通过，真实模型调用为零。
> 摘要：外部 Qdrant、Redis/PostgreSQL 与浏览器引擎当前未完成验证，不能用历史或 Fake 测试替代。

## 已完成

- 住宅押金纠纷 MVP 的产品范围、系统设计、接口、信源和测试契约已经建立。
- FastAPI Web/SSE 入口、六角色 TaskBoard Harness、两轮事实状态与最小权限 ContextView 已接通。
- ToolExecutor、Qdrant Adapter、安全 Evidence DTO、GLM Provider/Profile 和结构化候选调用已实现。
- DeliveryGate 已覆盖 provenance、Review、Claim-Evidence、法规有效期、PII、禁止承诺、内部标识、十段响应和 Trace fail-closed。
- supported、safe-error、limited、constructive-abstention 四条 SSE/ASGI 路径已有离线 E2E。
- 脱敏 Trace View、Replay、白名单故障注入及 Redis/PostgreSQL 存储 Adapter 已实现并通过 Fake 客户端契约测试。
- 新会话五问入口、环境预检、应用启动和核心验证入口已经建立；旧巨型 handoff 和重复 Requirements 已迁移删除。
- 根目录 `Makefile` 已收敛 setup、status、run、health、compile、test、lint、check、Qdrant 和模型 smoke 标准命令。
- Redis 7.4.2 与 PostgreSQL 16.6 已通过 Compose 安装并健康运行；agent 环境已安装 redis-py 6.4.0 与 psycopg 3.3.4，真实持久化 smoke 通过。

## 正在做

1. 恢复真实 Qdrant 端口，完成 Qdrant → Evidence → DeliveryGate 组合验证。
2. 把已验证的 Redis/PostgreSQL Adapter 接入应用组装配置，并补删除级联/重启恢复 E2E。
3. 提供浏览器引擎后执行 Web 提交、SSE 消费、Trace Viewer 和视觉回归。
4. 建立 30 条固定产品评测、确定性金额工具与用户触发的文本式文书建议。
5. 建立统一 lint、独立跨模型 Review、benchmark、profile 和完整产品验证入口。

## 当前阻塞

| 阻塞 | 影响 | 解除条件 |
|---|---|---|
| Qdrant 容器曾启动但 `127.0.0.1:6333` 当前不可达 | 不能声明实时检索与 DeliveryGate 组合链已复验 | 恢复端口并保存 collection/查询/交付证据 |
| 没有 Playwright/Selenium/浏览器二进制 | 浏览器 E2E 与视觉回归无法执行 | 安装或提供浏览器运行环境 |
| `bin/agent_review`、视觉、benchmark/profile 入口缺失 | 0–18 工作流不能完整收尾 | 实现统一入口并由不同模型/Persona 执行 |
| Git ownership 安全检查 | status/log/commit/tag 尚未按工作流完成 | 在不修改用户全局配置的前提下提供安全仓库访问方式 |

## 最近验证

- `/root/miniconda3/envs/agent/bin/python -m compileall ...`：通过。
- `/root/miniconda3/envs/agent/bin/python -m unittest discover -s tests -v`：147/147 通过。
- ASGI HTTP 正常完成与 Trace 故障安全错误路径：通过。
- 真实 API `GET /health`：已在显式测试端口启动验证通过。
- 当前 `bin/project_status`：关键文件/Python READY；`.env` 存在；Qdrant unavailable。

## 下一恢复点

先运行 `bin/project_status` 和 `bin/verify_all`。不要自动重复调用真实 GLM；现有六角色矩阵已有四角色成功、Safety/Review 限流的记录。随后优先处理不消耗模型 token 的 Qdrant 组合验证。
