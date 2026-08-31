# ADR-0001: MVP Runtime and Application Surfaces
> 摘要：记录 LawAgent MVP 的模块化单体、ScenarioPack、应用入口和第三方 Agent Backend 采用策略。
> 摘要：决策以住宅押金纵向切片和 Harness 可验证性为优先，不以高并发或多壳应用为目标。
> 摘要：WebUI/API 为产品路径，CLI/Trace Viewer 为开发路径，桌面端与独立管理后台延期。
> 摘要：LawAgent 保有 Policy、状态、Evidence 与 Delivery 控制；Pi/Claude Agent SDK 只能通过 Adapter 候选接入。
> 摘要：具体模型与生成/Review Provider 在开发阶段按成本、质量和延迟评测决定。
> 摘要：远程源码核验可能要求兼容迁移；任何变化必须更新本 ADR。

## 状态

Accepted for planning；implementation unverified。

## 背景

项目需要在求职演示中同时证明真实法律咨询闭环与通用 Harness，但现有本地包没有源码，且历史设计曾同时包含桌面、服务端、Worker、Redis、实时法规和文书导出等过大范围。

## 决策

1. 首版采用单机模块化单体，容量目标为同时 3–5 个 Run。
2. 领域变化通过 ScenarioPack；首版只实现住宅押金。
3. WebUI/API 实现真实用户路径；CLI 负责评测/回放；Trace Viewer 为开发面板；桌面/管理后台延期。
4. ModelProvider 与 AgentBackend 分层；Node 声明 ModelProfile，Router 解析 Provider/Model。
5. Pi、Claude Agent SDK 或自研 loop 通过 AgentBackend Adapter 比较；不得接管 PolicyOrchestrator。
6. 固定法规快照和案例库进入 MVP；实时权威法规延期。
7. 不预引入消息中间件、Redis、微服务或容器编排；只有真实瓶颈与第二 Adapter 出现后再建立 seam。

## 备选

- 直接以 Pi/Claude Agent SDK 作为整个应用 Runtime：拒绝，可能泄漏 SDK 状态并绕过领域门禁。
- 预建完整多端平台：拒绝，缺少真实消费者且稀释纵向闭环。
- 微服务与队列优先：拒绝，容量目标和故障面不支持该复杂度。

## 后果

- 优点：小接口、领域控制集中、可测试、可替换、演示叙事清楚。
- 代价：需要维护 Adapter 和 LawAgent 自己的状态/Policy；无法宣称生产级扩展性。
- 退出路径：当远程现有 Runtime 具备更深接口时，通过契约测试证明后替换实现，不改变应用与 ScenarioPack 契约。

## 验证

- WebUI、CLI 使用同一应用契约；
- Fake/Replay 与至少一个真实 Model Adapter 通过契约测试；
- 第三方 Agent Backend 不可直接写 MatterState；
- 3–5 并发隔离与过载测试；
- 一条成功、空检索、Provider 失败、Review 失败和 Trace 失败 E2E。

