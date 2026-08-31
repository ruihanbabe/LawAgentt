# LawAgent Session Feedback Log
> 摘要：记录每个 session 对协作流程、工具、文档和验证体系的反馈。
> 摘要：反馈用于定期改进 AGENTS、workflow、脚本和 linter，不代替项目状态表。
> 摘要：只记录可行动的观察：发生了什么、造成何种成本、建议怎样改变、如何验证。
> 摘要：相同问题重复出现时应升级为自动化、规则或文档路由，而不是持续提醒。
> 摘要：敏感数据、密钥、原始 PII 和隐藏思维链不得写入反馈。
> 摘要：最新条目放最上方，每次 session 结束至少填写一条“保留/改变/自动化”结论。

## 2026-08-19 · WS-20260819-11-persistence-services

- 保留：Python 客户端进入 agent 环境，Redis/PostgreSQL 服务由项目 Compose 隔离管理。
- 自动化：`make services-up/status/smoke/down` 统一服务生命周期与真实 Adapter 验证。
- 安全：端口只绑定 localhost；停止不删除数据；开发默认密码必须在非本机环境覆盖。
- 发现：scripts 直接运行缺少项目根模块路径，Make 已统一注入 `PYTHONPATH=.`。
- 镜像策略：默认源成功时不无条件切镜像；超时、限流或不可达时再使用清华/阿里云来源并记录。

## 2026-08-19 · WS-20260819-10-standard-make-commands

- 保留：Makefile 只做稳定入口，具体逻辑继续复用 `bin/` 和 `scripts/`。
- 改变：新会话和开发者不再记忆解释器绝对路径、unittest 参数、Docker socket 和 smoke 输出路径。
- 自动化：setup/status/run/compile/test/E2E/check/Qdrant/model smoke 已可通过 `make help` 发现。
- 诚实失败：Ruff 未安装时 `make lint` 返回 code 2；`make check` 明示不覆盖真实服务、浏览器、视觉、性能和独立 Review。
- 验证：`make check` 完成 compile 与 147/147 测试；外部服务和真实模型未自动触发。

## 2026-08-19 · WS-20260819-08-platform-completion

- 保留：外部服务验证与离线契约证据分开记录；不把Fake Adapter、历史Qdrant或ASGI HTTP冒充真实数据库、当前Qdrant或浏览器。
- 改变：Trace持久化移动到回复发布之前；Starlette流式测试改用`httpx.ASGITransport`，消除TestClient卡死路径。
- 自动化：需要为Docker/Qdrant状态命令加入短超时和预授权只读入口，避免权限窗口长时间卡住session。
- 观察与成本：Docker容器返回Started但端口不可达，随后状态读取权限命令卡顿并被中断；后续不再无界等待。
- 验证方式：compileall及147/147 unittest；零真实模型调用。真实Qdrant、Redis/PostgreSQL、浏览器和独立Review均明确Blocked。

## 2026-08-19 · WS-20260819-05-delivery-gate-glm

- 保留：模型只生成候选；最终接受由单一确定性Gate控制，失败码只进入安全Trace元数据。
- 改变：移除Orchestrator对裸`RESPONSE_CANDIDATE`和无Review Final的接受旁路；法规版本未确认时supported answer fail closed。
- 自动化：新增六角色GLM smoke/质量矩阵脚本，统一记录六Profile调用、token、延迟、降级与Gate结果。
- 观察与成本：FastAPI TestClient在当前Starlette/httpx组合消费流式响应时超时；SSE应用逻辑改从`build_chat_stream` seam验证，浏览器HTTP E2E仍是债务。
- 流程调整：支持被Git忽略且权限为`600`的项目级`.env`，进程环境优先；缺Key时脚本快速失败，不把凭据写入聊天、Trace或报告。
- 验证方式：compileall、130/130 unittest、成功/失败SSE E2E通过；真实GLM/Qdrant、跨模型Review、视觉/性能和Git收尾待完成。

## 2026-08-19 · WS-20260819-04-progress-sync

