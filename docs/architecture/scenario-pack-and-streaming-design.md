# ScenarioPack 接口与流式架构设计（待 Review 定稿）

> 本文档是本轮需求与架构复核会话的阶段性产出，覆盖两个已确定方向：
> ScenarioPack 接入点设计、六角色进度实时流式推送设计。
> 尚未覆盖 Safety/DeliveryGate/Understanding 等模块的现状核实，
> 这些模块的核对与本文档的最终定稿状态互相独立，后续核对如发现冲突，
> 按 `DECISIONS.md` "既有代码不享有默认豁免" 原则处理，可能回头修订本文档。
>
> **2026-09-01 更新**：六角色（`board_runtime.py`）现状已核实完毕，结论是
> ScenarioPack 落地不是"新增模块供角色调用"的简单加法，而是一次**抽取重构**——
> `UnderstandingAgent`/`RetrievalAgent`/`AnalysisAgent`/`ResponseAgent` 四个角色
> 已经把押金专属的清单、关键词匹配逻辑、兜底文案、行动建议硬编码在代码里，
> 需要先抽取搬迁到 ScenarioPack，角色代码再改为调用接口。完整清单见 §1.7。
> 本次更新前的 §1.1-§1.6 判断依然成立，§1.7 是在此基础上的范围澄清和补充。

---

## 0. 评估依据声明

按 `DECISIONS.md` 已记录的原则，本文档中每一项"保留现有结构"或"修改现有结构"的判断，
均基于该结构是否满足 `docs/product/requirements.md`（含 §14 起新增定稿章节）与已记录架构决策，
而非该代码是否已经存在。具体判断依据见各节"现状核实"小节。

---

## 1. ScenarioPack 接口设计

### 1.1 现状核实

| 模块 | 现状 | 是否符合当前需求 | 结论 |
|---|---|---|---|
| `MatterBlackboard`（`intake/blackboard.py`） | `confirmed_facts`/`candidate_facts` 为通用 `dict[str, str]`，无场景专属硬编码字段 | 符合——ScenarioPack 解耦不要求改动此数据结构 | 保留不改 |
| `AgentContextView.scenario_id`（`runtime/context.py`） | 硬编码默认值 `"rental-deposit-v0.1"`，全代码库无任何消费方 | 不符合——ScenarioPack 需要真正被读取和使用，而非静态占位字段 | 需要改造为真实注入值 |
| `SufficiencyState`（`intake/blackboard.py`） | `clarification_round` 校验上限 `le=2`，`max_clarification_rounds: int = 2` 硬编码 | 不符合——已定稿需求为最多四轮 | 需要修改为 4，且应改为由配置/ScenarioPack 提供而非硬编码字面量 |
| 事实充分性判断逻辑（"够不够进入下一层"的判断代码） | 尚未核实具体实现位置（推测在 Understanding 角色实现中，本轮未读） | 待核实 | 留待后续模块核对时确认是否存在场景专属硬编码 |

### 1.2 接口设计

```python
from typing import Literal, Protocol

class FactKeySpec(BaseModel):
    """单个事实字段的声明。"""
    key: str
    layer: Literal["intake", "analysis", "action"]
    required: bool
    description: str


class AmountItemSpec(BaseModel):
    """单个金额计算项目的声明。"""
    item_key: str
    display_name: str
    legal_basis_hint: str  # 供 Retrieval 检索对应法条使用的提示


class ScenarioPack(Protocol):
    scenario_id: str

    def required_fact_keys(
        self, layer: Literal["intake", "analysis", "action"]
    ) -> list[FactKeySpec]:
        """返回该层级判定"信息是否充分"所需的事实字段清单。"""
        ...

    def amount_calculation_items(self) -> list[AmountItemSpec]:
        """返回本场景固定的金额计算项目清单（押金场景为定稿的5类，占位场景可为空列表）。"""
        ...

    def is_amount_item_applicable(
        self, item_key: str, facts: dict[str, str]
    ) -> bool:
        """给定当前已知事实，判断某金额项目是否适用。涉及条件判断，用函数而非纯配置表达。"""
        ...

    def is_out_of_scope(self, facts: dict[str, str]) -> bool:
        """给定当前已知事实，判断是否属于本场景的排除范围。"""
        ...

    def extract_facts(self, text: str, existing_facts: dict[str, str]) -> dict[str, str]:
        """从用户原始陈述文本中抽取候选事实。关键词/信号匹配等具体识别逻辑
        完全由 ScenarioPack 实现，Understanding 角色本身不包含任何场景专属的
        文本匹配规则，只负责调用本方法并把结果写入 Blackboard。"""
        ...
```

