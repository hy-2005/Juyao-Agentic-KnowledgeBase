# 社区层增强方案与实施路线图（REVIEW）

> 状态:❌ 未完成（方案讨论稿，未实施）
> 创建:2026-08-14 · 更新:2026-08-14
> 关联:[GRAPH_QUERY_REVIEW.md](GRAPH_QUERY_REVIEW.md)(§6.4 社区构建现状) · [GRAPH_COMMUNITY_UI_REVIEW.md](GRAPH_COMMUNITY_UI_REVIEW.md)(展示层) · [COMMUNITY_SYNC_REVIEW.md](COMMUNITY_SYNC_REVIEW.md)(同步/双写)

## 一、现状盘点（2026-08-14，含实测数据）

### 1.1 实测数据（MySQL rag_community）

| 项 | 实测值 | 说明 |
|---|---|---|
| kb12（5000 篇税文库） | **0 个社区** | 社区摘要从未跑过——社区层当前等于未启用 |
| kb0 社区数 | 75 | 摘要已建（2026-08-13），entity-only prompt 产出 |
| kb0 社区大小 | 平均 22 实体，最大 177 | 分布极偏：少数巨社区 + 大量小社区 |
| kb0 空摘要 | 0（抽样级） | 当时运气好；本地模型 180s 超时下成片空串是必然 |
| rag_community 列 | 无 title/rating 列 | 结构化摘要需加列（全删全建，零迁移成本） |

### 1.2 代码盘点

| 环节 | 现状 | 问题 |
|---|---|---|
| 检测 | 单层 Leiden（igraph，`ModularityVertexPartition`），**边无权重** | 均匀权重丢信息；单层无层级；resolution 参数从未调过 |
| 摘要输入 | **只有实体名 `entities[:40]`**（igraph 内部顺序乱截，非核心实体），无三元组、无证据 | LLM 只能猜主题；税务场景（实体=「25%」「小型微利企业」）纯实体名必然泛化 |
| 摘要输出 | 2-3 句自由文本，开头 70% 是「这些实体共同构成了…」模板话术 | 无 title/findings 结构；检索键被模板词稀释 |
| 摘要调用 | 10 线程池 + 超时 180s，**0 重试**，失败返回空串 | 空串**照常写 Neo4j + 嵌入空串写 Qdrant**（污染检索，占 top-K 名额） |
| 存储 | Neo4j Community 节点 + Qdrant 摘要 collection（每 kb）+ MySQL 快照 | Qdrant 写入 best-effort：失败静默 → L1 永久 0 命中降级 L2，无人知晓 |
| 检索 | L1 向量检索摘要 → top-K 直拼（全局问答）/ 实体范围约束（子图查询） | 无打分聚合（map-reduce）、无 rating 加权 |
| 重建 | 先删后建全量重建，调度器 debounce 合并 | 无增量；大库重建小时级 + 检索空窗；快照同步耦合在重建末尾（批量入库暂停时管理台数据冻结） |
| 图谱地基 | 实体 `MERGE` 精确名匹配，**无归一化**（「税务总局」vs「国家税务总局」是不同节点）；关系谓词自由词汇 | 实体碎片化 → Leiden 社区失真；查询 hint 精确匹配召回差（`relation_category` 已抽取但未用于匹配） |
| 实体描述 | **无合成步骤**：实体节点仅 name；抽取的 head_type/head_sense 提示散存在边上数组（kind/sense_hints），未合并为实体级综合描述（GraphRAG 第 3 步 Summarization 缺失） | Local Search 靠「问题实体精确名匹配」，对表述差异零容忍；实体详情无法进社区摘要输入 |

## 二、主流做法调研（2026-08-14）

### 2.1 Microsoft GraphRAG：层级社区 + 社区报告

