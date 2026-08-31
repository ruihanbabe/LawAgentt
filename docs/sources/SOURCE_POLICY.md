# LawAgent Source & Evidence Policy
> 摘要：定义法规、案例、模板和非可信网页的来源等级、导入元数据、证据用途与引用限制。
> 摘要：MVP 使用固定法规快照和当前案例库，不把数据源声明包装为实时权威核验。
> 摘要：案例只能作为相似争议参考，不能替代法规证明一般法律规则或支持胜诉概率。
> 摘要：模板来源暂留槽位；未经人工核验不得展示为可信或官方模板。
> 摘要：模型记忆、搜索摘要和未核验转载只能提出检索候选，不得进入最终法律证据。
> 摘要：仓库已有数据实物；历史数量与索引状态仍须用 manifest 和在线查询区分验证。

## 1. 信任等级

| 等级 | 来源 | 允许用途 |
|---|---|---|
| S1 | 已核验官方法规来源 | 支撑确定性法律主张 |
| S2 | 固定法规快照、未实时核验 | 支撑有限分析，显示快照与时效警告 |
| S3 | 当前案例数据集 | 相似案例参考，不证明普遍裁判结果 |
| S4 | 人工核验的公开模板来源 | 文书结构与必要项建议 |
| S5 | 未核验网页、模型记忆、搜索摘要 | 仅生成检索候选，不作交付证据 |

MVP 当前仅计划使用 S2、S3；S4 预留；S1 不进入完成条件。

## 2. 历史数据记录（待核验）

来源：已迁移的 `docs/testing/RETRIEVAL_BASELINES.md` 与历史 worksheet。

- 案例：最终语料 92,523；query/template 各 1,146；qrels 13,096；`cases_collection` 记录为 92,523 points，dense+sparse。
- 法规 v0.2：`laws_collection` 记录为 66,147 points，dense+sparse。
- Embedding：BGE-M3，dense 1024 + sparse lexical weights。
- 案例 query、语料和 qrels 据称物理分离；133 个重叠 CaseId 已排除。
- 当前仓库存在法规 Markdown、数据和模型目录；完整性、manifest 与在线索引状态必须分别核验。

这些数字不得进入“已验证”状态，直至完成远程文件、hash、Schema、collection count 与 smoke 检查。

## 3. 已知数据限制

案例数据不能稳定提供法院、案号、裁判日期、官方 URL 或来源权威等级；系统不得推断或展示这些字段。`legal_basis` 空数组保留为空，不补造。

法规快照中的“现行法律”只是来源声明。`刑法.md` 等整合文本不能可靠重建任意历史时点；发生版本不明或冲突时有限回答并建议权威复核。

法规唯一性使用 `lawFamilyId` + `lawVersionId`，不得只用法名与条号。有效期采用 `[effectiveFrom, effectiveTo)`。

## 4. 数据分层

```text
L0 原始数据（只读）
→ L1 规范化、版本化文档 + manifest
→ L2 Qdrant index/payload
→ L3 安全 Evidence DTO
→ L4 Claim、回答与引用
```

任何层级不得反向覆盖上游。派生产物记录输入 hash、代码版本、Schema、模型/索引版本和生成时间。

## 5. 来源记录

每个 `SourceRecord` 至少包含：来源 ID、类型、标题、发布者/数据提供者、原始 URL（若可靠存在）、获取时间、内容 hash、快照版本、法域、有效期、许可/使用限制、人工核验状态和已知缺陷。

模板额外记录文书类型、适用程序和发布机构。状态为 `UNVERIFIED | VERIFIED_REFERENCE | AUTHORITATIVE`；不得按域名自动升级。

## 6. Claim-Evidence 规则

- 实质性法律 Claim 至少绑定一项合格 Evidence；一项 Claim 可绑定多项 Evidence。
- 一般法律规则优先由法规证据支撑；案例只说明类似争议如何处理及其局限。
- 相似案例展示相似点、差异点和不可直接类推项。
- 找不到证据时删除 Claim 或明确降级，不得用模型记忆填补。
- 引用使用稳定 Evidence ID 与 locator，UI 在主张旁显示并提供可展开证据卡片。

## 7. 模板源为空的行为

模板数据未补充时返回 `TEMPLATE_SOURCE_UNAVAILABLE`。系统可以根据固定产品规则提供通用必要项检查，但不能展示模板正文、发布机构或来源引用。测试 fixture 必须标记为 fixture，不能用于演示可信度声明。

## 8. 远程核验清单

1. 定位原始案例、query、qrels、法规文件及 manifest；
2. 记录路径、数量、Schema、hash、许可和数据版本；
3. 核对 Qdrant 版本、collection、point count、vector config 与 payload Schema；
4. 随机抽样验证 L0→L3 可追溯关系和 PII 处理；
5. 运行真实 dense/sparse/hybrid/rerank smoke；
6. 把差异写回本文件、STATUS、HANDOFF 与评测基线。
