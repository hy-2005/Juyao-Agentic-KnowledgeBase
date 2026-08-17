# LightRAG 迁移方案（评审）

> 状态：🔄 进行中（P0 入库侧 / P1 检索侧 / P2 拆旧已实施并通过单测 69 项；P3 新库实测与 RAGAS 评测待跑）
> 创建：2026-08-16 · 更新：2026-08-17
> 关联：[AGENT_FLOW.md](AGENT_FLOW.md)（已重写为新架构流程图）、[GRAPH_QUERY_REVIEW.md](GRAPH_QUERY_REVIEW.md)（旧图谱设计，L1/L2/L3 级联已废弃）、[COMMUNITY_SYNC_REVIEW.md](COMMUNITY_SYNC_REVIEW.md) / [COMMUNITY_ENHANCEMENT_REVIEW.md](COMMUNITY_ENHANCEMENT_REVIEW.md)（社区方案已整体废弃）、[PITFALLS.md](PITFALLS.md)

## 0. 实施结论（2026-08-16）

- **P0/P1/P2 全部落码**，`tests/` 64 项单测通过；改动清单见 §10 状态列
- 需求方拍板：社区**全删**（兼容 URL 保留防 Java 404）；存量数据**不迁移**，新开知识库测试重新生成；`rag_strict_refusal` 默认 True（按原始需求"不齐不回答"）
- 待验证（P3）：新库入库跑通卡片双写 → 对话实测双路并行/拒答 → RAGAS 对照（qa100）
- **2026-08-16 补充**：① 实体摘要升级为**语义合并**（Entity.summary 由 LLM 融合"旧摘要+新 gloss"，merged_hint_count 游标增量幂等，失败退机械拼接）；② 新增**双模型组**（kg_card_embed/rerank 独立端点**或独立模型名**任一配置即独立并发池，与传统链路不争抢；服务器已在 swarp_config_amd.yaml 补 `bge-m3-Q8_0-card` / `bge-reranker-v2-m3-Q8_0-card` 双实例，复用同一 GGUF、独立 llama-server 进程）；③ 卡片检索全链路日志（召回/展开/融合/重排逐段）。部署踩坑：docker compose v5 的 `config` 需显式 `--profile` 才激活 default profile 服务，否则依赖检查误报 undefined
- **2026-08-17 补充（异步合并定稿）**：④ 摘要合并**异步化**（`kg_summary_merge_async=true`，✅ 已实施）：入库同步路径只投递队列立即返回，卡片先写拼接占位摘要（可检索）；后台 `summary_merge_worker` 用专用 **mini 模型**（`kg_summary_merge_model=local_Qwen3-30B-A3B-mini`，服务器条目已调小 ctx 32768→16384）**10 并发独立池**消费：读 Neo4j 最新 → LLM 融合 → 写回 summary+游标 → 覆盖更新实体卡。可靠性：pending set 实体级去重（批量上传 N 文档只融合一次）+ merged_hint_count 游标幂等 + 首次投递前全库 catchup 补投（重启兜底）。`rebuild_kg_cards` 保持同步合并（管理端低频手动，期望"重建完即最新"）。新增测试 5 项（tests/test_summary_merge_worker.py），全套 69 项通过。⚠️ 实测发现 `chat_template_kwargs.enable_thinking` 在 llama-swap 层**不生效**（主模型请求狂吐 6000+ reasoning token，单请求 3~9 分钟），详见 [PITFALLS.md](PITFALLS.md) #32；mini 是否同样不生效待服务器实测（本地代码已下发该字段）

## 1. 背景与动机

现行对话主路是**串行链**：意图路由 → 图谱/向量分支 → 判足（sufficiency）→ 图谱不足补强（P1-2 vector fallback）→ 生成。图谱侧对比 LightRAG 存在两个结构性缺口（2026-08-12 讨论结论）：

1. **实体零描述**：Entity 节点只有 name，实体级语义信息全靠社区摘要间接承载；"介绍下 XX 实体"类问题偏弱
2. **无语义级图检索入口**：图定位靠实体名三层匹配（精确/归一化/子串），改写或换个称呼就漏

本方案将图谱侧重构为 **LightRAG 设计模式**（自研借鉴，不引入 LightRAG 库），并与传统 RAG 检索**并行**执行，砍掉串行补强链。

### 与现状的关键差异

