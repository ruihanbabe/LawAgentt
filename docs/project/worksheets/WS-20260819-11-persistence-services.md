# WS-20260819-11 Persistence Services
> 摘要：在 agent Conda 环境安装 Redis/PostgreSQL Python 客户端，并通过 Compose 安装真实服务。
> 摘要：Redis/PostgreSQL 只绑定 localhost，持久化数据位于被 Git 忽略的 `.runtime/`。
> 摘要：Redis TTL/删除和 PostgreSQL schema/事务/读写已通过真实 Adapter smoke。
> 摘要：默认镜像源成功，本轮未切换清华或阿里云镜像。
> 摘要：应用组装仍需显式启用真实 Adapter，不把服务安装等同于产品持久化 E2E 完成。
> 摘要：跨模型 Review、完整验证、commit 和同名 tag 仍是工作流债务。

## 安装结果

- Python：`redis==6.4.0`、`psycopg==3.3.4`、`psycopg-binary==3.3.4`。
- Redis：`redis:7.4.2-alpine`，localhost:6379，AOF。
- PostgreSQL：`postgres:16.6-alpine`，localhost:5432。
- 数据：`.runtime/redis-data`、`.runtime/postgres-data`。

## 验证

- Compose `--wait`：两个容器 healthy。
- `make services-smoke`：Redis ping/TTL/round-trip/delete 通过。
- `make services-smoke`：PostgreSQL connect/schema/transaction/round-trip/cleanup 通过。
- 首次 smoke 的项目模块导入失败已通过 Make 显式 `PYTHONPATH=.` 修复。

## 剩余工作

- 将服务连接配置接入应用组装层。
- 测试进程/容器重启恢复、7天TTL和用户删除级联。
- 独立 Review、完整产品验证、commit/tag。
