# LawAgent 开发说明

> 项目进度、架构、数据、环境和协作流程的操作手册。
> 最后更新：2026-08-04（Asia/Shanghai）

## 1. 当前基线

| 项目 | 当前状态 |
|---|---|
| 工作区 | `/root/lawagent` |
| Git | 已初始化，当前分支 `main`，远端跟踪 `origin/main` |
| Python | 3.11.15，Conda 环境 `agent` |
| 计算资源 | 8 CPU / 43 GB RAM；宿主环境 RTX 3090 24GB 可用，Codex 默认沙箱不映射 GPU 设备 |
| 数据 | `data/` 约 658 MB |
| 本地模型 | `models/` 约 7.9 GB |
| Agent 原型 | MVP 基线为自研轻量 Agent Runtime；旧 LangGraph + FastAPI 文件仍存在作历史原型，LangGraph/LangChain 不作为当前依赖 |
| 安全 | 明文 Key 已从两处代码移除；旧 Key 必须轮换 |
| Docker | Engine/CLI `29.7.1`、Compose `v5.4.0`；项目专用 daemon 已启动并通过 `hello-world` 验证 |

## 2. 基础架构决策

架构选型讨论记录在 `docs/architecture-selection.md`。2026-08-04 用户确认：
MVP 不使用 LangGraph，改为自研轻量 Agent Runtime / State / Node / Router；
LangGraph 仅保留为后续对照实验或可替换参考，不作为当前实现依赖。

采用“自研多跳 Agentic Runtime + Harness 确定性约束”。Agent 必须根据每一跳获得的证据动态规划下一跳；Harness 负责过滤、预算、权限、校验和停止条件。法律问答中查询改写、问题拆解、证据缺口分析和答案组织需要模型能力，而数据库过滤、检索执行、金额计算和安全边界需要确定性代码。

```text
API / CLI
  -> 输入校验与会话加载
  -> 查询理解（意图、法域、时间、案由、法律实体）
  -> 结构化检索计划
  -> 多路召回（Dense + Sparse/BM25 + Payload Filter）
  -> 融合去重 -> Rerank
  -> 证据充分性与时效校验
  -> 基于证据生成 -> 引用一致性校验
  -> 答案 / 澄清问题 / 安全拒答
```

核心规则：

- LLM 不直接拼接数据库 filter；由 Pydantic schema 校验后的代码生成。
- 原始文档、规范化文档、chunk、embedding/index 分层，任何一层可重建。
- 所有数据对象具有稳定 ID、schema 版本、来源、内容哈希和处理版本。
- 检索结果必须经过 rerank；生成答案必须引用证据 ID。
- 每个节点记录输入摘要、输出、耗时、错误类型、重试次数和模型/Prompt 版本。
- 入库与查询均通过接口/协议解耦具体 embedding、reranker 和向量库实现。
- 法律结论默认关闭，只有证据门控通过后才开放；门控不通过时进入澄清、有限回答或建设性拒答分支。

### 法律安全与证据门控

生成具体法律结论前，证据集合至少通过以下检查：

| 维度 | 检查内容 | 不通过时动作 |
|---|---|---|
| 事实完整性 | 影响争点的关键事实是否由用户确认 | 询问最少量澄清问题 |
| 法域 | 国家/地区及管辖相关信息是否明确 | 仅给一般信息或请求补充 |
| 时效性 | 法规版本、施行/失效时间是否覆盖事件时间 | 补检索历史版本；仍不明则拒绝具体结论 |
| 权威性 | 是否来自可验证法规或裁判来源 | 排除低可信来源 |
| 覆盖度 | 每个关键法律子问题是否有证据支持 | 针对缺口进行下一跳检索 |
| 一致性 | 法条、案例和用户事实是否冲突 | 展示冲突并降低结论强度 |
| 可引用性 | 答案中的主张能否绑定精确证据 ID | 删除无引用主张或拒答 |

输出等级：

1. `supported_answer`：门控通过，可给出带引用的条件化分析。
2. `limited_answer`：只回答有充分证据覆盖的部分，明确未覆盖范围。
3. `clarification_needed`：关键事实缺失，提出少量高信息量问题。
4. `constructive_abstention`：不能可靠作答，提供材料清单、检索缺口、一般程序建议和律师转介。

禁止使用“保证胜诉”“一定可以追回”等确定性承诺。系统输出是法律信息和材料辅助，不替代执业律师意见。

### 记忆分层设计

| 层级 | 保存内容 | 生命周期 | 安全规则 |
|---|---|---|---|
| 工作记忆 | 当前几轮原始消息、当前节点和工具结果引用 | 单次请求/短窗口 | 超预算裁剪，不直接长期保存 |
| 案件状态 | 结构化事实、用户目标、缺失材料、已确认/争议事实、草稿版本 | 当前案件会话 | 每个字段保留来源、确认状态和更新时间 |
| 证据记忆 | 本次任务命中的证据 ID、版本、分数、支持/反对关系 | 当前运行或案件 | 只引用知识库，不复制为公共知识 |
| 用户偏好 | 语言、解释深度、通知和保存偏好 | 跨会话可选 | 明示同意、最小化保存、可删除 |
| 公共知识库 | 经处理的法规、案例及版本关系 | 持久 | 只由受控入库管线更新，禁止对话写回 |

案件事实字段必须区分：

- `user_stated`：用户原始陈述，尚未核验。
- `system_extracted`：模型从陈述抽取的候选事实。
- `user_confirmed`：用户明确确认。
- `document_supported`：由用户材料或可靠来源支持。
- `disputed`：存在相互冲突的陈述。

检索 filter 和具体结论不能把 `system_extracted` 自动升级为已确认事实。

### 工具与路由设计

第一阶段工具保持少而清晰：

| 工具 | 职责 | 风险级别 |
|---|---|---|
| `search_statutes` | 按法域、时间、效力、法律层级和条款检索法规 | 只读 |
| `search_cases` | 按案由、法院、时间、程序和关键事实检索类案 | 只读 |
| `fetch_source` | 按证据 ID 获取可引用父级原文与版本信息 | 只读 |
| `calculate_claim` | 按显式公式计算金额、利息或期限 | 确定性计算 |
| `build_document_outline` | 根据已确认事实和证据生成文书结构/缺失字段 | 生成，不对外提交 |
| `prepare_lawyer_handoff` | 生成案件摘要与材料清单 | 涉及敏感数据，需用户确认 |

路由不是让 LLM 直接输出任意工具调用。Planner 只能输出结构化意图：

```text
ToolIntent
  - objective
  - legal_issue
  - source_type
  - query_terms
  - jurisdiction
  - event_date
  - filters_as_slots
  - evidence_gap
```

Policy Router 负责：