### 1.3 接入点

- `ScenarioPack` 实例作为构造参数注入 `ConversationHarness`（或其下层的 `TaskBoardRuntime`），
  不修改 `MatterBlackboard`/`context.py` 的数据结构本身。
- `context.py` 的 `scenario_id` 字段改为从注入的 `ScenarioPack.scenario_id` 读取，不再是静态默认值。
- 事实充分性判断逻辑（待核实的具体实现位置）需要改为调用 `ScenarioPack.required_fact_keys()`，
  不得保留场景专属的硬编码判断分支。
- `SufficiencyState.max_clarification_rounds` 改为由外部配置注入（值为 4），不再是类定义里的字面量 `2`。

### 1.4 押金纠纷 ScenarioPack 的具体取值（对齐 `docs/product/requirements.md`）

- `amount_calculation_items()` 返回定稿的五类：应退押金基数、扣除项、违约金、逾期利息/资金占用赔偿、争议扣除项。
- `required_fact_keys("intake")` 对应定稿的准入清单：租赁关系状态、押金金额凭证、拒退理由、书面合同情况、是否属排除范围。
- `is_out_of_scope()` 对应定稿的排除场景判断，命中后仍正常处理（不返回错误，只是后续不走押金专属清单）。

### 1.5 占位 ScenarioPack（可扩展性验证用）

- 同一 Protocol 的另一份极简实现，`required_fact_keys` 可仅含 1-2 个字段，`amount_calculation_items` 返回空列表。
- 验收标准：切换到占位 ScenarioPack 后，`TaskBoardRuntime`/`Safety`/`DeliveryGate` 代码零改动即可运行完整一轮对话。

### 1.7 抽取重构完整清单（2026-09-01 六角色核实后新增）

按角色列出需要从代码中抽取、迁移到 ScenarioPack 的具体内容，以及需要修改的角色代码本身：

| 角色 | 需要抽取的内容 | 抽取后角色代码应变为 |
|---|---|---|
| `UnderstandingAgent` | `_questions` 字典（准入清单五项+需补充的押金金额项）；关键词匹配逻辑（`tenancy_ended`/`landlord_reason`/`contract_terms`/`evidence` 的判断规则）；硬编码的 `intent` 字符串；超范围场景判断（当前完全缺失，需新增） | 调用 `ScenarioPack.required_fact_keys("intake")` 获取清单；调用 `ScenarioPack.extract_facts()` 完成文本→事实抽取（角色代码本身不含任何场景专属文本匹配规则）；调用 `ScenarioPack.is_out_of_scope()` 判断 |
| `RetrievalAgent` | 检索 query 硬编码前缀 `"住宅租赁 押金返还 "` | 前缀改为从 `ScenarioPack` 提供的检索提示（可复用已设计的 `AmountItemSpec.legal_basis_hint` 思路，或新增单独的检索提示字段） |
| `AnalysisAgent` | 兜底文案硬编码押金专属句子；金额计算框架生成逻辑（当前完全缺失，需新增） | 兜底文案改为通用措辞或由 `ScenarioPack` 提供；新增调用 `ScenarioPack.amount_calculation_items()` + `is_amount_item_applicable()` 生成金额框架的逻辑 |
| `ResponseAgent` | 对 `UnderstandingAgent._questions` 的直接引用（角色间硬耦合）；`_final_response_content()` 中四段固定字符串（`materials`/`low_cost_communication`/`formal_notice`/`other_remedies`） | 改为通过 Context/Artifact 获取清单（不直接引用其他角色内部状态）；四段建议内容改为基于当前案件事实动态生成或至少由 `ScenarioPack` 提供模板化取值，而非全局固定字符串 |
| `FinalResponseSections` | `landlord_reason_analysis` 字段定义了但无赋值路径（死字段）；缺失 `amount_items`、`document_draft_points` 两个字段 | 补全缺失字段；`_final_response_content()` 需要真正填充 `landlord_reason_analysis` |

**范围澄清**：`SafetyAgent`、`ReviewAgent` 场景无关，本次抽取重构不涉及这两个角色。

### 1.8 已解决：ResponseAgent 行动建议生成方式定稿为"条件化模板选择"

不采用模型自由生成方案，理由与具体接口设计见 §1.9。

### 1.9 ResponseAgent 四段行动建议的模板化接口补充

`ScenarioPack` 接口在 §1.2 基础上新增：