- **层级 Leiden**：跑出 ~4 层（C0-C3），社区表含 parent/children/level；叶子社区细节、顶层主题
- **社区报告**（community_reports）：title + summary + rating（成员显著性 0-10）+ rating_explanation + findings（5-10 条洞察，每条 summary + explanation）
- **输入组装**：实体/关系按**节点度数与边两端度数**排序（sort_context），塞满 `max_input_length` token 预算（默认 12k），超出丢弃——主流不是全量返回，是预算截断
- **分层聚合**：逐层 bottom-up，高层社区输入含子层报告。⚠️ 坑：issue #1907——官方实现里子报告常为空，层级上下文未真正生效；我们若做分层必须显式实现 bottom-up
- **查询期**：Global Search map-reduce（并行给每份报告打分 0-10 → 聚合高分报告答案）；DRIFT（primer 社区报告 → 追问 → local 细化）；Local Search（实体锚定）
- **成本**：索引期全层级摘要 = token 大头（$1544/M tokens vs 向量 RAG $1.45）

### 2.2 增量维护（GraphRAG 2.0 `update` 命令）

- **新实体优先放进现有社区**——能归入就不重跑 Leiden
- **只对成员发生变化的社区重新摘要**——未变社区报告直接复用
- **阈值**（归不进去的新实体数 / 模块度变化）超了才全量重跑 Leiden；新社区 ID 递增追加保持层级
- 限制：不支持删除/修改文档；官方生态通行建议**「每日增量 + 每周全量」混合**防漂移

### 2.3 LazyGraphRAG：摘要延迟到查询时

- 索引期**只做检测不写摘要**；查询时对命中的社区**现算摘要+缓存**
- 索引成本降至 0.1%；代价：单查询成本高于预计算；适合低查询量场景

### 2.4 LightRAG：干脆不做摘要

- 跳过社区摘要，双级（实体级+关系级）检索；全局类问题无社区报告支撑

### 2.5 对我们的结论

我们是「单层轻量 GraphRAG」，索引成本本来就低，不需要 LazyGraphRAG 那么激进；要补的是 GraphRAG 的**摘要质量机制（预算截断 + 结构化报告）**与**增量复用机制**。层级和 map-reduce 按收益逐步上。见 §三 分档方案。

## 三、优化方案分档（S0 → S4）

> 档位编号与旧 P0/P1/P2 的映射：旧 P0 = 本档 S0 的 3/4 条；旧 P1 = 本档 S2；旧 P2 = 本档 S4。旧编号在新引用中一律用 S 档。

### S0 · 先可用档（kb12 首跑前必做，~半天，全在 community_build.py / community.py 内部）

| # | 条目 | 改动 | 解决什么 |
|---|---|---|---|
| S0-1 | 空摘要跳过 Qdrant 写入 | `summaries_for_vector` 过滤空串；日志统计「空摘要 N 个」 | 空串向量污染检索结果、占 top-K 名额 |
| S0-2 | 度数 top40 替代乱截 | `detect_communities` 返回时带度数；摘要取度数 top40 | LLM 看到的是社区核心实体而非 igraph 内部顺序的随机 40 个 |
| S0-3 | 摘要输入加三元组+证据 | 从 MySQL `rag_graph_edge` 按 kb 查社区内边（in/out_degree 已预计算）；实体按度数排序、边按两端度数排序，字符预算 ~8000 截断；`evidence_snippets` 截前 100 字 | 检索键质量之根：税务实体集合无关系边 LLM 只能瞎猜 |
| S0-4 | 输出结构化 title+summary | prompt 输出 JSON `{title, summary}`；title 一句话必含具体实体名；Neo4j Community 加 title 属性、MySQL rag_community 加列、Qdrant 嵌入 title+summary 拼接 | 检索键从「模板话术+主题词混合」变为「具体主题」；UI 列表直接展示 title |
| S0-5 | 摘要生成加 1 次重试 | `get_chat_llm(..., max_retries=1)` | 本地模型 180s 超时成片空串（比抽取更该有重试：重建一次成本高） |
| S0-6 | 边权重进 Leiden | `fetch_entity_graph` 返回边权 = `size(r.chunk_ids)`（支撑文档数）；igraph 传 weights | 跨文档共识三元组权重高，社区检测质量上一台阶，一行级改动 |

**实施顺序说明**：S0 六条互相独立，一次改完统一跑。

### S1 · 地基档（图谱质量，~1-2 天）

