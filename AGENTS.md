# LawAgent Codex 入口

## 项目概览

LawAgentt 是 Python 法律援助 Agent MVP，当前实现主要面向中国大陆住宅租赁押金纠纷。

## 项目目的

构建受证据约束的法律援助产品，并验证可复用的 Harness/Runtime 工程能力。产品目标与范围见 [`docs/product/requirements.md`](docs/product/requirements.md)。

## Runtime 与环境

- 标准命令：`Makefile` 和 `bin/`。
- 环境变量：`.env.example`；进程变量优先于 `.env`。
- 默认使用 `python3`；其他环境通过 `PYTHON` 或 `LAWAGENT_PYTHON` 覆盖。
- 不得使用 Markdown 证明当前依赖、服务健康或外部系统状态。

## 首次运行

```bash
make setup
make check
make run
make health
```

`make check` 只是本地代码门禁，不证明真实模型、服务、浏览器、性能或法律质量已经验收。

## 新会话首次读取

1. 本文件：确认硬约束。
2. [`README.md`](README.md)：确认系统用途和运行入口。
3. [`ARCHITECTURE.md`](ARCHITECTURE.md)：按任务定位模块、数据 owner 和依赖方向。
4. [`PROGRESS.md`](PROGRESS.md)：确认当前状态、阻塞和近期重点。
5. 只读取文档地图中与当前任务直接相关的专项文档。

## 硬约束

- 开始前运行 `git status --short --branch`，保留用户已有改动。
- 只读取和修改当前任务需要的文件，不做相邻重构。
- 不提交 `.env`、凭据、原始 PII、完整 Provider payload 或未脱敏 Trace。
- 连接远程服务器、调用真实模型或产生费用前必须获得用户明确授权。
- 只报告当前环境实际执行成功的验证；mock 和历史结果不是当前证据。
- 代码与机器配置优先于 Markdown。
- 过时历史不留在工作树；用户明确要求回溯时再从 Git 历史恢复。

## 文档地图

- 文档入口：[`docs/README.md`](docs/README.md)
- 当前系统架构：[`ARCHITECTURE.md`](ARCHITECTURE.md)
- 开发与运行：[`docs/development/DEVELOPMENT.md`](docs/development/DEVELOPMENT.md)
- 产品目标：[`docs/product/requirements.md`](docs/product/requirements.md)
- 信源与证据约束：[`docs/sources/SOURCE_POLICY.md`](docs/sources/SOURCE_POLICY.md)
- 当前进度：[`PROGRESS.md`](PROGRESS.md)
- 文档记录规则：[`DOCUMENT-WRITING.md`](DOCUMENT-WRITING.md)

## 历史文档

仓库不保留历史归档区或会话工作表。需要历史信息时，由用户明确指定后从 Git 恢复；不得默认搜索历史并将其作为当前实现依据。
