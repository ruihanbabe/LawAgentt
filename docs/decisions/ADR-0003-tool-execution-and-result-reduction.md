# ADR-0003: Tool Execution, Write Confirmation and Result Reduction
> 摘要：决定模型只选择 ToolIntent，唯一 ToolExecutor 负责授权、执行、结果持久化与压缩，禁止任何旁路调用。
> 摘要：每个工具拥有独立的 timeout、权限、预算、并发、重试、幂等、数据、沙箱、审计和结果上限配置。
> 摘要：查询与命令分离；外部副作用写先 dry-run/preview，再使用一次性、参数绑定的确认令牌执行。
> 摘要：权限采用短期 CapabilityGrant，不向模型暴露长期凭据；owner、参数或目标版本变化使授权失效。
> 摘要：原始 Tool 结果先持久化，MessageReducer 只生成有界 ToolResultView，不能破坏 provenance 与关键精确字段。
> 摘要：MVP 禁止代表用户执行外部写操作；本决策为未来扩展建立安全 seam，具体实现待远程核验。

## 状态

Accepted for planning；implementation unverified。

## 问题

若模型选完工具后直接执行，会把模型判断、权限、凭据和副作用混在一起；统一全局 timeout/权限又无法表达不同工具风险。大型原始结果直接回填上下文还会造成 token 膨胀、Prompt Injection 和来源丢失。

## 决策

1. 模型只产生候选 ToolIntent；ToolExecutor 是唯一实现调用入口。
2. AgentBackend 自动 tool loop 必须关闭或通过执行 hook 委托 ToolExecutor。
3. 每工具配置 operation/side-effect、Schema、timeout、retry、idempotency、concurrency/rate、size、cost、data class、allowlist、sandbox、audit、dry-run、confirmation、cancel 与 compensation。
4. PolicyOrchestrator 签发一次性 CapabilityGrant，绑定 owner epoch、tool、参数 hash、数据范围和过期时间。
5. READ/WRITE 接口与凭据分离。外部写需要 ExecutionPreview + ConfirmationGrant；执行前重验目标版本以防 TOCTOU。
6. 无上游原生 dry-run 时只能称本地 preview，并标记非权威。
7. RawToolResult 先保存；MessageReducer 产生受限 ToolResultView。确定性压缩优先，模型摘要计入预算。
8. Reducer 必须保留精确金额/日期、Evidence/locator、版本、错误、部分失败、来源、截断和 raw 引用。

## 边界

内部 Message/Matter/Artifact/Trace 写入是 Orchestrator 管理的系统状态写，不逐次要求用户确认，但仍受权限、版本、幂等和审计控制。MVP 的所有外部写工具保持禁用。

## 后果

- 优点：模型无法直接产生副作用；权限最小化；工具差异局部化；上下文成本可控且可追溯。
- 代价：ToolExecutor/Registry/Grant/Preview/Reducer 状态与测试增加。
- 风险：Reducer 丢失关键信息；通过不可压缩字段、raw 引用、lossy 标志和回归夹具控制。

## 验证

以 `TESTING.md` 的旁路、权限、dry-run、确认重放/TOCTOU、timeout、幂等和 Reducer 保真测试为门禁；以 `PERFORMANCE.md` 分段度量执行与压缩成本。

