# juyao-agentic-rag

<p align="center">
  <strong>通用知识库 RAG 引擎</strong><br>
  混合检索 + Agentic 编排 + GraphRAG · CLI / HTTP API / Kafka 异步入库
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/python-3.10+-green.svg" alt="Python">
  <img src="https://img.shields.io/badge/langchain-1.x-orange.svg" alt="LangChain">
</p>

---

## 功能概览

| 能力 | 说明 |
|------|------|
| 文档入库 | 语义切分（LLM 三层策略 + 规则降级）→ Qdrant + Elasticsearch + 可选 Neo4j |
| 混合检索 | Query 改写、HyDE、向量 + BM25、双层 RRF、Cross-Encoder 重排 |
| Agentic 对话 | 意图路由 → 向量 / 图谱分支 → 充分性评估 → 流式 SSE 作答 |
| GraphRAG | 三元组抽取、实体种子多跳、chunk 锚定查边 |
| 会话记忆 | Redis 多轮历史（HTTP API 模式） |

## 环境要求

- Python **3.10+**
- [Ollama](https://ollama.com/) — Embedding（默认 `mxbai-embed-large:latest`）
- [Qdrant](https://qdrant.tech/) — 向量库（默认 `http://localhost:6333`）
- [Elasticsearch 7.x](http://localhost:9201) — 全文检索（可选但推荐）
- [Neo4j](https://neo4j.com/) — 知识图谱（GraphRAG，可选）
- [Redis](https://redis.io/) — 会话（HTTP API 模式）
- 阿里云百炼 **DashScope API Key** — 对话、切分、图谱抽取、重排

> 推荐使用项目根目录的 `docker-compose.yml` 一键启动基础设施。

## 安装

```powershell
cd juyao-agentic-rag
pip install -e .

# 开发依赖（ruff、pytest）
pip install -e ".[dev]"
```

## 配置

配置优先级（高 → 低）：**环境变量 → `.env` → `config/local.toml` → `config/default.toml`**

```powershell
copy .env.example .env
# 编辑 .env，至少填入 DASHSCOPE_API_KEY
```

非密钥默认值在 `config/default.toml`；本地覆盖可 `copy config\local.toml.example config\local.toml`。

## 快速体验

```powershell
# 1. 确保 Ollama、Qdrant 已启动
ollama pull mxbai-embed-large:latest

# 2. 导入样例
python -m rag_core.cli.ingest --file src/data/samples/sample_medical.txt

# 3. 命令行问答
python -m rag_core.cli.qa --question "请简要介绍知识库中关于感冒处理的关键信息"
```

详细步骤见 [快速启动指南](docs/GETTING_STARTED.md)。

## CLI 命令

| 命令 | 说明 |
|------|------|
| `juyao-ingest` | 向量 + ES（+ 可选 Neo4j）入库 |
| `juyao-ingest-kg` | 仅重建/补充知识图谱 |
| `juyao-rag` | 命令行单次问答 |
| `juyao-rag-api` | 启动 FastAPI 服务（默认 `0.0.0.0:8000`） |
| `juyao-rag-kafka-consumer` | Kafka 消费异步入库 |

等价模块调用：`python -m rag_core.cli.ingest` 等。

## HTTP API

启动服务后访问 **http://127.0.0.1:8000/docs** 查看 Swagger。

```powershell
juyao-rag-api
```

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/api/v1/chat/stream` | SSE 流式对话 |
| POST | `/api/v1/chat/sessions` | 创建会话 |
| GET | `/api/v1/chat/sessions?user_id=` | 会话列表 |
| GET | `/api/v1/chat/sessions/{id}/messages?user_id=` | 历史消息 |
| PUT | `/api/v1/chat/sessions/{id}` | 更新会话标题 |
| DELETE | `/api/v1/chat/sessions/{id}?user_id=` | 删除会话 |
| POST | `/api/v1/internal/rag/ingest/event` | 内部入库 webhook（需 Token） |

> 文档上传/列表/删除走 **Java** `/rag/documents/*`（Kafka 异步入库），不在 FastAPI 暴露。
> 完整接口说明与 Java 网关对照见 [API.md](docs/API.md)。

SSE 事件类型：`meta`（引用与路由元数据）→ `token`（正文）→ `done` / `error`。

## 包结构

```
src/rag_core/
├── core/              # 配置（TOML + .env）、路径常量
├── domain/            # chunk_id / source_doc_id 数据公约
├── llm/               # LLM 工厂、JSON 结构化输出
├── prompts/text/      # System Prompt（Markdown，可直接编辑）
├── ingestion/         # 加载 → 语义切分 → 入库管线
├── indexing/          # Qdrant、Elasticsearch 客户端封装
├── retrieval/         # 混合检索（改写、HyDE、RRF、重排）
├── knowledge_graph/   # Neo4j 三元组抽取与图谱查询
├── orchestration/     # Agentic 对话编排（routed_flow 为默认）
├── memory/            # Redis 多轮会话状态
├── api/               # FastAPI 应用与路由
└── cli/               # 命令行入口
```

架构细节见 [ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 开发

```powershell
ruff check src tests
pytest
```

贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 文档索引

| 文档 | 说明 |
|------|------|
| [GETTING_STARTED.md](docs/GETTING_STARTED.md) | 环境搭建、自检清单、常见问题 |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | 请求 / 入库 / 检索链路 |
| [API.md](docs/API.md) | FastAPI 完整接口与 Java 网关对照 |
| [KNOWLEDGE_GRAPH.md](docs/KNOWLEDGE_GRAPH.md) | GraphRAG 构建与配置 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 开发规范与 PR 流程 |

## 许可证

MIT License — 详见项目根目录 [LICENSE](../LICENSE)。
