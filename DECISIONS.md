# LawAgent 当前设计决策

这里只记录仍约束当前实现的决策及其原因；完整变更过程以 Git history 为准。过时决策不保留为当前指导。

## 2026-08-31：以业务与数据边界组织 `src/`  <!-- id: D01 -->

- 决策：代码按 `api`、`conversation`、`intake`、`runtime`、`safety`、`knowledge`、`persistence`、`infrastructure` 组织；不创建尚无稳定数据 owner 的 `domain`。
- 原因：模块边界以业务职责、数据所有权、语义变化、invariants 和可替换实现为准，不能由 Agent roster 或具体 Provider 决定。
- 约束：Runtime 不拥有具体案件事实；Infrastructure 不定义业务规则；Safety 门禁 fail closed；未确认 Intake 事实不得升级为确认事实。

## 2026-08-31：当前文档只服务当前实现  <!-- id: D02 -->

- 决策：顶层 `ARCHITECTURE.md` 是系统架构事实来源，模块级 `ARCHITECTURE.md` 靠近代码；`PROGRESS.md` 只保存当前状态与下一步。
- 原因：减少历史过程和重复文档对新会话决策的干扰。
- 约束：不恢复已删除的 archive、worksheet、旧 ADR、RunState、evaluation 或 ingestion；需要历史时由用户指定 Git revision。

## 2026-08-31：可执行命令优先于 Markdown  <!-- id: D03 -->

- 决策：setup、run、test、lint、check 的权威入口是 `Makefile`；文档只说明使用边界并链接命令。
- 原因：避免文档维护第二套已失真的命令。
- 约束：`make check` 仅证明本地代码门禁，不能证明真实模型、服务、浏览器、性能或法律质量。

## 2026-09-01：ScenarioPack 解决"全场景目标 vs MVP 单场景"的张力  <!-- id: D04 -->

- 决策：Runtime 六角色为通用机制层，不感知具体业务场景的领域知识（准入清单、计算项目清单、证据门槛等）；领域知识由独立 ScenarioPack 提供。ScenarioPack 内部实现采用混合形式：枚举类清单（准入信息、计算项目）用配置数据表达；涉及适用性判断的逻辑（如"违约金是否适用取决于合同条款+法定情形组合"）用少量注册函数表达。
- 原因：项目实际目标是覆盖全场景法律咨询，但 MVP 只能实现单一场景；通过接口解耦而非全场景覆盖来证明可扩展性，且保持可测试、可审计。
- 约束：MVP 完整实现"押金纠纷 ScenarioPack"；另需一个极简占位 ScenarioPack（业务内容可以很简单），仅用于验证 Runtime 核心代码加载新场景时无需修改 Runtime/Safety/DeliveryGate 代码。占位包不追求业务完整性，只作为解耦的可运行证据。

## 2026-09-01：六角色协作机制现状核实——沿用现有设计，不重做  <!-- id: D05 -->

- 决策：现有 `context.py`（`ROLE_CONTEXT_POLICIES` + `ContextService`）与 `taskboard.py`/`board_runtime.py`（claim 竞价的动态依赖任务板）已经是"Graph 控制流 + 字段级约束数据流"设计的良好实现，不是自由黑板模式，不需要推倒重做。
- 原因：`MatterBlackboard` 仅作事实存储，真正决定"谁能看到什么"的是显式声明的 `ContextRolePolicy`，每个角色只拿到按策略投影出的不可变 `AgentContextView`；控制流不是硬编码顺序，而是任务带 `dependency_ids`、角色通过 confidence 竞价认领，且已有 `BoardLimits`（`max_rounds`、`max_no_progress_rounds`、`max_task_depth`、去重）防止空转和任务爆炸，属于比静态状态图更完整的动态依赖驱动设计。
- 约束：后续架构工作聚焦在衔接细节，而非重新设计协作机制：（1）ScenarioPack 如何接入任务创建与 Context Policy（当前 `AgentContextView.scenario_id` 为占位硬编码，需要改造）；（2）Model Provider 多供应商 + SSE 抽象层现状核对（`model_provider.py`）；（3）工具执行层权限模型与 ScenarioPack 检索/计算工具的接入方式（`tools.py`）。

## 2026-09-01：存储与测试环境边界  <!-- id: D06 -->

- 决策：PostgreSQL 使用 SQLAlchemy（异步引擎 + asyncpg 驱动）；Redis 使用原生 `redis.asyncio` client，不引入 ORM。会话历史与 Trace（审计记录）存 PostgreSQL；关键运行时短期状态存 Redis；评测数据/结果存版本化文件系统目录（如 `data/evaluation/results/`），不进数据库。测试环境边界：单元测试完全不连网络，复用现有 Port/Adapter 模式的内存 Fake；模块测试连远程真实 Redis/PostgreSQL，但用独立命名空间隔离（独立 key 前缀/DB index、独立 test schema）；模块间耦合测试连全链路真实服务（含真实 GLM）。
- 原因：异步 ORM 与 FastAPI 异步栈范式一致，SQLAlchemy 认可度高且自带 Alembic 迁移；Redis 场景简单，原生 client 更轻量；Trace 的结构化查询需求（审计能力是项目核心展示点）适合关系型数据库；测试边界划分以复用现有架构、控制时间成本为优先，同时在模块层获得真实服务的边界行为覆盖。
- 约束：单元测试不得依赖外部网络；模块测试不得写入共享生产命名空间；耦合测试涉及真实模型调用前需遵守 `AGENTS.md` 中"连接远程服务器、调用真实模型或产生费用前必须获得用户明确授权"的硬约束。

## 2026-09-01：押金纠纷 ScenarioPack 领域细节定稿  <!-- id: D07 -->

