# 代码架构评审与重构方案

> 状态：阶段 4/5/6 已实施（目录重组/编排重构/配置分组），阶段 2/3 清理与单测完成 · 更新：2026-08-07
> 范围：juyao-agentic-rag Python 服务（rag_core）架构；Java 侧不动（若依标准结构）
> 前置评审：CHUNK_SPLITTING / RETRIEVAL / GRAPH_QUERY / INGESTION_UPDATE / TENANT_PERMISSION 五份 REVIEW.md
> 关键决策：**不套用 MVC（无 View 层 + Controller 会成上帝类），采用"分层 + 管线"结构**（MVC 精神：职责分离，适配 RAG 流水线形态）；§9 为全部决策定稿

---

## 1. 现状总评

```
api/            网关（FastAPI）
orchestration/  编排（意图→检索→补图→生成）
retrieval/      检索（改写/HyDE/rerank/RRF）
knowledge_graph/ 图谱（抽取/查询）
ingestion/      入库（loader/splitter/pipeline）
indexing/       存储适配（qdrant/es）
llm/  memory/  domain/  core/  cli/  rag_eval/
```

依赖方向基本单向（api → orchestration → retrieval/knowledge_graph → indexing/llm），**分层骨架合理，不需要推倒重来**。乱在层内。

## 2. 乱点清单（有代码证据）

| # | 问题 | 证据 |
|---|---|---|
| A | 切分三件套命名无法自解释 | splitter.py（入口）/ split_ai.py（LLM）/ split_spans.py（算法） |
| B | re-export 空壳误导 | knowledge_graph/query.py 只有 __all__ 转发，实现全在 edge_queries.py |
| C | 两个"实体抽取"命名不对齐 | extractor.py（入库）vs question_seed.py（查询） |
| D | 双入口并存（两代实现） | qa.py（单轮遗留？）vs chat.py→routed_flow.py（多轮） |
| E | 编排单函数膨胀 | routed_astream_chat_events 270 行：分支×4、状态变量×8、日志+元数据全塞一起 |
| F | 死代码/遗留未清理 | _legacy/legacy_planner.py、build/lib/、__pycache__、.ruff_cache；query_edges_for_chunks 与 build_graph_observation_text 无调用方（后者待接线） |
| G | 检索逻辑住在错误的包 | search_elasticsearch 在 indexing/（indexing 应只放写入） |
| H | 配置 70+ 字段平铺 | Settings 无嵌套分组，找配置靠猜前缀 |
| I | LLM 调用失控 | 一次问答最多 6-7 次 LLM 调用，决策点分散在 intent_router/sufficiency/graph_route，无统一决策轨迹 |

---

## 3. 为什么不用 MVC（用户提议，结论：核心精神可取，形态不适配）

1. **View 层无物可放**：输出是 SSE 流，无页面渲染，硬拆 views/ 只会有空壳
2. **Controller 变上帝类**：编排逻辑全塞 Controller = 现在的 270 行单函数换个名字
3. **RAG 本质是流水线不是 CRUD**：入库管线 + 问答管线，适合"分层 + 管线"模式

---

## 4. 目标架构：分层 + 管线

```
rag_core/
├── api/                    # 接口层（= Controller，薄路由，只做转发）
│   ├── routes/             # chat.py / ingest.py / sessions.py（保持）
│   └── schemas.py
│
├── application/            # 应用服务层（= Service，编排归属地）
│   ├── chat_flow/          # 问答管线 ← 现 orchestration/ 拆出
│   │   ├── flow.py         #   FlowState + 步骤管线（替代 routed_flow.py 单函数）
│   │   ├── state.py        #   FlowState 数据类
│   │   └── steps/          #   每步一个文件：
│   │       ├── route.py            # 意图路由
│   │       ├── retrieve.py         # 向量检索
│   │       ├── sufficiency.py      # 充足性判断
│   │       ├── graph_supplement.py # 图谱补充
│   │       └── finalize.py         # 生成
│   └── ingest_flow/        # 入库管线 ← 现 ingestion/pipeline.py 拆出
│       ├── ingest.py       #   文档入库编排（步骤表驱动）
│       └── update.py       #   更新/增量/删除编排
│
├── domain/                 # 领域层（= Model，纯业务逻辑，无 IO 编排）
│   ├── chunking/           #   切分：splitter / semantic_splitter / span_utils
│   ├── retrieval/          #   检索：retriever / fusion / hyde / query_rewrite / reranker
│   ├── graph/              #   图谱：extract（入库抽取）/ query（查询）/ schema
│   ├── llm/                #   模型调用：factory / json_client / embeddings
│   └── memory/             #   会话逻辑（redis 客户端注入）
│
├── infrastructure/         # 基础设施层（IO 适配）
│   ├── qdrant.py           # ← 现 indexing/qdrant.py
│   ├── elasticsearch.py    # ← 现 indexing/elasticsearch.py（只放写入，检索挪 domain）
│   ├── neo4j.py            # ← 现 knowledge_graph/store.py
│   ├── redis.py            #   redis 客户端封装
│   └── kafka.py            #   消费/生产封装
│
├── core/                   # 配置（嵌套分组）、常量、路径
├── cli/                    # 运维入口（保持）
└── rag_eval/               # 评测（保持独立）
```

