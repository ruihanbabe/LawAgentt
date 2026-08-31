# LawAgent 开发指南

## 标准命令

```bash
make setup
make check
make run
make health
```

当前命令以 `make help` 为准。`Makefile` 和 `bin/` 是权威入口，不在文档中复制其实现。

`make setup` 只检查解释器并在缺少 `.env` 时复制安全模板，不安装 Python 依赖。`make status` 只检查项目入口和本地解释器；服务状态使用对应的 `services-status` 或 `qdrant-status` 命令。

## 环境

- 将 `.env.example` 复制为 `.env`，密钥不得进入 Git。
- 进程环境变量优先于 `.env`。
- 当前代码要求 Python 3.11 或更高版本。默认使用 `python3`；需要指定解释器时，通过 `PYTHON` 或 `LAWAGENT_PYTHON` 覆盖。
- `LAWAGENT_GLM_ENABLED=true` 开启 GLM Provider。
- `LAWAGENT_RAG_ENABLED=true` 开启懒加载 Qdrant 检索。
- 服务镜像和拓扑以 `compose.yaml` 为准。
- `requirement.txt` 是人工环境记录，不是锁文件。

## 可选服务

```bash
make services-up
make services-status
make services-smoke
make services-down
```

持久化 smoke 会连接真实 Redis/PostgreSQL；默认应用仍使用内存 Adapter。

## 可选模型验证

`make model-smoke` 会调用真实模型。执行前必须获得用户明确授权，并确认凭据和潜在费用。

## 验证边界

`make check` 只执行离线语法编译和当前测试。lint/type-check 尚未纳入门禁；它也不证明真实 GLM、Qdrant、Redis/PostgreSQL 应用接入、浏览器行为、性能或法律质量。