- 决策：追问机制从"最多两轮"改为"最多四轮，每轮合并追问"；四轮后信息仍不足则有限回答。准入信息充分后追加一次独立于追问轮次配额之外的"意图确认"步骤，采用固定选项式（非开放问答）。金额计算采用"LLM给出适用项目类别 + 检索法条依据 + 输出计算逻辑框架，不给最终精确数字，交由用户二次确认"的降级方案；固定金额项目清单为：应退押金基数、扣除项、违约金、逾期利息/资金占用赔偿、争议扣除项（五类，不得自由新增）。行动/文书层范围收紧为"必要信息收集 + 结构化要点整理"，不做完整文书生成或导出。超范围场景（转租/群租/非住宅等）维持现状正常处理，仅不套用押金专属清单。相似案例展示规避已知数据缺陷字段（不展示案号/法院/裁判日期/URL，只展示案情摘要、裁判要点、相似/差异点）。
- 原因：详见 `docs/product/requirements.md` §14–§21，为本次可行性复核会话产出，2026-09-01 已合并入该文件，替代原文档中标注"以开发时核验为准"的留白表述。
- 约束：文书类型具体覆盖范围（催告函/调解申请等）待用户调研公开文书模板数据库后回填，不阻塞其他部分开发；意图确认选项具体措辞待最终确认。

## 2026-09-01：`model_provider.py` / `tools.py` 现状核实  <!-- id: D08 -->

- 决策：`tools.py`（`ToolPermission`/`ToolSpec`/`ToolExecutor` 权限校验+JSON Schema校验+PII处理+失败降级）判定为设计良好，ScenarioPack 新增工具（如金额计算）直接按现有 `ToolAdapter` 协议注册进 `ToolRegistry`，不改造该层核心架构。`model_provider.py` 的 `ModelGateway`/`ModelProfile`/预算治理设计合理且已预留多 Provider 接口（`ModelProvider` Protocol），但 `generate()` 完全同步非流式；现有 `src/api/sse.py` 的 SSE 实为"伪流式"——`iter_agent_events()` 等 `TaskBoardRuntime` 完整同步跑完全部六角色后，才把最终文本切成24字符块伪装打字机效果，任务/工具事件也是运行结束后一次性回放，不是运行时实时推送。`scenario_id` 字段在 `context.py` 中声明但全代码库无任何消费方，ScenarioPack 接入点当前是 0 实现。
- 原因：为下一步流式改造与 ScenarioPack 接入设计提供准确现状基线，避免基于错误假设（如误以为现有 SSE 已是真流式）展开设计。
- 约束：后续架构工作需在此现状基础上展开，不得假设 `scenario_id` 已被消费或现有 SSE 已支持真实进度/token流。

## 2026-09-01：流式架构范围——选择"六角色进度实时推送"，不做最终回答 token 级真流式  <!-- id: D09 -->

- 决策：真流式改造范围确定为"全部六角色运行进度实时推送给前端"，不做最终回答文本的 token 级真流式；继续保留当前"生成完毕后分块推送"的展示方式用于最终回答正文。
- 原因：token 级真流式与项目硬约束"最终回答不得绕过 DeliveryGate 交付"（见 `AGENTS.md`）存在架构性冲突——真流式的本质是模型吐字过程中同步展示给用户，而 Response 角色输出必须先经 Review 角色与 DeliveryGate 的证据/结构/PII 校验后才能展示；若采用"未审核草稿区展示+审核通过后转正"等折中方案，会显著增加复杂度且改变产品体验为两段式确认，另有"审核不通过后撤回已展示内容"的法律咨询场景不可接受的风险。六角色进度实时推送不涉及未审核内容提前展示，且直接呼应项目"可审计 Trace"与 Agent Harness 设计能力的展示核心，故选择该范围。
- 约束：`TaskBoardRuntime.run()` 需从同步阻塞循环改造为异步生成器，按任务/角色执行进度实时 yield 事件；此项改造范围不包含 `ModelProvider.generate()` 签名的流式化，也不包含 GLM Provider 的 `stream=True` 支持；后续如产品需求变化需要 token 级流式，需重新评估 DeliveryGate 前置审核与展示时序的折中方案。

## 2026-09-01：既有代码不享有默认豁免——评估标准是需求符合度，不是代码新旧  <!-- id: D10 -->

- 决策：本次需求与架构复核过程中，对任何既有代码模块的"保留/不改"判断，必须基于该代码是否满足本轮重新梳理定稿的需求与架构决策，而非该代码是否已经存在、已经跑通编译或曾经"看起来完整"。既有实现与新写代码在评估标准上完全对等，不因"是历史产物"而获得默认保留的豁免。
- 原因：呼应 `AGENTS.md` 已有硬约束"只报告当前环境实际执行成功的验证；mock、语法编译和历史结果不是完整验收"——现有代码此前从未在当前需求版本下被完整验证（`PROGRESS.md` 记录 `make test` 因依赖缺失无法运行），其当前状态准确定性应为"未经验证的历史实现"，不是"已定稿基线"。避免后续架构评估因"这是已有代码所以先默认保留、只在外围补丁"的隐性假设，导致新需求下实际已不再适用的旧逻辑被误当作既定事实继承下来。
- 约束：后续每一个模块的保留/修改/重写判断，都需要显式给出"该模块的现状是否满足当次已定稿需求"的结论和依据（如本次对 `MatterBlackboard` 事实结构予以保留、对 `SufficiencyState` 两轮上限予以修改的判断过程），不得仅以"代码已存在"作为保留理由；该原则适用于本文档记录的全部历史决策条目与后续新增条目。

## 2026-09-01：六角色（`board_runtime.py`）ScenarioPack 耦合现状完整核实  <!-- id: D11 -->

