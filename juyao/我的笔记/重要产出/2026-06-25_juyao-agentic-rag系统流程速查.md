# 2026-06-25 juyao-agentic-rag 系统流程速查

> 个人备忘：5 分钟回顾「入库建图 + 问答 + UI」全链路。

---

## 两条主链路

```
【入库】文件 → 切 chunk → Qdrant + ES + Neo4j（LLM 抽三元组）
【问答】问题 → 路由 → 向量 / 图谱 / 直答 → SSE 流式输出
```

---

## 入库（图谱在这里建）

| 步骤 | 做什么 | 代码 |
|------|--------|------|
| 1 | 读文件 | `ingestion/loader.py` |
| 2 | 语义切分 | `ingestion/splitter.py` |
| 3 | 写向量 | `indexing/qdrant.py` |
| 4 | 写全文 | `indexing/elasticsearch.py` |
| 5 | **建图** | `graph_writer.py` → `extractor.py` → `store.py` |

**Neo4j 模型**

```
(Entity {name}) -[:RELATED {relation: "位于"}]-> (Entity)
边上：chunk_ids, doc_ids, source_names, evidence_snippets ...
```

**生产路径**：UI 上传 → Java Kafka → Python `ingest_file`

**CLI**：`python -m rag_core.cli.ingest --file <path>`

---

## 问答（Routed 编排）

```
                    ┌─ direct ──────────────┐
问题 → 意图路由(B) ─┼─ graph_only → Neo4j(C) ─┤→ 流式作答(H)
                    └─ vector_only → 检索(D)   │
                              ↓                │
                         充分性(E)             │
                         ↓不够    ↓够          │
                      补图(F)   仅向量(G) ─────┘
```

| 分支 | 适用 |
|------|------|
| `direct` | 闲聊、无需知识库 |
| `graph_only` | 关系/流程/实体连接类问题 |
| `vector_only` | 默认；先检索，不够再补图 |

**混合检索**：改写 + HyDE → Qdrant ∥ ES → 双层 RRF → 重排

**入口**：`POST /api/v1/chat/stream`

---

## UI 图谱页 ≠ 建图

| 页面 | 作用 |
|------|------|
| 文档上传 | 触发入库（含建图） |
| 对话页 | 走问答链路 |
| **图谱管理** | 查/改/删已有 Neo4j 数据 + ECharts 可视化 |

---

## 三库分工

| 存储 | 问答怎么用 |
|------|------------|
| Qdrant | 语义相似 chunk |
| Elasticsearch | 关键词/BM25 chunk |
| Neo4j | 实体关系 observation |

`chunk_id` 三处统一，可互相溯源。

---

## 文档

- `juyao-agentic-rag/docs/ARCHITECTURE.md`
- `juyao-agentic-rag/docs/KNOWLEDGE_GRAPH.md`

## 来源

- 对话整理，2026-06-25
