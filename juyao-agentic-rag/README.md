# juyao-agentic-rag · 聚耀 RAG 引擎

<p align="center">
  <strong>General-purpose RAG engine with Agentic orchestration + GraphRAG</strong><br>
  Hybrid Retrieval + Agentic Orchestration + Community-First GraphRAG · CLI / HTTP API / Kafka
</p>

<p align="center">
  <strong>通用知识库 RAG 引擎</strong><br>
  混合检索 + Agentic 编排 + 社区优先 GraphRAG · CLI / HTTP API / Kafka 异步入库
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/python-3.10+-green.svg" alt="Python">
  <img src="https://img.shields.io/badge/langchain-1.x-orange.svg" alt="LangChain">
</p>

---

## Features / 功能概览

| Capability | Description |
|-----------|-------------|
| Document ingestion | Structure-aware **parent-child chunking** (LLM 3-layer strategy + rule fallback) → Qdrant + Elasticsearch + optional Neo4j |
| Hybrid retrieval | Query rewrite + HyDE + Multi-Query, vector + BM25, double-layer RRF, Cross-Encoder rerank |
| Agentic chat | Cascade intent routing (rule fast-path → LLM) → vector / graph branches → sufficiency eval → streaming SSE |
| GraphRAG | Triple extraction, **community-first L1/L2/L3 cascade** search (Leiden + summaries), A+B+C query pipeline |
| Layout-aware PDF | PyMuPDF4LLM tables → Markdown, cross-page table merging |
| Session memory | Redis multi-turn history (HTTP API mode) |
| Evaluation | RAGAS toolkit with curated datasets and concurrent scoring |

> 中文：文档入库（父子分块，子块检索→父块生成）；混合检索（改写/HyDE/双层 RRF/重排）；Agentic 对话（级联意图路由→充分性评估→流式 SSE）；GraphRAG 社区优先三级级联；PDF 布局感知解析；Redis 会话；RAGAS 评测。

## Requirements / 环境要求