- 决策：六角色（Safety/Understanding/Retrieval/Analysis/Response/Review）逐一核实完毕，结论为耦合程度显著高于此前预期，不是"新增 ScenarioPack 模块供角色调用"的简单加法，而需要一次真正的**抽取重构**——把已经写死在角色代码里的押金专属逻辑搬到 ScenarioPack，角色代码改为调用接口。具体发现：
  - `SafetyAgent`：场景无关（风险关键词是人身安全通用信号），保留不改。
  - `UnderstandingAgent`：`_questions` 字典硬编码押金专属准入清单五项；关键词匹配业务逻辑（`("已退租", "已经退租", "交了钥匙", ...)` 等）直接写在角色代码里；`content` 硬编码 `"intent": "residential_rental_deposit"`；准入必需字段列表缺失"押金金额"这一项（功能性缺口，非仅架构问题）；完全没有超范围场景（排除范围）判断逻辑；`SufficiencyDecision` 枚举只有三态（`ASK_CLARIFICATION`/`START_RETRIEVAL`/`DELIVER_LIMITED_RESPONSE`），未包含本轮新定稿的"意图确认"独立状态。
  - `RetrievalAgent`：检索 query 硬编码场景前缀 `"住宅租赁 押金返还 "`。
  - `AnalysisAgent`：模型候选缺失时的兜底文案硬编码押金专属句子；完全没有金额计算框架（§6 定稿的五类项目）的生成逻辑，这是功能性缺口。
  - `ResponseAgent`：直接引用 `UnderstandingAgent._questions`（角色间硬耦合，违反角色间应通过 Context/Artifact 通信而非直接引用彼此内部状态的原则）；`_final_response_content()` 中 `materials`/`low_cost_communication`/`formal_notice`/`other_remedies` 四段均为固定字符串，不随案情变化，"分级行动建议"当前是套壳文案而非真实生成内容。
  - `ReviewAgent`：场景无关，独立复核逻辑扎实，保留不改。
  - `FinalResponseSections`（`final_response.py`）：`landlord_reason_analysis` 字段在类型中定义但全代码库无任何赋值路径，是与 `scenario_id` 同类的死字段；`amount_items`/`document_draft_points`（金额项目、文书要点整理）两个字段完全缺失，需要新增。
- 原因：按"既有代码不享有默认豁免"原则逐一核实六角色代码是否符合本轮定稿需求，发现耦合面广于此前设计文档（`docs/architecture/scenario-pack-and-streaming-design.md`）的预估，需要如实记录以避免低估后续开发工作量。
- 约束：`docs/architecture/scenario-pack-and-streaming-design.md` 需要更新，明确标注本次重构范围是抽取重构而非简单接入；`docs/features.json` 拆分 Feature 时，六角色的抽取重构需要拆成独立可验证的子任务，不得笼统合并为一项。

## 2026-09-01：ScenarioPack 接口细化——文本抽取与行动建议生成方式定稿  <!-- id: D12 -->

- 决策：(1) `UnderstandingAgent` 的文本→事实抽取逻辑（关键词/信号匹配规则）完全下沉到 `ScenarioPack`，新增接口方法 `extract_facts(text, existing_facts) -> dict[str, str]`；角色代码本身不包含任何场景专属的文本匹配规则，只负责调用该方法并把结果写入 Blackboard。(2) `ResponseAgent` 的四段行动建议（`materials`/`low_cost_communication`/`formal_notice`/`other_remedies`）采用"条件化模板选择"方案，即根据当前案件事实（缺失材料类型、争议焦点类型等条件）从 `ScenarioPack` 提供的多组预设模板中选择并组合，不采用模型自由生成的完全动态方案。
- 原因：条件化模板方案与本轮会话中其他一致性取舍保持统一（金额计算降级为"框架不给精确数字"、文书层收紧为"要点整理不做成文生成"，均为"确定性优先于个性化"的同一路线）；且完全动态生成会在 `DeliveryGate` 证据门禁之外开一个未被校验的自由文本生成口子——`DeliveryGate` 当前只校验 `claims` 是否有证据支撑，不校验这四段自由文本内容，若改为模型自由生成，需要额外扩展门禁校验范围，增加复杂度与风险，与"证据受限的确定性交付"核心原则相悖。
- 约束：模板条件分支的具体设计（覆盖哪些缺失材料/争议焦点组合）留待 ScenarioPack 具体实现阶段细化，不在本文档展开；后续如产品需求变化需要更强个性化，需重新评估 `DeliveryGate` 校验范围扩展方案。

## 2026-09-01：持久化层现状核实与存储技术决策修正  <!-- id: D13 -->

- 决策：核实发现 `persistence_adapters.py` 中 `RedisUserProfileStore`（原生 redis-py 同步 client）与 `PostgresConversationRepository`（原生 psycopg 风格 DB-API，同步阻塞，每次操作新建/关闭连接、无连接池，PostgreSQL 存储方式为 `run_id`/`session_id`/`created_at` 独立列 + 其余字段整体打包进单一 `payload JSONB` 列）已完整实现，此前 `docs/features.json` F09/F10 中"需要从零实现"的描述不准确，需修正为"迁移改造"。存储技术决策维持异步（SQLAlchemy 异步引擎+asyncpg、redis.asyncio），原因是持久化调用方按 `ARCHITECTURE.md` 职责划分位于 Conversation 层而非 Runtime 内部，不会与本轮已定的"Runtime 保持同步、线程+队列桥接流式"架构冲突，无需额外同步转异步桥接；且异步引擎自带连接池，同时解决现有实现无连接池的效率问题。PostgreSQL 存储结构从"整体 JSONB 打包"改为"关键筛选字段独立列（`status`/`decision`/`delivery_approved`/`total_cost_usd`/`total_latency_ms`）+ 其余细节仍打包 JSONB"的混合结构，不做完全规范化多表设计。
- 原因：完全规范化设计对本项目规模（MVP、3-5并发）是过度工程；但完全不拆分关键字段，会让"可审计 Trace"这一核心卖点在演示时只能"打开单条记录看JSONB"，无法展示"筛选被拦截的Run""按成本排序"这类真正体现审计能力的查询，与项目定位（求职作品，核心展示Agent Harness设计能力）不符。
- 约束：`docs/features.json` F09/F10 需要修正为"迁移改造现有同步实现为异步 SQLAlchemy/redis.asyncio，并将 PostgreSQL 存储结构从整体 JSONB 改为关键字段独立列+细节JSONB的混合结构"，而非"从零实现"；具体拉出哪些字段以本决策列出的五项为准，如后续 Trace Viewer 设计发现需要更多筛选维度，可增量补充列，不需要重新设计整体结构。

