# 图谱详情持久化（评审与实施）

> 状态：✅ 已完成（代码已实施，单测 3 项新增、全量 64 项通过；线上库 ALTER 已执行。老数据按需求方决策不回填——本地开发，新链路数据自然带详情）
> 创建：2026-08-16 · 更新：2026-08-16
> 关联：[AGENT_FLOW.md](AGENT_FLOW.md)（§5 入库链路）、[LIGHTRAG_MIGRATION_REVIEW.md](LIGHTRAG_MIGRATION_REVIEW.md)（hints 数据源）

## 1. 需求

图谱前端点击节点/边时展示完整属性（类 Neo4j Browser 属性面板），且详情**持久化在 MySQL**——不再只有度数/chunk_ids。

## 2. 方案

Neo4j 侧本来就存着全部 hints（summary_hints / relation_full_hints / time / location / kinds / senses / modality / doc_ids / source_names），缺的只是 MySQL 快照列 + 详情接口 + 前端点击链路。**不动 Neo4j、不动抽取，只加同步与展示。**

```
入库抽取（gloss/hints 全量）
  → graph_writer._accumulate_snapshot_delta（增量聚合扩展为携带全部 hints）
  → upsert_graph_delta（MySQL 新列，本批覆盖语义 + 调度器全量同步校正）
  → 前端点击 → /rag/graph/entity|edge/detail → MySQL 直查 → 属性面板
```

## 3. 实施清单

### 后端 ✅

- [x] `sql/rag_graph_detail.sql`：**完整 CREATE TABLE 现状结构（审核单一事实源）+ 迁移 ALTER**；两表新增 13 详情列并带全部列注释，已在线上库执行（幂等：重复执行先查 information_schema）
- [x] 线上库列注释补齐：14 个新列 + community_id 过时注释修正（MODIFY 重述完整定义；注意 `update_time` 的 information_schema EXTRA 含 DEFAULT_GENERATED，不能与手写 DEFAULT CURRENT_TIMESTAMP 拼接，会 1064）
- [x] `mysql_graph.py`：`_fetch_entities/_fetch_edges` 拉全部 hints；全量同步写新列；`upsert_graph_delta` 增量写新列；新增 `entity_detail_mysql` / `edge_detail_mysql`（含合并摘要 convenience 字段）
- [x] `graph_writer._accumulate_snapshot_delta`：实体累积 gloss、边累积全部 hints（set 去重，跨 chunk 合并与 Neo4j 累积语义一致）
- [x] `routes/graph.py`：`GET /entity/detail`、`GET /edge/detail`（404 = 不存在或快照未同步）
- [x] Java `RagGraphController`：`/rag/graph/entity/detail`、`/rag/graph/edge/detail` 转发

### 前端（juyao-ui）✅

- [x] `api/rag.js`：`getRagGraphEntityDetail` / `getRagGraphEdgeDetail`
- [x] 新组件 `KgDetailDrawer.vue`：节点/边共用属性面板（实体=摘要+简注列表+度数；边=三元组+断言概括+全部 hints+证据原文）
- [x] `KgGraphPanel`：边点击 emit `edge-click`（ECharts edge data 反解 source/target/relation）
- [x] `KgGraphViewport`：转发 node-click / edge-click
- [x] `index.vue`：内联视口接线节点/边点击 → 共享抽屉；表格行「详情」升级为同一抽屉（API 全量 hints）
- [x] `KgFullGraphShell`（全屏）：节点抽屉顶部增加实体摘要；边点击 → 共享详情抽屉

### 测试 ✅

- [x] `tests/test_graph_detail_persist.py`：gloss/hints 聚合、跨 chunk 去重合并、自环过滤（3 项）
- [x] 全量单测 64 项通过；线上库详情函数实测（老数据 hints 为空符合预期）

## 4. 语义与边界

1. **增量覆盖 + 全量校正**：每文档 delta 的 hints 按本批覆盖（与 chunk_ids 同语义），调度器静默窗口后的全量同步写入 Neo4j 权威值——跨文档累积以 Neo4j 为准
2. **老数据无 hints**：kb=12 等存量库 relation_full/time 等 Neo4j 里其实有，但按需求方决策**不回填**；新入库文档自然带全。需要时随时可跑一次全量同步补上
3. **手工改图**：管理台增删改实体/边仍走 `_mark_graph_dirty`（快照静默同步），详情在新数据入库/同步后可见
4. JSON 列空值归 NULL（空串不是合法 JSON，历史坑，`_json_col` 统一处理）

## 5. 遗留问题

（无）
