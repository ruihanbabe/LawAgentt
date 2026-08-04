# LawAgent 项目记忆

> 这是跨会话的项目事实源。每次开发结束前更新“当前状态、决策、待办和风险”，不保存密钥、个人敏感信息或冗长逐字聊天记录。
> 最后更新：2026-08-04（Asia/Shanghai）

## 长期目标

构建一个可迁移、可评估、可审计的法律检索问答 Agent，并将架构选择、RAG、记忆、容错和评估设计沉淀为可用于大厂 Agent 岗位面试的真实工程经验。

## 产品边界

- 面向法律文献检索与基于证据的问答，不替代律师意见或司法裁判。
- 核心知识源为法律法规与裁判案例，回答必须给出可追溯引用。
- 证据不足、来源冲突或法条时效不明时必须明确提示不确定性。
- 项目采用“安全拒答优先”：宁可不输出具体法律结论，也不能用未经验证或不适用的证据补全答案；拒答时应提供澄清问题、材料清单、一般性程序信息或律师转介等建设性下一步。
- 核心必须是多跳 Agentic Retrieval，而不是检索一次即生成的单跳 RAG。
- 采用 Orchestrator 主控的受控多 Agent 架构，并设计多 Agent 结构化通信；Agent 数量与检索跳数是两个独立维度，多 Agent 通信用于角色隔离、上下文隔离、权限隔离和可审计协作，不采用自由聊天式多 Agent。
- 目标用户是法律知识有限、需要理解自身问题并完成基础材料准备的普通用户。
- 产品面向普通人的高频日常法律场景，不预先承诺全法域覆盖；正式业务场景包含劳动纠纷、租房纠纷、保险理赔、消费维权等，底层按全场景通用能力建设，高频场景通过 Skill/场景包做产品化增强。
- MVP 提供法条原文、相似案例检索、办事/诉讼材料结构指导和确定性金额计算。
- 系统提供信息与材料辅助，不承诺胜诉、不代替律师作最终法律判断，并预留人工律师转介通道。

## 求职与成本约束

- 求职目标以 100 人以下的小型公司为主，项目应体现端到端交付、成本意识和工程可靠性。
- 这是个人求职 Demo，经费有限；优先单机、开源组件、本地 embedding/rerank 和按需调用生成模型。
- 不为了展示概念引入 Kubernetes、复杂微服务或知识图谱；低成本约束不能削弱多跳 Agentic 设计。
- 项目的核心面试亮点是 Agentic Retrieval 与 Harness Engineering，而不是基础设施规模。

## 已确认的技术方向

- 主流程：外部状态机控制确定性步骤，模型只负责查询理解、改写和受约束生成。
- Agent：MVP 采用自研轻量 Agent Runtime / State / Node / Router，承载可观测的多跳工作流；宏观规划法律子问题，每一跳根据已获得证据和证据缺口选择下一查询或停止。LangGraph 仅保留为后续对照实验或可替换参考，不作为当前实现依赖。
- 检索：法律领域结构化切分；Dense + Sparse/BM25 + metadata filter 多路召回；合并去重后统一 rerank。
- 模型：本地 BGE-M3 embedding；reranker 型号需在基准测试后最终确认。
- 存储：Qdrant 作为向量及 payload 存储；原始数据与索引数据分离。
- API：FastAPI + Pydantic v2；配置仅来自环境变量和配置文件。
- 评估：从入库前即维护小型 gold set，覆盖 Recall@K、MRR/NDCG、引用准确率、忠实度、拒答质量、延迟和成本。

## 数据记忆

- `data/cases`：现有 1,146 个评测 JSON。全量契约化处理确认 92,656 个唯一候选 `CaseId`，其中 133 个与 query case 重叠并从语料库全局排除，最终案例语料为 92,523 条；另保存 1,146 个 template query、1,146 个 case query 和 13,096 条 qrels。query case、检索语料和 qrels 已物理分离，避免评测答案泄漏。
- 案例粗筛得到约 10,305 个租赁相关唯一案例，其中房屋租赁合同纠纷 1,335 个；粗筛同时包含车辆、土地、融资和设备租赁，必须依靠案由过滤与 rerank 区分。
- `data/laws`：共有 1,611 个 Markdown，其中排除 `案例` 目录后为 1,554 个；按“第×条”标题保守识别 65,988 条，继续拆款/项后索引记录可能接近或超过十万。需重点处理类型、版本、效力状态和重复。
- `models`：约 7.9 GB，包含 BGE-M3 与 BGE reranker；模型文件不进入 Git。
- 数据规模已经足够支撑垂直场景 Demo 和较广的检索实验；具体场景尚待全库画像选择，当前瓶颈是质量与评估，不是继续扩充数量。