| 维度 | 现行 | 目标 |
|---|---|---|
| 执行模型 | 路由决策 → 单路 → 判足 → 串行补强 | 传统 + LightRAG **并行**，无补强 |
| 前置路由 | LLM 意图路由（route.py） | 删除；仅保留规则级闲聊短路 |
| 图检索入口 | 实体名匹配 + 社区摘要向量（L1） | 实体/关系卡片向量库（local + global 双路） |
| 实体信息 | name-only 节点 | 实体摘要（summary_hints 累积） |
| 证据不足 | 有什么答什么（had_evidence 即答） | 审核大模型把关，不齐**拒答并告知** |
| 图扩展 | 多跳（graph_max_hops=4） | 一跳（LightRAG 原版模式，hops 参数保留升级空间） |

## 2. 设计前提（已与需求方对齐）

1. **自研借鉴而非引入 LightRAG 库**：库自带存储层，与"实体映射回 Neo4j 一跳"直接冲突；沿用现有 Neo4j 标签隔离 + Qdrant 每库 collection 栈
2. **抽取单元 = 父块**：现行图谱抽取已跑在父块上（`ingest.py:150` → `write_chunks_to_graph(chunks=chunks)`，父子模式下 chunks 即父块），无需改动
3. **关系摘要复用现有 `relation_full`**，不新抽字段；实体摘要是**新增**能力
4. **摘要是摘要，不是原文**：新向量库存摘要（供检索）；evidence/modality/time/location 等 hints 体系保留在 Neo4j（防幻觉锚定，与检索用途不冲突）
5. **不齐不回答**：审核不过即拒答（工程上做成 `strict_refusal` 开关，灰度对照用）

## 3. 目标架构

```
用户问题（含会话历史）
 ├─ 并行 ─ 传统链路：query 改写/HyDE → Qdrant向量+ES BM25 → 双层RRF → rerank → chunks
 └─ 并行 ─ LightRAG 链路：
       关键词提取（LLM，一次产出高层+底层两组；多轮对话带历史做共指消解）
       ├─ local：底层关键词 → 卡片VDB(type=entity) topk 实体
       │         → Neo4j EntityKb{id} 一跳 → 实体卡 + 边卡（头尾实体描述+关系摘要）
       └─ global：高层关键词 → 卡片VDB(type=relation) topk → 关系卡（payload 自带 head/tail/摘要）
       两路融合去重 → rerank（用拼接全文，防锚定丢失）
两路汇合 → 审核大模型（证据齐全？）─ 否 → 拒答并告知缺什么
                                  └ 是 → 生成回答（SSE 流式）
```

延迟结构：`max(传统路, LightRAG路) + 审核 + 生成`，替代现行"路由→单路→判足→补强→生成"的最差串行路径。

## 4. 入库侧设计（P0）

### 4.1 抽取 prompt 增字段

`prompts/text/kg_triple_extraction_system.md` 每个三元组新增两个可选字段：

- `head_gloss` / `tail_gloss`：头/尾实体的一句话简注（≤30 字，只描述该实体在此断言语境下的角色，不引入文中未出现的事实）

输出 token 增幅预计 ~30%（`ingest_graph_workers=3` 的 MiniMax 并发限制不变）。`schema.py` 的 `Triple` dataclass 与 `parse_triples` 同步扩字段。

### 4.2 Neo4j：实体摘要累积（沿用 hints 模式）

Entity 节点新增 `summary_hints: list[str]` 属性，写入走 `neo4j.py:46` `_upsert_related_batch_query` 的 ON CREATE/ON MATCH SET 追加模式（与 evidence_snippets 等完全同构，纯模板扩展）。同一实体跨 chunk 的多份 gloss 自动累积去重。

### 4.3 新向量库：实体/关系卡片

**单一 collection + `type` 元数据区分**（需求方明确要求元数据标识），每 kb 一个物理容器：

- 命名：`kg_cards`（基名）→ `kg_cards_kb{id}`，复用 `config.py:234` 的 `chunk_collection` 命名函数模式，新增 `kg_card_collection(kb_id)`
- Qdrant payload 建 `type` 字段的 payload index（否则过滤全扫）

**记录结构**（向量文本是防"丢主客"的关键设计，见 §5.3）：

| type | 向量文本 | payload |
|---|---|---|
| entity | `{实体名} —— {实体摘要}` | type/name/summary/kb_id |
| relation | `{头实体} {谓词} {尾实体} —— {关系摘要}` | type/head/predicate/tail/summary/categories/kb_id |

