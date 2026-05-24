# 本地启动与测试

本文档帮助你在本机跑通 **最小可用链路**：安装 → 配置 → 启动依赖 → 入库 → 问答。

## 1. 安装

在 `juyao-agentic-rag` 目录下：

```powershell
pip install -e .
```

开发时建议：

```powershell
pip install -e ".[dev]"
```

验证安装：

```powershell
python -m rag_core.cli.qa --help
```

## 2. 配置

```powershell
copy .env.example .env
```

**必填**（使用百炼能力时）：

| 变量 | 说明 |
|------|------|
| `DASHSCOPE_API_KEY` | 阿里云百炼 API Key |

**常用可选**：

| 变量 | 默认 | 说明 |
|------|------|------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Embedding 服务 |
| `QDRANT_URL` | `http://localhost:6333` | 向量库 |
| `ELASTICSEARCH_URL` | `http://localhost:9201` | 全文检索 |
| `NEO4J_URI` | `bolt://localhost:7687` | 知识图谱 |
| `NEO4J_PASSWORD` | — | Neo4j 鉴权密码 |
| `REDIS_URL` | `redis://localhost:6379/0` | 会话（API 模式） |

非密钥项可在 `config/default.toml` 查看；个人覆盖用 `config/local.toml`（参考 `config/local.toml.example`）。

## 3. 启动外部服务

按你的使用场景启动对应组件：

| 组件 | 用途 | 最低要求 |
|------|------|----------|
| Ollama | Embedding | CLI 问答 / 入库 |
| Qdrant | 向量检索 | CLI 问答 / 入库 |
| Elasticsearch | BM25 全文 | 推荐（混合检索） |
| Neo4j | GraphRAG | 可选 |
| Redis | 多轮会话 | 仅 HTTP API |

拉取 Embedding 模型：

```powershell
ollama pull mxbai-embed-large:latest
```

## 4. 导入样例数据

```powershell
python -m rag_core.cli.ingest --file src/data/samples/sample_medical.txt
```

成功后会写入 Qdrant 集合 `juyao_knowledge_chunks`（首次自动创建），并同步 Elasticsearch。

仅构建/补充图谱：

```powershell
juyao-ingest-kg --file src/data/samples/sample_medical.txt
```

详见 [KNOWLEDGE_GRAPH.md](./KNOWLEDGE_GRAPH.md)。

## 5. 问答测试

```powershell
python -m rag_core.cli.qa --question "请简要介绍知识库中关于感冒处理的关键信息"
```

预期输出包含：回答正文、`chunk_id` 引用、检索分数、免责声明。

## 6. 启动 HTTP API（可选）

```powershell
juyao-rag-api
```

默认监听 `http://0.0.0.0:8000`，健康检查：`GET /health`。

FastAPI **共 8 个接口**（对话 + 会话 + 内部入库），Swagger：`http://127.0.0.1:8000/docs`。文档上传不在 FastAPI，而走 Java `/rag/documents/*` → Kafka。详见 [API.md](./API.md)。

流式对话：`POST /api/v1/chat/stream`（SSE）。

## 7. 自检清单

- [ ] `python -m rag_core.cli.qa --help` 正常
- [ ] `.env` 中 `DASHSCOPE_API_KEY` 已设置
- [ ] Ollama、Qdrant 可访问
- [ ] 已执行入库后再问答
- [ ] `pytest` 通过（开发环境）

## 8. 常见问题

**`ModuleNotFoundError: rag_core`**

未 editable 安装，执行 `pip install -e .`。

**Qdrant 连接失败**

检查 `QDRANT_URL` 与服务是否启动。

**Ollama 模型不存在**

执行 `ollama pull mxbai-embed-large:latest`，或修改 `config/default.toml` 中的 `embed_model`。

**百炼 401 / 403**

检查 `DASHSCOPE_API_KEY` 是否有效。

**检索结果为空**

确认已入库，且问题与文档内容相关。集合不存在时，问答会按「无证据」路径返回，执行一次入库即可创建集合。

**Elasticsearch 不可用**

混合检索会降级为仅向量路；建议启动 ES 以获得更好召回。