## 用户开发偏好

- 使用简体中文协作。
- 先给结论，再解释关键原因。
- 在交互中始终明确当前开发目标、完成进度、风险和下一步。
- 重视服务器之间的可迁移性、模块化、数据特性扩展能力和面试可讲述性。
- 持续维护依赖、Git 同步、开发笔记、数据集信息和阶段进度。
- 重要目标、架构决策和阶段结果写入本文件，便于每日复盘。
- 用户希望在真实开发过程中逐步学习 Codex：在关键节点主动提示如何更好地描述任务、限定范围、授权操作、设置验收标准和组织子任务，并提供可复用提示模板。
- Codex 教学应服务当前开发，不应每轮重复、制造额外负担或要求用户先掌握提示工程。
- 功能开发采用设计确认门控：先聊天讨论模块和最小原型，用户确认设计后再开发；原型通过验收后再逐步增加功能。

## 本任务窗口目标

1. 在每个开发切片中明确目标、当前进度和验证结果，并随事实变化修正本文件。
2. 通过交流逐步确认根目录需要长期保存的开发语言、框架、基础架构和协作约束。
3. 将数据修正、清洗、整理、打包、校验和恢复步骤持续追加到 `DEVELOPMENT.md`。
4. 建立后续任务恢复机制，使新窗口先读 `AGENTS.md`，再加载本文件、开发说明和依赖台账。
5. 架构选型讨论沉淀到 `docs/architecture-selection.md`；新增内容与既有已确认表述冲突时，先提示用户人工二次确认是合并还是选其一。

## 决策状态约定

- **已确认**：由用户明确确认，或已被代码/环境验证，可作为实现约束。
- **暂定**：当前推荐方案，可以用于小型实验，但不能未经评估固化。
- **待验证**：来源于旧文档、历史描述或现有原型，不视为事实。

当前已确认：

- 开发语言为 Python 3.11，使用 Conda `agent` 环境。
- API 技术基线为 FastAPI + Pydantic v2。
- 工作流基线为自研轻量 Agent Runtime；数据库过滤由代码根据结构化槽位生成。LangGraph 仅作为后续对照实验或可替换参考。
- 检索结果必须经过 rerank，最终答案必须可追溯引用。
- 多跳 Agentic Retrieval 是已确认的核心目标：查询改写/问题分解、检索、重排、证据充分性判断、针对缺口补检索、生成与引用校验。
- RAG 是后续服务的事实基础；文书指导、金额解释和法律建议均须通过证据门控，不允许模型仅凭参数知识生成具体法律依据。
- 数据入库前先明确记忆分层、工具契约、路由策略和证据充分性标准，因为这些约束决定数据 schema 与索引 metadata。
- MVP 面向普通用户，覆盖法条/案例检索、基础文书写作指导、金额计算和律师转介入口。
- 正式业务场景包含劳动纠纷、租房纠纷、保险理赔、消费维权等；系统按共享 RAG/Runtime/证据门控底座做全场景业务开发，不把通用 schema 写死为任何单一场景。高频场景通过 Skill/场景包封装争点分类、关键事实槽位、检索策略、文书模板和拒答条件。
- MVP 采用受控多 Agent + 多 Agent 结构化通信：`IntakeAgent`、`RetrievalAgent`、`AnalysisAgent`、`DraftingAgent`、`ReviewAgent` 等角色通过 schema 化消息和共享状态协作，Orchestrator 统一控制流程与仲裁。
- 架构必须控制个人 Demo 成本，并适合小团队理解、维护和部署。
- 项目按“需求澄清 → 模块设计 → 用户确认 → 最小原型实现 → 验收 → 增量扩展”推进，未确认设计不得直接实现业务模块。
- 法规检索以 `effective_from` 为核心时间字段，不把通过、公布、修订日期放入首版 Qdrant 检索 payload；原始文件头仍随源文件保留。仅靠生效起点无法排除已被替代版本，因此历史适用所需的结束边界采用派生 `effective_to` 还是版本关系实时计算仍待最终确认。
- 数据源标注“现行法律”只记为来源方声明 `source_claimed_status=current`，不能自动升级为已核验效力状态；未通过权威来源核验的记录使用 `validity_status=unverified`，不得单独支撑具体法律结论。
- 同名法律文件按具体版本逻辑分离：同一法律可用 `law_family_id` 关联，每个文件/有效文本拥有独立 `law_version_id`，chunk ID 必须包含版本；不能只用“法律名 + 条号”。
- 法律、行政法规、司法解释、部门规章和修正案统一进入规范性法律文献 collection，以类型和层级过滤；攻略、普法/案例文章等非规范性资料不混入该 collection。
- 条文以完整法律条文为基本引用单元；“第×条之一/之二”在法律文本中属于独立新增条文，不是“第×条”正文内的分点，但不为此维护 `article_number/article_suffix/article_group_key` 三个持久字段。首版只保存规范化字符串 `article_no`（如 `120-1`）且原文保留完整条号。案例出现精确引用时先按 `article_no` 定位，证据不足才由查询时逻辑补查基础条或相邻扩展条。