| # | 条目 | 改动 | 解决什么 |
|---|---|---|---|
| S1-1 | 实体归一化后处理 | 离线脚本：候选对（同义实体）生成 + LLM 批量判定 + Neo4j 合并（引用数组/边合并）；**不动入库链路** | 实体碎片化 → 社区失真、检索召回差的根。GRAPH_QUERY_REVIEW 遗留待办，社区上量前优先级提前 |
| S1-2 | 关系 hint 匹配用 category | 查询链路 relation_hints 匹配优先 `relation_category`（边属性已存），精确谓词降级 | 谓词自由词汇下召回差；存量数据零重抽 |
| S1-3 | 增量摘要复用 | 全量 Leiden 照跑（秒级）→ 新旧社区按实体重叠度匹配（Jaccard > 0.6 复用旧摘要，< 0.6 重摘要，新社区新摘要）；配「每 N 次增量 / 每 7 天」全量兜底防漂移 | 新增几篇文档时重摘要 <10 个社区，重建从小时级/几十元降到分钟级/几毛钱 |
| S1-4 | 重建空窗缓解 | 摘要先生成、后删旧社区（或在旧社区上先更新再删孤儿）；Qdrant 同理先写新后删旧 | reset 先删后建期间 L1 全空（功能上降级 L2 不致命，但全局问答质量归零） |
| S1-5 | 实体描述合成（⏸ 已决策暂缓，2026-08-14） | 把散落在边上的 head_sense/type hints + evidence_snippets 用 LLM 合成为实体级描述（GraphRAG 第 3 步 Summarization）。**决策：暂缓**——政策文件实体表述规范（准受控词表），精确名匹配 + S1-1 归一化召回损失可控；成本（每实体 1 次调用，kb12 预估 5-10 万实体 → 本地 3-10 小时 / DS 30-80 元）与收益（需新建实体检索链路才兑现）不划算。**复评条件**：S4-1 评测集跑出「精确名匹配 + 归一化」召回不足时重启。折中（非 LLM 拼接 sense 进社区摘要输入）保留为 S0-3 可选增强 | — |

### S2 · 检索档（S0 跑出效果数据后）

| # | 条目 | 改动 |
|---|---|---|
| S2-1 | 社区 rating 加权 | 摘要时输出 rating（1-10）；L1 排序 = 相似度 × rating 加权；rag_community 加列 |
| S2-2 | 轻量 map-reduce | top-K(10) 命中后一次 LLM 调用并行打分（本地模型便宜）→ 只把 top 2-3 份报告全文交给答案合成（替代直拼） |
| S2-3 | 层级社区（可选） | 检测跑 C0-C2，摘要显式 bottom-up（避开 GraphRAG #1907 坑）；先看 S4-2 resolution 扫描结果与 kb12 社区分布再定 |

### S3 · 运维档（~半天）

| # | 条目 | 改动 |
|---|---|---|
| S3-1 | 三处对账脚本 | Neo4j / Qdrant / MySQL 社区计数 + 空摘要计数定时比对，差异打告警；顺带覆盖 Qdrant 摘要写入 best-effort 失败静默问题 |
| S3-2 | 快照同步解耦 | MySQL 图谱快照同步从社区重建末尾拆出（独立调度或挂入库事件），批量入库暂停时管理台数据不再冻结 |
| S3-3 | Lazy 开关（可选） | `COMMUNITY_LAZY_SUMMARY=true` 时重建只检测不摘要，查询时现算+缓存；适合「传完库偶尔问一次」 |

### S4 · 验证档

| # | 条目 | 改动 |
|---|---|---|
| S4-1 | 社区固定评测集 | 30-50 条全局类问题（「整个库涉及哪些税种」「XX 政策适用范围」型）；每次社区改造回归对比命中率 |
| S4-2 | Leiden resolution 扫描 | 0.5/1.0/1.5 各跑一次检测（纯 CPU 秒级），看社区大小分布与摘要抽样质量，选定参数后**kb12 首跑**用 |

## 四、实施路线图（从哪里开始）