**幂等 id**：`uuid5(entity_name)` / `uuid5(head|predicate|tail)`——直接复用 `qdrant.py:238` 社区摘要的 uuid5 upsert 成熟模式（同记录重建覆盖而非重复）。

### 4.4 双写一致性

- **Neo4j 是事实源**：结构（节点/边）+ 完整 hints + summary_hints 全在 Neo4j
- **卡片 VDB 是检索副本**：文档入库完成后（`write_chunks_to_graph` 返回后），从 Neo4j **读回**本批 touched 实体的 summary_hints + touched 关系的 relation_full_hints，合并成摘要文本，批量 embed + upsert（读回而非内存拼接，保证与事实源一致）
- VDB 写失败 best-effort（warn 不阻断入库，与社区摘要同策略）；提供按 kb 全量 rebuild 命令兜底
- 删除路径：`purge_document_edges` / `purge_chunk_ids` 清理后，同步删除对应孤儿卡片（或 rebuild 重建）

### 4.5 存量迁移

实体/关系摘要在存量库中不存在，**每个库需全量重跑图谱抽取**（重写 Neo4j 图谱 + 重建卡片 VDB）。借社区重建的批量模式（暂停调度 + 手动触发）执行。

## 5. 检索侧设计（P1）

### 5.1 关键词提取（替代原意图路由的 LLM 调用）

一次 LLM 调用产出 `{high_level: [...], low_level: [...]}` 两组关键词（LightRAG keyword extraction 模式）：

- 底层 = 具体实体/名词（喂 local）；高层 = 主题/概念（喂 global）
- **多轮对话必须带会话历史**做共指消解（"那它的税率呢？"→ 解析出实体），否则并行架构下第二轮起图谱路全空
- 超时/失败降级：退化为直接用原句同时当高层+底层关键词检索

### 5.2 local 链路

1. 底层关键词 → 卡片 VDB `type=entity` 向量检索 topk（参数 `kg_local_topk`）
2. 命中实体名映射回 Neo4j（`EntityKb{id}` 标签隔离不变；实体名三层解析 `resolve_entity_names` 保留作归一化对齐，不再是唯一入口）
3. 一跳扩展（复用 `cy_expand_from_seeds`，hops=1）
4. 组装上下文卡：每条边 = 头实体描述 + 谓词 + 尾实体描述 + 关系摘要（全部来自 Neo4j hints 合并文本）

### 5.3 global 链路（有意偏离 LightRAG 原版，自创路线）

原版 global 也是搜实体描述再取命中实体集合内部的边；本方案**直接对关系卡片做向量检索**——主题类问题（"这份文件的核心政策是什么"）往往不点名实体，实体路召不回，关系直搜让主题词直接命中主题内容。

代价与对策：

- **锚定问题**：只 embed 关系摘要会丢主客（三条"补贴标准提高了"向量几乎重合，无法区分财政部→芯片企业 vs 地方政府→制造业）。对策 = §4.3 的拼接全文向量文本，rerank 也用全文（只 rerank 摘要会在 rerank 阶段复发锚定丢失）
- 摘要写得越泛（"双方达成合作"）区分度越差 → 抽取 prompt 要求摘要具体化；评测单独盯 global 路（§7）

### 5.4 融合与重排

- 去重 key：`(head, predicate, tail)`（payload 取）
- local 边卡与 global 关系卡合并去重 → rerank（复用现有 bge-reranker-v2-m3 基建，重排文本 = 拼接全文）→ 取 `kg_card_rerank_top_n`
- LightRAG 卡片与传统 chunks **各自保序拼接**进审核上下文（跨类型不做统一 RRF——chunk 与卡片语义密度不同，混排无意义），总量设上限防 prompt 膨胀

### 5.5 审核大模型（sufficiency 重定义）

- 输入：传统 chunks + LightRAG 卡片合并上下文
- 输出：`{sufficient: bool, missing: "缺什么的自然语言描述"}`
- 不过 → 拒答并告知缺什么（`strict_refusal` 开关，默认开；关闭时退回"有什么答什么"旧行为，供灰度对照）
- 复用 `rag_sufficiency_timeout_s` 配置与 heuristic 降级模式骨架

### 5.6 规则级闲聊短路

LLM 意图路由删除后，"你好"类问题会全量跑两路再被拒答——体验不可接受。保留**纯规则** DIRECT 短路（问候/身份正则，零 LLM 调用）在 flow 最前置。

