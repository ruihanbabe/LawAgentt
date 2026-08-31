# LawAgentt

LawAgentt 是 Python 法律援助 Agent MVP。当前已实现的纵向链路主要面向中国大陆住宅租赁押金纠纷。

## 当前实现

```text
FastAPI /chat
  → ConversationHarness
  → TaskBoardRuntime
  → Safety / Understanding / Retrieval / Analysis / Response / Review
  → DeliveryGate
  → SSE 响应
```

应用支持按配置启用 GLM 和 Qdrant。默认使用内存存储；Redis/PostgreSQL Adapter 已存在，但尚未注入默认应用组装。

当前架构、模块边界和数据所有权见 `ARCHITECTURE.md`。产品目标见 `docs/product/requirements.md`，不得把产品目标当作已完成功能。

## 运行

```bash
make setup
make check
make run
make health
```

`make setup` 只准备本地配置并检查解释器，不安装依赖。完整命令以 `make help` 为准；命令、环境变量和服务版本分别以 `Makefile`、`.env.example`、`compose.yaml` 为准。当前还没有可复现的依赖定义和锁文件。

## 文档

- Codex 入口与硬约束：`AGENTS.md`
- 当前系统架构：`ARCHITECTURE.md`
- 文档索引：`docs/README.md`
- 开发指南：`docs/development/DEVELOPMENT.md`
- 当前进度：`PROGRESS.md`

本地测试、mock 和进程内 ASGI 测试不能证明真实模型、Qdrant、数据库、浏览器或法律质量已经验收。
