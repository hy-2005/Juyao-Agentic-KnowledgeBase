# 图谱层面评审与规划（查询 + 入库 + 社区）

> 状态：🔄 进行中（查询/入库/社区全链路已实施；实体消歧为设计限制待确认，重灌策略文档化） · 更新：2026-08-07
> 范围：juyao-agentic-rag 知识图谱链路（`rag_core/knowledge_graph/` + `orchestration/` + `ingestion/graph_writer.py`）
> 配套代码：
> - 查询侧：`edge_queries.py`、`cypher.py`、`observation.py`、`question_seed.py`、`intent_router.py`、`routed_flow.py`、`sufficiency.py`、`finalize.py`
> - 入库侧：`extractor.py`（LLM 抽取）、`schema.py`（Triple 模型/校验）、`store.py`（Neo4j 写入）、`graph_writer.py`（并行入库）、`prompts/text/kg_triple_extraction_system.md`（抽取 prompt）
> 关联文档：`CHUNK_SPLITTING_REVIEW.md`、`RETRIEVAL_REVIEW.md`（min_relevance=0.35 阈值问题与 sufficiency 联动）、`INGESTION_UPDATE_REVIEW.md`（图增量/引用计数式删除）

---

## 1. 现状：图谱查询链路

```
意图路由（LLM/rules）→ direct | graph_only | vector_only
  ├─ graph_only   → question_seed（LLM 抽实体）→ resolve_entity_names（精确匹配）
  │                 → cy_expand_from_seeds 多跳（1..5 跳双向）→ relation_hints 内存过滤
  │                 → format_edges_for_prompt → Observation
  ├─ vector_only  → 向量检索 → sufficiency 判断（LLM/启发式）
  │                 → 需要补图则问句驱动查图（同上）→ Observation
  └─ 图谱 Observation → finalize 页脚 + 正文明细（带 chunk 引用）
```

两条查询路径设计（edge_queries.py）：
- `query_edges_for_chunks`：向量命中的 chunk_id → 关联三元组（chunk 锚定，确定性）
- `query_edges_from_entity_seeds`：问句实体 → 多跳扩展（依赖 LLM 抽取 + 精确匹配）

### 关键配置

| 参数 | 当前值 | 含义 |
|---|---|---|
| graph_query_enabled | true | 图谱总开关 |
| graph_expand_max_edges | 40 | 单次查询边数上限 |
| graph_max_hops | 4 | 多跳扩展跳数（P1-1 后用户定稿；上限 10） |
| graph_expand_internal_path_cap | 120 | 路径数上限（结果上限，非遍历上限） |
| graph_question_extract_timeout_s | 30 | 问句实体抽取 LLM 超时 |
| vector_then_graph_supplement | true | 向量不足时补图开关 |
| rag_sufficiency_mode | llm | 补图判断模式（llm/heuristic） |

---

## 2. 问题清单

### 🔴 P0-1：chunk 锚定查询未接线（死代码）

- **位置**：`query_edges_for_chunks` 仅被 `build_graph_observation_text` 调用，而后者在 `routed_flow.py` 中**没有任何调用方**；F 补强节点（routed_flow.py:175）实际走 `build_graph_observation_question_driven`（问句实体驱动）
- **问题**：向量检索命中的 chunk 携带图谱边线索（边上的 `chunk_ids` 锚定字段，确定性信号），但系统绕过了这条最可靠的路，选择了"LLM 实体抽取 + 精确匹配"的最脆弱路径
- **修复**：`routed_flow.py` 的 F 补强改用 `build_graph_observation_text(向量命中 chunk_ids)`——把 `merged_docs` 的 key 传进去；问句实体作为补充路径

### 🔴 P0-2：实体匹配只有逐字精确匹配

- **位置**：cypher.py:25（`WHERE e.name IN $names`）
- **问题**：问句侧抽取（question_seed）与入库侧抽取（extractor）是两次独立 LLM 调用，命名风格天然不一致（问句用自然语言称呼，入库用原文全名）；无归一化（大小写/全半角/空格）、无子串/模糊兜底。匹配失败 → "未匹配到节点" → 图谱路径白跑
- **修复**：`resolve_entity_names` 三层递进——精确 → 归一化 → 包含/被包含子串匹配

### 🟡 P1-1：多跳扩展无方向、无谓词约束、遍历爆炸