## 2026-09-01：修正此前判断——`ConversationHarness.handle()` 现状核实，持久化调用与 Runtime 执行同处一个同步函数  <!-- id: D14 -->

- 决策：核实 `conversation/harness.py` 后，纠正此前"持久化调用位于 Conversation 层、不会与线程化 Runtime 执行冲突，无需同步转异步桥接"的判断——该判断基于未读取 `harness.py` 前的推测，实际现状是 `ConversationHarness.handle()` 为单一同步函数，`create_run`/`append_history`（前）、`runtime.run()`（六角色执行）、`save_blackboard`/`save_trace`/`append_agent_message`/`append_history`（后）全部在同一个同步调用链中；且 `src/api/sse.py` 当前整体调用的是这个 `handle()`，不是直接调用 `TaskBoardRuntime.run()`。修正后的方案：`ConversationHarness` 需要拆分为三段——准备阶段（PII处理+`create_run`/`append_history`，异步持久化调用在主事件循环直接 `await`）、Runtime 执行阶段（仅 `runtime.run()` 本身通过 `asyncio.to_thread()` 放入后台线程，`event_sink` 走队列桥接进度事件，此部分设计不变）、收尾阶段（`save_blackboard`/`save_trace`/`append_agent_message`/`append_history`，异步持久化调用在线程结束后于主事件循环 `await`）。拆分后必须原样保留 `save_trace` 失败即阻断本轮交付（`TracePersistenceError`）这一业务不变量。
- 原因：诚实记录此前判断错误的过程与修正依据，避免同一错误在后续实现阶段被无意识地沿用；呼应"既有代码不享有默认豁免"原则——包括本文档自身此前基于不完整信息做出的判断，同样需要在新证据出现时被重新检验和修正，不因"已经写进决策文档"而免于修正。
- 约束：`docs/features.json` F12（SSE 端点改造）需要更新为覆盖 `ConversationHarness` 的三段式拆分，而不只是"给 TaskBoardRuntime.run() 加 event_sink"；新增 Feature 描述 `ConversationHarness` 拆分本身的验收标准。

## 2026-09-01：权限管理现状核实——用户身份验证缺失，违反已定稿隐私需求  <!-- id: D15 -->

- 决策：核实确认 `src/api/sse.py` 当前无任何用户身份验证机制——`user_id` 为客户端传入的裸字符串，服务端未做哈希校验或绑定关系验证，直接作为 `session_id` 使用；未发现任何 token 哈希、admin 权限校验的实现。此现状直接违反 `docs/product/requirements.md` §9 已定稿的"匿名 Token 仅访问绑定咨询，服务端只保存 Token Hash"要求，判定为需要设计与实现的真实缺口，而非架构选择。同时确认：现有 `EventVisibility`（USER/ADMIN/DEVELOPER）机制只解决"哪些事件该被看到"，未解决"谁有资格看 ADMIN/DEVELOPER 级别事件"；`FaultInjectingConversationRepository.inject()` 无权限门槛保护，目前安全性仅依赖"未被暴露为 API 端点"这一偶然状态。
- 原因：按"既有代码不享有默认豁免"原则核实用户直接提出的权限管理问题，发现该问题不是需要论证是否要新增的可选项，而是已定稿需求要求、但从未被实现的缺口。
- 约束：需要新增 Feature 覆盖 token 哈希验证机制的设计与实现；Trace/Admin 可见性事件的访问控制需要在任何 Trace Viewer 或外部数据转发功能上线前完成，本会话新设计的 Hook 机制（见下一条决策）直接依赖此权限管理能力，不能假设其已自洽。

## 2026-09-01：Hook 扩展机制设计——仅只读观察，不具备流程干预能力  <!-- id: D16 -->

- 决策：项目可以扩展 Hook 机制，但严格限定为"Observer模式"（只读通知外部代码事件发生，不允许 Hook 修改 Context、拦截决策或改变流程走向）；不采用"可拦截/可修改流程"的 Hook 形态。具体设计：`HookDispatcher` 作为 `TaskBoardRuntime.event_sink` 的实际实现，支持多个订阅者（`HookSubscription`），每个订阅者声明 `min_visibility` 过滤接收的事件级别；`dispatch()` 对每个订阅者做异常隔离（单个订阅者故障不影响主流程或其他订阅者）。用于外部审计/监管平台接入时，订阅者 handler 本身只做入队操作，真正的网络转发由独立的异步任务消费缓冲队列完成，与 Runtime 主流程同步执行路径完全解耦，避免外部平台的网络延迟或故障拖累 Run 执行。转发数据严格限定为 `CollaborationEvent` 对象本身（已经引用脱敏后的 payload，不额外附加原始文本/PII/凭据）。
- 原因：与本次会话中"不做自由 Plan 机制""ScenarioPack 行动建议用模板不用自由生成"等历次取舍保持同一原则——允许的扩展点必须是"只读/只通知"，不能是"能左右流程走向"，以保持 `DeliveryGate` 等确定性门禁的可预测性不被 Hook 机制绕过。通用的"可拦截修改"型 Hook 系统属于框架级能力，与项目作为单人使用的求职作品定位不匹配，属于过度设计。
- 约束：外部审计/监管平台若需要 `min_visibility=DEVELOPER`（内部细节级别）的数据，必须先具备本文档上一条决策中记录的权限验证能力（如 webhook 签名密钥或 API Key 校验），本 Hook 设计不能在权限管理缺口补齐前，安全地向外部暴露 DEVELOPER 级别数据；MVP 阶段该接口可先预留（接口存在但不接入真实外部平台），实际启用需等待权限管理 Feature 完成。

