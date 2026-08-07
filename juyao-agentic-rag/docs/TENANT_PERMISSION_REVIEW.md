# 租户（知识库）与权限评审

> 状态：评审中（待讨论） · 更新：2026-08-07
> 范围：juyao-agentic-rag 租户（知识库 kb）隔离与权限体系（Java 网关 → Python FastAPI → 三库数据）
> 配套代码：`RagController.java`（聊天网关）、`RagDocIngestService.java`（上传/删除）、`RagChatClient.java`（Java→Python HTTP）、`api/routes/chat.py`、`api/routes/ingest.py`（Python API）、`retriever.py`（检索）、`memory/redis_session.py`（会话）、`sql/rag_document_registry.sql`（MySQL 注册表）
> 关联文档：`INGESTION_UPDATE_REVIEW.md`（P0-1 kbId 入库，同一病根）、`RETRIEVAL_REVIEW.md`（检索链路）

---

## 1. 现状架构

```
前端 → Java RagController（若依 Spring Security，登录态 getUserId()）
  → RagChatClient HTTP → Python FastAPI /api/v1/chat/*（无 token，只传 user_id/session_id/message）
  → Python 检索：无 kbId 概念——搜索全局唯一 Qdrant 集合 / ES 索引
入库：Java 上传（kbId 在 Kafka payload 和 MySQL 中都有）→ Kafka → Python（kbId 被丢弃）
```

### 数据模型现状

| 层 | 是否有 kb 维度 | 说明 |
|---|---|---|
| MySQL rag_document_hash | ✅ 有 kb_id + 唯一键 (kb_id, doc_logical_key) | Java 数据库层明确 multi-kb 设计 |
| Kafka payload | ✅ 有 kbId 字段 | Python 未读取 |
| Qdrant / ES chunk | ❌ 无 kb_id 字段 | 单集合/单索引全局 |
| Neo4j | ❌ 无 kb 维度 | source_names 只有文件名 |
| Redis 会话 | 按 user_id 隔离（天然安全） | rag:chat:{user_id}:{session_id} |
| Python 检索 | ❌ 无 | 全集合/全索引搜索 |

---

## 2. 问题清单

### 🔴 P0-1：检索侧租户隔离完全缺失 = 数据越权

- 位置：retriever.py `_vector_topk` / elasticsearch.py `search_elasticsearch`（无 kbId filter）；RagController.java:94 `/chat/stream`（请求无 kbId 字段）
- 问题：A 知识库用户检索的是全库数据；前端选择的知识库不会传给 Python。即使入库侧修好 kbId，检索侧不隔离 = 跨库数据泄露
- 图谱查询同理（Neo4j 无 kb 维度）
- 修复：参数链路全通——前端/Java ChatRequest 加 kbId → RagChatClient 转发 → Python kb_id → 入库 chunk metadata 写 kb_id → 检索时 Qdrant filter / ES term / 图谱前缀过滤

### 🔴 P0-2：入库侧 kbId 被忽略

- 位置：events.py:22（只用 docLogicalKey 当 source_name）；sql/rag_document_registry.sql（MySQL 明确 multi-kb）
- 问题：跨 kb 同名文档互删（详情见 INGESTION_UPDATE_REVIEW P0-1，同一病根）
- 修复：source_name = {kbId}:{logicalKey}，与 INGESTION_UPDATE_REVIEW 合并实施

### 🟡 P1-1：Python API 无鉴权（chat 通道）

- 位置：api/routes/chat.py（零鉴权）；ingest.py:20（有 X-Internal-Token，做得对）；RagChatClient.java:59（调 Python 不带凭据）
- 问题：8000 端口若对外暴露，任何人可直接调 /api/v1/chat/stream 绕过 Java 网关检索全部数据
- 修复：chat/sessions 路由补 X-Internal-Token；Java RagChatClient 配置同 token；生产 8000 不对外（内网/反向代理）

### 🟡 P1-2：kb 级数据权限不存在

- 位置：若依用户/角色/菜单体系仅管"能否登录/传文件"，无"哪个用户能访问哪个知识库"
- 问题：kb 无实体表（rag_document_hash.kb_id 只是字段），无知识库名称/创建人/权限配置；上传接口权限粗粒度
- 修复：kb 实体表（id/name/owner）+ user_kb 授权表（admin/member）；Java 网关校验"当前用户有权访问该 kb"再转发；上传/删除接口加 kb 权限校验

### ✅ 做对的地方：会话隔离安全

- Redis key = rag:chat:{user_id}:{session_id}（redis_session.py:11），Python 用 Java 传入的登录态 userId 拼 key → 跨用户天然不可读；会话标题同理（rag:session_meta:{user_id}）。无需修改

---

## 3. 优化方案（按优先级）

| 优先级 | 改动 | 说明 |
|---|---|---|
| P0-1 | 检索链路通 kbId | 参数链路全通 + chunk metadata 写 kb_id（Qdrant payload + ES source）→ 检索 filter；图谱按 kb 前缀过滤 |
| P0-2 | 入库 kbId 并入 source_name | {kbId}:{logicalKey}，与 INGESTION_UPDATE_REVIEW P0-1 合并实施 |
| P1-1 | Python 全路由鉴权 | chat/sessions 补 X-Internal-Token；Java RagChatClient 配同 token；生产 8000 不对外 |
| P1-2 | kb 实体 + 授权模型 | kb 表（id/name/owner）+ user_kb 授权表（admin/member）；Java 网关校验后转发 |
| P2 | kb 管理 API | 创建/授权/删除知识库（删除时级联清理 Qdrant/ES/Neo4j 索引） |

**本质判断**：单知识库场景可跑（kb_id 默认 0），但任何多知识库/多租户设想（目录 rag/{kb}/、MySQL 表、Kafka payload 已有痕迹）都在 Python 侧断掉。**数据越权是 P0**，入库 kbId 与检索隔离必须一起修——链路贯通：入库写不进 kb_id → 检索时没得过滤。

---

## 4. 待确认事项

1. **前端知识库选择**：前端是否已有知识库切换 UI（kb 列表从哪来——Java 是否有 kb 管理接口）
2. **Python 部署形态**：8000 端口实际暴露方式（宿主机直跑 / 容器 / 反向代理），决定鉴权方案强度
3. **kb 权限粒度**：是否需要角色级（admin 可管理/上传，member 只读）还是仅"用户-库"关联即可
4. **图谱 kb 维度方案**：Neo4j 边加 kb 属性 vs source_name 前缀化（与 INGESTION_UPDATE_REVIEW 的 doc_stable_id 设计一起定）
