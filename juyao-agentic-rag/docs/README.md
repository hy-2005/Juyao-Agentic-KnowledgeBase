# 文档目录索引

> 维护规则（见 CLAUDE.md）：新增/改名文档必须同步本索引；状态变化同步更新标记。
> 状态标记（严格三态，见 CLAUDE.md）：✅ 已完成 / 🔄 进行中 / ❌ 未完成
> 时间维护：每份文档头部保留「创建 / 更新」日期；本索引同时落两列便于审计（按 CLAUDE.md 「禁止事后回填或猜测」）。
> 创建：2026-08-07 · 更新：2026-08-13

## 评审与方案（docs/）

| 文档 | 说明 | 状态 | 创建 | 更新 |
|---|---|---|---|---|
| [CHUNK_SPLITTING_REVIEW.md](CHUNK_SPLITTING_REVIEW.md) | chunk 拆分评审：预分批/规则主通道/父子分块/OCR 已生效/表格与层级待办 | 🔄 进行中（表格结构/层级解析待办） | 2026-08-07 | 2026-08-07 |
| [RETRIEVAL_REVIEW.md](RETRIEVAL_REVIEW.md) | 检索评审：相对截断（已回退）/阈值 0.5/HyDE+simple_query 配置化/漏斗扩容/多样性/match_phrase | 🔄 进行中（rerank 截断/缓存遗留） | 2026-08-07 | 2026-08-12 |
| [GRAPH_QUERY_REVIEW.md](GRAPH_QUERY_REVIEW.md) | 图谱评审：查询/入库/社区（Leiden+摘要+global 兜底）+ 2026-08-12 多图谱改造（标签隔离 + MySQL 管理快照） | 🔄 进行中（hops 约束/实体合并等 6 项待办；多图谱改造已实施待实测） | 2026-08-07 | 2026-08-12 |
| [GRAPH_COMMUNITY_UI_REVIEW.md](GRAPH_COMMUNITY_UI_REVIEW.md) | 图谱社区展示：节点按社区着色 + 社区面板 + 聚类布局/边界气泡 + §3 批量入库模式（2026-08-13） | ✅ 已完成（2026-08-08，2026-08-12 增强恢复，2026-08-13 §3） | 2026-08-08 | 2026-08-13 |
| [COMMUNITY_SYNC_REVIEW.md](COMMUNITY_SYNC_REVIEW.md) | 社区同步方案评审：全量重建现状 + 摘要缓存/子图增量/双写切换方案对比 | ❌ 未完成（方案讨论稿） | 2026-08-13 | 2026-08-13 |
| [INGESTION_UPDATE_REVIEW.md](INGESTION_UPDATE_REVIEW.md) | 文档更新/增量评审：先写后删差集/chunk_id 内容寻址方案 | 📌 先写后删已实施，增量 chunk_id 待办 | 2026-08-07 | 2026-08-07 |
| [CHUNK_MYSQL_PERSISTENCE_REVIEW.md](CHUNK_MYSQL_PERSISTENCE_REVIEW.md) | 切片 MySQL 持久化：管理查询走 MySQL，ES 仅保留全文检索 | ✅ 已完成（2026-08-08） | 2026-08-08 | 2026-08-08 |
| [TENANT_PERMISSION_REVIEW.md](TENANT_PERMISSION_REVIEW.md) | 租户/权限评审：kbId 贯通/API 鉴权/kb 授权模型 | 📌 kbId 贯通已实施，权限模型待办 | 2026-08-07 | 2026-08-07 |
| [ARCHITECTURE_REVIEW.md](ARCHITECTURE_REVIEW.md) | 架构评审：分层+管线重构方案（§9 决策 + §10 映射表） | ✅ 已完成 | 2026-08-07 | 2026-08-07 |
| [PARENT_CHILD_CHUNKING.md](PARENT_CHILD_CHUNKING.md) | 父子分块 + 结构化识别方案 | 🔄 进行中（已启用 chunk_parent_enabled=true + child_chunk_size=300；4311 大块根因待查） | 2026-08-07 | 2026-08-12 |
| [PARENT_CHILD_UI_REVIEW.md](PARENT_CHILD_UI_REVIEW.md) | 父切片展开查看子切片已实施 | ✅ 已完成 | 2026-08-07 | 2026-08-08 |
| [PITFALLS.md](PITFALLS.md) | **开发踩坑记录**（24 个坑 + 模式总结，必须持续维护） | ✅ 持续更新（记录文档） | 2026-08-07 | 2026-08-12 |
| [AGENT_FLOW.md](AGENT_FLOW.md) | **整体 Agent 流程图**：HTTP→路由→三分支→检索/图谱子管线→流式生成→SSE；含 §0 白话讲解、§1 概览、§7 入库详细、§8 检索详细（含派系 2 L1/L2/L3） | ✅ 已完成 | 2026-08-11 | 2026-08-12 |