依赖方向：`api → application → domain → infrastructure/core`。

## 5. 问答管线拆法（核心设计）

```python
# application/chat_flow/state.py
@dataclass
class FlowState:
    question: str
    history: list[dict]
    route: RouteBranch | None = None
    intent_backend: str = ""
    merged_docs: dict[str, Document] = field(default_factory=dict)
    max_score: float = 0.0
    graph_snapshots: list[dict] = field(default_factory=list)
    observation_lines: list[str] = field(default_factory=list)
    executed_steps: list[StepRecord] = field(default_factory=list)
    had_evidence: bool = False
    stop_reason: str = ""

# application/chat_flow/flow.py
async def run_chat_flow(question, history, ...):
    state = FlowState(question=question, history=history)
    route_question(state)                      # 步骤 1：意图路由
    if state.route == RouteBranch.DIRECT:
        pass
    elif state.route == RouteBranch.GRAPH_ONLY:
        await graph_query_flow(state)          # 步骤 2a：纯图谱
        if not state.had_graph_edges:
            await vector_retrieve(state)       # 兜底：图谱未命中降级向量（顺带修复 P1-2）
    else:
        await vector_retrieve(state)           # 步骤 2b：向量检索
        evaluate_sufficiency(state)            # 步骤 3：充足性判断
        if state.needs_graph:
            await graph_supplement(state)      # 步骤 4：图谱补充（chunk 锚定优先）
    await finalize(state)                      # 步骤 5：生成
    yield from stream_meta_and_tokens(state)
```

**顺带解决三个历史问题**（重构时一起做）：
1. chunk 锚定接线（GRAPH_QUERY_REVIEW P0-1）：graph_supplement 先走 query_edges_for_chunks(向量命中 chunk_ids)，无结果再问句实体
2. graph_only 兜底（GRAPH_QUERY_REVIEW P1-2）：图谱 0 边自动降级向量
3. 决策轨迹结构化：executed_steps 升级 StepRecord（步骤名/工具/状态/输入输出摘要/耗时），SSE meta 输出

## 6. 入库管线拆法

```python
# application/ingest_flow/ingest.py
async def ingest_document(kb_id, path, sha, ...):
    steps = [
        ("load", load_document),        # 解析
        ("split", split_into_chunks),   # 切分
        ("vector", write_qdrant),       # 向量
        ("bm25", write_es),             # 全文
        ("graph", write_graph),         # 图谱（增量 skip）
        ("purge", purge_old),           # 旧数据清理（先写后删，修复 P0-2）
    ]
    for name, step in steps:
        record = await run_step(step, state)   # 统一错误处理 + 记录
    return state.summary()
```

同一套"步骤管线"模式，问答/入库共用，架构一致；顺带实现 INGESTION_UPDATE_REVIEW 的"先写后删 + chunk 级 skip"。

## 7. 迁移步骤

| 阶段 | 内容 | 风险 | 前置 |
|---|---|---|---|
| 0 | 跑基线评测（rag_eval） | - | - |
| 1 | 功能 P0 修复（chunk 大小、长文档分批、kbId 贯通） | 中 | 评测基线 |
| 2 | 纯清理：删 _legacy/build/pycache，补 .gitignore | 零 | - |
| 3 | 补核心单测（span 切分、判重、purge 语义） | 零 | - |
| 4 | 目录重组（机械 move + 改 import，行为不变） | 低 | 单测兜底 |
| 5 | 编排重构（chat_flow / ingest_flow + 3 个顺带修复） | 高 | 单测 + 阶段 1 稳定 |
| 6 | 配置嵌套分组（pydantic 嵌套模型 + alias 兼容） | 低 | - |
| 7 | 再跑评测对比 | - | - |

关键原则：**功能修复（阶段 1）先于架构重构（阶段 5）**——先修功能再动结构，避免一次改两件事分不清问题归属。

## 8. 明确不做的

- 不拆微服务（单服务 + Kafka 解耦足够）
- 不做 async 全面化（入库线程池、问答 async，混合合理）
- domain 层不引 FastAPI/配置（依赖方向单向）

## 9. 架构决策定稿（2026-08-07 已拍板）

### 决策 1：chat_flow 步骤粒度 = 6 步，与流程图节点对齐

步骤与既有流程图节点 B/C/D/E/F/G/H 一一对应，**不引入新抽象**：
- route（B）→ graph_query（C，复用 graph_supplement 的问句实体路径）/ retrieve（D）→ sufficiency（E）→ graph_supplement（F，chunk 锚定优先 + 问句实体兜底，双路径）→ finalize（H）
- graph_only 分支不单独建步骤文件，复用 graph_supplement 的核心查询函数 + 0 边时降级 retrieve

### 决策 2：llm/ 放 infrastructure，domain 允许务实豁免