1. 用 Pydantic 校验字段和枚举。
2. 根据当前图节点检查工具白名单。
3. 把槽位转换为确定性的 Qdrant filter。
4. 应用超时、重试、并发、跳数和预算。
5. 对空结果、低分结果、版本冲突和工具异常返回结构化错误。
6. 对保存、导出或律师转交等操作要求显式确认。

### 架构与入库的先后顺序

入库前必须冻结 v0 契约，但不需要先完成全部运行时功能：

1. 确认产品输出等级和证据门控字段。
2. 确认案件状态、工具意图和检索结果 schema。
3. 由检索 schema 反推法规/案例 metadata。
4. 对现有数据做只读 profile，判断字段能否满足契约。
5. 再实现 normalize、领域切分、父子索引和版本化入库。
6. 建立单跳检索 baseline，验证数据和索引质量。
7. 在可靠 baseline 上实现多跳 Agentic 循环与 Harness。

这里的“单跳 baseline”只是用于隔离评估入库与检索质量，不是最终产品架构；最终演示必须运行多跳 Agentic Retrieval。

### 面向低成本 Demo 的 MVP 工作流

产品倾向定位为高频日常法律场景助手，但具体场景尚未确定。租赁押金争议仅作为便于讨论和抽样的候选，不代表首发范围；共享领域模型不得写死为租赁或其他单一场景：

```text
用户叙述
  -> 安全与隐私提示
  -> 事实槽位抽取
  -> 缺失关键事实？-> 生成澄清问题
  -> 争点与检索计划
  -> 法条召回 + 类案召回
  -> 融合去重 + rerank
  -> 证据充分性判定
       ├─ 不足且预算允许：query 改写后补检索
       ├─ 仍不足：明确缺口并建议人工咨询
       └─ 充分：生成分层解释与可追溯引用
  -> 可选任务
       ├─ 金额计算器
       ├─ 起诉材料/文书结构指导
       └─ 律师转介摘要
```

模型负责：

- 从自然语言提取候选事实槽位和待确认项。
- 识别争点、生成受约束的检索 query、解释证据和组织文书草稿。
- 在证据集合内判断“还缺哪类材料”，但不能自行判定数据库过滤语法。

确定性代码负责：

- Pydantic schema 校验、状态流转、循环次数、token/时间预算和超时。
- 数据库 filter、融合去重、rerank 门槛、引用 ID 和法条时效检查。
- 金额、利息、期限等计算；模型只解释公式和所需输入。
- 敏感操作授权、日志脱敏、错误分类、重试和降级。

### 多跳 Agentic Retrieval 核心闭环

这是求职项目的核心能力，不是普通 RAG 外加重试。系统至少实现以下可观测状态：

1. `understand`：抽取案情事实、用户目标、法域/时间和缺失信息。
2. `plan`：把法律任务分解为存在依赖关系的结构化子问题，例如先确认法律关系和争点，再寻找规范依据，最后按关键事实检索可比案例。
3. `retrieve`：执行多路召回。
4. `rerank`：统一重排并去除近重复证据。
5. `grade_evidence`：按子问题覆盖度、来源权威性、时效性和相互一致性评分，并输出尚未解决的证据缺口。
6. `refine_query`：基于上一跳证据产生的新实体、法条引用、争点或缺口，生成下一跳查询；不是简单换一种措辞重试。
7. `answer`：基于证据生成回答并校验引用。

多跳的成立标准：

- 后一跳输入显式依赖前一跳 observation，而不是预先并行执行若干固定 query。
- 状态中保留子问题、已覆盖争点、证据 ID、证据缺口、失败原因和剩余预算。
- Agent 可选择继续某一争点、回退改写、切换法条/案例检索工具或停止。
- 终止同时受证据充分性和 Harness 预算约束；达到预算后必须披露未解决问题。

开发阶段默认设置可配置的最大跳数，防止死循环；具体默认值通过检索效果、延迟和成本基准确定，不预先把两轮写成固定产品上限。

### Harness Engineering 最小安全带

| 能力 | MVP 实现 |
|---|---|
| 上下文预算 | 固定 token 上限；证据按 rerank、来源和覆盖度选择；重复内容压缩 |
| 状态与记忆 | 当前任务状态持久化；事实分“用户原话、系统抽取、用户确认”三种可信等级 |
| 工具路由 | Pydantic 入参；白名单工具；超时、重试、熔断和结构化错误 |
| 权限分级 | 检索/计算默认允许；保存敏感资料、生成可下载文件、转交律师需显式确认 |
| 可观测性 | 每节点记录耗时、状态、检索 query、文档 ID、分数、错误和预算，不记录完整敏感正文 |
| 输出校验 | 引用存在性、法条时效、金额计算来源、证据不足提示和禁止承诺性表达 |
| 人工接入 | 输出结构化案件摘要、已确认事实、缺失材料、检索证据和用户问题；转交前确认 |

### 第一阶段明确不做

- 不采用自由聊天式多 Agent，不让多个 Agent 绕过 Orchestrator 自行推进全局状态；多 Agent 采用受控节点与结构化通信。
- 自动替用户提交诉讼材料或对外发送消息。
- 自动生成数据库 filter 或执行任意代码。
- 自建知识图谱、模型训练、Kubernetes 和复杂微服务。
- 将全部原始对话长期写入向量记忆。

## 3. 推荐目录

```text
lawagent/
├── src/lawagent/
│   ├── api/             # HTTP/SSE 接口与 DTO
│   ├── agent/           # 图、状态、节点和路由
│   ├── application/     # 用例编排
│   ├── domain/          # 法律文档、Chunk、Citation 等领域模型
│   ├── ingestion/       # reader -> normalize -> chunk -> index
│   ├── retrieval/       # query、召回、融合、重排
│   ├── generation/      # 证据上下文与答案生成
│   ├── evaluation/      # 离线/回归评估
│   ├── infrastructure/  # Qdrant、模型、LLM、持久化适配器
│   └── config/          # Settings 与日志配置
├── tests/
│   ├── unit/
│   ├── integration/
│   └── evaluation/
├── scripts/             # 薄 CLI，不承载核心业务逻辑
├── data/                # 默认不入 Git
├── models/              # 默认不入 Git
├── requirement.txt      # 实际环境与依赖台账
├── requirements.txt     # 顶层可安装依赖
├── MEMORY.md            # 跨会话项目记忆
└── DEVELOPMENT.md       # 本文件
```

现有代码暂不批量移动；先补测试和契约，再渐进迁移，避免在未知可运行状态下重构。

## 4. 入库数据契约

### 法规文档版本（LawDocumentVersion v0.1，已实现）