当前暂定：

- Qdrant 为向量及 payload 存储。
- BGE-M3 为 embedding 模型。
- 最大跳数、补检索次数和预算阈值需要通过效果/成本实验确定，不能把固定两轮写成产品能力上限。
- 记忆只保存任务事实、用户确认和文书草稿版本，不默认保存敏感原始对话。

当前待验证：

- 法规“十万条”的业务统计口径是否按条、款/项还是最终 chunk 计算。
- 案例库对劳动纠纷、租房纠纷、保险理赔、消费维权等正式业务场景的数据量、字段完整性、标签纯度、时间覆盖和评测可用性。
- 最终生成模型是否为 DeepSeek、Qwen 或其他模型。
- reranker 的准确型号，以及 CRAG、Step-back 是否带来可量化收益。

## 当前阶段

阶段 1：RAG 数据与检索基线。

已完成：

- 盘点工作区、数据规模、模型目录、解释器和现有代码。
- 切换并确认 `agent` Conda 环境：Python 3.11.15。
- 建立依赖台账、项目记忆和开发说明。
- 新增根目录 `AGENTS.md`，使后续任务自动恢复记忆与协作规则。
- 对法规和案例完成首轮少量只读抽样，确认现有数据不能未经分类直接全量入库。
- 识别明文密钥、硬编码绝对路径、强制 CUDA、集合命名不一致等风险。
- 移除代码中的两处明文 Qwen API Key，改为环境变量读取。
- 已在 `agent` 环境安装并验证 `cn2an==0.5.24`，用于复合中文条号解析。
- 已安装并启动 Docker Engine `29.7.1`，官方 `hello-world` 验证通过。当前环境无 systemd bus且系统 Docker 默认目录只读，daemon 使用 `.runtime/docker-data` 和 `/tmp/lawagent-docker.sock`；客户端需设置对应 `DOCKER_HOST`。
- 已通过 Docker 启动 Qdrant `1.18.2`，建立 `laws_collection` 并完成法规 v0.1 全量 GPU 入库：1,534 个唯一规范性文档、66,448 个 dense+sparse chunks，精确点数与关键回溯验收通过。
- 已建立案例 `cases-v0.1` 契约及三轨评测数据，使用 RTX 3090 将 92,523 个去重候选案例以 BGE-M3 dense+sparse 向量完整写入 `cases_collection`；集合 green，点数、双向量、payload 索引、断点完成状态和脱敏样本已在线核验。
- 已实现案例三轨统一评测框架，并完成 Case-to-Case 全量 1,146 条 baseline。Hybrid 最优：HitRate@10=0.5166、Recall@10=0.2307、MRR@10=0.4319、NDCG@10=0.3061，P50/P95=55.0/134.0ms；Dense 与 Sparse 单路指标接近。Template-to-Case 尚未全量运行；User-to-Case 通过人工 `user_queries.jsonl` 的 `source_query_id` 继承 gold cases，正式人工集缺失时必须跳过。
- 新增 `lawagent_runtime` 自研 Runtime 包的 `RunState v0` Pydantic 模型，覆盖运行元信息、用户输入、事实、法律子问题、工具意图、检索尝试、证据、证据缺口、预算、终止原因和 trace；长期记忆和内容管理暂不接入。
- 已实现 `Multi-Agent Communication v0`：`AgentMessage`、`StatePatch`、`Observation`、`AgentRole`、`MessageType`、补丁权限表和 `apply_authorized_patch`；Orchestrator 控制流程字段，业务 Agent 只能按角色权限追加结构化状态，Review 可追加缺口/失败但不能直接确认事实。
- 已实现 `Node/Router/AgentRuntime v0`：`NodeConfig`、`AgentNode` 协议、`NodeRegistry`、`DefaultRouter`、`RouteDecision`、`AgentRuntime` 和 `RuntimeResult`；可运行 intake → plan → retrieve → answer 的 stub 流程，并覆盖澄清、越权补丁和缺失节点失败路径。