```python
class ActionTemplateSpec(BaseModel):
    """一组行动建议模板，命中条件时整体输出。"""
    condition_key: str  # 对应案件事实的某种组合特征，如 "missing_written_contract"
    materials: list[str]
    low_cost_communication: list[str]
    formal_notice: list[str]
    other_remedies: list[str]


class ScenarioPack(Protocol):
    ...
    def action_templates(self, facts: dict[str, str]) -> ActionTemplateSpec:
        """根据当前已知事实（缺失材料类型、争议焦点类型等），从预设模板中
        选择并返回一组行动建议。不由模型自由生成，保证内容可预测、可测试，
        且不需要扩展 DeliveryGate 的证据校验范围。"""
        ...
```

`ResponseAgent._final_response_content()` 改为调用 `ScenarioPack.action_templates(facts)` 获取
四段内容，不再使用当前代码里的固定字符串。具体模板条件分支（覆盖哪些缺失材料/争议焦点组合）
留待 ScenarioPack 具体实现阶段设计，本文档不展开。

---

## 2. 流式架构设计（六角色进度实时推送）

### 2.1 现状核实

| 模块 | 现状 | 是否符合当前需求 | 结论 |
|---|---|---|---|
| `TaskBoardRuntime.run()`（`runtime/board_runtime.py`） | 完全同步阻塞循环，内部通过 `board.append_event()` 写事件，外部只能在 `run()` 返回后读取完整事件列表 | 不符合——需要运行时实时推送进度 | 需要改造 |
| `src/api/sse.py` 的 `iter_agent_events()` | 等 `conversation_harness.handle()` 完整同步跑完，才把最终文本切片、把事件回放，是"伪流式" | 不符合——决策要求真实的进度实时推送 | 需要改造 |
| `EventVisibility`（`runtime/taskboard.py`） | 枚举已定义 USER/ADMIN/DEVELOPER，但事件创建时默认值为 `DEVELOPER`，现有代码未做可见性过滤 | 部分符合——机制已存在，但未被使用，需要显式规划哪些事件标记为 USER | 复用机制，补充分级策略 |
| `ModelProvider.generate()`（`runtime/model_provider.py`） | 完全同步非流式 | 符合当前决策范围——已定稿"不做 token 级真流式"，故此签名不需要改造 | 保留不改 |

### 2.2 设计方案：后台线程 + 队列桥接（不做全异步重写）

**为什么不做全异步重写**：六角色内部逻辑（模型调用、工具执行）目前均为同步阻塞实现；
全部改为 `async def` 涉及 `TaskBoardRuntime`、所有 `BoardAgent` 实现、`ModelGateway`、`ToolExecutor`
的连锁修改，改动面大、回归风险高。"线程+队列桥接"是标准的同步代码对接异步 Web 框架模式，
改动面小，且能达成"运行时实时推送"的目标。

**具体设计**：

1. `TaskBoardRuntime` 增加可选的 `event_sink: Callable[[CollaborationEvent], None] | None` 构造参数。
2. `board.append_event(...)` 之后，若 `event_sink` 存在则同步调用一次（该调用本身仍是同步的，
   由线程内部触发，不改变 `append_event` 本身的语义和调用方）。
3. `sse.py` 中，用 `asyncio.to_thread(...)` 在后台线程执行 `TaskBoardRuntime.run()`；
   `event_sink` 内部通过 `loop.call_soon_threadsafe(queue.put_nowait, event)` 把事件安全地
   跨线程送入一个 `asyncio.Queue`。
4. SSE 端的异步生成器并发地 `await queue.get()`，实时把事件转换为前端 SSE frame 并 `yield`，
   不再等待后台线程完全结束。
5. 后台线程结束（`run()` 返回）后，往队列放入一个哨兵值（如 `None`），SSE 生成器收到后结束循环，
   随后按现有逻辑推送最终 `done`/`[DONE]` 事件。

### 2.3 EventVisibility 分级策略（复用现有机制，补充策略）

- **USER 可见**（推送到浏览器 SSE）：每个角色的 `TASK_STARTED`/`TASK_COMPLETED`（六角色进度里程碑）、
  `RUN_COMPLETED`、`DELIVERY_ACCEPTED`/`DELIVERY_BLOCKED`。
- **DEVELOPER 可见**（仅进入 Trace，不推送浏览器）：`CLAIM_REQUESTED`/`CLAIM_ACCEPTED`/`CLAIM_REJECTED`
  （认领竞价内部细节）、`CONTEXT_BUILT`（含 content_hash 等内部字段）、`NO_PROGRESS`、`TASK_DEDUPLICATED`。
