# LawAgent 交接缺口追踪表

> 追踪 2026-09-01 交接会话中识别的 7 个缺口的处理状态，以及后续 harness 同步记录。
> 每次会话更新后同步维护本表，避免下次开新对话需要重新翻聊天记录才能知道当前进度。

| # | 问题 | 状态 | 备注 |
|---|---|---|---|
| 1 | EscalationRequest schema 未定义 | ✅ 已解决 | Pydantic schema 已写入 `scenario-pack-and-streaming-design.md` §9.1，已合并进 `DECISIONS.md`/`features.json` |
| 2 | Scheduler 与 `_select_agent()` 竞价机制关系不清 | ✅ 已解决并合并 | `TaskIntent` 接口（§9.2）+ 确定性快速路径设计（§10.1）已写入 `DECISIONS.md`/架构文档/`features.json` F17。范围边界（仅限intake充分+意图确认）已确认 |
| 3 | 四级风险词表无内容 | ✅ 流程已定，内容留白 | 词表由 Codex 在编码 F16 时直接生成；验收需人工复核签字（F16 verification.acceptance_precondition） |
| 4 | Scheduler 单元测试策略无指导 | ✅ 已解决并合并 | 已写入 `DECISIONS.md`、架构文档 §10.2、`features.json` F18 verification（分单元测试/模块间耦合测试两层） |
| 5 | `depends_on` 字段是否转正 | ✅ 已解决并合并 | 已加入 `docs/features.json` 全部21个Feature。`docs/development/DEVELOPMENT.md` 已同步更新为六字段契约，并新增「Feature 选择顺序与并行边界」「自动修复与升级上限」章节 |
| 6 | `requirements.md` 未正式替换 `requirements-v2-draft.md` | ✅ 已合并 | 2026-09-01 已将草案的更新/新增内容（§1、§4、§7 更新，§14–§21 新增）合并入 `docs/product/requirements.md`，原 §1–§13 编号不变；草案文件已删除。所有引用草案文件与旧章节号的地方（`DECISIONS.md`、`docs/features.json`、架构文档、`AGENTS.md`、`DEVELOPMENT.md`）已同步更新为新编号 |
| 7 | 文书类型清单 / 意图确认选项措辞未回填 | ✅ 意图确认选项已定稿 / 🔶 文书类型清单仍待用户调研 | 意图确认选项已在 `docs/product/requirements.md §4` 定稿；文书类型清单待回填 `§15.3`，见下方「剩余待办」 |

## 剩余待办（仅此一项）

1. **文书类型覆盖范围清单**：需用户调研公开文书模板数据库后回填 `docs/product/requirements.md §15.3`，不阻塞其他部分开发。

## 2026-09-01 追加：harness 同步记录

- 交接包文件已落位：`DECISIONS.md`（27 条决策，标题行均带 `<!-- id: Dxx -->` 稳定锚点）、`docs/features.json`（21 个 Feature，六字段契约 + `context_refs` 定点索引）、`docs/architecture/scenario-pack-and-streaming-design.md`。
- `AGENTS.md`/`docs/development/DEVELOPMENT.md` 已增量更新：`depends_on` 拓扑选择、受限并行 active、四级验证递进（语法/类型检查→lint→单元测试→模块/系统层测试，分级独立重试上限各 3 次）、`EscalationRequest` 统一升级格式（覆盖编码修复超限与运行时角色能力/权限不匹配两类场景）、跨 Feature 修复隔离、按 `context_refs` 定点读取 `DECISIONS.md`/架构文档/`docs/product/requirements.md`（禁止整份读取三份文件全文）。
- 已识别并解决的两处一致性问题：(1) 「全局单一 active Feature」硬约束 vs 多 Agent 并行分支开发——已放开为受限并行（无依赖关系 + 独立分支 + 无共享文件重叠时允许多个 Feature 同时 `active`）；(2) 架构文档存在重复的 `## 3.` 标题（会破坏按章节号 grep 定位）——已删除过时的占位小节，Hook 设计章节唯一保留为 `## 3.`；顺带修正了 `DECISIONS.md` D15 与架构文档 §4.1 中把 Token Hash 要求误引用为 `requirements-v2-draft.md §9` 的引用错误（该内容实际在 `docs/product/requirements.md §9`）。
- 工作区清理：已删除 `.agents/`（第三方 skill 定义，与本项目无关）、`skills-lock.json`、`HANDOFF-TO-CLAUDE-CODE.md`（一次性会话交接文档，任务已执行完毕）、散落的 `.DS_Store`（已加入 `.gitignore`）。

## 当前状态

交接包同步、harness 增量修改、文档合并与工作区清理均已完成，可以把仓库交给 Codex 按 `docs/features.json` 的 `depends_on` 顺序开始实现。