| 字段 | 含义 |
|---|---|
| `law_family_id` | 同一部法律跨版本的关联 ID；权威来源稳定 ID 优先，缺失时由法域 + 文档类型 + 规范化标题生成 |
| `law_version_id` | 每个同名文件/有效文本独立 ID，由 `law_family_id` + 版本标识/原文哈希生成，版本间绝不覆盖 |
| `title` / `normalized_title` | 原标题与用于归并版本的规范化标题 |
| `document_type` | `law`、`administrative_regulation`、`judicial_interpretation`、`department_rule`、`amendment`、`other_normative`、`non_normative` |
| `authority` / `jurisdiction` | 制定机关与适用法域；未知必须显式为空，不推测 |
| `effective_from` | 首版唯一直接入 Qdrant 的法规日期，ISO 8601；无法可靠提取时为 `null`，不得用通过/公布/修订日代替 |
| `effective_to` | 建议保留的派生适用结束边界；不是用户要求的核心源字段，是否入 payload 待确认 |
| `validity_status` | `pending`、`effective`、`amended`、`repealed`、`unverified` |
| `status_verified_at` | 效力状态最近核验时间；未核验为 `null` |
| `source_claimed_status` | 数据源自身声明，如 `current`；仅作线索，不等同于核验结论 |
| `source_name` / `source_url` / `source_path` | 数据提供方、权威来源 URL、本地相对路径 |
| `source_authority_level` | `official`、`secondary`、`unknown` |
| `amends_version_ids` / `supersedes_version_id` | 修正案、修订版本间关系；用于在不保存多类日期时计算历史适用范围 |
| `content_hash` / `schema_version` / `pipeline_version` | 内容幂等、契约版本和处理管线版本 |

通过、公布和修订日期不进入首版 Qdrant payload，原始文件头仍保存在原始数据中。
需要注意：`effective_from <= event_date` 只能证明“已经开始施行”，不能证明该版本在
事件发生时仍有效。首版必须在“派生 `effective_to`”与“通过
`supersedes_version_id` 实时排除旧版本”之间选择一种，否则旧版本可能被误用。

### 法规条文 Chunk（LawChunk v0.1，已实现）

| 字段 | 含义 |
|---|---|
| `chunk_id` | `law_version_id` + 规范化结构定位 + chunk 内容哈希生成 |
| `law_family_id` / `law_version_id` | 关联法律家族及其逻辑分离的具体版本 |
| `chunk_type` | `article`、`amendment_item`、`section` |
| `article_no` | 唯一条号字段，使用规范化字符串，如 `120`、`120-1`、`120-2`；原始中文完整条号保留在 `content`，不再持久化主号、后缀和分组键三个冗余字段 |
| `ordinal` / `structure_path` | 文档内稳定顺序与可解析的编/章/节路径 |
| `content` | 保留条号的原始可引用文本 |
| `embedding_text` | 标题 + 版本 + 层级路径 + 原文组成的检索文本，不作为权威引用原文 |
| `content_hash` / `schema_version` / `pipeline_version` | 幂等、契约和管线版本 |

款/项独立子 chunk、父子索引和交叉引用结构化解析未进入 v0.1；先以完整条文保证
法律条件、例外和但书不被切断，后续只在检索评测证明有必要时增加。

Qdrant point ID 使用 `chunk_id`；payload 保存 `chunk_id`、`law_family_id`、
`law_version_id`、`title`、`document_type`、`authority`、`authority_level`、
`jurisdiction`、`effective_from`、`effective_to`、`validity_status`、`source_path`、
`source_authority_level`、`chunk_type`、`article_no`、`ordinal`、`structure_path`、
`content`、`content_hash`、`schema_version`、`pipeline_version`。`embedding_text` 仅用于
生成向量，不写入 payload。首批建立
`law_family_id`、`law_version_id`、`document_type`、`jurisdiction`、`authority`、
`authority_level`、`validity_status`、`effective_from`、`article_no`、`chunk_type`、
`source_path` 的 payload index；
日期使用 Qdrant `DATETIME`，
不再把中文日期作为 `KEYWORD`。原始完整文档、版本关系和处理报告保存在
processed/manifest 层，Qdrant 不是唯一事实源。

法规首版按“完整条文”生成必备检索点，不能跨条切分。“第×条之一/之二”是独立
新增条文而不是基础条正文内的分点，但只用一个 `article_no` 字符串精确定位，不为
少量特殊编号增加多个 payload 字段。案例明确引用 `120-1` 时先精确检索该条；只有
证据不足时，查询逻辑才临时推导并补查 `120` 或相邻扩展条，不把这种关系固化为
额外 schema。超长条文可额外生成款/项子 chunk，但返回与引用时必须带回完整条文。修正案使用独立 parser，按
“一、二、三……”修改事项生成 `amendment_item`，并尽可能解析被修改条号和
修改动作；同时保留修正后的有效整合文本作为主要问答证据。

法律、行政法规、司法解释、部门规章和修正案统一进入一个规范性法律文献
collection，通过 `document_type`、`authority` 和效力层级区分。攻略、普法文章、
案例文章等非规范性资料不进入该 collection，可暂存 quarantine，后续需要时另建
低权威资料库。

### 案例文档与检索点（cases-v0.1，已实现）

案例采用“可重建文档层 + Qdrant 检索点 + 独立评测层”三层结构：

- `CaseDocument` 保存完整规范化案例、当事人结构和来源路径，输出到
  `data/processed/cases_v0_1/documents.jsonl`，不直接作为 Qdrant point。
- `CaseRetrievalPoint` 的 `retrieval_text` 仅由案件类型、审理程序、案由、分类、
  案件经过、诉请与事实、关键词组成。裁判理由、裁判结果、法律依据及当事人不参与
  embedding，避免 Case-to-Case 评测泄漏答案信息。
- 当事人名称及常见身份证号、手机号、银行卡号在检索视图和 Qdrant payload 中脱敏；
  原始 `data/cases` 保持不变。
- Qdrant point ID 为稳定 UUID5；`case_version_id` 由 `CaseId + 内容哈希` 生成，
  支持内容版本逻辑分离和幂等 upsert。

Qdrant `cases_collection` 向量：`dense` 为 BGE-M3 1,024 维 Cosine float32，
`text_sparse` 为 BGE-M3 lexical weights。payload 字段为：
`point_id`、`case_id`、`case_version_id`、`title`、`case_type`、`procedure`、
`case_causes`、`category_l1`、`category_l2`、`keywords`、`jurisdiction`、
`source_count`、`case_record`、`claims_and_facts`、`judge_reason`、`judge_result`、
`legal_basis`、`content_hash`、`schema_version`、`pipeline_version`。
`retrieval_text` 只用于生成向量，不写入 payload；`parties` 和 `source_paths` 只留在
文档层。payload index 建在 `case_id`、`case_version_id`、`case_type`、`procedure`、
`case_causes`、`category_l1`、`category_l2`、`keywords`、`jurisdiction`。

