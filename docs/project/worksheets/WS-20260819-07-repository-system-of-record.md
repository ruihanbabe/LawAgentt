# WS-20260819-07 Repository System of Record
> 摘要：把项目、组织、运行、验证和当前进度收敛为新会话可直接回答的五问入口。
> 摘要：新增机器预检、应用启动和核心验证命令，并明确完整产品验收债务。
> 摘要：旧离线与规划 handoff 已完成来源迁移后删除，DEVELOPMENT 已精简为运行手册。
> 摘要：历史检索指标保存在专项基线文档，旧产品需求副本已删除。
> 摘要：预检确认关键入口和 Python 可用，当前 Qdrant 不在线。
> 摘要：核心测试首次暴露一个过时断言；修正后 compile 与 138/138 测试通过。

## 目标与范围

- 让任何新会话只读仓库即可回答五问，并用命令核对机器现况。
- 消除重复、过时且高发现成本的 handoff/requirements/development 内容。
- 不启动外部服务、不调用真实模型、不把核心测试冒充完整验收。

## 改动

- 新增 `README.md`、`bin/project_status`、`bin/run_app`、`bin/verify_all`。
- 重写 `DEVELOPMENT.md`；新增 `docs/testing/RETRIEVAL_BASELINES.md`。
- 删除两份旧 handoff 与 `docs/product/REQUIREMENTS.md`。
- 更新路由、Handoff、文档结构、工具、测试、信源、状态与任务队列。

## 验证与发现

- `bin/project_status`：关键文件与 Python READY；`.env` 存在；Qdrant unavailable，未自动启动。
- `bin/verify_all` 首跑：compile 通过；138 项测试中 1 项旧断言错误。
- 根因：测试期待未知 Evidence 回退成主张，但当前 Gate 要求法规版本未确认时不输出 Claim。
- 修正：断言 constructive abstention、空 Claim 和版本限制；`bin/verify_all` 复跑 138/138 通过。
- `LAWAGENT_PORT=8765 bin/run_app`：短暂启动成功，`GET /health` 返回 `{"status":"ok"}` 后正常关闭。

## 未完成强制步骤

- 独立跨模型/Persona Review：统一入口尚未建立。
- 真实 Qdrant、浏览器 E2E、视觉、性能和 30 条评测：未运行。
- commit/tag：未创建。
