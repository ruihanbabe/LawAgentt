# LawAgent Development Guide
> 摘要：这是本地开发、启动与外部依赖操作的简明手册。
> 摘要：项目五问入口是根目录 `README.md`；本文件不再兼任架构、需求、历史日志或 handoff。
> 摘要：当前解释器是 `/root/miniconda3/envs/agent/bin/python`，也可用 `LAWAGENT_PYTHON` 覆盖。
> 摘要：默认最小应用不启用真实 GLM/RAG；外部能力必须显式配置并单独验证。
> 摘要：历史检索基线已迁入 `docs/testing/RETRIEVAL_BASELINES.md`。
> 摘要：当前进度只以 `HANDOFF.md`、`docs/project/STATUS.md` 和 `TODOS.md` 为准。

## 快速开始

```bash
make setup
make check
make run
```

应用默认监听 `127.0.0.1:8000`，提供 `/`、`POST /chat` 和 `/health`。可通过 `LAWAGENT_HOST`、`LAWAGENT_PORT`、`LAWAGENT_PYTHON` 覆盖默认值。

所有标准操作见根目录 `Makefile`；运行 `make help` 查看目标。底层 `bin/` 入口继续保留，供 CI、Agent 和 Make 复用。

## 配置与密钥

复制 `.env.example` 为根目录 `.env`，保持权限 `600`。应用会加载 `.env`，进程环境同名变量优先。不得把密钥、完整 Provider 请求/响应或原始 PII 写入 Git、Trace、测试报告和聊天。

- `LAWAGENT_GLM_ENABLED=true`：需要 `GLM_API_KEY`，兼容 `ZAI_API_KEY`。
- `LAWAGENT_RAG_ENABLED=true`：默认 Qdrant 为 `http://127.0.0.1:6333`。
- `QDRANT_URL`、`CASES_COLLECTION`、`LAWS_COLLECTION`：覆盖检索配置。

六角色模型 smoke：

```bash
/root/miniconda3/envs/agent/bin/python scripts/smoke_glm_six_roles.py --output data/reports/glm-six-role-smoke.json
```

## Qdrant

`compose.yaml` 固定 Qdrant 1.18.2。现有环境使用项目专用 Docker socket：

```bash
export DOCKER_HOST=unix:///tmp/lawagent-docker.sock
docker compose up -d qdrant
curl -fsS http://127.0.0.1:6333/collections
```

预检只报告 Qdrant 是否可达，不自动启动或修改外部服务。

## Redis 与 PostgreSQL

Python 客户端安装在 `agent` 环境；服务由 Compose 启动，只绑定本机端口：

```bash
make services-up
make services-status
make services-smoke
make services-down
```

Redis 使用 AOF 并保存到 `.runtime/redis-data`；PostgreSQL 保存到 `.runtime/postgres-data`。`services-down` 只停止容器，不删除持久化数据。开发默认凭据仅用于本机隔离环境，部署时必须通过 `.env` 覆盖。

## 权威文档边界

- 产品：`docs/product/requirements.md`
- 系统：`docs/design/SYSTEM_DESIGN.md`、`docs/interfaces/API_CONTRACTS.md`
- 信源/检索：`docs/sources/SOURCE_POLICY.md`、`docs/testing/RETRIEVAL_BASELINES.md`
- 测试：`docs/testing/TESTING.md`
- 当前状态：`HANDOFF.md`、`docs/project/STATUS.md`、`TODOS.md`
- 依赖：`requirement.txt`

不再把开发日志追加到本文件；session 命令与证据写入独立 worksheet。