评测层独立保存：`template_queries.jsonl`、`case_queries.jsonl`、`qrels.jsonl`、
`query_case_references.jsonl`。`gt_idx` 仅转换为 `query_id -> case_id` qrels，绝不写入
Qdrant payload。所有 query case ID 从候选语料全局排除。

## 5. 数据入库开发顺序

1. Profile：统计字段缺失率、长度分布、枚举值、重复率、时间字段和脏数据。
2. Contract：用 Pydantic 定义原始、规范化文档、chunk 和索引记录。
3. Reader：不同数据源各自适配，只输出统一原始对象。
4. Normalize：字段映射、日期/案号/法条编号标准化、脱敏和内容哈希。
5. Chunk：按文档类型使用可插拔策略，保留父子关系和结构路径。
6. Index：批处理 embedding、幂等 upsert、断点续跑、失败清单。
7. Validate：数量守恒、随机抽检、重复率、Recall@K 和可回溯性检查。
8. Manifest：每次运行保存数据版本、配置、代码 commit、模型版本和指标。

### 数据修正、整理与打包记录规范

原始数据目录保持只读，采用以下目录层级：

```text
data/
├── raw/                 # 原始快照，不原地修改
├── interim/             # 解析、修正后的中间数据
├── processed/           # 可入库的规范化数据
├── evaluation/          # gold set 与回归集
└── manifests/           # 每次处理和打包的清单
```

每次数据任务必须记录：

| 项目 | 必填内容 |
|---|---|
| 任务 ID | 日期 + 数据类型 + 简短动作，如 `20260729_cases_profile_v1` |
| 输入 | 相对路径、数据版本、文件数、总大小、抽样/全量 |
| 处理 | 脚本路径、命令、参数、代码 commit、schema 版本 |
| 修正规则 | 字段映射、标准化、去重、脱敏、丢弃条件及理由 |
| 输出 | 相对路径、格式、文件数、记录数、总大小 |
| 异常 | 失败记录数、失败清单路径、是否可重试 |
| 验证 | 数量守恒、schema 校验、抽检、哈希、质量指标 |
| 打包 | 包名、压缩算法、分卷策略、SHA-256、解包命令 |
| 恢复 | 原始快照位置、回滚或重建步骤 |

标准步骤：

1. 对输入生成只读快照或至少生成文件清单与 SHA-256。
2. 运行 profile，明确 schema、数量、缺失率、重复率和异常分布。
3. 在版本化派生目录执行修正，禁止覆盖原始文件。
4. 输出逐条校验报告和失败清单，失败数据进入 quarantine。
5. 对结果重新统计并与输入做数量守恒解释。
6. 打包前移除缓存、索引临时文件和密钥，生成 manifest。
7. 使用可跨平台格式打包，保存包级 SHA-256，并实际试解包抽检。
8. 把完整记录追加到本节“数据处理日志”，阶段结论同步到 `MEMORY.md`。

### 数据处理日志

| 任务 ID | 状态 | 输入 → 输出 | 结果与验证 |
|---|---|---|---|
| `20260729_workspace_inventory_v0` | 完成 | 现有 `data/cases`、`data/laws` 只读盘点 | 案例 JSON 1,146 个；法规目录文件 1,618 个；尚未修正或打包 |
| `20260729_rag_sample_audit_v0` | 完成 | 3 个完整案例样本、30 个案例文件的候选集、法规多版本与租赁相关文件 | 每个案例样本含 100 个候选和 `gt_idx`；30 个文件共 3,000 个候选、2,975 个唯一 CaseId；法规目录混合多种文档并存在同法多版本 |
| `20260729_rag_full_count_v0` | 完成 | 全量案例 JSON 去重统计；法规 Markdown 条文标题计数 | 114,600 条候选引用、93,669 个唯一案例、13,096 个正例标注；租赁相关粗筛 10,305 个；非案例法规文件 1,554 个、条文标题 65,988 条 |
| `20260729_laws_metadata_cleanup_v1` | 完成 | `data/laws/.github` 与所有递归 `_index.md` → 删除 | 删除 1 个 GitHub Actions 工作流和 20 个 `_index.md`；复查剩余 `_index.md` 为 0；清理后 `data/laws` 共 1,597 个文件、约 28 MB |
| `20260731_laws_schema_review_v0` | 完成（设计/只读） | `scripts/ingest_laws.py` + 公司法双版本、刑法修正案、房屋租赁司法解释、非规范性攻略样本 | 确认旧脚本存在版本覆盖、日期误判、条号解析、文档误分类、CUDA/import 副作用和不可审计等问题；形成 LawDocumentVersion/LawChunk v0 设计，未修改脚本、未连接 Qdrant、未入库 |
| `20260804_docker_setup_v1` | 完成 | Docker 官方 Ubuntu Jammy APT 仓库 → 系统 Docker CE | 安装 Engine/CLI `29.7.1`、Compose `v5.4.0`、containerd `2.2.6`；因 systemd bus 不可用且 `/var/lib/docker`、`/var/run` 对任务只读，daemon 改用 `.runtime/docker-data` 与 `/tmp/lawagent-docker.sock`；官方 `hello-world` 成功 |
| `20260804_laws_ingestion_v0_1` | 完成 | `data/laws` → `data/processed/laws_v0_1` → Qdrant `laws_collection` | 1,591 个输入文件；纳入 1,534 个唯一规范性文档，排除 52 篇案例文章、2 个“其他”文档及 3 个完全重复来源；生成并用 RTX 3090 入库 66,448 chunks；精确点数、双向量、版本分离、条号回溯和排除规则均通过 |
| `20260804_cases_ingestion_v0_1` | 完成 | `data/cases` → processed/evaluation v0.1 → Qdrant `cases_collection` | 1,146 文件全部有效；92,656 个唯一候选，排除 133 个 query case 后入库 92,523 点；13,096 qrels 全部可回溯；RTX 3090 完成 2,892 批 dense+sparse 入库，collection green，脱敏与 schema 抽样通过 |
| `20260804_cases_three_track_eval_v0_1` | 已实现，smoke 通过 | Case-to-Case / Template-to-Case / User-to-Case 统一评测框架 | 前两轨各 2 条真实 GPU+Qdrant smoke 通过；输出 Dense、Sparse、RRF Hybrid 的 Recall/HitRate/MRR/NDCG 与延迟；User 轨因正式人工 query 集缺失按契约跳过 |

### `20260804_cases_ingestion_v0_1` 物理操作记录

- 入口：`scripts/ingest_cases_v2.py`；核心：`lawagent_ingestion/cases/pipeline.py`；
  契约：`lawagent_ingestion/cases/models.py`；schema/pipeline 版本分别为
  `cases-v0.1` / `cases-ingest-v0.1`。
