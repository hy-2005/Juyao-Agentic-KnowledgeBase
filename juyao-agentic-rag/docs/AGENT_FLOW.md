# 整体 Agent 流程图（LightRAG 并行架构版）

> 涵盖 **HTTP 入口 → 闲聊短路 → 双路并行检索（传统向量 + LightRAG 图谱卡片） → 证据审核门 → 流式生成/拒答 → SSE 输出** 与 **入库链路（切块 → 三库写入 → 三元组抽取（含实体简注）→ 卡片同步）** 的完整链路。
> 配套代码：`rag_core/api/routes/chat.py`、`rag_core/application/chat_flow/`、`rag_core/domain/retrieval/`、`rag_core/domain/graph/query/kg_card_search.py`、`rag_core/application/graph/kg_card_sync.py`。
> 创建：2026-08-11 · 更新：2026-08-16（LightRAG 迁移整体重写，旧串行架构文档已废弃，见 LIGHTRAG_MIGRATION_REVIEW.md）

## 0. 用人话说一遍（先看这段再看图）

### 0.1 一句话总览

**用户问了一个问题，系统不再"掂量该查哪路"，而是两路一起查——档案柜翻一遍、人脉图查一遍——然后把两摞材料一起交给一个审核员，审核员说"够答"就流式写答案，说"不够"就直接告诉用户缺什么。**

### 0.2 类比：秘书小聚的工作日常（新版）

小聚桌上还是两样东西：

- 🗄️ **档案柜**——合同、制度、报告原文（Qdrant 向量 + ES 全文）
- 🕸️ **人脉卡盒**——每个实体一张名片（名字+一句话简介），每条关系一张便签（谁—对谁—干了什么，LIGHTRAG 卡片向量库）

老板扔过来一个问题，小聚的新工作流：

| 步骤 | 秘书动作 | 系统对应 |
|---|---|---|
| **1️⃣ 是不是打招呼** | "你好"就直接回礼，不翻任何柜子 | 规则闲聊短路（纯正则，零 LLM） |
| **2️⃣ 两路同时找** | 左手翻档案柜，右手翻卡盒——**同时进行，谁也不等谁** | 并行检索：传统链路 ∥ LightRAG 链路 |
| **3️⃣ 审核员把关** | 把两摞材料一起递给审核员："这些够回答老板吗？" | 证据审核门（LLM：sufficient + missing） |
| **4️⃣ 写答案或明说不够** | 够 → 一边写一边念；不够 → 直说"缺 XX 资料" | 流式生成 ∥ 严格拒答（strict_refusal） |

### 0.3 与旧架构的根本区别（为什么改）

旧架构是**串行接力**：意图路由判断走哪路 → 单路检索 → 判足 → 不足再补另一路。三个问题：

1. **路由判错全盘皆输**——graph_only 判错就漏掉向量证据（P1-2 靠兜底打补丁）
2. **图谱入口太脆**——靠问句实体名三层匹配，换个称呼/改写就漏
3. **补强轮拉高时延**——最差路径 = 路由 + 向量 + 判足 + 补图 + 生成五段串行

新架构并行两路 + 一次审核，时延 = max(两路) + 审核 + 生成；图谱入口换成**卡片向量语义召回**（实体卡/关系卡），称呼怎么换都能按语义命中。

### 0.4 卡盒里的卡片是什么（LightRAG 数据模型）

入库时抽取三元组**顺带**产出两样东西：

- **实体简注（gloss）**：每个实体在当前 chunk 语境下的一句话角色（≤30 字）。同一实体在 82 个 chunk 出现就有 82 条，Neo4j 实体节点的 `summary_hints` 列表**累积去重**（原始审计轨迹）；同时 `summary` 属性由 **LLM 语义合并**维护——每次入库把当前摘要与本批新增 gloss 融合成一段通顺新摘要（`merged_hint_count` 游标保证增量幂等，失败退机械拼接）
- **关系概括（relation_full）**：一句中文概括该断言（不引入文中未出现的事实）——这个字段旧架构就有，直接复用

这两样东西做成**卡片**写进独立向量库 `kg_cards`（每 kb 一个 collection）：

| 卡片 | 向量文本（语义召回用） | payload |
|---|---|---|
| 实体卡 | `实体名 —— 摘要`（hints 合并） | type=entity / name / summary |
| 关系卡 | `头 谓词 尾 —— 摘要`（**必须带头尾，防丢主客**） | type=relation / head / predicate / tail / summary / categories |

Neo4j 是**事实源**（结构 + 全部 hints），kg_cards 是**检索副本**（uuid5 幂等 upsert，漂移可 rebuild）。

## 1. 全局流程图

