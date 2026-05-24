# Changelog

本文档记录 juyao-agentic-rag 的重要变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- 混合检索：Multi-Query 改写 + HyDE + 向量 + BM25 + 双层 RRF + Cross-Encoder 重排
- Agentic 对话编排：意图路由、RAG 充分性评估、按需图谱补强
- GraphRAG：LLM 三元组抽取写入 Neo4j，实体种子多跳查询
- FastAPI HTTP 服务：SSE 流式对话 + Redis 会话管理
- Kafka 异步入库消费者
- CLI 入口：入库、图谱构建、命令行问答
- 分层配置：TOML + `.env`，Prompt 外置为 Markdown
- Docker Compose 一键启动全部基础设施

### Supported Formats
- 文档加载：TXT / Markdown / PDF / DOCX / CSV
- LLM 提供方：阿里云百炼 DashScope / OpenAI 兼容接口
- Embedding：Ollama（默认 `mxbai-embed-large`）
- 向量库：Qdrant
- 全文检索：Elasticsearch 7.x
- 图数据库：Neo4j 5.x
- 重排：DashScope / Ollama