- SSE 端点在转发前按 `event.visibility == EventVisibility.USER` 过滤；`DEVELOPER`/`ADMIN` 事件仍完整写入
  `AgentRunTrace`（供 Trace Viewer 使用），只是不出现在面向普通用户的 SSE 流中。

### 2.4 待确认事项

- 现有代码创建事件时基本未显式指定 `visibility` 参数（沿用默认 `DEVELOPER`），需要在具体角色实现代码中
  逐处补上 `visibility=EventVisibility.USER` 标记，这部分改动点需要在核对 Safety/Understanding 等角色
  具体实现时一并确认清单。
- 并发 Run（3-5个）场景下，多个后台线程 + 多个 Queue 的资源管理（比如 Run 异常终止时线程/队列的清理）
  需要在实现阶段设计测试用例覆盖，本设计文档暂不展开具体代码。

---

## 3. Hook 扩展机制设计（外部审计/监管平台接入）

### 3.1 设计原则

严格限定为 Observer 模式：Hook 只能读取事件、不能修改 Context、不能拦截或改变流程走向。
理由与本轮会话中其他扩展点取舍（不做自由 Plan 机制、ScenarioPack 行动建议不做自由生成）一致，
详见 `DECISIONS.md` 对应条目。

### 3.2 接口设计

```python
class HookSubscription(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    handler: Callable[[CollaborationEvent], None]
    min_visibility: EventVisibility


class HookDispatcher:
    """作为 TaskBoardRuntime.event_sink 的实际实现，支持多订阅者。"""

    def __init__(self) -> None:
        self._subscriptions: list[HookSubscription] = []

    def subscribe(
        self, handler: Callable[[CollaborationEvent], None],
        *, min_visibility: EventVisibility = EventVisibility.USER,
    ) -> None:
        self._subscriptions.append(HookSubscription(handler=handler, min_visibility=min_visibility))

    def dispatch(self, event: CollaborationEvent) -> None:
        for sub in self._subscriptions:
            if not _meets_visibility(event.visibility, sub.min_visibility):
                continue
            try:
                sub.handler(event)
            except Exception:
                pass  # 单订阅者故障不得影响主流程或其他订阅者
```

### 3.3 数据流

```
TaskBoardRuntime.run()（后台线程）
  → board.append_event(...)
  → HookDispatcher.dispatch(event)
       ├─→ SSE订阅者（min_visibility=USER）→ asyncio.Queue → 前端浏览器
       └─→ 外部审计/监管平台订阅者（min_visibility=DEVELOPER）
             → 内部缓冲队列（与Runtime主流程同步执行路径解耦）
             → 独立异步任务消费缓冲队列 → 真正的网络转发（webhook/消息队列）
```

### 3.4 硬约束

1. `dispatch()` 内部对每个订阅者异常隔离，单个订阅者故障不得影响 Run。
2. 外部网络转发必须与 Runtime 同步执行路径解耦，不得在 `dispatch()` 内直接发起同步 HTTP 请求。
3. 转发数据严格限定为 `CollaborationEvent` 对象本身（已引用脱敏 payload），不额外附加原始文本/PII/凭据。
4. **DEVELOPER 级别数据的外部访问，依赖权限管理能力**（见 §4）。MVP 阶段该接口可先预留（接口存在但不接入真实外部平台），实际启用需等待权限管理 Feature 完成，不得假设本 Hook 设计自身足以保证安全。

## 4. 权限管理缺口（新发现，需要设计）

### 4.1 现状核实

- `src/api/sse.py` 的 `user_id` 为客户端传入裸字符串，无 token 哈希验证、无绑定关系校验，直接作为 `session_id` 使用。**直接违反 `docs/product/requirements.md` §9**："匿名 Token 仅访问绑定咨询，服务端只保存 Token Hash"。
- `EventVisibility`（USER/ADMIN/DEVELOPER）只解决"哪些事件该被看到"，未解决"谁有资格看 ADMIN/DEVELOPER 级别事件"。
- `FaultInjectingConversationRepository.inject()` 无权限门槛，目前安全性仅依赖"未被暴露为 API 端点"这一偶然状态。

### 4.2 待设计（本文档暂不展开具体方案）

- Token 哈希验证机制的具体设计（如何生成、如何校验、如何绑定 session）。
- Trace/Admin 可见性事件的访问控制机制（如管理端认证方式）。
- 本文档 §3 Hook 机制中外部平台的身份验证方式（如 webhook 签名密钥）。