```mermaid
flowchart TD
    A[HTTP /api/v1/chat/stream] --> B{规则闲聊短路<br/>纯正则}
    B -- 命中 --> Z1[direct：无 KB 人设直接作答]
    B -- 未命中 --> P1[并行 gather]

    subgraph P1 [② 并行双路]
        direction LR
        D[传统链路<br/>改写/HyDE → 向量+BM25<br/>→ 双层RRF → rerank] --> M[merged_docs + Observation]
        L[LightRAG链路<br/>关键词提取(高层+底层)<br/>local: 实体卡→Neo4j一跳<br/>global: 关系卡直检<br/>→ 融合去重 → rerank] --> K[卡片 Observation]
    end

    M --> R{③ 证据审核门<br/>sufficient? missing?}
    K --> R
    R -- "不足 & strict_refusal" --> Z2[拒答：告知缺什么<br/>不调生成 LLM]
    R -- "充足 或 宽松模式" --> F[④ 流式生成 LLM → SSE token]
```

关键点：

- **没有 LLM 意图路由**——route.py 已删除；meta 里的 `route_branch` 值只剩 `direct` / `parallel`（旧枚举值保留仅为消费端兼容）
- **没有补强轮**——两路一次性到位，审核门只做放行/拦截，不做"再去补一路"
- 单路异常不炸穿另一路（`asyncio.gather(return_exceptions=True)`）

## 2. 对话主链各节点

| 节点 | 代码 | 说明 |
|---|---|---|
| 闲聊短路 | `flow._is_chitchat` | 极短问候正则；宁漏勿滥（漏判只是多跑一轮检索） |
| 传统检索 | `steps/retrieve.py` → `domain/retrieval/retriever.search_context` | 与旧版完全一致（见 §3） |
| LightRAG 检索 | `steps/lightrag_retrieve.py` → `kg_card_search.run_kg_card_search` | 见 §4 |
| 证据审核 | `steps/sufficiency.py run_review_step` | LLM 读合并 Observation → `{sufficient, missing}`；heuristic 模式=双路全空才拦；LLM 失败回退 heuristic |
| 拒答 | `flow._stream_refusal_answer` | 固定模板流式输出"缺什么"，不调生成 LLM（`rag_strict_refusal=True` 时生效） |
| 生成 | `steps/finalize.stream_final_answer` | 与旧版一致（system prompt 按证据有无二选一 + 图谱页脚） |

SSE 契约：meta 事件保留旧全部 key（新增 `kg_card_count` / `review_missing`），executed_steps 元素字段不变（新增步骤名 `lightrag_retrieve`，tool 仍为 `query_knowledge_graph`）。

## 3. 传统检索子管线（未改动，摘要）

改写（LLM 多 sub-query，简单问题跳过）→ HyDE 假答案 → 多 query 并行召回（Qdrant 向量 `similarity_search_with_relevance_scores` + ES BM25）→ 双层手写 RRF（单 query 内向量+ES 融合 → 跨 query 融合，rrf_k=60）→ rerank（多 query 精排 + 跨 query rerank-RRF + 同源多样性采样）。详见 RETRIEVAL_REVIEW.md。

## 4. LightRAG 图谱链路（kg_card_search.run_kg_card_search）

```
问题+历史
  → ① 关键词提取（一次 LLM，输出 high_level[] + low_level[]；
     带最近 6 轮历史做共指消解——"那它的税率呢"必须解析出"它"；
     失败/为空 → 双路都用原问句兜底）
  → ② local（底层关键词）
     " ".join(low) 向量检索 kg_cards(type=entity) topk=kg_local_topk
     → 命中实体名为种子 → Neo4j EntityKb{id} 一跳扩展（hops=1）
     → 涉及实体批量读 summary_hints → 边卡=头(描述)—[谓词]→尾(描述)：关系概括+时间
  → ②' global（高层关键词，与 local 并行）
     " ".join(high) 向量检索 kg_cards(type=relation) topk=kg_global_topk
     → 关系卡（payload 自带头/尾/摘要/类别）
  → ③ 融合：实体卡 + local 边卡 + global 关系卡，文本级去重
  → ④ rerank（原问句 × 卡片全文，bge-reranker-v2-m3；失败保留召回序）
     → 取 kg_card_rerank_top_n 张 → Observation 文本
```

- 卡片相似度下限 `kg_card_min_similarity=0.35`（摘要短文本与问句语义距离天然大于原文片段，比 chunk 的 0.5 松）
- collection 不存在（新库未入库）→ 本路安静返回空，向量路不受影响
- global 直检关系卡是**有意偏离 LightRAG 原版**（原版 global 也搜实体）——主题类问题不点名实体，关系卡让主题词直接命中断言本身；代价是关系摘要写得泛时区分度差，评测需分路盯（见 LIGHTRAG_MIGRATION_REVIEW §7）

## 5. 入库链路（ingest.py → graph_writer.py）

