# GraphRAG 知识图谱

在向量 RAG 之外，本引擎支持将文档三元组写入 **Neo4j**，并在问答时通过实体种子做多跳关系查询。

## 链路概览

```
文本 → split_into_chunks → LLM 三元组抽取 → Neo4j MERGE 写入
问句 → 实体种子抽取 → 多跳 Cypher → observation 注入对话上下文
```

向量检索与图谱查询**并行增强**，不互相替代。默认编排见 [ARCHITECTURE.md](./ARCHITECTURE.md) 中的 routed 流程。

## 前置条件

- Neo4j 5.x 已启动（默认 `bolt://localhost:7687`）
- 已配置 `DASHSCOPE_API_KEY`（抽取与问句实体识别共用百炼）
- 若 Neo4j 开启鉴权，在 `.env` 设置 `NEO4J_PASSWORD`

## 配置项

在 `config/default.toml` 或环境变量中：

| 键 | 说明 |
|----|------|
| `neo4j_uri` | Bolt 地址 |
| `neo4j_username` | 用户名（默认 `neo4j`） |
| `graph_query_enabled` | 是否启用图谱查询 |
| `graph_max_hops` | 实体种子多跳上限 |
| `graph_expand_max_edges` | 单次查询返回边数上限 |
| `kg_extract_timeout_s` | 三元组抽取超时 |

Prompt 模板：`src/rag_core/prompts/text/kg_triple_extraction_system.md`

## 构建图谱

### 与向量一同入库（推荐）

```powershell
python -m rag_core.cli.ingest --file src/data/samples/sample_medical.txt
```

默认会写入 Qdrant、Elasticsearch 并抽取三元组到 Neo4j。

### 仅补充图谱

```powershell
juyao-ingest-kg --file src/data/samples/sample_medical.txt
```

对已有 chunk 重新跑抽取，适合调整 Prompt 后重建图谱。

## Neo4j 数据模型

| 元素 | 说明 |
|------|------|
| 节点标签 | `Entity` |
| 关系类型 | `RELATED` |
| 关系属性 | `relation`（自然语言关系动词） |
| 溯源 | `chunk_ids`、`doc_ids`、`source_names` |

同一关系通过 `MERGE` 幂等写入，避免重复膨胀。

## 查询路径

1. **graph_only 分支**：从用户问句抽取实体种子 → `query_edges_from_entity_seeds` 多跳扩展
2. **vector 补强分支**：向量检索后若充分性不足 → 同样走问句驱动查图

chunk 锚定查询（检索命中的 `chunk_id` 关联边）见 `knowledge_graph/edge_queries.py`。

## 关闭图谱

若暂不使用 Neo4j，可设置：

```toml
graph_query_enabled = false
```

或在 `config/local.toml` 中覆盖。入库时可传 `--no-graph` 跳过图谱写入。

## 相关文档

- [GETTING_STARTED.md](./GETTING_STARTED.md) — 环境与 Neo4j 启动
- [ARCHITECTURE.md](./ARCHITECTURE.md) — 编排中 C / F 分支说明