## 5. 风险分级改造设计（四级）

### 5.1 RiskLevel 扩展

```python
class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"        # LLM软判断，跨轮次趋势信号（意图倾向违法行为）
    HIGH = "high"             # 硬编码检测，用户正在遭受人身威胁（威胁人身/跟踪/堵门）
    CRITICAL = "critical"     # 硬编码检测，自伤或大规模暴力意图（自杀/公共场所暴力威胁）
```

CRITICAL 与 HIGH 的区分依据：CRITICAL 指向"用户自身可能造成伤害"，HIGH 指向"用户正在遭受伤害、前来求助"——
两种处境完全不同，不应共用同一套系统行为。

### 5.2 硬编码检测词表扩展

现有 `high_markers` 需要拆分为两组，并补充当前缺失的公共安全类信号：

```python
critical_markers = ("自杀", "杀", "拿刀", "炸", "爆炸", ...)  # 需要业务补全，覆盖自伤+大规模暴力
high_markers = ("威胁人身", "正在打我", "堵门", "跟踪", "骚扰")  # 用户正在遭受威胁类
```

具体词表需要业务侧补全审核，本文档不承诺列表完整性。

**产出流程定稿（2026-09-01）**：词表不在设计阶段预先给出候选清单，由 Codex 在实现本 Feature
（F16）时直接生成初版；**验收时必须人工复核并签字确认后方可视为可用**，不得默认 Codex 生成的
初版可直接上生产。详见 `DECISIONS.md` 对应决策。

### 5.3 CRITICAL 路由

`SafetyAgent.execute()` 检测到 CRITICAL 时，创建的下一步任务从 `understand_message` 改为
新的任务类型（如 `deliver_safety_redirect`），跳过 Understanding/Retrieval/Analysis，
直接产出安抚劝诫候选回答；但仍需经过 Review 与 DeliveryGate 的独立复核流程，
不得因安全场景绕过既有的确定性交付门禁。

### 5.4 跨轮次趋势判断

新增逻辑读取 `board.blackboard.risk_assessments`（历史 `RiskAssessment` 列表，现有代码
只追加存储、从未被读取），结合当前轮次的 LLM 软判断，识别"随交互轮次增多、意图逐渐
倾向违法行为"的趋势，判定为 MEDIUM。`recommended_action` 字段需要被 `ResponseAgent`/
`FinalResponseSections` 实际读取展示（现有代码计算了但从未使用）。

## 6. 独立调度 Agent 设计（LLM驱动动态调度 + 循环防护）

### 6.1 触发机制

调度 Agent 监听 `MatterBlackboard` 指定字段变化，触发字段由 `ScenarioPack` 声明
（不同场景可以不同）。`ScenarioPack` 接口在 §1.2 基础上新增：

```python
class ScenarioPack(Protocol):
    ...
    def dispatch_trigger_fields(self) -> frozenset[str]:
        """声明本场景中，哪些 Blackboard 字段变化应触发调度 Agent 重新评估下一步。"""
        ...
```

### 6.2 调度决策

触发时，调度 Agent 调用 LLM 判断下一步应调度哪个能力角色，通过现有 `TaskBoardRuntime`
的任务创建机制（与六角色现有的 `_child_task()` 模式一致）生成下一个 `BoardTask`，
不改变底层任务板引擎（依赖驱动+竞价认领机制不变）。

### 6.3 循环防护机制（借鉴 ADR-0002，作为正式开发目标）

以下机制来自历史文档 `docs/decisions/ADR-0002-orchestrated-task-ownership-and-loop-guards.md`
（原文档状态为"Accepted for planning，implementation unverified"），本项目将其采纳为正式
开发目标，具体阈值为初始草案值，需实现后用真实场景校准：

- **动作指纹循环检测**：对脱敏规范化后的动作（去PII、去时间戳/随机ID、稳定排序）做 SHA256；
  触发规则（任一命中即触发）：最近5条窗口内连续3次相同指纹；无进展动作连续3次；
  短周期（1-2步）重复；相同错误结果连续3次。
- **升级不转派**：能力角色执行单元发现自己不匹配时，只返回结构化升级请求（含原因码：
  能力不匹配/权限不匹配/上下文不足/依赖阻塞/策略冲突/预算告急/其他），不得自行转派，
  由调度 Agent 决定下一步。
