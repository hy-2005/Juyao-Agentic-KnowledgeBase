# 架构速览

> 更多细节见 [GETTING_STARTED.md](./GETTING_STARTED.md)、[KNOWLEDGE_GRAPH.md](./KNOWLEDGE_GRAPH.md)。

## 请求链路（HTTP 对话）

```
POST /api/v1/chat/stream
  → api/routes/chat.py
  → orchestration/chat.astream_chat_events
  → orchestration/routed_flow
  → orchestration/finalize.stream_final_answer
  → SSE: meta → token → done
```

## Routed 流程（默认）

```
用户问题
  → intent_router（B：direct | graph_only | vector_only）
  → graph_only：question_seed → Neo4j 多跳
  → vector_only：retrieval → sufficiency（E）→ 可选 graph 补强（F）
  → finalize：按 had_evidence 选 system prompt → 流式作答
```

| 节点 | 模块 | 含义 |
|------|------|------|
| B | `intent_router` | 判定是否检索、走向量还是图谱 |
| C | `knowledge_graph/query` | 问句驱动查图 |
| D | `retrieval_step` | 混合检索 |
| E | `sufficiency` | 向量证据是否足够 |
| F | `knowledge_graph/query` | 不足时补图 |
| H | `finalize` | 流式生成答案 |

## 入库链路

```
ingestion/pipeline.ingest_file
  → loader → splitter（split_ai + split_spans）
  → indexing/qdrant + indexing/elasticsearch
  → ingestion/graph_writer（可选 Neo4j）
```

`chunk_id` / `source_doc_id` 公约见 `domain/chunk.py`，三处索引共用同一标识。

## 检索链路

```
retrieval/retriever.search_context
  → query_rewrite + HyDE（可选）
  → 向量 + ES 并行 → 单 query 内 RRF（fuse_two_rankings）
  → 跨 query RRF（fuse_query_rankings）
  → reranker（多 query 精排后再融合）
```

HyDE 通道仅走向量库，避免假答案污染 BM25。

## 配置

优先级：环境变量 > `.env` > `config/local.toml` > `config/default.toml`

## Prompt

编辑 `src/rag_core/prompts/text/*.md`，无需改 Python。

## Kafka 异步入库（可选）

```
Java 管理端 / 外部系统 → Kafka topic
  → cli/kafka_consumer → ingestion/pipeline
```

Topic 与 group 见 `config/default.toml` 中 `kafka_*` 项。