- 输入：1,146 个 JSON，657,468,093 bytes；聚合 SHA-256
  `e5651592c445250bbaa2a4a27d78bb4840e8c891e523e933249c4287fc080c44`。
- 输出 `documents.jsonl` 与 `retrieval_points.jsonl` 均为 92,523 条，SHA-256 分别为
  `9846a81dc71e72a461ff51738e29ec9a9420c6ad3f7ceedaccb763e8e7e3965d`、
  `c403fc424bed2b70430631ad94069fcdda59c42836f3ffd79721d0bd1e8a028c`。
- 评测输出：1,146 template queries、1,146 case queries、1,146 query references、
  13,096 qrels；无非法 qrel、无缺失 corpus case、无 GT/query-case 重叠。
- 正式命令使用 `--mode index --device cuda --parse-workers 16 --upload-workers 2
  --embed-batch-size 32 --collection cases_collection`；结果为 2,892/2,892 批、
  submitted=completed=92,523、points_count=92,523。
- 在线验收：collection `green`、update queue 为 0；dense 维度 1,024，抽样 sparse
  非空；9 个 payload index 覆盖全部适用点。当事人脱敏样本通过。
- Qdrant 的 `indexed_vectors_count=182,603` 高于逻辑点数，属于待进一步解释的
  segment/优化统计；唯一业务点数以稳定 UUID 的 `points_count=92,523` 为准，后续
  持久化重启测试同时复核该指标，不将其误报为重复案例数。
- 恢复：原始数据未修改；保留
  `data/manifests/cases_v0_1/index_checkpoint.json` 可按相同 collection 和 batch size
  断点续跑。完整重建时从 versioned processed/evaluation/manifest 派生目录重建，
  不覆盖 `data/cases`。

### 案例三轨检索评测 v0.1

入口为 `scripts/evaluate_cases_v2.py`，核心实现为
`lawagent_evaluation/cases.py`，测试为 `tests/test_cases_evaluation.py`。三条轨道共享
同一 corpus，但分别报告，禁止混合平均：Case-to-Case 读取脱敏后的
`case_queries.jsonl`；Template-to-Case 读取原始模板式 `template_queries.jsonl`；
User-to-Case 读取人工维护的 `user_queries.jsonl`，用独立 `query_id` 和
`source_query_id` 继承原任务 qrels，允许同一案件配置多种口语化表达。正式 User
query 文件缺失时明确 skipped，不用模型自动生成内容冒充人工测试集。

每批 query 只生成一次 BGE-M3 dense+sparse 表示，分别召回后使用 RRF（`k=60`）
融合；三个分路统一计算 HitRate、Recall、MRR、NDCG@5/10 和 P50/P95 检索延迟。
每轨原始排名写入 cache，汇总写入 `retrieval_summary.json`，逐 query 结果写入
`retrieval_details.jsonl`。

真实接口 smoke 命令：

```bash
/root/miniconda3/envs/agent/bin/python scripts/evaluate_cases_v2.py \
  --device cuda --tracks case_to_case template_to_case user_to_case \
  --limit 2 --candidate-k 10 --ks 5 10 \
  --output-dir data/evaluation/cases_v0_1/runs/smoke_v0_1
```

smoke 仅证明 GPU embedding、Qdrant dense/sparse、RRF、qrels 和指标接口连通，不作
效果结论。其后已完成 Case-to-Case 全量 1,146 条、candidate-k=50 的正式 baseline：

| 分路 | HitRate@10 | Recall@10 | MRR@10 | NDCG@10 | P50/P95 ms |
|---|---:|---:|---:|---:|---:|
| Dense | 0.4974 | 0.2219 | 0.4217 | 0.2958 | 29.9 / 74.7 |
| Sparse | 0.4843 | 0.2225 | 0.4194 | 0.2964 | 25.6 / 60.7 |
| Hybrid RRF | **0.5166** | **0.2307** | **0.4319** | **0.3061** | 55.0 / 134.0 |

Hybrid 在主要效果指标上均领先，但延迟接近两路召回之和；下一步应基于逐 query cache
分析 Dense/Sparse 互补、Hybrid 退化和零命中样本，再决定融合参数与 reranker 候选池。
当前全仓库 27 项单元测试通过。

本次项目 Docker daemon/socket 消失后重新启动既有 Qdrant 容器，
`cases_collection` 恢复后仍为 green、92,523 points，案例 collection 的持久化关键
检查通过。完整性/脱敏全量验证器已实现为 `scripts/validate_cases_v2.py`，但最终全量
报告尚未完成，不能把未完成扫描记录成通过。

`20260729_laws_metadata_cleanup_v1` 恢复说明：本次按用户明确指令直接删除，工作区没有可用于恢复这些文件的项目级 Git 历史；如需恢复，应从原始数据源重新下载或复制。删除内容均为站点/仓库维护文件，不是法规正文。

### `20260804_laws_ingestion_v0_1` 物理操作记录

基础设施：

1. 从 Docker 官方 Ubuntu Jammy APT 仓库安装 Docker CE；安装版本见环境台账。
2. 新增 `compose.yaml`，固定 `qdrant/qdrant:v1.18.2`，REST/gRPC 只绑定
   `127.0.0.1:6333/6334`，持久化目录为 `.runtime/qdrant-storage`。
3. 当前受控环境无 systemd bus且默认 Docker 目录只读，项目 daemon 使用：

   ```bash
   dockerd --host=unix:///tmp/lawagent-docker.sock \
     --data-root=/root/lawagent/.runtime/docker-data \
     --exec-root=/root/lawagent/.runtime/docker-exec \
     --pidfile=/tmp/lawagent-dockerd.pid
   export DOCKER_HOST=unix:///tmp/lawagent-docker.sock
   docker compose -f compose.yaml up -d --pull always qdrant
   ```

4. Qdrant 健康检查返回 `1.18.2`、container healthy、初始集合为空。

数据处理与代码：

1. 新增 `lawagent_ingestion/laws/`：Pydantic 契约、普通条文/修正案/section
   parser、BGE-M3 adapter、profile/manifest、Qdrant collection 与并行上传逻辑。
2. 新增 `scripts/ingest_laws_v2.py`；旧 `scripts/ingest_laws.py` 保留作历史对照，
   不再用于正式入库。
3. 新增 `tests/test_laws_ingestion.py`，8 个标准库单元测试全部通过。
4. 首轮 dry-run 发现 3 个重复版本、161 个重复 chunk ID、9 个空文档；定位为
   跨目录完全重复文件和修正案分类/格式差异。修复后第二轮结果为重复 ID=0、
   纳入文档空 chunk=0。