```
文件 → 切块（父子模式：父块进 ES/图谱/MySQL，子块进 Qdrant）
  → ① Qdrant（子+父，uuid5(chunk_id) 幂等）
  → ② ES + MySQL 切片表
  → ③ 图谱写入 write_chunks_to_graph：
       每 chunk LLM 抽三元组（含 head_gloss/tail_gloss/relation_full/evidence）
       → Neo4j MERGE：实体节点累积 summary_hints，RELATED 边累积各 hints 列表
       → MySQL 快照增量 upsert_graph_delta（度数/边 + 全部 hints 详情列，
         供前端点击节点/边展示属性，见 GRAPH_DETAIL_PERSIST_REVIEW.md）
       → kg_card_sync.sync_kg_cards：读回 Neo4j 事实源 →
         本批 touched 实体/关系合并摘要 → 批量 upsert kg_cards（best-effort）
  → ④ 先写后删差集清理（文档更新场景）
  → 调度器 mark_dirty → 静默窗口后 MySQL 快照全量同步（校正度数漂移）
```

- 抽取单元 = **父块**（上下文大、LLM 调用少）
- 卡片同步**读回 Neo4j** 而非内存拼接——半成品批次不污染副本
- 文档删除：purge 返回 deleted_edges/deleted_entities 清单 → 对应卡片删除；**幸存实体的 gloss 不回滚**（角色描述非事实断言，可接受）
- 手工改图（管理台 entities/edges 端点）**不自动同步卡片**——编辑后调 `POST /api/v1/admin/graph/kg-cards/rebuild` 全量重建

## 6. 删除与清库路径

| 场景 | 动作 |
|---|---|
| 删文档 | Qdrant/ES/MySQL 按 source_name 删 + Neo4j purge（前缀）→ 卡片按删除清单清理 |
| 文档更新（重传） | 先写后删：新旧 chunk_id 差集 → purge_chunk_ids → 卡片清理 |
| 删知识库 | 删 Qdrant 容器（chunks + kg_cards）+ ES index + Neo4j 标签整片（含存量 CommunityKb{id} 垃圾）+ MySQL 快照表 |

## 7. 图谱卡片同步运维

- `rebuild_kg_cards(kb)`：全图扫描 → 清空 kg_cards → 重写（`POST /api/v1/admin/graph/kg-cards/rebuild?kbId=`）
- 幂等 id：`uuid5("kg_card:{entity:名}")` / `uuid5("kg_card:{relation:头|谓词|尾}")`——同卡重写覆盖不重复
- 社区功能（Leiden 检测/LLM 摘要/Community 节点）**已整体删除**；`/internal/rag/community/*` 三个 URL 保留为快照同步调度的兼容入口（Java RagCommunityController 在调，改路径会 404），`/admin/graph/communities` 恒返回空

## 8. 新增/变更配置一览

| 配置 | 默认 | 说明 |
|---|---|---|
| `kg_card_collection` | kg_cards | 卡片 collection 基名（每 kb 加 `_kb{id}`） |
| `kg_local_topk` / `kg_global_topk` | 8 / 8 | 双路召回数 |
| `kg_card_rerank_top_n` | 6 | 融合后保留卡片数 |
| `kg_card_min_similarity` | 0.35 | 卡片向量召回下限 |
| `kg_card_summary_max_chars` | 400 | 合并摘要截断上限 |
| `kg_keyword_timeout_s` | 15 | 关键词提取 LLM 超时 |
| `rag_strict_refusal` | True | 审核不足时严格拒答（False=旧行为照答，灰度对照用） |
| `graph_sync_debounce_s` | 180 | 快照同步静默窗口（原 community_rebuild_debounce_s 更名） |
| `kg_card_embed_base_url` / `kg_card_embed_model` | 空 | **双模型组**：卡片向量化独立端点/模型（空=跟随主组同源同池） |
| `kg_card_rerank_base_url` / `kg_card_rerank_model` | 空 | 卡片重排独立端点/模型（空=跟随主组） |
| `kg_card_max_concurrency` | 10 | 卡片组独立线程池并发（仅独立端点时生效） |
| `kg_summary_merge_enabled` | True | 实体摘要语义合并开关（False=退机械分号拼接） |
| `kg_summary_merge_batch_size` / `workers` / `timeout_s` | 8 / 3 / 90 | 语义合并 LLM 批大小/并发/超时 |

已删除：`vector_then_graph_supplement`、`intent_route_mode/timeout`、`graph_search_l1_*/l2_*`、全部 `community_summary_*`、`community_rebuild_debounce_s`。

## 9. 遗留与注意

1. **Java/Vue 端社区面板待清理**：Python 侧功能已删，兼容 URL 不炸但面板恒空；后续在 Java/Vue 侧移除入口
2. **多跳能力降级**：local 固定一跳（LightRAG 原版模式），A→B→C→D 长链问题变弱；`query_edges_from_entity_seeds` 留了 hops 参数可升级
3. **实体摘要合并没有 LLM 重写**：机械去重拼接，评测发现质量不足时在 `kg_card_sync._merge_summary` 单点升级
4. **存量库无卡片**：实体/关系摘要不存在，需全量重抽才有——按用户决策走"新库测试、数据不迁移"
