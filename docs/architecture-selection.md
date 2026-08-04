# LawAgent 架构选型设计

> 用途：记录架构选型的候选、取舍、冲突和待确认事项。本文是设计讨论文档，不等同于实现授权。
> 最后更新：2026-08-04（Asia/Shanghai）

## 维护规则

1. 新增设计内容前，先检索本文和 `MEMORY.md`、`DEVELOPMENT.md`、`AGENTS.md` 中的同主题表述。
2. 如果新内容与既有“已确认”或硬约束冲突，必须在“冲突与人工审核”记录，并提示用户二次确认。
3. 冲突处理方式只能是以下三种之一：
   - **合并**：新旧表述可同时成立，更新为更精确版本。
   - **选其一**：用户明确选择新方案或旧方案，另一项降级为历史方案。
   - **保留待定**：暂不修改全局规则，只作为设计倾向继续讨论。
4. 未经用户明确确认，不把待定设计改写为 `AGENTS.md` 硬约束。
5. 本文只保存可复用的架构决策、原因、边界、风险和验收标准，不保存逐字对话。

## 当前结论

当前倾向采用 **混合架构 + 自研轻量 Agent Runtime**：

```text
确定性 Workflow 控制主流程
  + LLM 节点处理不确定语义任务
  + 规则 Router 控制下一步
  + 显式 State 记录证据、缺口、预算和失败
```

LawAgent 不追求把流程完全交给 Agent，也不把系统退化为单跳 RAG。主流程由代码控制，模型只在受约束节点中参与：

- 用户问题理解。
- 事实槽位抽取。
- 法律争点拆解。
- 查询改写。
- 证据缺口描述。
- 基于证据的回答组织。

确定性代码负责：

- Pydantic schema 校验。
- 数据库 filter 构造。
- dense/sparse 检索执行。
- 结果融合、去重和 rerank。
- 法条版本与时效检查。
- 引用一致性校验。
- 跳数、成本、超时、重试和降级。
- 权限与敏感操作控制。

一句话表述：

```text
模型可以提出“查什么”和“还缺什么”，但不能直接决定“数据库怎么过滤、证据是否足够、能否输出具体法律结论”。
```

## 选型：不用 LangGraph，改为自研 Runtime

### 当前决策

用户明确确认：MVP 不使用 LangGraph，虽然求职市场流行，但个人开发 Demo 更希望参考 Claude 一类产品架构，自己实现 state/runtime，以便降低黑盒感，明确耦合边界，方便后续排查错误和讲清楚架构。LangGraph 可以作为后续对照实验或可替换参考，当前不做。

推荐方案：

```text
AgentRuntime：执行循环、预算、日志、异常、停止条件
AgentState：保存案件事实、子问题、证据、缺口、阶段
Node：一个可执行步骤，例如 understand / retrieve / rerank / grade
Router：根据 state 和 observation 决定下一个 node
Observation：节点执行后的结构化结果
```

### 选择原因

- 法律问答对状态、证据、时效和引用校验要求高，显式状态比框架魔法更容易审计。
- 个人 Demo 更需要能讲清楚内部机制，而不是依赖流行框架名词。
- 自研轻量 Runtime 可以把模型职责、规则职责、工具职责和安全边界拆得更清楚。
- 排查错误时可以直接观察每一步输入、输出、路由原因、证据缺口和预算消耗。
- 后续仍可保留替换空间：LangGraph 可作为对照实验或可替换参考，但当前业务状态不依赖 LangGraph。

### 代价与风险

- 需要自己实现节点注册、状态持久化、执行日志、失败恢复和测试工具。
- 需要避免自研 Runtime 演化成隐式复杂框架。
- 面试中不能只说“不用 LangGraph”，必须讲清楚替代设计的状态、路由、可观测性和安全收益。

## 混合架构边界

LawAgent 的主干是 Workflow，不是自由 Agent。

```text
Request
  -> 输入校验与会话加载
  -> understand
  -> plan_issues
  -> retrieve
  -> rerank
  -> grade_evidence
      -> evidence_gap? refine_query -> retrieve
      -> missing_facts? clarify
      -> supported? answer
      -> exhausted_or_high_risk? limited_answer / abstain
```

固定阶段负责控制复杂度，局部循环负责体现 Agentic Retrieval。多跳成立的标准是：后一跳输入必须显式依赖前一跳 observation，例如新发现的法条、争点、案由、相似案例或证据缺口，而不是简单换一种措辞重复搜索。

## Runtime v0 对象模型

### AgentRuntime

职责：

- 初始化 `RunState`。
- 按 `Router` 选择下一个 `Node`。
- 执行节点并接收 `Observation`。
- 应用状态更新。
- 记录 trace、耗时、错误、预算和停止原因。
- 在终止状态输出答案、澄清问题、有限回答或建设性拒答。

不负责：

- 直接拼接检索 filter。
- 直接调用外部工具的细节实现。
- 让 LLM 任意决定流程跳转。

### RunState

`RunState v0` 已在 `lawagent_runtime/state.py` 实现，采用 Pydantic v2 模型。当前字段分为运行元信息、用户输入、事实、法律子问题、工具意图、检索尝试、证据、证据缺口和控制信息九组。