5. 最终只读 profile 命令：

   ```bash
   /root/miniconda3/envs/agent/bin/python scripts/ingest_laws_v2.py \
     --mode profile --parse-workers 16
   ```

6. GPU 在 Codex 默认沙箱中因缺少 `/dev/nvidia*` 不可见，但宿主终端可见 RTX 3090。
   CPU 32 条基准约 11.8 秒，不用于全量。宿主终端正式命令：

   ```bash
   python scripts/ingest_laws_v2.py \
     --mode index --device cuda --parse-workers 16 \
     --upload-workers 2 --embed-batch-size 32 \
     --collection laws_collection
   ```

7. 并行方式：16 个读取/解析 worker；单个 BGE-M3 GPU 模型批量生成 dense+sparse，
   避免多进程重复占用显存；2 个有界上传 worker。checkpoint 每个确认写入的批次
   原子更新，稳定 UUID 支持幂等重跑。

输入、输出和哈希：

| 对象 | 数量/大小 | SHA-256 |
|---|---:|---|
| `data/laws/**/*.md` 聚合 | 1,591 文件 / 25,513,017 bytes | `3c8e54a1b1ef74cbc85ef99ed2718d2e77d5c871eb9e207a4cb0bfadb291711c` |
| `source_files.jsonl` | 1,591 条 | `a4f2b720b7e2dc49d241a2298d8db0f13c2ef7b9845d5e53fb85595ff8510142` |
| `documents.jsonl` | 1,534 条 | `feeb569e51762985ab12deb131d684ddc5c45dc2a9268572d5bedcf164e9ca3e` |
| `chunks.jsonl` | 66,448 条 | `c67756ce8a6a034322000b3d5ef724227c7c3c5942d13bc7b5c05ed7f285a7c4` |
| processed 目录 | 约 106 MB | 逐文件哈希见 manifest |
| Qdrant storage | 约 438 MB | 运行时目录，不提交 Git |

最终 profile：339 部法律、710 部行政法规、439 份司法解释、29 份部门规章、
17 份修正案；65,770 个 `article`、284 个 `amendment_item`、394 个 `section`。
1,069 个文档提取到明确 `effective_from`，465 个保持 `null`；全部
`validity_status=unverified`，在权威来源核验前不得单独支撑确定性法律结论。

Qdrant collection：

- 名称：`laws_collection`。
- dense：BGE-M3，1,024 维，Cosine，float32。
- sparse：BGE-M3 `lexical_weights` 转换为 `text_sparse`。
- 正式结果：2,077 批，submitted=completed=66,448，device=`cuda`，精确点数 66,448。
- 验收：集合 green；抽样点均有 dense+sparse；`article_no=120-1` 精确回溯；
  2018/2023《公司法》family ID 相同、version ID 不同，分别 218/266 chunks；
  `案例/`、`其他/` 点数均为 0。
- 容器重启持久化验证因授权被拒绝而未执行；在线持久化目录存在，不能把重启恢复
  记为已验证。后续执行 `docker compose restart qdrant` 后需再次核对 66,448 points。

恢复与重建：原始 `data/laws` 未修改。删除 `data/processed/laws_v0_1`、对应
manifest 和 Qdrant collection 后，可按 profile → index 命令完整重建；正常中断时保留
`data/manifests/laws_v0_1/index_checkpoint.json` 即可从已确认批次继续。

### 首轮样本审计结论

1. `data/cases/*.json` 顶层结构稳定为 `q_i`、`query`、`query_case`、`gt_idx`、`ctxs`。
2. 抽查样本的 `ctxs` 均为 100 个候选，`gt_idx` 提供多个相关候选位置，适合作为检索/rerank 评测数据；其生成来源和标注语义仍需确认。
3. 30 个 query 文件的 3,000 个候选中有 2,975 个唯一 `CaseId`，候选跨 query 有少量复用；不得把目标案例或 `gt_idx` 泄漏进索引文本。
4. 案例含案由、程序、诉请/事实、裁判理由、结果、关键词、法律依据和当事人，但抽样中关键词有缺失，且未看到统一的裁判日期、法院、案号和来源 URL。
5. `data/laws` 并非纯法规目录，至少混合了法律、司法解释和案例文章，必须先按 `document_type` 分类。
6. 同一法律存在多个版本，例如 2018 与 2023《公司法》；条号和内容会变化，不能只用 `law_name + article` 作为唯一 ID。
7. 《民法典》按分编拆成多个文件，文件头包含通过/施行日期，正文具备编/章/条结构，适合领域结构切分。
8. 租赁样板已有《民法典》合同编、城镇房屋租赁司法解释和部分租赁案例；候选中同时出现土地租赁、融资租赁等近词噪声，适合验证 metadata filter 与 rerank。
9. 全量规模已足以支撑求职 Demo；后续不以继续扩充数据量为优先目标，而以数据质量、版本适用、检索效果和评测可信度为优先。

### 当前开发范围：RAG 优先

当前阶段只实现和验证：

- 数据 profile、分类、清洗和版本建模。
- 法规按条/款/项、案例按法律事实结构的领域切分。
- Dense、Sparse/BM25、metadata filter、多路融合和 rerank。
- 检索评测、错误分析、时效性检查和引用回溯。

暂不实现完整 Agent 图、长期记忆、文书生成、金额计算、权限 UI 和律师转介。仅保留会影响 RAG schema 的接口字段，待检索基线可靠后进入多跳 Agentic 阶段。

### 全场景业务与高频场景 Skill

采用“共享 RAG 核心 + 高频场景 Skill/场景包”，避免每个领域复制一套检索系统。正式业务场景包含劳动纠纷、租房纠纷、保险理赔、消费维权等；底层按全场景通用能力建设，高频场景通过 Skill 包做产品化增强：

```text
共享核心
  - 统一法规/案例 schema
  - 版本与效力过滤
  - Dense + Sparse + rerank
  - 引用回溯与证据门控
  - 通用评测框架

场景包
  - 争点分类
  - 关键事实槽位
  - 案由与法规范围
  - 查询改写词表
  - 场景专用评测集
  - 拒答与转介条件
  - 文书模板与生成前硬校验
```

场景包优先级仍需结合数据画像和产品价值排序。画像不是为了决定“是否做多场景”，而是为了确认各场景的覆盖质量、评测可行性和 Skill 包落地顺序：

1. 案例数量与时间覆盖。
2. 案由和标签纯度，是否能与近邻场景可靠区分。
3. 事实、裁判理由、结果和法条引用的字段完整性。
4. 对应现行法规及司法解释是否完整、可做版本校验。
5. 是否存在可用评测 query/qrels，或能否低成本人工补标。
6. 普通用户需求频率、问题可结构化程度和 Demo 可解释性。
7. 错答风险、金额风险、隐私风险和人工律师介入需求。