- **位置**：cypher.py:31（`MATCH p=(s)-[:RELATED*1..5]-()` 双向任意 5 跳）
- **问题**：
  - relation_hints 是查询后内存过滤（edge_queries.py:95），非 Cypher 内过滤——先捞无关边再滤
  - 过滤为空时退回全量边（edge_queries.py:71）：hints 未命中时把全部边塞进 Observation（"防误杀"副作用=全噪声）
  - 高扇出实体 5 跳无方向 = 指数级路径展开，path_cap=120 是结果上限不是遍历上限，密集图可能慢/爆
  - max_edges=40 截断下第一跳高扇出边占满配额，2-3 跳关系被截掉——**hops=5 与 max_edges=40 参数自相矛盾**
- **修复**：relation_hints 下沉到 Cypher WHERE；hops 默认降到 2（1 跳全返回、2 跳限制）；方向按"边方向 + 关系大类"约束

### 🟡 P1-2：graph_only 分支无向量兜底

- **位置**：intent_router.py `_GRAPH_COMPLEX_RE` 含"为什么|为何|因果|导致|关系"；routed_flow.py:77
- **问题**："为什么"类词命中率高，误判为 graph_only 后只查图；图谱未命中 → had_graph_edges=False → 直接走"无知识库依据"人设，**不降级到向量检索**（仅 graph_query_enabled=false 才降级）
- **修复**：图谱未命中（0 边）时自动补一轮向量检索；意图路由规则收敛（"为什么/因果"从 graph_only 触发词移除，仅"关系/关联/路径/多人之间"走 graph_only）

### 🟡 P2：其他

1. **图谱 Observation 体积大**：40 边 ×（实体+谓词+chunk 引用+类型+220 字证据摘录）≈ 几 KB 全量进 prompt（finalize.py:51），与向量 5 chunk 叠加窗口压力大，证据摘录与 chunk 内容常重叠
2. **time_hints / location_hints / modality_hints 未利用**：Cypher 返回了（cypher.py:9），但 format_edges_for_prompt 未格式化——时间线类问题（"哪一年/先后"）本可答
3. **无实体消歧**：同名不同 sense（head_sense_hints）多节点，IN $names 全返回，多跳跨含义混跳
4. **sufficiency 联动 min_relevance=0.35**（sufficiency.py:106）：全局 0.35 阈值过高 → 检索结果够用的问题也白白多一次图谱查询 + 实体抽取 LLM 调用（时延/成本）；与 RETRIEVAL_REVIEW P1 同源

---

## 3. 做对的地方（不需要改）

1. 双路径设计思路本身对（chunk 锚定 + 实体种子）——只是 chunk 那条未接线
2. 失败降级完整（Neo4j 挂 → "图谱查询暂时不可用"，不炸流程）
3. 图谱页脚有截断保护（format_graph_snapshots_footer 的 per_query/total max）
4. 图谱证据带 chunk 引用（cite），可溯源
5. sufficiency 的 LLM 模式（读 Observation 判断是否够答）比纯阈值合理，失败回退启发式也完整

---

## 4. 优化路线图（2026-08-07 实施状态）

| 优先级 | 改动 | 状态 | 说明 |
|---|---|---|---|
| P0-1 | F 补强改用 chunk 锚定查询 | ✅ 已实施 | graph_supplement 步骤 chunk 锚定优先（query_edges_for_chunks 接线），0 边问句实体兜底；SSE 契约 diff 验证通过 |
| P0-2 | 实体匹配三层递进兜底 | ✅ 已实施 | resolve_entity_names 精确→归一化→子串；实测"盾构机"/"ZTE-9000"命中库内全名 |
| P1-1 | Cypher 下沉 hints + hops 约束 | ✅ 已实施 | graph_max_hops 5→4（用户定稿，平衡多跳能力与遍历成本）；relation_hints 参数化下沉 Cypher（遍历时按谓词/大类过滤）；实测 2 跳查询正常 |
| P1-2 | graph_only 未命中降级向量 | ✅ 已实施 | flow.py 0 边自动降级（stop_reason=graph_only_fallback_vector） |
| P2 | Observation 体积 + time_hints | ✅ 已实施 | evidence/关系表述截到 120 字；time_hints/location_hints 格式化输出（时间线/位置问题可答） |
| P2 | 实体消歧 | 📌 设计限制 | 同名不同义需 sense 进节点主键（成本高）；现状：入库 MERGE 按 name 合并 sense_hints 列表、查询侧用 sense_hints 辅助——已覆盖常见场景，完整消歧待业务确认 |

**额外完成（2026-08-07）**：
- **意图路由误判修复**：prompt 偏置反转（默认检索）+ 规则保护（direct 仅限问候）+ 触发词精确化（裸"号"→"门牌号"）——6 条测试全部正确路由，4 个回归测试
- **图谱边 kb 隔离**：cypher 边级 kb 过滤（`$kb IN coalesce(r.kb_ids, [])`），Entity 节点全局共享

---

