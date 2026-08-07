# 文档目录索引

> 维护规则（见 CLAUDE.md）：新增/改名文档必须同步本索引；状态变化同步更新标记。
> 状态标记（严格三态，见 CLAUDE.md）：✅ 已完成 / 🔄 进行中 / ❌ 未完成
> 创建：2026-08-07 · 更新：2026-08-08

## 评审与方案（docs/）

| 文档 | 说明 | 状态 |
|---|---|---|
| [CHUNK_SPLITTING_REVIEW.md](CHUNK_SPLITTING_REVIEW.md) | chunk 拆分评审：预分批/规则主通道/父子分块/OCR 已生效/表格与层级待办 | 🔄 进行中（表格结构/层级解析待办） |
| [RETRIEVAL_REVIEW.md](RETRIEVAL_REVIEW.md) | 检索评审：相对截断/漏斗扩容/多样性/match_phrase/query 分级 | 🔄 进行中（rerank 截断/缓存遗留） |
| [GRAPH_QUERY_REVIEW.md](GRAPH_QUERY_REVIEW.md) | 图谱评审：查询/入库/社区（Leiden+摘要+global 兜底） | 🔄 进行中（hops 约束/实体合并等 6 项待办） |
| [INGESTION_UPDATE_REVIEW.md](INGESTION_UPDATE_REVIEW.md) | 文档更新/增量评审：先写后删差集/chunk_id 内容寻址方案 | 📌 先写后删已实施，增量 chunk_id 待办 |
| [TENANT_PERMISSION_REVIEW.md](TENANT_PERMISSION_REVIEW.md) | 租户/权限评审：kbId 贯通/API 鉴权/kb 授权模型 | 📌 kbId 贯通已实施，权限模型待办 |
| [ARCHITECTURE_REVIEW.md](ARCHITECTURE_REVIEW.md) | 架构评审：分层+管线重构方案（§9 决策 + §10 映射表） | ✅ 已完成 |
| [PARENT_CHILD_CHUNKING.md](PARENT_CHILD_CHUNKING.md) | 父子分块 + 结构化识别方案 | 🔄 进行中（PDF 表格布局/子块大小验证遗留） |
| [PARENT_CHILD_UI_REVIEW.md](PARENT_CHILD_UI_REVIEW.md) | 父切片展开查看子切片已实施 | ✅ 已完成 |
| [PITFALLS.md](PITFALLS.md) | **开发踩坑记录**（14 个坑 + 模式总结，必须持续维护） | ✅ 持续更新（记录文档） |

## 评测（docs/eval/）

| 文档 | 说明 | 状态 |
|---|---|---|
| [WORKFLOW.md](eval/WORKFLOW.md) | RAGAS 评测流程 | ✅ 命令已修正 |
| [METRICS.md](eval/METRICS.md) | 四指标含义与分数解读 | ✅ |
| [GETTING_STARTED.md](eval/GETTING_STARTED.md) | 评测快速开始 | ✅ |
| [RESULTS_20260807.md](eval/RESULTS_20260807.md) | 终评对比（基线/1.2 后/终评） | ✅ 检索优化后需重跑 |
| [CALIBRATION_DECISION.md](eval/CALIBRATION_DECISION.md) | chunk 参数校准决策（保持 800/1400） | ✅ |

## 其他

| 路径 | 说明 |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 项目原始架构文档（非评审产出） |
| `src/data/samples/downloaded/` | 开源真实样本（README/PDF/源码，结构识别测试用） |
| `src/data/samples/multiformat/` | 本地生成多格式样本（docx/pdf/扫描件/csv/md/html/json） |
| `reports/` | 评测报告（baseline/after12/final/calib*） |
| `scripts/` | 工具脚本（relocate_imports/diff_sse_contract/record_sse_snapshot） |