自动画像负责把约 9 万个唯一案例汇总为可审阅的统计、样本和异常报告，人只需要审查劳动纠纷、租房纠纷、保险理赔、消费维权等场景的代表样本，而不是逐条阅读全部案例。

## 6. 评估先行

首个 baseline 至少维护：

- 检索：Recall@5/10、MRR、NDCG、过滤准确率、重复率。
- 重排：正例排名提升率与 top-k 命中率。
- 生成：引用准确率、引用完整率、faithfulness、拒答正确率。
- 系统：P50/P95 延迟、失败率、重试率、token/请求成本。
- 法律专项：失效法条误用率、条款引用粒度、案例与法规来源可追溯率。

`data/cases` 中的 `gt_idx` 可能可直接构造检索 gold set，但必须先确认候选集含义，避免训练/检索语料与测试答案泄漏。

## 7. Agent Runtime 开发日志

### `20260804_runstate_v0`

状态：完成。

范围：

- 新增 `lawagent_runtime/state.py` 和 `lawagent_runtime/__init__.py`。
- 实现 `RunState v0` 及其子模型：`FactItem`、`LegalIssue`、`ToolIntent`、`RetrievalAttempt`、`EvidenceItem`、`EvidenceGap`、`Budget`、`TraceEvent`、`FailureItem`。
- 暂不接入长期记忆和内容管理；仅保留 `session_id`、`case_id` 作为未来关联字段。
- 不修改旧 `agent/state.py` 的 LangGraph 原型；该目录暂作历史原型和后续对照参考，当前 Runtime 新代码放在 `lawagent_runtime/`。

设计要点：

- `ToolIntent.filters_as_slots` 只保存结构化槽位，不保存 Qdrant filter 表达式。
- `EvidenceGap` 绑定 `issue_id`，作为下一跳检索依据。
- `Budget` 控制最大步骤数、检索轮数、token/time 预算和截止时间。
- `TraceEvent` 只保存节点输入/输出摘要、路由原因、耗时和错误码，不保存完整敏感正文。

验证：

```bash
/root/miniconda3/envs/agent/bin/python -m unittest tests.test_runtime_state
/root/miniconda3/envs/agent/bin/python -m unittest discover -s tests
```

结果：`tests.test_runtime_state` 8 个测试通过；全量 `tests/` 24 个测试通过。

### `20260804_multi_agent_communication_v0`

状态：完成。

范围：

- 新增 `lawagent_runtime/messages.py`：`AgentRole`、`MessageType`、`AgentMessage`。
- 新增 `lawagent_runtime/patches.py`：`PatchOperation`、`PatchTarget`、`StatePatch` 和 `apply_state_patch`。
- 新增 `lawagent_runtime/permissions.py`：角色到状态补丁的权限表、`assert_patch_allowed`、`apply_authorized_patch`。
- 新增 `lawagent_runtime/observations.py`：`ObservationStatus`、`Observation`。
- 新增 `tests/test_runtime_communication.py`。

设计要点：

- v0 只支持 `append` 和 `set_control` 两类补丁操作。
- `IntakeAgent` 可追加事实、法律子问题和证据缺口，但不能把事实标记为 `user_confirmed` 或 `document_supported`。
- `RetrievalAgent` 可追加工具意图、检索尝试、证据和证据缺口。
- `AnalysisAgent` 可追加法律子问题和证据缺口。
- `ReviewAgent` 可追加证据缺口和失败记录，但不能直接修改事实。
- `Orchestrator` 可追加失败记录，并且是唯一可写 `stage`、`next_node`、`route_reason`、`stop_reason`、`final_decision` 控制字段的角色。
- 每次授权补丁应用都会写入 `TraceEvent`，便于审计和回放。

验证：

```bash
/root/miniconda3/envs/agent/bin/python -m unittest tests.test_runtime_state tests.test_runtime_communication
/root/miniconda3/envs/agent/bin/python -m unittest discover -s tests
```

结果：Runtime 相关 16 个测试通过；全量 `tests/` 35 个测试通过。

### `20260804_node_router_runtime_v0`

状态：完成。

范围：

- 新增 `lawagent_runtime/nodes.py`：`NodeConfig`、`AgentNode` 协议、`NodeRegistry`。
- 新增 `lawagent_runtime/router.py`：`RouteDecision`、`DefaultRouter`。
- 新增 `lawagent_runtime/runtime.py`：`AgentRuntime`、`RuntimeResult`。
- 新增 `tests/test_runtime_execution.py`。

设计要点：

- 节点不直接修改 `RunState`，只能返回 `Observation` 和 `StatePatch`。
- Runtime 执行节点后统一应用 `apply_authorized_patch`，因此多 Agent 权限在执行层生效。
- Router v0 采用规则优先：初始进入 `intake`；关键事实缺失进入 `clarify`；无争点进入 `plan`；无证据进入 `retrieve`；证据可用进入 `answer`；预算耗尽时按是否已有证据输出有限回答或建设性拒答。
- Orchestrator 通过控制补丁写入 `stage`、`next_node`、`route_reason`、`stop_reason` 和 `final_decision`。
- Runtime 对缺失节点、节点失败和越权补丁转为失败状态，写入 `failures` 和 trace。

验证：

```bash
/root/miniconda3/envs/agent/bin/python -m unittest tests.test_runtime_state tests.test_runtime_communication tests.test_runtime_execution
/root/miniconda3/envs/agent/bin/python -m unittest discover -s tests
```

结果：Runtime 相关 20 个测试通过；全量 `tests/` 39 个测试通过。

## 8. 环境与配置规范

- 当前使用 Python 3.11.15 独立 Conda 环境 `agent`。受限终端中 `conda run` 因环境目录只读而失败，实际执行改用 `/root/miniconda3/envs/agent/bin/python`。
- 所有路径基于项目根目录或环境变量，不出现 `/root/agent` 绝对路径。
- 机密仅放在未提交的 `.env` 或密钥管理服务；仓库只提供 `.env.example`。
- CPU/GPU 由 `DEVICE=auto|cpu|cuda` 配置；无 GPU 环境自动回退 CPU，并禁用 fp16。
- Qdrant 本地开发建议 Docker Compose；连接信息使用 `QDRANT_URL`。
- 当前 Docker daemon 不由 systemd 管理。启动参数为 `dockerd --host=unix:///tmp/lawagent-docker.sock --data-root=/root/lawagent/.runtime/docker-data --exec-root=/root/lawagent/.runtime/docker-exec --pidfile=/tmp/lawagent-dockerd.pid`；Docker/Compose 命令前设置 `DOCKER_HOST=unix:///tmp/lawagent-docker.sock`。`.runtime/` 已加入 Git 忽略。
- 配置按 `dev/test/prod` 分环境，启动时输出脱敏后的有效配置。