## 2026-09-01：SafetyAgent 风险分级改造为四级，扩展硬编码检测与跨轮次趋势判断  <!-- id: D17 -->

- 决策：`RiskLevel` 从现有三级（LOW/MEDIUM/HIGH）扩展为四级（LOW/MEDIUM/HIGH/CRITICAL）。CRITICAL 专指自伤或大规模暴力意图（如自杀、公共场所爆炸威胁），由硬编码规则单轮检测，命中后**不进入正常分析流程**，直接路由到安抚劝诫响应（但仍需经过 Review 与 DeliveryGate，不得因安全场景绕过独立复核）。HIGH 保留给人身安全受威胁类信号（威胁人身、跟踪、堵门等，用户通常是求助方而非风险来源），照常处理并附加安全提示。MEDIUM 由 LLM 软判断产生，覆盖"咨询过程中意图逐渐倾向违法行为"这类跨轮次趋势信号，照常处理但在 FinalResponse 中附加说明。硬编码关键词需要补充覆盖当前缺失的公共安全类信号（现有 `high_markers` 偏重人身伤害/自杀/被威胁，缺公共场所暴力类词汇）。跨轮次趋势判断需要新增逻辑读取 `board.blackboard.risk_assessments` 历史记录，现有代码仅追加存储、从未被读取使用。硬规则判定的等级不得被模型判断下调，模型只能维持或升级（现有此约束保留）。
- 原因：现有 `SafetyAgent` 已具备硬编码检测+模型软判断的雏形，但存在具体功能缺口：检测到高危信号后未改变后续行为（HIGH/CRITICAL 混在一起、流程照常往下走）；`recommended_action` 字段被计算但从未被 `ResponseAgent`/`FinalResponseSections` 读取展示；跨轮次趋势数据已存储但从未被使用。四级划分把"用户自身有伤害意图"与"用户正在遭受人身威胁前来求助"两种处境不同的信号分开，避免将求助者信号误判为需要阻断的风险来源。
- 约束：CRITICAL 触发的路由逻辑不新增模块，由 `SafetyAgent` 决定创建不同类型的下一步任务（跳过 Understanding/Retrieval/Analysis，直接产出安抚劝诫候选），职责仍在 Safety 内部，不下沉给 ScenarioPack 或依赖 LLM 判断（保持确定性）。

## 2026-09-01：独立调度 Agent 角色 + 借鉴 ADR-0002 的循环防护/预算/升级机制  <!-- id: D18 -->

- 决策：新增独立的调度 Agent 角色，职责是监听 `MatterBlackboard` 指定字段的变化（触发字段由 ScenarioPack 按场景声明，不同场景可以不同，呼应此前"字段粒度按业务和场景选择"的决策），触发时调用 LLM 判断下一步应该调度哪个能力角色，通过现有 `TaskBoardRuntime` 的任务创建机制（`_child_task` 同类模式）生成下一个 `BoardTask`，不改变底层任务板引擎本身。为约束这一层新增的不确定性，借鉴历史文档 `ADR-0002-orchestrated-task-ownership-and-loop-guards.md`（原仓库中"Accepted for planning，implementation unverified"的规划性设计）中的以下机制，作为本项目正式的开发目标：
  1. **循环检测**：对脱敏规范化后的"动作指纹"（去 PII、去时间戳/随机 ID、稳定排序）做 SHA256，触发规则为最近 5 条窗口内连续 3 次相同指纹、无进展动作连续 3 次、短周期（1-2步）重复、相同错误结果连续 3 次，四条规则任一命中即触发；不得直接对原始文本做 hash（会包含 PII 且产生假阴性）。
  2. **升级不转派**：调度产生的每个能力角色执行单元，如果发现自己不匹配（能力/权限/上下文不足），只能返回结构化的升级请求（含原因码），不得自行决定转派给哪个角色；由调度 Agent 决定下一步。
  3. **预算单调累积**：Node/Task/Run 三层预算累计消耗，重试/转派/重规划不得清零已消耗预算。
  4. **有限转派+一次兜底合并重规划**：默认最多 3 次转派，到限后合并当前上下文（不得丢失已确认事实、证据 ID、失败原因、预算消耗）生成一次兜底重规划，再失败即终止或有限回答，不再重置计数。
  5. 循环触发或预算耗尽时必须原子执行：取消当前调用、节点标记终止、写入对应事件、释放资源、控制权交还调度 Agent；每个 Task 最多一次自动重规划。
- 原因：切换为 LLM 驱动的动态调度后，"下一步该谁执行"不再是确定性代码硬编码决定，失控风险显著上升（LLM 可能反复调度、判断失误导致死循环或预算逃逸）；`ADR-0002` 已经是同类问题的成熟规划性设计，具体机制（动作指纹规范化+多重窗口规则、owner/epoch 防止迟到写入、升级不转派保持责任单一）经过原文档的完整论证（如"为什么不直接 hash 原始消息""为什么静态 DAG 不够"），直接复用可以避免重新发明，且与本项目一贯坚持的"确定性兜底、不能仅靠 Prompt 要求 Agent 自觉"的原则完全一致。
- 约束：**具体阈值（5条窗口、连续3次、maxHandoffs=3 等）沿用 ADR-0002 草案数值作为初始值，明确标注为未经真实负载校准，需要在实现后用真实场景测试调整，不得当作已验证的最终值**；Safety 角色永远第一个执行，不受此调度器影响（不交由 LLM 判断是否要先跑安全检查）；此机制不影响现有六角色内部逻辑，只影响"下一步调度谁"这一层决策；`docs/features.json` 需要新增对应 Feature 覆盖调度 Agent 本身、循环防护机制两部分，按粒度拆分为独立可验收单元，不得合并为一项笼统任务。