- Python **3.10+**
- [Ollama](https://ollama.com/) — Embedding (default `mxbai-embed-large:latest`)
- [Qdrant](https://qdrant.tech/) — vector store (default `http://localhost:6333`)
- [Elasticsearch 7.x](http://localhost:9201) — full-text (optional, recommended)
- [Neo4j](https://neo4j.com/) — knowledge graph (GraphRAG, optional)
- [Redis](https://redis.io/) — sessions (HTTP API mode)
- Aliyun Bailian **DashScope API Key** — chat / split / extraction / rerank (OpenAI-compatible)

> 推荐使用项目根目录的 `docker-compose.yml` 一键启动基础设施。Start all infra with the repo-level `docker-compose.yml`.

## Install / 安装

```powershell
cd juyao-agentic-rag
python -m pip install -e ".[dev,eval]"   # dev + eval extras (ruff, pytest, RAGAS)
```

## Config / 配置

Config priority (high → low): **env vars → `.env` → `config/local.toml` → `config/default.toml`** · 配置优先级（高 → 低）。

```powershell
copy .env.example .env
# edit .env — at minimum set DASHSCOPE_API_KEY
```

Non-secret defaults live in `config/default.toml`; local overrides go to `config/local.toml` (copy from `config\local.toml.example`, not committed). 非密钥默认值在 `config/default.toml`，本地覆盖用 `config/local.toml`（不提交）。

## Quick Experience / 快速体验

```powershell
# 1. ensure Ollama + Qdrant are running
ollama pull mxbai-embed-large:latest

# 2. ingest a sample
python -m rag_core.cli.ingest --file src/data/samples/sample_medical.txt

# 3. chat from the CLI
python -m rag_core.cli.qa --question "请简要介绍知识库中关于感冒处理的关键信息"
```

Details: [GETTING_STARTED.md](docs/GETTING_STARTED.md) · 详细步骤见[快速启动指南](docs/GETTING_STARTED.md)。

## CLI Commands / CLI 命令

| Command | Description |
|---------|-------------|
| `juyao-ingest` | Ingest to vector + ES (+ optional Neo4j) |
| `juyao-ingest-kg` | Rebuild / supplement the knowledge graph only |
| `juyao-rag` | Single-shot CLI Q&A |
| `juyao-rag-eval` | Offline RAGAS evaluation (see [docs/eval/](docs/eval/GETTING_STARTED.md)) |
| `juyao-rag-api` | Start the FastAPI service (default `0.0.0.0:8000`) |
| `juyao-rag-kafka-consumer` | Kafka consumer for async ingestion |

Equivalent module calls: `python -m rag_core.cli.ingest`, `python -m rag_eval.cli.main`, etc.

## RAGAS Evaluation / RAGAS 测评

Evaluation code lives in `src/rag_eval/` (sibling of `rag_core`); curated QA datasets are in `src/rag_eval/datasets/`.

```powershell
pip install -e ".[eval]"
juyao-rag-eval --output reports/eval_run.json
```

See [eval getting started](docs/eval/GETTING_STARTED.md) · [workflow](docs/eval/WORKFLOW.md) · [metrics](docs/eval/METRICS.md) · 详见[测评快速启动](docs/eval/GETTING_STARTED.md)。

## HTTP API

Interactive docs at **http://127.0.0.1:8000/docs** (Swagger) · 启动后访问 Swagger 查看。

```powershell
juyao-rag-api
```

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/api/v1/chat/stream` | SSE streaming chat |
| POST | `/api/v1/chat/sessions` | Create session |
| GET | `/api/v1/chat/sessions?user_id=` | List sessions |
| GET | `/api/v1/chat/sessions/{id}/messages?user_id=` | Session history |
| PUT | `/api/v1/chat/sessions/{id}` | Rename session |
| DELETE | `/api/v1/chat/sessions/{id}?user_id=` | Delete session |
| GET | `/api/v1/admin/chunks` · `/stats` · `/{chunk_id}` · `/{chunk_id}/children` | Chunk management (list / stats / detail / parent-child) |
| GET | `/api/v1/admin/graph/*` | Graph admin: stats / communities / entities / edges / subgraph / full |
| POST | `/api/v1/internal/rag/ingest/event` | Internal ingest webhook (token-protected) |
| DELETE | `/api/v1/internal/rag/kb/{kb_id}` | Purge a knowledge base |

> Document upload / list / delete go through the **Java** `/rag/documents/*` API (Kafka async ingestion), not FastAPI. 文档上传/列表/删除走 Java `/rag/documents/*`（Kafka 异步入库）。Full API spec: [API.md](docs/API.md).

SSE event types: `meta` (citations & routing metadata) → `token` (body) → `done` / `error`.

## Package Layout / 包结构

```
src/rag_core/
├── core/              # config (TOML + .env), path constants
├── domain/            # chunk_id / source_doc_id conventions
├── llm/               # LLM factory, JSON structured output
├── prompts/text/      # system prompts (editable Markdown)
├── ingestion/         # load → structure-aware split → index pipeline
├── indexing/          # Qdrant / Elasticsearch client wrappers
├── retrieval/         # hybrid retrieval (rewrite, HyDE, RRF, rerank)
├── knowledge_graph/   # Neo4j extraction, community detection, L1/L2/L3 search
├── orchestration/     # agentic chat flow (routed_flow default)
├── memory/            # Redis multi-turn session state
├── api/               # FastAPI app & routers
└── cli/               # command-line entry points
```

Architecture details: [ARCHITECTURE.md](docs/ARCHITECTURE.md) · 架构细节见 [ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## Development / 开发

```powershell
ruff check src tests
pytest
```

Contribution flow: [CONTRIBUTING.md](CONTRIBUTING.md) · 贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## Docs / 文档索引

| Doc | Description |
|-----|-------------|
| [GETTING_STARTED.md](docs/GETTING_STARTED.md) | Environment setup, self-check list, FAQ |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Request / ingestion / retrieval chains |
| [AGENT_FLOW.md](docs/AGENT_FLOW.md) | Full agentic pipeline incl. GraphRAG L1/L2/L3 cascade |
| [PARENT_CHILD_CHUNKING.md](docs/PARENT_CHILD_CHUNKING.md) | Small-to-Big parent-child chunking design |
| [API.md](docs/API.md) | Full FastAPI spec + Java gateway mapping |
| [eval/](docs/eval/GETTING_STARTED.md) | RAGAS evaluation setup / workflow / metrics |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev conventions & PR flow |
| [README.md](docs/README.md) | Full design-doc index (Chinese) |

## License / 许可证

MIT License — see the repo-level [LICENSE](../LICENSE). MIT License — 详见项目根目录 [LICENSE](../LICENSE)。