## 6. 拆旧与兼容（P2）

| 对象 | 处置 |
|---|---|
| `chat_flow/steps/route.py` | 删除 LLM 意图路由；规则闲聊短路迁入 flow 前置 |
| `chat_flow/steps/sufficiency.py` | 重写判据（§5.5，合并上下文审核） |
| `chat_flow/steps/graph_query.py` + `graph_search.py`（L1/L2/L3 级联） | 废弃，由 §5 双路替代 |
| `community_search.py`（L1 社区向量检索） | 待拍板（§8 决策 4）：保留作第三路或废弃 |
| `chat_flow/flow.py` 分支链 | 重写为并行模型（asyncio.gather / 线程池） |
| `state.py` | RouteBranch/had_graph_edges 等字段随链路重定义 |
| **SSE 事件契约** | observation_lines/sources 事件字段需保持兼容（Java admin 在消费），或同步改 Java 侧——实施前用 `scripts/diff_sse_contract` 对比快照 |
| `AGENT_FLOW.md` | P2 落地后同步重写流程图（CLAUDE.md 文档同步规则） |

## 7. 评测（P3）

1. **RAGAS 对照**：`qa100.jsonl` 跑 现行串行架构 vs 新并行架构 全量对比
2. **local/global 分路打分**：分别只开单路跑评测，global 路质量不被 local 路掩盖（§5.3 代价验证）
3. **拒答口径**：拒答样本的 faithfulness/answer_relevancy 打分规则单独定义（sufficient=false 时答案即拒答文本）
4. **时延**：P50/P95 对比（并行模型的理论收益验证）
5. 落盘 `docs/eval/RESULTS_*.md`

## 8. 决策表（2026-08-16 需求方已拍板）

| # | 问题 | 结论 | 状态 |
|---|---|---|---|
| 1 | 实体摘要合并策略 | gloss 抽取 → Neo4j hints 累积 → 文档级读回合并 upsert（§4 设计，机械合并非 LLM 重写） | ✅ 已实施 |
| 2 | 关系卡片向量文本 = 头+谓词+尾+摘要 拼接 | 是（锚定问题，§5.3） | ✅ 已实施 |
| 3 | 社区摘要（L1 那套）保留还是废弃 | **全删**（兼容 URL 保留防 Java 404；MySQL 社区表保留列不写入） | ✅ 已实施 |
| 4 | 存量库迁移 | **不迁移**——新开知识库测试重新生成 | ✅ 按用户决策 |
| 5 | `strict_refusal` 默认值 | **True**（按原始需求"不齐不回答"）；False 可灰度对照 | ✅ 已实施 |
| 6 | SSE 契约兼容 or 同步改 Java | 字段兼容：meta 旧 key 全保留（新增 kg_card_count/review_missing），executed_steps 字段不变 | ✅ 已实施 |

## 9. 风险清单

1. **存量重抽成本**：每库全量重跑抽取（LLM token + 时间），MiniMax 3 并发限制下单库耗时可观
2. **双写一致性**：卡片 VDB 与 Neo4j 是两份派生数据，项目先例（社区摘要 best-effort）已踩过漂移坑；靠"读回事实源再写副本 + rebuild 兜底"控制
3. **global 路质量依赖摘要具体度**：抽取 prompt 若产出泛化摘要，global 向量区分度崩塌——评测单独盯
4. **行为断崖**：拒答替代"有什么答什么"，线上体验突变；靠 strict_refusal 开关灰度
5. **多跳能力降级**：一跳替代 4 跳，A→B→C→D 型长链问题变弱（接受取舍，hops 参数保留）
6. **重构波及面**：chat_flow 全链 + Java SSE 消费端 + 存量数据迁移，需严格分阶段（P0→P3），每阶段可独立回退

## 10. 实施条目（分阶段，逐项验收）

### P0 入库侧 ✅

- [x] ✅ 抽取 prompt 增 head_gloss/tail_gloss 字段 + `schema.py` Triple/parse_triples 扩展（gloss 截 120 字）
- [x] ✅ Neo4j 模板增 summary_hints 追加（实体节点 SET CASE 去重追加，与边 hints 同构）
- [x] ✅ `config.py` 新增 `kg_card_collection(kb_id)` + topk/rerank/阈值/超时参数组
- [x] ✅ `qdrant.py` 新增卡片 ensure/upsert/delete 函数（uuid5 幂等 + type payload index）
- [x] ✅ 入库流程接双写：graph_writer 图谱写完 → 读回 touched 实体/关系 → 合并摘要 → 分批 upsert（best-effort）
- [x] ✅ 删除路径同步清卡片：purge_document_edges/purge_chunk_ids 改为先读后删返回清单 → delete_kg_cards_for；`POST /api/v1/admin/graph/kg-cards/rebuild` 全量重建端点