## 2026-09-01：Review 不与 Scheduler 合并；ScenarioPack 落地为七个 Agent（不含 ContextAgent）  <!-- id: D19 -->

- 决策：`ReviewAgent` 不与调度 Agent（Scheduler）合并，保持独立角色。用户提出"Review需要完整blackboard读写权限综合判断、需要能重新触发SafetyAgent复查风险"两个真实诉求，通过以下更精确的方式满足，不通过合并角色实现：(1) 放宽 `ReviewAgent` 自身的 `ContextRolePolicy`，允许其看到比现有策略更完整的 Blackboard 内容（而非通过合并获得"主Agent"式的全局读写权）；(2) `ReviewAgent` 可以发起结构化"升级请求"（复用本文档上一条决策中"升级不转派"的模式），请求重新评估安全风险，但**是否真的重新调度 SafetyAgent，决定权在调度 Agent，不在 ReviewAgent 自己**，避免复核者自己决定要不要给自己重新机会这种自我循环风险。最终确认 Agent 总数为七个：Safety/Understanding/Retrieval/Analysis/Response/Review（原六角色）+ Scheduler（新增调度 Agent）；此前讨论中提出的"ContextAgent"不作为第八个独立 Agent（见下一条决策）。
- 原因：技术上合并不会直接破坏 `DeliveryGate` 的 provenance 链检查（该检查依赖 `producer_agent` 不同而非依赖调度权分离，此前判断该点论据不准确已修正）；但合并会带来两项实际代价：其一，同一角色同时承担"规划下一步"（建设性、面向未来）与"挑剔审视最终结果"（怀疑性、面向已完成产物）两种不同性质的判断，两种思维模式混在同一次调用中通常导致两者表现均打折扣；其二，"复核者拥有决定是否给自己重新评估机会的权力"本身构成利益冲突，与本项目独立复核机制的设计初衷相悖。放宽 Context 策略与升级请求机制均不需要合并角色即可实现用户提出的诉求，且实现代价更小、边界更清晰。
- 约束：`ReviewAgent` 放宽后的 `ContextRolePolicy` 具体范围需要在实现阶段明确列出新增可见的 Blackboard 字段/Artifact 类型，不得笼统开放全部内容；升级请求机制复用 F18（循环防护）中已定义的结构化升级请求格式，不另起一套。

## 2026-09-01：Memory 管理归属数据流层（MemoryService），不做成独立 Agent；ContextAgent 定位为 ContextService 的只读能力扩展  <!-- id: D20 -->

- 决策：Memory（对话历史/记忆）的存储、压缩、淘汰规则归属新拆分的 `MemoryService`，属于数据流层的确定性规则（写入时即完成筛选/管理），不做成 Agent 层面的判断实体。此前讨论提出的"ContextAgent"最终定位为：**不是独立 Agent，不占用任务板调度节点，不被 Scheduler 调度，不需要 LLM 判断力**；而是 `ContextService.build()` 现有机制的能力扩展——在现有从 Blackboard/Artifact 构建 `AgentContextView` 的基础上，新增一步从 `MemoryService` 读取"已经在存储时筛选管理好"的记忆数据，纯粹取数，不做二次加工判断。同时确认一处现状缺陷：现有滑动窗口历史管理（`sliding_window_context_manager`）目前实现在 `src/api/sse.py`（API传输层），不符合模块职责划分原则（该逻辑属于业务/记忆策略，不属于传输层），需要迁移到 `MemoryService` 归属的正确位置。
- 原因：与本次会话反复坚持的原则一致——能用确定性规则/服务层封装解决的判断，不引入独立的、走 Agent 调度和 LLM 判断的实体，减少不必要的失控风险面和审计复杂度；"记忆该保留多少、该怎么压缩"这类策略性判断如果做成独立 Agent，本质上是新增了一个不受现有门禁约束的判断点，与"金额计算不让LLM自由发挥""行动建议用模板不自由生成"等已确认原则相悖。`sliding_window_context_manager` 位置错误是按"既有代码不享有默认豁免"原则核实用户描述时顺带发现的现状问题，一并记录。
- 约束：`MemoryService` 内部如果确实需要"智能概括压缩超出窗口的历史"这类需要判断力的动作，应做成窄范围的结构化模型调用（类似 `AnalysisAgent` 调用模型生成金额框架的模式），不得包装成拥有宽泛判断权的独立 Agent 角色；`docs/features.json` 需要新增 Feature 覆盖 `MemoryService` 的拆分与 `sliding_window_context_manager` 的迁移，以及 `ContextService.build()` 读取 `MemoryService` 这一能力扩展。

## 2026-09-01：RAG 检索能力服务化——ContextService 可直接调用检索 Service 补洞，不经过 Scheduler 审批  <!-- id: D21 -->