- **预算单调累积**：Node/Task/Run 三层预算累计消耗，重试/转派/重规划不清零。
- **有限转派+一次兜底合并重规划**：默认最多3次转派（`maxHandoffs=3`），到限后合并当前
  上下文（不丢失已确认事实、证据ID、失败原因、预算消耗）生成一次兜底重规划，再失败即
  终止或有限回答，不再重置计数。
- **原子终止**：循环触发或预算耗尽时，取消当前调用、节点标记终止、写入对应事件、
  释放资源、控制权交还调度 Agent；每个 Task 最多一次自动重规划。

### 6.4 不受此调度器影响的部分

Safety 角色永远第一个执行，不交由 LLM 判断是否要先跑安全检查；此机制只影响
"下一步调度谁"这一层决策，不改变六角色内部执行逻辑本身。


## 7. Review 独立性与 Memory/Context 定位澄清（2026-09-01 追加）

### 7.1 ReviewAgent 不与 Scheduler 合并

`ReviewAgent` 保持独立角色。为满足"完整 Blackboard 可见性"与"能触发安全复查"两个诉求：

- 放宽 `ReviewAgent` 自身的 `ContextRolePolicy`（具体新增哪些字段/Artifact类型留待实现阶段列出，
  不得笼统开放全部内容）。
- `ReviewAgent` 可发起结构化升级请求（复用 §6.3 循环防护机制中定义的升级请求格式），
  请求重新评估安全风险；是否真的重新调度 SafetyAgent，决定权在 Scheduler，不在 ReviewAgent 自己。

理由与完整论证见 `DECISIONS.md` 对应条目。

### 7.2 最终 Agent 总数确认：七个

Safety / Understanding / Retrieval / Analysis / Response / Review（原六角色）+ Scheduler（新增调度 Agent）。
不含 ContextAgent——见 §7.3。

### 7.3 Memory 归属 MemoryService（数据流层），ContextAgent 不是独立 Agent

- **MemoryService**（新拆分服务）：负责对话历史/记忆的存储、压缩、淘汰规则，写入时即完成筛选管理，
  属于确定性数据流层，不做成 Agent。若需要"智能概括压缩超窗历史"这类需要判断力的动作，
  做成窄范围结构化模型调用（类似 AnalysisAgent 生成金额框架的模式），不包装成独立 Agent 角色。
- **ContextAgent**：不是独立 Agent，不占用任务板调度节点，不被 Scheduler 调度，不需要 LLM 判断力。
  定位为 `ContextService.build()` 的能力扩展——现有从 Blackboard/Artifact 构建 `AgentContextView`
  的过程中，新增一步从 `MemoryService` 读取已经在存储时筛选管理好的记忆数据，纯粹取数，
  不做二次加工判断。
- **现状缺陷**：`sliding_window_context_manager` 当前实现在 `src/api/sse.py`（API传输层），
  职责归属错误，需要迁移到 `MemoryService`。


## 8. RAG 检索服务化（ContextService 补洞调用，2026-09-01 追加，替代早前的升级请求方案）

### 8.1 设计

`SearchCasesAdapter`/`SearchStatutesAdapter` + `ToolExecutor` 本身即可视为独立检索 service，
被两个调用方共用：

```
                ToolExecutor + SearchCasesAdapter/SearchStatutesAdapter（唯一执行入口）
                        ↑                                    ↑
              RetrievalAgent（主线）                ContextService（补洞，新增）
              - 任务板调度，LLM精炼查询             - 直接同步调用，确定性拼接查询
              - 属于主链路一环                       - 不引入LLM，保持无判断力原则
```

`ContextService` 一侧不经过升级请求、不经过 Scheduler 审批——"补洞取数"与 Scheduler 负责的
"下一步该调度谁执行"是不同层面的问题。

### 8.2 硬性前提（不可违反）

不论哪个调用方，每次真实检索都必须产出正式的 `RAG_EVIDENCE_BUNDLE` Artifact（完整
`producer_agent`/`task_id`/`evidence_refs`）并写入 `board.artifacts`，不得因为是"顺手补洞"
省略这一步。守住此前提，`DeliveryGate` 现有检查逻辑不需要修改。调用必须经过 `ToolExecutor`，
不得绕过直连 Qdrant。

### 8.3 升级请求机制的收窄

"升级请求"机制保留，但不再用于 RAG 补洞（已被本节的直接 service 调用取代），收窄为服务于
"执行单元发现自己能力/权限/上下文确实不匹配、需要 Scheduler 裁决下一步"的场景（见 §6.3）。

---