- 保留：以实际源码和当次可复现命令为状态证据，历史真实Qdrant证据与本轮单元测试证据分开表述。
- 改变：修正“六角色尚未消费ModelGateway”“本地无源码”和98/113项测试等过期描述，当前基线为119/119。
- 自动化：需要文档状态一致性检查，至少识别测试基线、源码存在性、任务状态和目录清单中的缺失Skill。
- 观察与成本：`skills/handoff-maintainer/SKILL.md` 被文档声明但实际不存在；手工同步增加遗漏风险，已登记GOV-004。
- 流程调整：为进度盘点单独建立worksheet，不覆盖实现session的历史证据；外部链路未重跑时显式标记为历史证据。
- 验证方式：compileall与119/119 unittest通过；真实GLM/Qdrant、E2E、视觉、性能、跨模型Review和Git收尾仍为债务。

## 2026-08-11 · WS-20260811-01-agentic-workflow

- 保留：以 `AGENTS.md` 作为唯一入口，并使用文档前 7 行摘要帮助 `rg` 检索。
- 改变：用户明确否定 Agent 自行提出的“精简/最小文档体系”；流程必须严格以用户给出的 0–18 条为蓝本，不自行裁剪。
- 自动化：源码接入后实现 `agent_review`、`verify_all`、虚假信心审计、视觉回归、benchmark、profile 和跨 commit review 统一入口。
- 观察：本地仓库无源码且无 commit，工作流能力目前只能定义，不能声称已经运行。
- 流程调整：`AGENTS.md` 增加 0–18 一一映射；`AGENT_WORKFLOW.md` 逐阶段落实全部要求；新增 active handoff、性能、工具和 night-shift 文档。
- 验证：必需文件全部存在；0–18 索引连续；否定措辞与旧路径无残留；`git diff --check` 通过。
- 产品校准：不能预先知道任意法律问题需要哪些事实；首个切片改为小模型驱动的分阶段动态信息充分性评估，租房押金仅作为首条验收样例。
- 开工门槛：Feature Spec 达到 Problem、Appetite、Solution、No-gos、Rabbit holes 和验收标准后停止扩写文档，转入远程代码核验与纵向切片实现。

## 2026-08-15 · WS-20260815-01-mvp-product-architecture

- 保留：Grill 问答先写临时 Handoff，再把确认结论按 PRD、Feature、System、Interface、Source、Testing 和 ADR 职责迁移。
- 改变：旧 Feature 只覆盖 `ASK_CLARIFICATION/START_RETRIEVAL`，与用户要求的完整押金 MVP 不一致；已重写为端到端范围并保留纵向切片实现顺序。
- 自动化：需建立文档路径/链接/前 7 行摘要检查；本次只能用检索和文件存在性核验。
- 观察与成本：官方 Skill validator 依赖 PyYAML，但默认与工作区 Python 均未安装；两次验证均在 import 阶段失败，未将手工检查冒充官方验证。
- 流程调整：新增 Source Policy、API Contracts、Runtime ADR 和 Agent Backend research Skill；明确 ModelProvider 与 AgentBackend 分层。
- 删除：旧 `lawagent-design-doc.md` 完成迁移后删除；旧离线 handoff 因仍含唯一远程事实继续保留。
- 验证债务：跨模型/Persona Review、真实应用、E2E、视觉、性能、commit/tag 均待远程源码和相应工具。

## 2026-08-19 · WS-20260819-01-agent-loop-guards

- 保留：由调度器单点派单和状态转换，Worker 只返回结果或结构化 Escalation。
- 改变：原始 Tool/Assistant 文本裸 SHA256 改为去敏规范化 ActionRecord，避免 PII 风险和随机字段造成假阴性；仍保留五条窗口三连硬规则。
- 自动化：新增待建 `validate_task_graph` 与 `detect_agent_loop` 统一入口，远程源码核验后实现。
- 观察与成本：静态 DAG、单一 owner-id 和单一窗口 hash 都不足以覆盖运行时发现、租约竞争与 ABAB 循环，需最小补充契约。
- 验证债务：无源码和跨模型 review 入口，本 session 只能完成文档契约与静态一致性检查。
- 工具执行补充：模型选择与实现执行分离；唯一 ToolExecutor、独立 ToolPolicy、读写确认和 Raw/Reduced Result 进入同一 Harness seam。
- 风险修正：权限 token 明确为短期参数绑定 CapabilityGrant；无原生 dry-run 时不得把本地 preview 冒充权威模拟执行。

## 条目模板

```markdown
## YYYY-MM-DD · WS-ID
- 保留：
- 改变：
- 自动化：
- 观察与成本：
- 流程调整：
- 验证方式：
```