- 决策：现有 `SearchCasesAdapter`/`SearchStatutesAdapter` + `ToolExecutor` 本身即可作为独立的检索 service 被多个调用方复用，不需要新建。除 `RetrievalAgent`（主线，走任务板调度、LLM精炼查询、属于 Safety→Understanding→Retrieval→Analysis 主链路一环）外，`ContextService` 在构建 Context 过程中发现 Memory 无法满足信息需求时，可**直接同步调用同一套检索 service** 补洞，不需要经过升级请求、不需要 Scheduler 审批决定"要不要查"——因为"补洞取数"和 Scheduler 负责的"下一步该调度谁执行"是不同层面的问题，不应绑定同一套决策权收拢机制。`ContextService` 一侧的查询构建方式采用确定性拼接（复用 `RetrievalAgent` 现有的无LLM兜底查询逻辑思路），不引入 LLM 精炼，保持"ContextAgent不需要判断力"这一原则。
- 原因：相比此前"发现缺口→发起升级请求→由 Scheduler 决定是否触发 RetrievalAgent"的方案，直接 service 调用更直接、链路更短；"升级不转派"机制的设计初衷是防止执行单元自行决定"下一步调度谁"（这会破坏责任单一性），但补洞取数不涉及"决定下一步调度谁执行"，不属于该机制要管辖的范畴，强行套用反而增加不必要的复杂度。
- 约束：**硬性前提**——不论 `RetrievalAgent` 调用还是 `ContextService` 调用，每一次真实检索都必须产出正式的、带完整 `producer_agent`/`task_id`/`evidence_refs` 的 `RAG_EVIDENCE_BUNDLE` Artifact 并写入 `board.artifacts`，不得因为是"顺手补洞"而省略建 Artifact 这一步——否则 `DeliveryGate` 的 `EVIDENCE_EXISTS` 检查会出现无法追溯的证据链缺口。守住此前提后，`DeliveryGate` 现有检查逻辑不需要任何修改。调用必须经过 `ToolExecutor`，不得绕过直连 Qdrant（`AGENTS.md` 已有硬约束的适用范围明确包含此新增调用方）。"升级请求"机制保留，但收窄为服务于"执行单元发现自己能力/权限/上下文确实不匹配、需要 Scheduler 裁决下一步"的场景，不再用于 RAG 补洞这类可以直接靠 service 调用解决的场景。

## 2026-09-01：`EscalationRequest` 正式 Schema 定稿  <!-- id: D22 -->

- 决策：`EscalationRequest`（升级请求）此前只在文字描述中出现（"含原因码"），从未定义代码级字段结构，导致 F18/F19 存在各自实现出互不兼容格式的风险。现正式定稿：`EscalationReasonCode` 枚举（`CAPABILITY_MISMATCH`/`PERMISSION_MISMATCH`/`CONTEXT_INSUFFICIENT`/`DEPENDENCY_BLOCKED`/`POLICY_CONFLICT`/`BUDGET_AT_RISK`/`OTHER`，与 ADR-0002 原枚举一致不做扩展）与 `EscalationRequest` Pydantic 模型（字段：`request_id`/`task_id`/`board_id`/`origin_agent`/`reason_code`/`reason_detail`/`related_artifact_ids`/`attempted_count`/`created_at`，`frozen=True` 不可变）在 F18 对应模块中定义一次，F19 通过 import 复用，不得重新声明同名但字段不同的模型。完整字段定义与调用约束见 `docs/architecture/scenario-pack-and-streaming-design.md` §9.1。
- 原因：`_shared_schema_note` 中"F18定义一次、F19复用"只是文字提示，没有落到可供 Codex 直接实现的代码级接口，容易导致两个 Feature 各自"发明"格式、后续对接不上；`EscalationRequest` 不可变且不含调度指令（不允许出现"建议下一步调度谁"字段），是为了保留完整升级历史供循环检测按 `attempted_count` 判断，同时保证"只有 Scheduler 能决定下一步"这一权力单一性原则在 Schema 层面就被锁死，不给实现阶段留下被绕过的空子。
- 约束：`docs/features.json` F18 的 `behavior` 需要引用本决策定义的具体字段结构；F19 `behavior` 需要显式声明"复用 F18 定义的 EscalationRequest，不重新定义"。

## 2026-09-01：Scheduler 与现有 `_select_agent()` 竞价机制的接口关系定稿  <!-- id: D23 -->

- 决策：新增 `TaskIntent` 作为 Scheduler 与 `_select_agent()` 之间的唯一接口——Scheduler 产出 `TaskIntent`（只含 `required_capability` 能力标签、`priority`、`context_refs`、`budget_hint`，不得引用具体 Agent 类名或实例），`_select_agent()` 消费 `TaskIntent` 按现有 confidence 竞价机制选出具体执行者；两层是流水线上下游关系，不是二选一的竞争关系，`_select_agent()` 现有竞价逻辑不做任何改动。Scheduler 判断"当前没有任何已知能力标签能满足需求"时，应产出 `EscalationRequest`（`reason_code=CAPABILITY_MISMATCH` 或 `OTHER`），而不是勉强拼一个 `TaskIntent` 硬塞给竞价机制——这是 Scheduler 与循环防护/升级机制的唯一交汇点。完整接口定义见 `docs/architecture/scenario-pack-and-streaming-design.md` §9.2。
- 原因：`_shared_schema_note` 中"Scheduler只决定需要哪种能力的任务，竞价机制仍负责哪个具体Agent实例执行"此前只是一句文字澄清，没有对应的代码级接口，容易被 Codex 误解为"Scheduler 直接指定执行者、绕过竞价"或"两套机制冲突/重复"；`TaskIntent` 作为显式接口类型，把这句文字澄清变成 Codex 无法绕过的类型约束。
- 约束：Scheduler 产出物的类型只能是 `TaskIntent` 或 `EscalationRequest` 二选一，不存在第三种返回类型；`TaskIntent.required_capability` 取值必须是 `_select_agent()` 竞价机制已知的能力标签枚举之一，新增能力标签需要同时在两侧注册，不得只在一侧声明。

## 2026-09-01：四级风险硬编码词表——产出流程定稿为"Codex 开发时直接生成"  <!-- id: D24 -->

- 决策：四级风险硬编码词表（`critical_markers`/`high_markers`）不在设计阶段预先给出候选清单供人工复核，**由 Codex 在实现 F16（SafetyAgent 四级风险分级）时直接生成**，不再单独走"先起草候选、人工复核"的中间步骤。
- 原因：此前设计文档中的示例词（"自杀""杀""拿刀""炸""爆炸"等）明确标注为占位示例、非最终清单；用户明确决定该清单的产出时机后移到具体编码阶段，不在本轮交接中预先锁定内容。这不改变四级风险分级机制本身的设计，只影响"词表内容何时、由谁产出"这一执行细节。
- 约束：**遗留风险需在验收标准中体现**——由于词表并非经过业务侧专门审核产出，F16 验收时必须要求人工复核 Codex 生成的初版词表并签字确认，不得默认其可直接上生产；`docs/features.json` F16 的 `verification` 字段需要追加"词表需人工复核签字确认"这一验收前置条件。