## 9. EscalationRequest 正式 Schema 与 Scheduler-竞价机制接口（2026-09-01 追加，定稿）

> 本节把此前 `_shared_schema_note` 中的文字提示（"F18定义一次F19复用""Scheduler只决定
> 需要什么能力、竞价机制仍决定谁执行"）落实为代码级接口定义，供 Codex 直接实现，
> 不再停留在文字描述层面。

### 9.1 EscalationRequest 正式 Schema

在 F18（循环防护/预算/升级机制）对应模块中定义一次，F19（ReviewAgent 安全复查升级）
通过 import 复用，不得重新声明同名但字段不同的模型。

```python
from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class EscalationReasonCode(str, Enum):
    """升级原因码，取自 ADR-0002 既有枚举，原样复用，不做扩展。"""

    CAPABILITY_MISMATCH = "CAPABILITY_MISMATCH"      # 当前角色/Agent 不具备所需能力
    PERMISSION_MISMATCH = "PERMISSION_MISMATCH"      # 权限不足，无法执行
    CONTEXT_INSUFFICIENT = "CONTEXT_INSUFFICIENT"    # 上下文/证据不足，无法继续推进
    DEPENDENCY_BLOCKED = "DEPENDENCY_BLOCKED"        # 依赖的前置任务/Artifact 未就绪
    POLICY_CONFLICT = "POLICY_CONFLICT"              # 与既定策略/合规规则冲突
    BUDGET_AT_RISK = "BUDGET_AT_RISK"                # 循环/步数/Token 预算即将或已经超限
    OTHER = "OTHER"                                  # 以上均不适用，需人工归类


class EscalationRequest(BaseModel):
    """由任一角色在任务板上发起的升级请求。

    职责边界：
    - 本模型只描述"发生了什么、为什么升级"，不描述"接下来该怎么办"——
      后续处置（是否重试、是否转人工、是否终止任务）由 Scheduler/Review 角色决定，
      不属于本 schema 的职责范围。
    - 任何角色都可以产出 EscalationRequest，但只有 Scheduler 有权决定下一步调度，
      EscalationRequest 本身不携带调度指令（不得出现"建议下一步调度谁"这类字段）。
    """

    request_id: str = Field(..., description="唯一标识，建议 uuid4")
    task_id: str = Field(..., description="发起升级的原始任务在任务板上的 ID")
    board_id: str = Field(..., description="所属任务板 ID")
    origin_agent: str = Field(..., description="发起升级的角色标识，如 'RetrievalAgent'")
    reason_code: EscalationReasonCode
    reason_detail: str = Field(
        ..., min_length=1,
        description="人类可读的具体原因说明，用于日志、审计与人工复核，不做结构化解析"
    )
    related_artifact_ids: list[str] = Field(
        default_factory=list,
        description="与本次升级相关的 Artifact ID 列表（如已产出但不完整的证据），可为空"
    )
    attempted_count: int = Field(
        default=0, ge=0,
        description="在触发本次升级前，同一任务/同一 reason_code 已重试的次数，"
                     "供循环防护机制（§6.3）判断是否已达预算上限"
    )
    created_at: str = Field(..., description="ISO 8601 时间戳")

    class Config:
        frozen = True  # 一经创建不可变；处置结果需另建记录，不得原地修改，以保留完整升级历史
```

### 9.2 Scheduler 与 `_select_agent()` 竞价机制的接口关系

**分工原则（一句话版）**：Scheduler 决定"接下来需要什么能力的任务"，`_select_agent()`
决定"哪个具体 Agent 实例来执行这个任务"。前者产出任务描述，后者消费任务描述，
两者是流水线上下游关系，不是二选一的竞争关系。

```python
class TaskIntent(BaseModel):
    """Scheduler 的产出物：描述"需要做什么"，不指定"谁来做"。

    这是 Scheduler 与 _select_agent() 之间的唯一接口。Scheduler 的职责在产出
    TaskIntent 后即结束，不得直接引用或指定具体 Agent 实例或类名。
    """

    intent_id: str
    board_id: str
    required_capability: str = Field(
        ..., description="所需能力标签，如 'retrieval'、'analysis'、'safety_check'，"
                          "必须是 _select_agent() 竞价机制已知的能力枚举之一"
    )
    priority: int = Field(default=0, description="调度优先级，数值越大越优先")
    context_refs: list[str] = Field(
        default_factory=list, description="供执行者读取的上下文/Artifact 引用"
    )
    budget_hint: Optional[int] = Field(
        default=None, description="本任务允许的最大重试/步数预算，供循环防护参考"
    )
```

