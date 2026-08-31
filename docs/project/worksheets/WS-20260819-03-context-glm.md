# WS-20260819-03 ContextView 与 GLM Provider
> 摘要：本 session 建立六角色最小权限 ContextView、统一 ContextService 与 GLM OpenAI 兼容 Provider Adapter。
> 摘要：ContextView 只从显式 Task、脱敏消息、Blackboard、Artifact provenance 和安全 Evidence DTO 构建。
> 摘要：运行 Trace 只记录 context ID、hash、来源数量和裁剪信息，不保存完整 Prompt 或密钥。
> 摘要：六个 ModelProfile 已统一配置到可覆盖的免费 GLM 模型，六角色结构化模型候选调用已在后续切片接通。
> 摘要：当前本地 119 项测试与 compileall 通过；历史 FastAPI health 与 Context smoke 通过，真实 GLM smoke 因新 Key 未注入而未执行。
> 摘要：独立实现 Review 已发起；commit、tag、视觉、性能和完整 E2E 尚未完成。

## 目标

- 为 Safety、Understanding、Retrieval、Analysis、Response、Review 构建不同最小上下文。
- Context 构建集中到 ContextService，Agent 不自行读取 Store。
- 增加 GLM OpenAI 兼容 Provider 和六 Profile 免费模型装配。
- 不把 API Key、伪匿名用户 ID、完整 Prompt 或未脱敏消息写入上下文审计。

## 已实现

- `AgentContextView`、`ContextRolePolicy`、`ContextSourceRef`、`FactContext`。
- 六角色字段、历史、Artifact 与工具 allowlist。
- Review 沿显式 Artifact provenance 加载候选回答、分析和 Evidence Bundle。
- 历史优先裁剪，必要上下文超限时拒绝构建。
- `CONTEXT_BUILT` Trace event，仅记录引用元数据。
- `GLMProvider`、`build_glm_profile_configs`、`build_glm_gateway_from_env`。
- 默认免费模型 `glm-4.7-flash`，可由 `GLM_MODEL` 覆盖；Key 读取 `GLM_API_KEY`，兼容旧 `ZAI_API_KEY`。

## 验证

- `/root/miniconda3/envs/agent/bin/python -m compileall -q lawagent_runtime tests`：通过。
- `/root/miniconda3/envs/agent/bin/python -m unittest discover -s tests -v`：原 session 113/113；2026-08-19 进度同步复验为119/119通过。
- FastAPI `/health` TestClient smoke：通过；出现 Starlette/httpx 迁移 warning。
- ConversationHarness Context event smoke：通过。
- 真实 GLM smoke：未执行，当前进程未配置 `GLM_API_KEY`/`ZAI_API_KEY`。

## Review 与验证债务

- 独立模型实现 Review：已发起，finding 待回写。
- 后续源码已通过 `StructuredModelRunner` 将 ModelGateway 注入六角色；模型输出仍是受确定性规则约束的候选。
- 未执行 Qdrant 实时链路、完整 E2E、视觉和性能基准。
- Git ownership 安全检查阻止当前只读 status/log；未修改全局 Git 配置。
- commit/tag：未创建。

## 下一恢复点

完成统一 `DeliveryGate`，并使用真实 GLM 验证结构化候选、错误降级和预算路径；保持风险、事实确认、工具执行和引用存在性的确定性裁决。