## 2026-09-01：Scheduler 确定性快速路径——intake 事实收集阶段不占用 LLM 判断，与 Safety 优先执行同一原则  <!-- id: D25 -->

- 决策：在 Scheduler 的 LLM 决策入口前新增一段确定性快速路径：只要 `ScenarioPack.required_fact_keys("intake")` 中标记 `required=True` 的字段尚未全部进入 `confirmed_facts`，Scheduler 直接返回 `TaskIntent(required_capability="understanding")`，不调用 LLM；只有当 intake 事实全部确认、且已完成 §4 定义的"意图确认"步骤后，Scheduler 才真正调用 LLM 进入后续调度判断（决定 Retrieval/Analysis 等能力如何排布）。Understanding 角色内部既有的 `SufficiencyState`/`SufficiencyDecision`（含最多四轮追问上限、`DELIVER_LIMITED_RESPONSE` 兜底）机制不变，本决策只改变"由谁决定要不要调度 Understanding"这一层，不改变 Understanding 内部如何判断"信息是否够了"。
- 原因：这一步的"下一步该调度谁"在架构上本就只有唯一答案（intake 未齐必然调度 Understanding），属于可以直接用代码判断的确定性事实，不是需要模型裁量的决策；让 LLM 在这种必然结果上做判断，只会增加成本和不必要的失控风险面，且与本项目已确立的"确定性优先于自由判断""Safety 永远第一个执行、不受调度器影响"（见"独立调度 Agent 角色…"决策条目）是同一原则的延伸，不是新增例外。
- 约束：该快速路径的适用范围严格限定为"intake 事实充分 + 意图确认完成"为止，对齐 `docs/product/requirements.md §15.2`"用户确认意图后即可进入分析，不额外要求更细的争议焦点信息"这一定稿边界；过了这个点之后（是否需要多轮 RAG 补洞、Retrieval 与 Analysis 的顺序等）才交由 Scheduler 的 LLM 判断处理，不得把快速路径的确定性范围继续往后扩展到这些环节。`docs/features.json` F17（调度 Agent 实现）需要覆盖该快速路径的实现与验收标准。

## 2026-09-01：Scheduler/循环防护单元测试策略——对齐既有三层测试边界，不新增概念  <!-- id: D26 -->

- 决策：Scheduler 相关测试按以下方式落实到既有三层测试边界（见"存储与测试环境边界"决策条目），不新增独立的测试分类：(1) 现有"单元测试"层（完全不连网络）覆盖两类测试——其一是响应解析测试，Fake `ModelProvider` 返回与真实 GLM 响应**完整包装格式**一致的 JSON（而非简化后的业务对象），确保测到"解析真实响应结构"这段代码；其二是循环检测本身的确定性测试，用能持续返回相同决策的 Fake `CandidateGenerator` 制造"卡循环"场景来验证循环检测触发（5条窗口连续3次相同指纹等四条规则）。(2) 现有"模块间耦合测试"层（连全链路真实服务含真实 GLM）覆盖"LLM 判断质量本身"，即 Scheduler 在真实场景下是否真的会在该升级、该终止时做出正确决策——这类行为无法用 Fake 可靠模拟，必须连真实网络验证，调用前需按 `AGENTS.md` 硬约束获得用户明确授权。
- 原因：Scheduler 涉及"非确定性 LLM 判断"与"确定性防护机制"两种不同性质的逻辑，如果不加区分地全部塞进"单元测试不连网络"这一条硬约束，会导致 Codex 要么写出依赖真实 LLM 随机性的脆弱单元测试，要么因为约束互相矛盾而卡住；但也不需要为此新增第四层测试分类——现有三层边界的"单元/模块/耦合"划分标准（是否连网络、是否验证真实判断质量）本身已经能覆盖这两种情况，只是此前没有针对 Scheduler 场景写清楚具体怎么落地。
- 约束：`docs/features.json` F18 的 `verification.runtime` 对应"单元测试"层，需覆盖上述两类不连网络的测试；F18 新增或复用一个"模块间耦合测试"层的验证项，专门验证 Scheduler 真实判断质量，执行前需获得用户明确授权，不得在常规 CI/自动化流程中默认运行。

## 2026-09-01：`docs/features.json` 新增 `depends_on` 字段，正式转正 Feature 间依赖关系  <!-- id: D27 -->

- 决策：`docs/features.json` 的 Feature 数据契约从原有 `id`/`behavior`/`verification`/`state`/`evidence` 五字段扩展为六字段，新增 `depends_on: list[str]`，取值为该 Feature 直接依赖的其他 Feature `id` 列表，无依赖则为空数组。此前用顶层 `_recommended_order_note` 自然语言提示的做法作废，具体依赖关系见本次更新后的 `docs/features.json`。
- 原因：`_recommended_order_note` 只是临时应急，不是结构化数据，Codex 或后续工具无法按依赖关系做自动化排序/校验；转正为正式字段后，依赖关系可被程序读取和校验，且比自然语言描述更不容易在后续更新中出现遗漏或歧义。
- 约束：本决策改动了 `docs/development/DEVELOPMENT.md` 中已定义的 Feature 五字段契约，**`DEVELOPMENT.md` 需要同步更新为六字段契约说明**（本次会话未拿到该文件内容，无法直接编辑，需要用户在合并本次改动时一并更新该文档的字段说明）；新增 Feature 时必须同时声明 `depends_on`，不得留空绕过（无依赖显式写 `[]`，不得省略该字段）。