进行中：

- 前期开发范围收敛到 RAG：数据理解、数据契约、领域切分、版本化入库、召回/rerank 和检索评估。
- Agent 循环开始进入自研 Runtime 最小原型设计与实现；长期记忆、内容管理、文书生成和律师转介仅保留接口关联点，暂不实现。
- 法规数据切片已完成契约、解析、profile、manifest、测试、GPU embedding、Qdrant 入库和在线验收；原始数据未修改。
- 案例数据切片已完成契约、去重/排除、脱敏、评测拆分、manifest、测试、GPU embedding、Qdrant 入库和首轮在线 schema 抽检；原始数据未修改。

下一步：

1. 继续设计并实现 `ToolSpec / ToolResult v0`，为 `search_statutes`、`search_cases`、`fetch_source` 和后续 `calculate_claim` 接入 Runtime 做准备。
2. Qdrant 已在 daemon/socket 消失后恢复并验证 `cases_collection` 仍为 92,523 点；继续补核 `laws_collection` 的 66,448 点并记录双 collection 持久化结果。
3. 建立法规检索 baseline，验证 dense/sparse 融合、精确条号过滤和版本/时效门控。
4. 对 465 个缺少 `effective_from` 的文档设计权威来源核验优先级。
5. Case-to-Case dense/sparse/hybrid 全量 baseline 已完成；下一步先做 bad-case 分层，再运行 Template-to-Case，并在同一 Hybrid Top-50 cache 上加入 rerank。案例完整性/隐私全量报告仍待完成；User-to-Case 等待人工口语化 query 集。

## 关键风险与未决策

- 已暴露的 API Key 应在提供商后台立即撤销并重建；仅从文件删除不能使旧密钥失效。
- RTX 3090 在宿主终端可用并已完成本次 GPU 入库；Codex 默认沙箱因设备节点隔离看不到 GPU，需在沙箱外授权执行或由宿主终端运行。代码继续支持 `auto/cpu/cuda`，强制 CUDA 不可用时必须失败。
- 当前受限终端执行 `conda run -n agent` 会因环境目录只读失败，应直接使用环境解释器或另行配置可写临时目录。
- 多处路径写死为 `/root/agent`，与当前 `/root/lawagent` 不符。
- Qdrant collection 名存在 `law_collection`、`laws_collection`、`laws_collections` 等多种写法。
- 法规 v0.1 schema 与入库已实现；465 个日期缺失文档的权威核验、`effective_to` 派生和修正案到整合文本的版本关系仍待后续完善。
- 是否使用 Docker Compose、是否在本机部署 Qdrant、目标 GitHub 仓库均待确认。

## 记忆维护协议

- 长期稳定事实放在“长期目标、产品边界、偏好、技术方向”。
- 当日状态放在“当前阶段”；完成后压缩成阶段结论，不堆积流水账。
- 每项重要架构变更记录“决定、原因、替代方案、日期”，并同步开发说明。
- 更新任何主题前先审查全文中的同类表述；新确认的信息应替换冲突旧结论，而不是并列追加造成多个版本。
- 数据修正和打包的可复现细节只写入 `DEVELOPMENT.md`，本文件仅保留阶段结果和影响。
- 若实际代码或数据与本文件冲突，以验证后的代码/数据为准并立即修正文档。
