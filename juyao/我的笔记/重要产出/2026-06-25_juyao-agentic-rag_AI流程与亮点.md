# 2026-06-25 juyao-agentic-rag — AI 流程与亮点

> 个人备忘：理解「Agentic RAG + GraphRAG」怎么跑、亮点在哪。速查版见 [[2026-06-25_juyao-agentic-rag系统流程速查.md]]。

---

## 一句话定位

**企业知识库 RAG 引擎**：混合检索 + **Agentic 编排** + GraphRAG，Python 引擎 + Java 管理端 + Vue 前端，支持 CLI / HTTP SSE / Kafka 异步入库。

---

## AI 全流程（两条主链路）

### 1. 入库建图 — 文档变可检索知识

```
文件 → 语义切分(LLM) → 并行写入三库
                         ├─ Qdrant（向量）
                         ├─ Elasticsearch（BM25）
                         └─ Neo4j（LLM 抽三元组 → MERGE 幂等建图）
```

**AI 介入点**

| 环节 | 做什么 |
|------|--------|
| 切分 | LLM 三层语义切分 + 规则降级，保证 chunk 语义完整 |
| 建图 | 每 chunk 独立调用 `TripleExtractor`，输出 JSON 三元组写入 Neo4j |
| 溯源 | `chunk_id` 三库统一，向量命中 ↔ 图谱边 ↔ 原文可互查 |

**生产路径**：UI 上传 → Java Kafka → Python `ingest_file`

---

### 2. 问答编排 — Agentic Routed Flow

```
用户问题
  → B 意图路由（LLM 判：direct | graph_only | vector_only）
  → 分支执行
       direct      → 不检索，直答
       graph_only  → 问句抽实体种子 → Neo4j 多跳 → observation 注入
       vector_only → 混合检索(D) → E 充分性评估 → 不够则 F 图谱补强
  → H 流式作答（SSE，按是否有证据选 system prompt）
```

**AI 介入点**

| 节点 | 智能决策 |
|------|----------|
| B 意图路由 | 闲聊走 direct；关系/流程类走 graph_only；默认 vector_only |
| D 混合检索 | Multi-Query 改写 + HyDE → Qdrant ∥ ES → 双层 RRF → Cross-Encoder 重排 |
| E 充分性 | LLM 判断向量证据是否够答，不够才补图（避免每次都查 Neo4j） |
| F 图谱补强 | 问句驱动查图，与向量检索并行增强、不互相替代 |
| H 生成 | 有/无证据分 prompt，流式 token 输出 |

**入口**：`POST /api/v1/chat/stream` → `routed_astream_chat_events`

---

## 核心亮点

### 1. 真 Agentic，不是固定 RAG 流水线

- **意图路由**：按问题类型选路径，闲聊不浪费检索成本
- **充分性门控**：向量不够才补图，图谱是增强而非必走
- **三分支编排**：direct / graph_only / vector_only 清晰可测、可单独优化

### 2. 混合检索栈较完整

- Multi-Query 改写扩召回
- HyDE 仅走向量库（避免假答案污染 BM25）
- 向量 + ES 并行 → **单 query 内 RRF** → **跨 query RRF** → 重排
- 工业级召回 + 精排组合，不是简单「向量 top-k」

### 3. GraphRAG 与向量 RAG 深度融合

- 入库时自动 LLM 抽三元组，边上存 `chunk_ids` / `doc_ids` / 证据片段
- 问答时两种查图路径：纯图分支 + 向量不足时的补强分支
- chunk 锚定查边：检索命中的 chunk 可关联到具体图谱边

### 4. 工程化友好

| 维度 | 做法 |
|------|------|
| Prompt | 外置 `prompts/text/*.md`，改 prompt 不动 Python |
| 配置 | 环境变量 > `.env` > local.toml > default.toml |
| 部署形态 | CLI / FastAPI SSE / Kafka 消费者，同一套 core |
| 测评 | 独立 `rag_eval` 包 + RAGAS 离线评测 |
| 会话 | Redis 多轮记忆（HTTP 模式） |

### 5. 全栈分工清晰

| 层 | 职责 |
|----|------|
| `juyao-agentic-rag/` | RAG 引擎：入库、检索、编排、GraphRAG |
| `juyao-admin/` | HTTP 代理、Kafka 入库调度 |
| `juyao-ui/` | 对话、文档上传、**图谱可视化/CRUD**（图谱页只管理已有数据，不负责建图） |

---

## 和「普通 RAG」的差异（备忘）

| 普通 RAG | juyao-agentic-rag |
|----------|-------------------|
| 固定：检索 → 生成 | 路由 → 按需检索/查图 → 充分性门控 → 生成 |
| 单一向量库 | Qdrant + ES + Neo4j 三库协同 |
| 图谱可选装饰 | 入库建图 + 问答双路径查图，chunk 级溯源 |
| Prompt 硬编码 | Markdown 外置，迭代快 |

---

## 关键代码入口

| 阶段 | 模块 |
|------|------|
| 入库总管 | `ingestion/pipeline.py` → `ingest_file` |
| 建图 | `graph_writer.py` + `knowledge_graph/extractor.py` + `store.py` |
| 意图路由 | `orchestration/intent_router.py` |
| 对话编排 | `orchestration/routed_flow.py` |
| 混合检索 | `retrieval/retriever.py` → `search_context` |
| 问句查图 | `knowledge_graph/observation.py` |

---

## 延伸阅读

- 仓库文档：`juyao-agentic-rag/docs/ARCHITECTURE.md`、`KNOWLEDGE_GRAPH.md`
- AI 工作区摘要：[[../../AI工作区/会话存档/2026-06-25_RAG与图谱全流程_AI摘要.md]]
- 项目台账：[[../../项目空间/juyao-agentic-rag/overview.md]]

---

*整理自 2026-06-25 对话与代码阅读*