## 5. 入库侧评审（抽取与写入）

> 2026-08-07 第二轮补充：查询侧命中难的根本原因在入库侧——**归一化缺失**。

### 5.1 现状：入库流程

```
chunk（复用文本切分链路）
  → _extract_and_write_one_chunk：每个 chunk 独立调 LLM（TripleExtractor）
  → JSON → parse_triples 校验（schema.py）→ Neo4jTripleStore.upsert_triples
  → MERGE (h:Entity{name})-[:RELATED{relation}]->(t)，边属性带 chunk_ids/doc_ids/evidence 等
  并行：ingest_graph_workers=4 线程池；幂等：同 (head, relation, tail) 累加
```

### 5.2 问题清单

**🔴 P0-1：入库不归一化 + 查询精确匹配 = 命中全靠运气**
- 位置：store.py:24（`MERGE (h:Entity {name: $head_name})` 主键即实体名原文）
- 问题：同一实体在不同 chunk 被 LLM 以不同写法抽取（"陆沉" vs "陆沉（陆氏本源继承人）" vs "陆少"）→ 各自独立节点，图谱被碎实体污染；叠加查询侧逐字精确匹配（§2 P0-2），两边严格性叠加，图谱路径命中全靠运气。**这是图谱"经常白跑"的根源**
- 修复：抽取 prompt 加硬约束（统一称谓、禁止修饰语/括号）；Python 侧规范化函数（去括号修饰/全半角/首尾空格）；后续加别名表或 embedding 相似度合并

**🔴 P0-2：无跨 chunk 实体合并/消歧（entity resolution 缺失）**
- 位置：graph_writer.py:37（每 chunk 独立抽取直接入库）
- 问题：无任何跨 chunk 实体对齐；微软 GraphRAG 标准步骤（抽取 → 实体合并/消歧 → 社区层级）缺失——图谱只是平铺边集合，无社区结构、无层级聚合
- 后果：实体写法不同 → 节点爆炸；同名不同含义 → 无 sense 消歧，查询多跳跨含义乱跳

**🟡 P1-1：谓词无闭集约束，边爆炸**
- 位置：kg_triple_extraction_system.md:7（谓词只有示例无强制候选集）
- 问题："经营" vs "开办" vs "开设" 生成平行边（MERGE 键是 (head, relation, tail) 逐字一致才合并）
- 修复：prompt 强制谓词从固定候选集选（从属/时空/因果/属性/组成/业务/引用 + 少量业务词），细节进 relation_full

**🟡 P1-2：入库与查询两套独立 LLM 抽取，命名风格无对齐**
- 位置：kg_triple_extraction_system.md（入库，要求"与文中一致"）vs question_seed.py（查询，抽问句称呼）
- 问题：键名兼容了但命名风格天然不一致（"那台机器" vs "ZTE-9000型泥水平衡盾构机"）——入库归一化做好后查询仍可能匹配不上
- 修复：查询侧名称解析——question_seed 抽取时喂入图谱现有实体名候选（TOP-N），LLM 从中选择

**🟡 P1-3：抽取与 chunk 质量强耦合，单 chunk 上下文隔离**
- 位置：extractor.py:56
- 问题：单 chunk 独立抽取，跨 chunk 指代（"他""该工程"）抽不出来；chunk 被规则硬切出残句时抽取质量劣化；无重试（kg_extract_max_retries=0），失败静默返回 (0,0)——LLM 持续失败时文档图谱静默为空
- 修复：重试策略 + 入库统计图谱成功率并在日志/UI 暴露

**🟢 P2：其他**
1. 写入无批处理：每 triple 一次 `_run`（store.py:139），每 chunk = 1 次 LLM + N 次 Neo4j 往返；并发 MERGE 同 key 有唯一约束冲突概率无重试。应改 UNWIND 批量提交
2. evidence 截断三层不一致：prompt ≤120 字 / schema.py 600 / store.py 800
3. 实体类型只存边属性（head_type/tail_type），未建类型节点，无法按类型过滤路径
4. 重灌策略依赖前缀清理（purge_document_edges），无 schema 版本迁移路径——切分策略变更后易留脏数据

### 5.3 做对的地方

- MERGE 幂等设计好（同键累加 chunk_ids/doc_ids），重复入库不重复建边
- 边属性丰富（time/location/evidence/sense/modality/category/full hints）——信息留足，查询侧未全用
- prompt 质量规则好（禁止编造、反向边去重、modality 标注）
- 并行抽取 + 单 chunk 失败不中断整批

### 5.4 入库侧修复路线图

