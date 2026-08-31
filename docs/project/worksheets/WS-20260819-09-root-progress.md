# WS-20260819-09 Root Progress
> 摘要：建立根目录 `PROGRESS.md`，让新会话直接读取已完成、正在做和阻塞。
> 摘要：进度、handoff、任务队列和 session 证据各自只有一个职责，减少重复与知识衰减。
> 摘要：README、AGENTS、文档结构和机器预检均路由到新进度入口。
> 摘要：本 session 只整理文档与预检脚本，不修改产品运行行为。
> 摘要：当前 147/147 测试事实继承自最近 worksheet，本轮不以文档改动冒充重新测试。
> 摘要：独立 Review、完整验证、commit 和同名 tag 仍是工作流债务。

## 文档职责

- `PROGRESS.md`：唯一当前快照。
- `HANDOFF.md`：环境、远程入口和恢复步骤。
- `TODOS.md`：任务状态、优先级和验收。
- `docs/project/STATUS.md` 与 worksheets：逐 session 历史证据。

## 验证

- `bin/project_status`：待更新后复跑。
- `bash -n bin/project_status`：待运行。
- 旧进度入口引用扫描：待运行。

## 未完成

- 外部跨模型/Persona Review、完整产品验证、commit/tag。