```
第 0 步  改 S0 六条代码（半天）
         ├─ 验证：单元级——造 1 个小 kb 跑一次重建，确认
         │   ① 日志出现「度数 top40 摘要输入」「空摘要 N 个」统计
         │   ② rag_community 有 title 列数据、Qdrant 无空摘要点
         │   ③ 边权重传参生效（日志打加权边数）
第 1 步  Leiden resolution 扫描（S4-2）
         └─ 验证：kb12 三个分辨率下社区数/大小分布表 + 抽样 20 社区实体列表人工看
第 2 步  kb12 首次全量构建（选定分辨率 + 新摘要 pipeline）
         └─ 验证：对账——Neo4j/MySQL/Qdrant 三处社区数一致；空摘要计数；耗时记录
第 3 步  摘要质量人工抽检
         └─ 验证：抽 20 社区看 title 是否含具体实体名、summary 与三元组是否一致、有无幻觉
第 4 步  建社区评测集基线（S4-1）
         └─ 验证：30-50 全局问题 L1 命中率/答案正确率存档（后续每次改造对比）
第 5 步  按评测结果决定 S1/S2 顺序（S1-3 增量复用与 S0 强耦合，建议紧随）
```

**为什么不直接上层级/map-reduce**：单层 + 结构化摘要 + 轻量打分已覆盖「税务问答」的主场景；层级与 DRIFT 的收益在评测集上验证后再投入，避免在错误的地基上叠加复杂度。

## 五、成本预估（5000 篇 kb12 规模）

| 方案 | 索引期摘要成本 | 查询期额外成本 |
|---|---|---|
| 现状（entity-only，若直接跑） | 本地模型 0 元但 1-2 小时；DS flash ~3-5 元 | 0 |
| S0（预算截断+结构化+重试） | DS flash ~10-15 元；本地模型时间 ×1.3-1.5 | 0 |
| S1-3 增量复用后（每次新增几篇） | 重摘要 <10 社区，分钟级 | 0 |
| S2-2 map-reduce | 0 | 每问 +1 次 LLM 打分调用（本地模型忽略不计） |
| S3-3 Lazy | ~0 | 每次全局查询 0.01-0.1 元 |

## 六、验证方案

1. **摘要质量**：抽样 20 社区人工评审——title 是否含具体实体名、facts 与证据一致、有无幻觉（S0 后）
2. **L1 检索**：30-50 条全局问题固定集（S4-1），对比 S0 前后命中 top1 相似度、答案正确率（人工/RAGAS 双评）
3. **成本**：控制台 token 账单按日对比
4. **对账**：三处（Neo4j/Qdrant/MySQL）计数 + 空摘要计数（S3-1 脚本化）
5. **性能**：MySQL vs Neo4j 社区边查询基准（同 10 社区各 10 次取均值），定摘要输入的边数据源

## 七、遗留

- kb0 社区摘要还在 dashscope 向量空间（分数 0.03-0.06），需重建入 bge 空间——与 kb12 首跑同批处理
- 实体归一化（S1-1）是后处理脚本，不阻塞 S0；但其结果会改变图结构，**须在 S1-3 增量复用上线前完成**，否则重叠匹配基准会漂移
- 本地模型单点（一台 llama-swap 10 并发撑全链路）是整套系统最大的可用性风险点，属基础设施约束，不在本方案范围

## 参考

- [GraphRAG 增量索引与更新（DeepWiki）](https://deepwiki.com/microsoft/graphrag/4.7-incremental-indexing-and-updates)
- [update_community_reports.py 源码](https://github.com/microsoft/graphrag/blob/7f996cf5/graphrag/index/workflows/update_community_reports.py)
- [Incremental indexing Issue #741（重跑 Leiden 阈值讨论）](https://github.com/microsoft/graphrag/issues/741)
- [社区报告生成流程（DeepWiki）](https://deepwiki.com/microsoft/graphrag/4.5-community-reports-generation)
- [层级摘要上下文未生效 issue #1907](https://github.com/microsoft/graphrag/issues/1907)
- [DRIFT Search 官方文档](https://microsoft.github.io/graphrag/query/drift_search/)
- [LazyGraphRAG：索引成本 0.1%](https://particula.tech/blog/lazygraphrag-700x-cheaper-graphrag-knowledge-graphs)
- [GraphRAG vs LightRAG 成本对比（2026）](https://callsphere.ai/blog/vw6g-microsoft-graphrag-knowledge-graph-2026)