| 优先级 | 改动 | 涉及文件 | 收益 |
|---|---|---|---|
| P0-1 | 实体归一化（prompt 硬约束 + Python 规范化函数） | ✅ 已实施 | normalize_entity_name（全半角/括号/引号清洗）+ prompt 统一称谓；同实体不同写法合并为同节点（实测验证） |
| P1-1 | 谓词闭集（prompt 强制候选） | ✅ 已实施 | 27 词候选集 + 「其他（具体动词）」兜底，细节进 relation_full |
| P0-2 | 跨 chunk 实体对齐（entity resolution 工具） | ✅ 工具已提供 | scripts/merge_entities.py：embedding 相似度候选检测（dry-run）+ --apply 合并（边转移+属性合并）；保守阈值 0.95，人工确认后执行 |
| P1-2 | 查询侧名称解析（喂实体候选） | ✅ 已实施 | question_seed.extract 按 n-gram 粗筛图谱实体 top20 拼入 prompt，LLM 优先用库内名称 |
| P2 | UNWIND 批量写入 + 重试 | ✅ 已实施（UNWIND） | _UPSERT_RELATED_BATCH 一次 Cypher 写全部 triple；重试待办 |
| P2 | 重灌策略（全量重建 vs 增量） | ✅ 文档化 | --purge + chunk_id 差集清理（INGESTION_UPDATE P0-2）已覆盖切分变更重建；增量 chunk_id 改造见 INGESTION_UPDATE §3.2 |

---

## 6. 社区（Community）概念澄清与规划

> 2026-08-07 讨论澄清：社区不是按文档划分的。

### 6.1 概念澄清

**社区 = 按实体间连接密度用图算法（Leiden/Louvain）聚类的结果**，不是按文档划分：

- 在整张图上做社区检测：连接紧密（边多、路径短）的实体聚成社区，连接松散处形成边界
- **一个社区通常横跨多个文档**（跨文档实体关系是图谱核心价值）；**一个文档通常散落在多个社区**（同一文档的实体可能分属不同聚类）
- 同一实体横跨多文档（如《合同》与《售后协议》都提"ABC科技"）——按文档分社区会导致实体分裂，与碎实体问题相同

**为什么按文档分社区不行**：
1. 跨文档实体分裂（同实体出现在多个社区）
2. 跨文档关系被剪断（文档 A 人物 ↔ 文档 B 公司的关联丢失）
3. 全局性问题无法回答（"所有合同涉及哪些客户"需社区摘要）

### 6.2 社区解决什么问题（与归一化分工）

| 问题 | 解法 |
|---|---|
| 实体混乱/重复（"陆沉" vs "陆少"） | **实体归一化**（入库前统一命名、跨 chunk 合并）——不是社区 |
| 全局性/主题性问题（"整个库讲了什么"） | 社区检测 + 社区摘要（每社区一段摘要，global 检索） |
| 多跳推理（"A 和 B 什么关系"） | 图谱查询（现有问句实体多跳扩展，local 检索） |

### 6.3 对项目的意义

- 当前系统**只做了 GraphRAG 的前两步**（抽取 + 建图），且归一化缺失；社区检测（Leiden）、社区摘要、local/global 双检索均未实现
- 现有问答属于 **local 检索**（问句实体 → 多跳），不依赖社区
- 社区检测 + 社区摘要主要服务 **global 检索**（跨文档主题汇总），对强实体关系场景（小说/合同）价值大，但成本高（Leiden + 每社区一次 LLM 摘要）
- **建议顺序：先实体归一化（解"混乱"）→ 再做社区（解"全局汇总"）**——社区检测在脏图上做出来也是脏社区

### 6.4 社区规划（如实施）

1. 社区检测：Neo4j GDS 库 Leiden 算法（或 python-louvain/leidenalg），在 Entity 图上跑
2. 社区摘要：每社区一次 LLM 摘要（实体列表 + 边列表 → 主题摘要），存 Community 节点
3. 检索接入：global 问题（问句无实体/主题型）→ 社区摘要检索；local 问题 → 现有实体路径
4. 前提：先完成 §5.4 的实体归一化

---

## 7. 待确认事项

1. **图谱规模与密度**：当前库中实体/边数量、碎实体比例（归一化缺失的量化证据）、高扇出实体分布（决定 hops 参数与遍历风险）
2. **评测基准**：docs/eval/ 是否有图谱问答评测集，可对比修改前后
3. **图数据库资源**：Neo4j 版本/内存（GDS 库可用性——决定社区检测方案），5 跳遍历实际耗时
4. **社区检测范围**：是否实施 global 检索（社区摘要），还是先只做 local（现有路径）+ 实体归一化
5. **谓词候选集**：业务需要哪些自定义谓词（与业务方确认固定词表）