## 9. Git 与日常开发流程

Git 已初始化，当前分支为 `main` 并跟踪 `origin/main`；远端写权限与同步流程仍需在首次推送前核验：

1. 初始化仓库并建立 `main` 分支。
2. 检查 `.gitignore`，确保 `.env`、数据、模型、索引、缓存和评估运行产物不提交。
3. 首次提交只包含源码、配置模板、schema、测试和文档。
4. 功能使用短分支；提交信息建议 `feat: ...`、`fix: ...`、`docs: ...`。
5. 推送前运行格式化、静态检查、单元测试和小型检索回归。
6. 每日结束更新 `MEMORY.md` 当前阶段与本文件进度。

## 10. 跨任务恢复流程

根目录文件职责：

| 文件 | 用途 | 更新时机 |
|---|---|---|
| `AGENTS.md` | 新任务自动读取的协作规则与硬约束 | 协作方式或全局约束改变时 |
| `MEMORY.md` | 项目事实、决策状态、目标、偏好、阶段和下一步 | 每个有效开发切片完成时 |
| `DEVELOPMENT.md` | 架构、流程、数据处理记录和开发进度 | 实现或数据状态改变时 |
| `requirement.txt` | 实际环境与依赖审计 | 包或运行时发生变化时 |
| `requirements.txt` | 可安装的顶层运行依赖 | 依赖选型或版本范围变化时 |

新任务开始时先读取上述文件，再运行只读检查核实现状。任务结束时只写入可复用信息，不保存逐字对话、密钥或未经验证的推测。

### Codex 协作与渐进式学习

本项目采用“用户定方向和验收，Codex 调研、实现并验证”的协作方式。复杂任务遵循：

```text
Research -> Design -> Confirm -> Prototype -> Review -> Extend
```

### 设计确认门控

每个功能模块必须经过以下阶段：

1. **需求澄清**：明确用户场景、输入、输出、安全边界和不做什么。
2. **模块设计**：列出模块职责、依赖、数据流、接口和异常分支。
3. **最小原型设计**：明确本轮最少实现哪些功能，以及用什么样例和指标验收。
4. **用户确认**：用户明确表示接受设计或授权实现；未确认前只允许继续讨论、只读检查和更新设计文档。
5. **原型实现**：只实现已确认范围，配套测试、dry-run 和可回滚变更。
6. **验收复盘**：展示结果、测试、风险和与设计的偏差。
7. **增量扩展**：根据验收结果讨论下一批功能，重新经过确认门控。

设计确认时至少输出：

```text
目标与用户场景
模块清单及职责
输入/输出数据契约
模块间数据流
安全与失败分支
最小原型范围
明确不做的内容
验收标准
待用户确认的决策
```

“帮我分析、检查、探讨、设计”默认不授权修改业务代码；“按上述已确认设计实现”才视为实现授权。数据删除、正式入库、外部推送、安装依赖和部署仍需按各自风险单独确认。

用户不需要编写复杂提示词。一个高质量任务通常只需说明：

```text
目标：最终希望得到什么。
范围：允许读/改哪些文件、是否允许安装依赖或写入数据。
约束：不能破坏什么，成本、兼容性或安全要求是什么。
验收：用哪些测试、指标、样例或输出证明完成。
交付：希望得到代码、报告、对比方案还是可运行命令。
```

适用于当前项目的示例：

```text
请只读审计 scripts/ingest_laws.py。
目标是还原当前法条 payload，并找出会导致覆盖或时效错误的问题。
不要加载模型、连接 Qdrant、修改代码或入库。
请用 2 个真实法规文件验证结论，最后给出建议的 v0 schema。
```

Codex 应在以下节点主动给一条简短提示：

- 请求同时包含调研、设计、实现和上线，范围过大时，建议切成可验证开发切片。
- “检查/诊断”和“直接修复”授权可能混淆时，明确本轮是否写文件。
- 数据删除、覆盖、入库、外部推送或安装依赖前，提示授权和恢复方式。
- 缺少验收标准时，建议最小测试或指标。
- 存在多个合理架构方案时，先给决策维度，再请用户确认重大取舍。
- 一个结论值得并行验证或独立复核时，说明可使用第二任务/审查任务，但不默认增加复杂度。

无需提示的情况：

- 简单明确的只读查询。
- 用户已经给出目标、范围、约束和验收条件。
- 提示只会重复项目文档或上一轮刚说明的内容。

参考资料：

- [OpenAI：How OpenAI uses Codex](https://openai.com/business/guides-and-resources/how-openai-uses-codex/)
- [OpenAI：Harness engineering](https://openai.com/index/harness-engineering/)
- [OpenAI Codex 开源仓库的 AGENTS.md](https://github.com/openai/codex/blob/main/AGENTS.md)
- [开源 Awesome Codex CLI 资源索引](https://github.com/RoggeOhta/awesome-codex-cli)
- [开源 Codex CLI Best Practice](https://github.com/shanraisshan/codex-cli-best-practice)

社区教程只用于发现实践模式。引入 Skill、Plugin、Hook、MCP、自动审批或第三方工具前必须检查维护状态、权限、源码和项目必要性，不直接复制高权限配置。

## 10. 今日进度

### 已完成

- 阅读并提取“Agent 面试通关”中与架构、记忆、工程化、RAG 和评估相关的设计原则。
- 盘点现有代码、数据、模型、Python 环境和 Git 状态。
- 切换并核验 `agent` Conda 环境及已安装包。
- 建立三份持续维护文件。
- 新增 `AGENTS.md`，建立跨任务自动恢复和文档更新协议。
- 建立数据修正、整理、打包、校验和恢复的记录模板。
- 移除 `agent/llm.py` 与 `scripts/ragas_evaluate.py` 中的明文 API Key。
- 给出基础架构、入库契约、目录规划和全流程维护规范。

### 下一开发切片

- 数据画像脚本：输出法规/案例的 schema、数量、缺失率、长度分布和重复情况。
- Pydantic v2 数据契约与单元测试。
- 便携配置层与 `.env.example`。
- 清理入库脚本的 import 副作用、绝对路径、集合命名和 CUDA 假设。

## 11. 已知技术债

- `requirements.txt` 缺少实际 import 的多个核心包，且宽泛版本范围不可复现。
- 现有脚本 import 时即加载大模型，难以测试。
- `scripts/ingest_laws.py` 和 `scripts/ingest_case.py` 强制 CUDA，与当前服务器冲突。
- collection 名和 payload 字段在入库/检索代码之间不一致。
- `agent/tools.py` 混用了 `SentenceTransformer` 与 `embed_query` 接口。
- API 对话历史仅存进程内字典，重启丢失且多 worker 不一致。
- 当前评估脚本仍是占位生成逻辑，不能代表真实效果。
