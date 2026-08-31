# LawAgent Repository Guide
> 摘要：这是新会话回答项目五个基本问题的唯一入口。
> 摘要：产品、架构、运行、验证和当前进度均从这里路由到权威文档或可执行命令。
> 摘要：本页只陈述当前实现，不把目标契约误写成已经完成的能力。
> 摘要：`bin/project_status` 用机器检查环境和关键入口，避免每次人工重复调查。
> 摘要：`bin/verify_all` 提供当前可执行的核心验证；尚未具备的验证会明确列为债务。
> 摘要：代码、命令或状态变化时，本页必须在同一提交中更新。

## 五个基本问题

### 1. 这是什么系统？

LawAgent 是面向中国大陆个人住宅承租人的押金纠纷咨询 MVP，也是一个 Agent Runtime 与 Harness Engineering 求职作品。系统通过最多两轮追问，生成受法规和案例 Evidence 约束的有限分析、材料清单及行动建议；它不提供胜诉概率，也不替代律师或裁判。

权威范围与验收见 `docs/product/requirements.md` 和 `docs/features/rental-deposit-consultation.md`。

### 2. 怎么组织？

当前实现是 Python 3.11 模块化单体：

```text
main.py / api / web
  -> ConversationHarness + AgentRunBoard / TaskBoardRuntime
  -> Safety, Understanding, Retrieval, Analysis, Response, Review
  -> ContextService, ModelGateway, ToolExecutor, DeliveryGate
  -> Qdrant / model / memory adapters
```

确定性 Orchestrator 控制状态、工具、预算、Evidence 与最终交付；模型只生成结构化候选。权威设计见 `docs/design/SYSTEM_DESIGN.md`，当前/目标接口差异见 `docs/interfaces/API_CONTRACTS.md`。

## 技术栈与当前环境版本

以下是 `requirement.txt` 最近核验的运行环境摘要，不等同于可复现锁文件：

| 层级 | 技术与版本 |
|---|---|
| 语言与环境 | Python `3.11.15`、pip `26.1.2`、Conda 环境 `agent` |
| Web/API | FastAPI `0.140.8`、Uvicorn `0.51.0`、Pydantic `2.13.4`、HTTPX `0.28.1` |
| Agent Runtime | 自研 `lawagent_runtime`；LangGraph `1.2.10` 仅为环境中已有的对照依赖，不是当前 Runtime |
| 向量检索 | Qdrant Server `1.18.2`、qdrant-client `1.18.0` |
| 持久化 | Redis Server `7.4.2` / redis-py `6.4.0`；PostgreSQL Server `16.6` / psycopg `3.3.4` |
| Embedding/Reranker | FlagEmbedding `1.4.0`、sentence-transformers `5.6.1` |
| 模型与计算 | PyTorch `2.6.0`、Transformers `5.14.1`；宿主 RTX 3090 24 GB |
| 离线评测 | RAGAS `0.4.3`、OpenAI client `2.53.0`、Datasets `5.0.0` |
| 数据处理 | NumPy `2.4.6`、Pandas `3.0.5`、cn2an `0.5.24` |
| 容器 | Docker Engine/CLI `29.7.1`、Compose `v5.4.0`、containerd `2.2.6` |

`ruff`、`mypy`、`pytest`、`pytest-asyncio`、`pydantic-settings` 和 `python-dotenv` 当前未安装；项目测试使用标准库 `unittest`。Redis/PostgreSQL 客户端已安装在 `agent` 环境，服务由 Compose 管理。完整依赖状态、运行方式与变更审计以 `requirement.txt` 为准。

### 3. 怎么运行？

```bash
make setup
make run
curl -fsS http://127.0.0.1:8000/health
```

浏览器入口为 `http://127.0.0.1:8000/`。默认不启用真实 GLM 或 RAG；本地配置复制自 `.env.example`，密钥只写入被忽略且权限为 `600` 的 `.env`。可选依赖见 `DEVELOPMENT.md`。

### 4. 怎么验证？

```bash
make check
make verify
```

核心验证不等于完整产品验收。真实 Provider/Qdrant、浏览器 E2E、视觉、性能、跨模型 Review 与 30 条产品评测的状态会明确报告；权威清单是 `docs/testing/TESTING.md`。

### 5. 现在进度如何？

已完成最小六角色链路、两轮事实状态、ToolExecutor RAG、角色化 Context、GLM Adapter、DeliveryGate 及成功/阻断 SSE seam。当前重点是真实 GLM/Qdrant 复验、有限回答/拒答 E2E、Trace/Replay、30 条评测和治理工具。

当前进度的唯一总览是 `PROGRESS.md`。接手恢复看 `HANDOFF.md`，任务队列看 `TODOS.md`，逐 session 证据看 `docs/project/STATUS.md`；运行 `bin/project_status` 获取机器侧现况。

## 新会话规则

1. 先读本页，再按 `AGENTS.md` 的固定顺序加载文档。
2. 不从旧 handoff、历史 worksheet 或测试数量推断当前状态。
3. 在声称“可运行”或“已验证”前，运行预检和相应验证命令。
4. 如果本页与代码或动态状态冲突，立即修正文档并记录知识衰减。
