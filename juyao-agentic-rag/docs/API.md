# HTTP API 说明

Python FastAPI 服务默认监听 `http://0.0.0.0:8000`。启动后可在浏览器打开 **http://127.0.0.1:8000/docs** 查看 OpenAPI（Swagger）自动生成的接口列表。

## 设计边界：哪些不在 FastAPI

本仓库采用 **Java 网关 + Python 引擎** 分层，很多你在前端看到的接口并不在 FastAPI 上：

| 能力 | 对外路径（浏览器/前端） | 实际处理方 |
|------|-------------------------|------------|
| 流式对话 | `POST /rag/chat/stream` | Java `RagController` → 转发 FastAPI |
| 会话 CRUD | `GET/POST/PUT/DELETE /rag/sessions...` | Java → 转发 FastAPI |
| 文档上传/列表/删除 | `POST /rag/documents/upload` 等 | **Java** `RagDocIngestController` → Kafka → Python 消费 |
| 命令行入库/问答 | — | **CLI**（`juyao-ingest` / `juyao-rag`），无 HTTP |

因此 FastAPI 接口数量 intentionally 较少：**只负责对话编排 + Redis 会话 + 内部入库 webhook**，不做权限、文件存储、文档登记台账。

```
浏览器 ──► juyao-admin (8080, /rag/*)
              ├─ 对话/会话 ──HTTP──► FastAPI (8000)
              └─ 文档上传 ──Kafka──► juyao-rag-kafka-consumer / internal HTTP
```

## FastAPI 完整接口列表（共 8 个）

### 健康检查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 返回 `{"status":"ok"}` |

### 对话（SSE）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/chat/stream` | 流式对话，SSE 事件：`meta` → `token` → `done` / `error` |

请求体（`ChatStreamRequest`）：

```json
{
  "user_id": "1",
  "session_id": "abc123",
  "message": "用户问题"
}
```

### 会话（Redis）

前缀均为 `/api/v1/chat`：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/sessions` | 创建会话，body: `{"user_id":"..."}` |
| GET | `/sessions?user_id=...` | 列出用户会话 |
| GET | `/sessions/{session_id}/messages?user_id=...` | 历史消息 |
| PUT | `/sessions/{session_id}` | 更新标题，body: `{"user_id":"...","title":"..."}` |
| DELETE | `/sessions/{session_id}?user_id=...` | 删除会话 |

### 内部入库（Java / Kafka 消费者回调）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/internal/rag/ingest/event` | Kafka 事件等价 webhook，需 `X-Internal-Token`（若配置了 `RAG_INGEST_INTERNAL_TOKEN`） |

> **不存在** 公开的 `POST /api/v1/ingest` 文件上传接口；文档二进制由 Java 落盘后通过 Kafka 或上述 internal 接口触发索引。

## Java 网关接口（供前端对照）

`juyao-admin` 的 `RagController` / `RagDocIngestController`（前缀 `/rag`）：

| 方法 | 路径 | 转发目标 |
|------|------|----------|
| POST | `/rag/chat/stream` | FastAPI `/api/v1/chat/stream` |
| GET | `/rag/sessions` | FastAPI `/api/v1/chat/sessions` |
| POST | `/rag/sessions` | FastAPI `/api/v1/chat/sessions` |
| GET | `/rag/sessions/{id}/messages` | FastAPI messages |
| PUT | `/rag/sessions/{id}` | FastAPI 更新标题 |
| DELETE | `/rag/sessions/{id}` | FastAPI 删除 |
| GET | `/rag/documents/list` | MySQL 文档登记 |
| POST | `/rag/documents/upload` | 本地存储 + Kafka |
| DELETE | `/rag/documents` | Kafka 删除事件 |

## 若需要「更多 FastAPI 接口」

当前未暴露、可按需增加的 REST 能力（CLI 已有实现）：

- `POST /api/v1/qa` — 非流式单次问答（调试用）
- `POST /api/v1/ingest/file` — 直传文件入库（绕过 Java/Kafka）
- `POST /api/v1/retrieval/search` — 仅检索、不生成答案

如需其中某项，可在 Issue 中说明使用场景（内网调试 / 独立部署 / 第三方集成）。