### P1 检索侧 ✅

- [x] ✅ 关键词提取（lightrag_keyword_system.md，一次调用产双组 + 最近 6 轮历史共指 + 原句兜底）
- [x] ✅ local 链路（实体卡向量检索 → query_edges_from_entity_seeds hops=1 → 边卡带实体摘要）
- [x] ✅ global 链路（关系卡直检，payload 自带主客）
- [x] ✅ 融合去重（文本级）+ rerank_texts（复用 reranker 基建，失败保留召回序）+ kg_card_rerank_top_n 上限
- [x] ✅ 审核门重写（rag_sufficiency_eval_system.md 改为双路合并证据审核，输出 sufficient+missing；heuristic/降级保留）
- [x] ✅ flow.py 并行重写 + 规则闲聊短路 + meta 全 key 兼容（新增 kg_card_count/review_missing）+ 拒答流式路径

### P2 拆旧 ✅

- [x] ✅ 删除：steps/route.py、steps/graph_supplement.py、graph_search.py（L1/L2/L3）、question_pipeline/seed/rewriter/decomposer、5 个旧 prompt 文件、domain/routing 包、相关配置字段
- [x] ✅ 社区全删：community.py / community_build.py / community_search.py / community_scheduler.py / qdrant 社区函数 / neo4j community_label / MySQL 同步社区表写入 / cleanup 孤儿社区清理；调度器骨架迁移为 graph_sync_scheduler（job=快照同步）；/internal/rag/community/* 与 /admin/graph/communities 保留兼容
- [x] ✅ `AGENT_FLOW.md` 整体重写为新架构（986 行旧版废弃）
- [x] ✅ tests/test_intent_route.py 改测闲聊短路；test_admin.py 社区断言改无 community_id——**61 项全过**

### P3 评测与验证 ❌（待用户在新库跑）

- [ ] ❌ 新建知识库 → 入库验证卡片双写（日志【卡片同步】/ Qdrant kg_cards_kb{id} 点数）
- [ ] ❌ 对话实测：闲聊短路 / 双路并行 / 拒答告知 missing / 多轮共指
- [ ] ❌ RAGAS 对照（qa100）：新并行 vs 旧串行；local/global 分路打分；拒答口径定义
- [ ] ❌ 时延 P50/P95 对比

## 11. 实施中发现的问题

### P3-1：Java/Vue 端社区 UI 待清理 ⚠️ 遗留（按决策可接受）

- **现象**：Python 侧社区功能全删后，Java `RagCommunityController` 仍调用 `/internal/rag/community/*`，Vue 图谱页社区面板仍读 `/admin/graph/communities`
- **处置**：URL 全部保留兼容——community/* 三端点现语义为快照同步调度（status/auto-rebuild/rebuild），communities 端点恒返回空（存量库旧数据仍可读 MySQL 表）；图谱页节点不再带 community_id，前端按社区着色自然失效、无色渲染不受影响
- **状态**：⚠️ 待 Java/Vue 侧后续移除入口（不炸、仅空面板，优先级低）

### P3-2：手工改图不自动同步卡片 ⚠️ 遗留（已给修复端点）

- **现象**：管理台 entities/edges 增删改直接写 Neo4j，kg_cards 副本与 MySQL 快照都不会立即更新
- **根因**：卡片同步钩子挂在入库链路，管理台 mutations 只 `_mark_graph_dirty`（快照静默窗口同步）
- **处置**：`POST /api/v1/admin/graph/kg-cards/rebuild?kbId=` 手动全量重建；管理台编辑图谱后需调用
- **状态**：⚠️ 遗留（低频操作，可接受；后续可在 admin_mutations 内联动单卡 upsert）

### P3-3：venv 为旧拷贝安装（环境问题，已修复）

- **现象**：`.venv` 内 rag_core 是非 editable 的旧拷贝，改 src 不生效、导入新旧代码错位
- **修复**：`pip install -e . --no-deps` 重装为 editable；跑单测用全局 Python313（pytest 在该环境）
- **状态**：✅ 已解决