```text
run_id / session_id / case_id
schema_version / runtime_version / created_at / updated_at
raw_query / normalized_query / user_goal / language / jurisdiction / event_date
facts
legal_issues
tool_intents
retrieval_attempts
evidence_items
evidence_gaps
stage / next_node / route_reason
budget
stop_reason / final_decision
failures
trace
```

关键原则：

- `system_extracted` 不能自动升级为 `user_confirmed`。
- 证据只保存 ID、版本、分数、支持关系和摘要，不把公共知识写回案件记忆。
- 每个状态更新必须能追溯到节点、工具结果或用户确认。
- 长期记忆和内容管理后续再接入；v0 仅保留 `session_id`、`case_id` 作为未来关联点。
- `ToolIntent.filters_as_slots` 保存结构化槽位，不保存 Qdrant filter 表达式。
- `EvidenceGap` 是下一跳检索的发动机，下一跳必须服务于具体 `issue_id` 和 `gap_id`。

### Node

建议接口：

```text
NodeInput = RunState + NodeConfig
NodeOutput = Observation + StatePatch
```

节点应尽量小而清楚：

- `understand`：抽取用户目标、事实、法域、时间和缺失项。
- `plan_issues`：拆分法律子问题和证据需求。
- `retrieve`：执行法规/案例检索工具。
- `rerank`：融合、去重、重排检索结果。
- `grade_evidence`：判断子问题覆盖度、权威性、时效性和冲突。
- `refine_query`：基于证据缺口生成下一跳检索意图。
- `answer`：基于证据生成回答并做引用校验。
- `clarify`：提出少量高信息量澄清问题。
- `abstain`：输出建设性拒答、材料清单或人工律师转介建议。

### Router

Router 规则优先，LLM 只提供建议。

```text
if missing_critical_facts:
    next = clarify
elif all_required_issues_supported:
    next = answer
elif budget_exhausted:
    next = limited_answer_or_abstain
elif evidence_gap_exists:
    next = refine_query
else:
    next = abstain
```

Router 每次决策必须记录：

- 输入阶段。
- 命中的规则。
- 选择的下一节点。
- 未选择其他分支的原因。
- 剩余跳数、耗时和成本预算。

## 多跳循环待明确问题

当前多跳循环尚未冻结成最终状态图。下一轮设计需要确认：

1. `understand` 和 `plan_issues` 是否合并为一个节点。
2. 法规检索和案例检索是一个 `retrieve` 节点内部路由，还是两个显式节点。
3. `rerank` 是所有检索统一执行，还是法规/案例分开 rerank 后再融合。
4. `grade_evidence` 使用纯规则、LLM 受约束输出，还是规则 + LLM 混合。
5. 默认最大跳数、单跳 top-k、rerank top-k 和超时阈值。
6. 什么时候输出 `limited_answer`，什么时候输出 `constructive_abstention`。
7. 用户澄清后是恢复同一 `RunState`，还是开启新 run 并引用旧状态。
8. trace 保存粒度和敏感信息脱敏规则。

## 面试表达

可以这样解释选型：

```text
我没有直接使用 LangGraph，而是实现一个轻量 Agent Runtime。
原因是法律问答对状态、证据和错误追踪要求很高，我希望显式控制每一步的输入输出、预算、失败原因和证据缺口。
整体是 Workflow + Agent 节点的混合架构：主流程由状态机控制，LLM 只负责意图理解、查询改写、证据摘要等局部智能判断。
这样牺牲了一些框架便利性，但换来了更清晰的可观测性、可测试性和法律安全边界。
```

## 冲突与人工审核

### `20260804_runtime_langgraph_conflict`

状态：已确认，采用新方案。

新设计倾向：

- 不使用 LangGraph 作为 MVP Agent 编排框架。
- 参考 Claude 类架构，自研轻量 Runtime、State、Node、Router 和 Observation。
- LangGraph 保留为后续对照实验或可替换参考，当前不做。

现有冲突表述：

- `AGENTS.md` 写有硬约束：LangGraph 状态图承载多跳 Agentic 工作流。
- `MEMORY.md` 已确认技术方向中写有：Agent 使用 LangGraph，工作流基线为 LangGraph。
- `DEVELOPMENT.md` 当前基线写有：Agent 原型为 LangGraph + FastAPI 文件已存在。
- `requirement.txt` 依赖台账中仍列出 LangGraph/LangChain 缺失。

处理结果：

- `AGENTS.md`、`MEMORY.md`、`DEVELOPMENT.md`、`requirement.txt` 中的 LangGraph 表述已合并替换为“历史候选/后续对照，不作为当前依赖；自研 Runtime 为 MVP 基线”。
- 旧 `agent/` LangGraph 原型暂不删除，避免混入无关重构；新 Runtime 代码放在 `lawagent_runtime/`。

## 下一步设计切片

`RunState v0`、`Multi-Agent Communication v0` 与 `Node/Router/AgentRuntime v0` 已完成实现和单元测试。当前已具备 `AgentMessage`、`StatePatch`、`Observation`、角色权限表、节点注册、规则 Router 和最小执行循环。下一轮建议进入工具系统 v0，暂不接入长期记忆和内容管理：

```text
1. ToolSpec
2. ToolIntent 到 ToolSpec 的校验关系
3. ToolResult / ToolError
4. ToolRegistry
5. ToolExecutor
6. 工具权限与重试策略
7. search_statutes / search_cases / fetch_source 的 v0 接口
```
