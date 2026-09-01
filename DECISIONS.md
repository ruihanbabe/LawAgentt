# LawAgent 当前设计决策

这里只记录仍约束当前实现的决策及其原因；完整变更过程以 Git history 为准。过时决策不保留为当前指导。

## 2026-08-31：以业务与数据边界组织 `src/`

- 决策：代码按 `api`、`conversation`、`intake`、`runtime`、`safety`、`knowledge`、`persistence`、`infrastructure` 组织；不创建尚无稳定数据 owner 的 `domain`。
- 原因：模块边界以业务职责、数据所有权、语义变化、invariants 和可替换实现为准，不能由 Agent roster 或具体 Provider 决定。
- 约束：Runtime 不拥有具体案件事实；Infrastructure 不定义业务规则；Safety 门禁 fail closed；未确认 Intake 事实不得升级为确认事实。

## 2026-08-31：当前文档只服务当前实现

- 决策：顶层 `ARCHITECTURE.md` 是系统架构事实来源，模块级 `ARCHITECTURE.md` 靠近代码；`PROGRESS.md` 只保存当前状态与下一步。
- 原因：减少历史过程和重复文档对新会话决策的干扰。
- 约束：不恢复已删除的 archive、worksheet、旧 ADR、RunState、evaluation 或 ingestion；需要历史时由用户指定 Git revision。

## 2026-08-31：可执行命令优先于 Markdown

- 决策：setup、run、test、lint、check 的权威入口是 `Makefile`；文档只说明使用边界并链接命令。
- 原因：避免文档维护第二套已失真的命令。
- 约束：`make check` 仅证明本地代码门禁，不能证明真实模型、服务、浏览器、性能或法律质量。