- `llm/`（factory / json_client / embeddings / validators）→ `infrastructure/llm/`——模型调用是 IO 适配（HTTP、API key、超时重试）
- **不引入协议抽象/依赖注入框架**（过度设计）
- **务实豁免**：domain 层允许 import infrastructure.llm（semantic_splitter、extractor 本质是"调用外部模型的切分/抽取服务"，Python 项目常见务实做法）；豁免只限 llm 适配，其余 infrastructure 组件 domain 不得引用

### 决策 3：memory 不拆，整体搬 infrastructure/redis/

redis_session 逻辑简单（消息组装 + 轮次裁剪 + TTL），拆"业务逻辑/客户端"收益小成本高——整体搬到 `infrastructure/redis/session.py`，domain/memory 目录规划取消。

### 决策 4：qa.py 删除，cli/qa.py 改造

- 已确认调用方：orchestration/qa.py 只被 cli/qa.py 调用；rag_eval 用 search_context（不受影响）
- 决策：**删 orchestration/qa.py**（单轮非流式旧实现，无意图路由/补图能力，是双入口混乱源）
- cli/qa.py 改为调用 chat_flow（同步收集流式结果），保留单轮调试能力

### 决策 5：配置嵌套分组 + alias 兼容

- Settings 拆嵌套模型：ChunkSettings / RetrievalSettings / GraphSettings / KafkaSettings / LLMSettings / RagSettings
- 兼容：字段用 `validation_alias=AliasChoices("chunk.size", "chunk_size")`——旧配置（env/toml 平铺 chunk_size）和新配置（chunk.size）都能读，零行为变化
- 代码访问：阶段 6 先保留顶层兼容 property，调用点后续逐步迁移

### 决策 6：依赖铁律 + 检查机制

- `api → application → {domain, infrastructure}`；domain 不 import application/api；infrastructure 不反向依赖上层
- 阶段 4 后加 **import 方向检查测试**（scripts/check_import_dirs.py 或 pytest 单测，AST 扫 import 方向，零第三方依赖），防回归

---

## 10. 完整文件映射表（阶段 4 执行清单）

| 现在 | 目标 |
|---|---|
| ingestion/splitter.py | domain/chunking/splitter.py |
| ingestion/split_ai.py | domain/chunking/semantic_splitter.py |
| ingestion/split_spans.py | domain/chunking/span_utils.py |
| ingestion/loader.py | infrastructure/loaders.py（读文件/PDF/docx 是 IO 适配） |
| ingestion/pipeline.py | application/ingest_flow/ingest.py |
| ingestion/events.py | application/ingest_flow/events.py |
| ingestion/hash_guard.py | application/ingest_flow/hash_guard.py（判重是编排规则） |
| ingestion/cleanup.py | application/ingest_flow/cleanup.py（三库删除编排） |
| ingestion/graph_writer.py | application/ingest_flow/graph_writer.py |
| indexing/qdrant.py | infrastructure/qdrant.py |
| indexing/elasticsearch.py | infrastructure/elasticsearch.py（只留写入）；检索函数 → domain/retrieval/bm25.py |
| knowledge_graph/client.py | infrastructure/neo4j.py（与 store.py 合并） |
| knowledge_graph/store.py | infrastructure/neo4j.py（合并） |
| knowledge_graph/query.py | 删（re-export 移入 knowledge_graph 目标包的 __init__） |
| knowledge_graph/cypher.py | domain/graph/query/cypher.py |
| knowledge_graph/edge_queries.py | domain/graph/query/edge_queries.py |
| knowledge_graph/edge_view.py | domain/graph/query/edge_view.py |
| knowledge_graph/observation.py | domain/graph/query/observation.py |
| knowledge_graph/question_seed.py | domain/graph/query/question_seed.py |
| knowledge_graph/extractor.py | application/graph/extractor.py（LLM 抽取服务） |
| knowledge_graph/schema.py | domain/graph/schema.py |
| retrieval/* | domain/retrieval/*（保持子文件不变） |
| llm/* | infrastructure/llm/* |
| memory/redis_session.py | infrastructure/redis/session.py |
| orchestration/chat.py | application/chat_flow/entry.py |
| orchestration/routed_flow.py | application/chat_flow/flow.py（重构） |
| orchestration/intent_router.py | application/chat_flow/steps/route.py |
| orchestration/retrieval_step.py | application/chat_flow/steps/retrieve.py |
| orchestration/sufficiency.py | application/chat_flow/steps/sufficiency.py |
| orchestration/graph_route.py | application/chat_flow/steps/graph_supplement.py（合并） |
| orchestration/finalize.py | application/chat_flow/steps/finalize.py |
| orchestration/observations.py | application/chat_flow/observations.py |
| orchestration/history.py | application/chat_flow/history.py |
| orchestration/constants.py | application/chat_flow/constants.py |
| orchestration/types.py | application/chat_flow/state.py（合并 FlowState） |
| orchestration/qa.py | 删（见决策 4） |
| orchestration/_legacy/ | 删 |
| core/config.py | core/config.py（嵌套分组，见决策 5） |
| cli/* | cli/*（保持，调用 application 层） |
| rag_eval/* | 保持独立（不归 rag_core 管） |
