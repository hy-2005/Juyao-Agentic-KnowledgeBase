# JuYao Agentic RAG

<p align="center">
  <strong>面向企业知识库的 Agentic RAG + GraphRAG 开源方案</strong><br>
  混合检索 · 意图路由 · 图谱增强 · 流式对话 · 异步入库
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/python-3.10+-green.svg" alt="Python">
  <img src="https://img.shields.io/badge/langchain-1.x-orange.svg" alt="LangChain">
</p>

---

## 特性

- **混合检索**：向量（Qdrant）+ 全文（Elasticsearch）+ Multi-Query 改写 + HyDE + 双层 RRF + Cross-Encoder 重排
- **Agentic 编排**：意图路由（direct / graph_only / vector_only）、RAG 充分性评估、按需图谱补强
- **GraphRAG**：入库时 LLM 抽取三元组写入 Neo4j，问答时实体种子多跳关系查询
- **工程化**：TOML + `.env` 分层配置，Prompt 外置为 Markdown 可热编辑
- **多接入**：CLI / FastAPI（SSE 流式）/ Kafka 异步入库
- **优雅降级**：LLM 不可用时自动回退到规则；ES 不可用时降级为纯向量检索

## 架构概览

```
用户问题
  → 意图路由（LLM / 规则）
  → 向量检索 + 图谱查询（并行）
  → 充分性评估 → 按需图谱补强
  → 流式 SSE 作答（含引用溯源、免责声明）
```

```
文档入库
  → 加载（TXT/MD/PDF/DOCX/CSV）
  → 语义切分（LLM 三层策略 + 规则降级）
  → Qdrant + Elasticsearch 双写
  → 可选 Neo4j 三元组抽取
```

## 快速开始

### 方式一：Docker Compose（推荐）

```bash
# 1. 启动全部基础设施
docker compose up -d

# 2. 拉取 Embedding 模型
docker exec -it juyao-ollama ollama pull mxbai-embed-large:latest
```

然后按 [引擎文档](juyao-agentic-rag/README.md) 安装 Python 包，即可开始入库与问答。

### 方式二：手动启动

```powershell
cd juyao-agentic-rag
pip install -e .
copy .env.example .env
# 编辑 .env，填入 DASHSCOPE_API_KEY

python -m rag_core.cli.ingest --file src/data/samples/sample_medical.txt
python -m rag_core.cli.qa --question "简要介绍样例文档中的关键信息"
```

完整环境准备见 [快速启动指南](juyao-agentic-rag/docs/GETTING_STARTED.md)。

## 仓库结构

```
juyao-agentic-rag/          # Python RAG 引擎（核心，可独立安装与开源分发）
├── src/rag_core/
│   ├── core/               # 配置（TOML + .env）
│   ├── domain/             # chunk_id 数据公约
│   ├── llm/                # LLM 工厂、JSON 结构化输出
│   ├── prompts/text/       # System Prompt（Markdown，可直接编辑）
│   ├── ingestion/          # 加载 → 切分 → 入库管线
│   ├── indexing/           # Qdrant、Elasticsearch 封装
│   ├── retrieval/          # 混合检索（改写、HyDE、RRF、重排）
│   ├── knowledge_graph/    # Neo4j 三元组抽取与查询
│   ├── orchestration/      # Agentic 对话编排（routed_flow）
│   ├── memory/             # Redis 多轮会话
│   ├── api/                # FastAPI（8 个端点）
│   └── cli/                # 命令行入口
├── config/                 # 默认配置 + local.toml 模板
├── docs/                   # 架构、API、GraphRAG 文档
└── tests/                  # 单元测试
│
juyao-admin/                # Spring Boot 管理端（HTTP + Kafka）
juyao-ui/                   # Vue 前端（知识库对话、文档管理）
juyao-system/               # 系统模块（文档注册表等）
docker-compose.yml          # 一键启动全部基础设施
```

> 只需体验 RAG 能力，进入 `juyao-agentic-rag/` 即可，无需 Java 与 Vue。

## 依赖服务

| 服务 | 用途 | 必需 |
|------|------|------|
| Ollama | Embedding / 本地重排 | 是 |
| Qdrant | 向量检索 | 是 |
| Elasticsearch 7.x | BM25 全文检索 | 推荐 |
| Neo4j 5.x | GraphRAG 知识图谱 | 可选 |
| Redis | 多轮会话记忆 | HTTP API 模式必需 |
| Kafka | 异步入库 | 与 Java 管理端集成时必需 |
| DashScope API | 对话 / 切分 / 图谱抽取 / 重排 | 是（可替换为 OpenAI） |

## 文档

| 文档 | 说明 |
|------|------|
| [引擎 README](juyao-agentic-rag/README.md) | 安装、CLI 命令、配置、HTTP API |
| [快速启动](juyao-agentic-rag/docs/GETTING_STARTED.md) | 环境搭建、自检清单、常见问题 |
| [架构说明](juyao-agentic-rag/docs/ARCHITECTURE.md) | 请求 / 入库 / 检索链路 |
| [HTTP API](juyao-agentic-rag/docs/API.md) | FastAPI 完整接口 + Java 网关对照 |
| [知识图谱](juyao-agentic-rag/docs/KNOWLEDGE_GRAPH.md) | GraphRAG 构建与查询 |
| [贡献指南](juyao-agentic-rag/CONTRIBUTING.md) | 开发规范、改 Prompt、PR 流程 |

## 贡献

欢迎提交 Issue 和 Pull Request。请先阅读 [贡献指南](juyao-agentic-rag/CONTRIBUTING.md)。

## 许可证

本项目基于 [MIT License](LICENSE) 开源。

---

<p align="center">
  <sub>Built with LangChain · Qdrant · Elasticsearch · Neo4j · FastAPI</sub>
</p>