调用顺序：

```
Scheduler.decide_next_step(board_state) -> TaskIntent | EscalationRequest
        │
        │ 产出 TaskIntent（只描述"需要什么能力"，不指定执行者）
        ▼
TaskBoardRuntime._select_agent(task_intent)  ← 现有竞价机制，不做改动
        │
        │ 按 confidence 竞价，选出具体 Agent 实例
        ▼
   具体 Agent 执行任务
```

**约束**：
1. Scheduler 产出物的类型只能是 `TaskIntent` 或 `EscalationRequest` 二选一，不存在第三种返回类型。
2. Scheduler 不得在 `TaskIntent.required_capability` 中引用具体 Agent 类名或实例 ID——一旦出现，
   视为职责越界。
3. `_select_agent()` 现有竞价逻辑不做任何改动，Scheduler 是在它上游新增的一层，不替代、不修改
   其内部实现。
4. 当 Scheduler 判断"当前没有任何已知能力标签能满足需求"时，应产出 `EscalationRequest`
   （`reason_code=CAPABILITY_MISMATCH` 或 `OTHER`），而不是勉强拼一个 `TaskIntent` 硬塞给
   竞价机制——这是 Scheduler 与循环防护/升级机制（§6.3）的唯一交汇点。
5. 新增能力标签需要同时在 Scheduler 侧与 `_select_agent()` 竞价机制侧注册，不得只在一侧声明。

---

## 10. Scheduler 确定性快速路径与测试策略（2026-09-01 追加，定稿）

### 10.1 确定性快速路径

在 Scheduler 真正调用 LLM 之前，新增一段不经过模型判断的确定性检查：

```python
def decide_next_step(board: TaskBoard, scenario_pack: ScenarioPack) -> TaskIntent | EscalationRequest:
    if not _intake_facts_confirmed(board, scenario_pack):
        # 确定性快速路径：intake 必填事实未全部确认，必然调度 Understanding，
        # 不调用 LLM。与 Safety 永远第一个执行（§6.4）是同一原则的延伸。
        return TaskIntent(
            intent_id=..., board_id=board.id,
            required_capability="understanding",
        )
    # 走到这里，intake 事实已全部确认且已完成意图确认步骤，
    # 才真正进入 LLM 判断（决定 Retrieval/Analysis 等能力如何排布）
    return _llm_decide_next_step(board, scenario_pack)


def _intake_facts_confirmed(board: TaskBoard, scenario_pack: ScenarioPack) -> bool:
    required_keys = {
        spec.key for spec in scenario_pack.required_fact_keys("intake") if spec.required
    }
    return required_keys.issubset(board.blackboard.confirmed_facts.keys())
```

**范围边界（不得扩大）**：该快速路径只覆盖到"intake 事实充分 + 意图确认完成"为止，对齐
`docs/product/requirements.md §15.2`。Understanding 角色内部既有的 `SufficiencyState`/
`SufficiencyDecision`（四轮追问上限、`DELIVER_LIMITED_RESPONSE` 兜底）机制完全不变——
本节只改变"由谁决定要不要调度 Understanding"，不改变 Understanding 内部如何判断
"信息是否够了"。过了这个点之后（是否需要多轮 RAG 补洞、Retrieval 与 Analysis 顺序等），
交由 Scheduler 的 LLM 判断处理，不得把确定性范围继续往后扩展。

### 10.2 Scheduler/循环防护测试策略

对齐既有三层测试边界（§ 见 `DECISIONS.md`"存储与测试环境边界"决策条目），不新增测试分类：

| 层级 | 覆盖内容 | 具体做法 |
|---|---|---|
| 单元测试（不连网络） | 响应解析测试 | Fake `ModelProvider` 返回与真实 GLM 响应**完整包装格式**一致的 JSON，测到"解析真实响应结构"这段代码，而非只测简化后的业务对象 |
| 单元测试（不连网络） | 循环检测确定性测试 | Fake `CandidateGenerator` 持续返回相同决策，制造"卡循环"场景，验证 §6.3 四条循环检测规则（5条窗口连续3次相同指纹等）触发 |
| 模块间耦合测试（连真实GLM） | LLM 判断质量本身 | 验证 Scheduler 在真实场景下是否真的会在该升级、该终止时做出正确决策；无法用 Fake 可靠模拟；执行前需按 `AGENTS.md` 硬约束获得用户明确授权，不得在常规 CI 中默认运行 |