## 评测（docs/eval/）

| 文档 | 说明 | 状态 | 创建 | 更新 |
|---|---|---|---|---|
| [WORKFLOW.md](eval/WORKFLOW.md) | RAGAS 评测流程 | ✅ 命令已修正 | 2026-06-18 | 2026-08-07 |
| [METRICS.md](eval/METRICS.md) | 四指标含义与分数解读 | ✅ | 2026-06-18 | 2026-06-18 |
| [GETTING_STARTED.md](eval/GETTING_STARTED.md) | 评测快速开始 | ✅ | 2026-06-18 | 2026-06-18 |
| [RESULTS_20260807.md](eval/RESULTS_20260807.md) | 终评对比（基线/1.2 后/终评） | ✅ 检索优化后需重跑 | 2026-08-07 | 2026-08-07 |
| [RESULTS_20260808.md](eval/RESULTS_20260808.md) | 全 MiniMax 100 条 QA 评测（欠费跳过 68 条，32 条有效） | 🔄 进行中（欠费恢复后补跑全量） | 2026-08-08 | 2026-08-08 |
| [CALIBRATION_DECISION.md](eval/CALIBRATION_DECISION.md) | chunk 参数校准决策（保持 800/1400） | ✅ | 2026-08-07 | 2026-08-07 |
| [RESULTS_20260812_graphv2.md](eval/RESULTS_20260812_graphv2.md) | **派系 2 GraphRAG 改造评测**：社区优先 + L1/L2/L3 级联 + A+B+C 效果验证 | ⏸ 未跑（代码未启动，待部署后由用户跑 RAGAS） | 2026-08-12 | 2026-08-12 |

## 其他

| 路径 | 说明 | 创建 | 更新 |
|---|---|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 项目原始架构文档（非评审产出） | 2026-05-24 | 2026-06-18 |
| [GETTING_STARTED.md](GETTING_STARTED.md) | 本地启动与测试（安装/配置/依赖/入库/问答/FAQ，2026-08-13 自旧分支恢复并修正断链） | 未记录 | 2026-08-13 |
| [API.md](API.md) | HTTP API 说明（FastAPI 四组接口 + Java 网关对照，2026-08-13 自旧分支恢复） | 未记录 | 2026-08-13 |
| `src/data/samples/downloaded/` | 开源真实样本（README/PDF/源码，结构识别测试用） | — | — |
| `src/data/samples/multiformat/` | 本地生成多格式样本（docx/pdf/扫描件/csv/md/html/json） | — | — |
| `reports/` | 评测报告（baseline/after12/final/calib*） | — | — |
| `scripts/` | 工具脚本（relocate_imports/diff_sse_contract/record_sse_snapshot） | — | — |

## 列维护说明

- **创建**：文档首次落盘日期（YYYY-MM-DD）；禁止回填或猜测，不确定时写 `未记录`。
- **更新**：文档内容实质性变更（条目增删、状态变化、问题记录）日期；纯格式微调不更新。
- 文档头部必须保留对应日期行（与本索引保持一致，避免出现"文档说昨天写、索引说上月改"的错位）。
- 修改文档后：1) 更新文档头部日期 → 2) 更新本索引对应行；两步都做才视为完成。
