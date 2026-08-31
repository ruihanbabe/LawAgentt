# Infrastructure 模块指引

## 职责

提供 GLM、Qdrant、embedding 及环境配置等可替换外部实现；不定义核心业务规则或改变核心数据语义。

## 修改前

阅读 [`ARCHITECTURE.md`](ARCHITECTURE.md)、`.env.example`、`compose.yaml`、`env.py` 与相关 Provider/Adapter 测试；按调用方继续读取 Knowledge 或 Persistence 指引。

## 不变量与 contract

- 凭据不得进入代码、日志或 Trace；进程环境优先于 `.env`。
- 外部失败必须显式暴露或安全失败，不得伪装成功。
- 外部实现可替换且只通过核心端口进入，不反向定义 Runtime、Knowledge 或 Persistence 的业务语义。

## 修改后验证

运行 `PYTHONPATH=src python3 -m unittest tests.test_env tests.test_glm_provider tests.test_qdrant_runtime_tools -v`。真实模型或服务验证须先获用户授权，并按根开发指南执行相应 smoke；详见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。
