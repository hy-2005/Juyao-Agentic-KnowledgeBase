# 检索层面评审与规划

> 状态：评审中（待讨论） · 更新：2026-08-07
> 范围：juyao-agentic-rag 检索链路（`rag_core/retrieval/` + `orchestration/`）
> 配套代码：`retriever.py`（主流程）、`fusion.py`（RRF）、`reranker.py`（重排）、`query_rewrite.py`、`hyde.py`、`elasticsearch.py`（BM25）、`observations.py`
> 关联文档：`CHUNK_SPLITTING_REVIEW.md`（chunk 拆分评审）、`GRAPH_QUERY_REVIEW.md`（图谱查询评审；P0 embedding 窗口问题与 sufficiency 阈值联动）、`TENANT_PERMISSION_REVIEW.md`（检索链路 kbId 隔离）

---

## 1. 现状：检索主流程

```
search_context(query)
  ├─ Step1  query 组装：原 query + LLM 改写 sub-queries(≤4) + HyDE 假答案
  ├─ Step2  多 query 并行：每条 query →
  │           ├─ 向量路：Qdrant similarity_search top_k=15
  │           └─ ES 路：BM25 multi_match top_k=15（HyDE 通道跳过）
  │           → 向量阈值过滤(min_relevance=0.35) → 单 query 内 RRF
  ├─ Step3  跨 query RRF 二次融合 → 截断 rrf_top_n=8
  ├─ Step4  多 query rerank（每条 query 对 8 候选打分）→ 跨 query rerank RRF → 截断 rerank_top_n=5
  └─ 结果 → QA 组装（带 chunk_id 引用 + 相关度 max_score 展示）
```

### 关键配置

| 参数 | 当前值 | 含义 |
|---|---|---|
| top_k | 15 | 每路召回数 |
| rrf_top_n | 8 | 跨 query RRF 后进 rerank 的候选数 |
| rerank_top_n | 5 | 最终给 LLM 的 chunk 数 |
| min_relevance_score | 0.35 | 向量路全局绝对值过滤阈值 |
| rrf_k | 60 | RRF 平滑常数 |
| query_rewrite_max_subqueries | 4 | sub-query 上限 |
| rerank_provider / model | dashscope / gte-rerank-v2 | 重排模型 |

---

## 2. 设计上做对的地方（不需要改）

1. **双层 RRF**（单 query 内融合向量+ES，跨 query 融合多 query）——多个 sub-query 都命中的 chunk 自然加分，正是 Multi-Query Retrieval 的期望行为（fusion.py）
2. **HyDE 通道 vector_only=True** 跳过 ES——避免假答案的长文本稀释 BM25 关键词命中（retriever.py:87）
3. **rerank 层多 query 各打一次分再跨 query RRF**（reranker.py:34）——精排层也"听到"多 query 信号，避免"召回多 query / 精排单 query"的信息瓶颈
4. **全链路失败降级完整**：改写失败→原 query；HyDE 失败→跳过；rerank 失败→RRF 顺序；ES 不可用→纯向量。鲁棒性设计到位

---

## 3. 问题清单

### 🔴 P0：HyDE 通道同样踩 embedding 窗口

- **位置**：hyde.py:48（`_HYDE_MAX_LEN = 600`）
- **问题**：600 中文字符 ≈ 600-900 token，超过 mxbai-embed-large 的 **512 token** 窗口（注释声称"上限保护"，实际没保护到）。HyDE 假答案向量被截断，增强效果打折
- **修复**：`_HYDE_MAX_LEN` 按 embedding 窗口折算（512 token ≈ 350-400 字符）；与 chunk 大小修复同源联动

### 🔴 P1：min_relevance=0.35 全局绝对值过滤风险大

- **位置**：retriever.py:150-156
- **问题**：
  - 0.35 绝对值对不同 query/文档类型不可比；mxbai 类中文模型 cosine 普遍偏低（0.3-0.5），0.35 可能过滤掉一半以上正确 chunk
  - 过滤在 RRF **之前**：被过滤 chunk 即使 ES 路命中好，向量信号直接归零
  - 过滤后名次从 1 重编（retriever.py:156）：剩 3 条的 query 与剩 15 条的 query 在跨 query RRF 里权重相同——召回质量差的 query 反而"名次更靠前"
- **修复**：改相对截断——按本次召回的相似度分布动态保留（如相对最高分比例，或按 top-N 保底）；或取消过滤交给 rerank 层裁决

### 🟡 P2：15 → 8 → 5 三级漏斗，截断太狠 + 无多样性控制

- **位置**：retriever.py:63（rrf_top_n=8）、reranker.py:40（rerank_top_n=5）、qa.py:36（最终 5 条进 LLM）
- **问题**：
  - 6 条 query（原+4sub+HyDE）信号分散，正确 chunk 排第 9 位就被丢
  - 5 条 chunk 可能 4 条同源（overlap + 多 query 命中同一区域），多文档对比类问题覆盖度差
  - rerank 候选只有 8 条，cross-encoder 优势发挥不足
- **修复**：rrf_top_n 提到 12-15；rerank 后按 source_name 做多样性采样（每文档保底 1-2 条）或 MMR；rerank_top_n 提到 6-8

### 🟡 P2：ES BM25 路太原始

- **位置**：elasticsearch.py:145-148（仅 multi_match 查 content）
- **问题**：无 match_phrase 短语匹配（条款名/专有名词词序敏感场景没利用）；无字段加权（source_name 关键词可 boost 该文档 chunk）；无 IK 同义词、无 minimum_should_match
- **修复**：加 match_phrase + 按权重组合（content^1, source_name^3）；小改动大收益

### 🟡 P2：简单 query 也跑全链路，LLM 调用过多

- **问题**：一次检索最差 6-7 次 LLM 调用（意图路由 1 + 改写 1 + HyDE 1 + rerank 6 并行），时延最差 55s+ 才开始生成。简单事实型问题（"合同编号是多少"）没必要拆 sub-query + HyDE
- **修复**：query 复杂度分级——规则判定简单问题走"单路检索 + 单次 rerank"，复杂问题走全链路；意图路由扩展出检索深度维度

### 🟢 P3：小问题

1. **max_score 语义弱**（retriever.py:74 → qa.py:53）：仅"向量相似度最高值"，不参与排序，却作为最终相关度展示给 UI
2. **rerank query 截断 200 字**（reranker.py:31）：HyDE 文本被截断，多 query rerank 时 HyDE 通道信号失真
3. **无结果缓存**：同一问题重复问全链路重跑（小知识库可暂缓）

---

## 4. 优化路线图（2026-08-07 实施状态）

| 优先级 | 改动 | 状态 | 说明 |
|---|---|---|---|
| P0 | `_HYDE_MAX_LEN` 压缩 | ✅ 事实修正 | 实际 .env 用 text-embedding-v4（8192 token 窗口），600 字不超窗，保留为旋钮 |
| P1 | 向量阈值改相对截断 | ✅ 已实施 | `min_relevance_relative_ratio=0.6`：门槛 = min(绝对, 最高分×比例)，低分 query 放宽交给 rerank |
| P2 | 漏斗扩容 | ✅ 已实施 | rrf_top_n 8→12、rerank_top_n 5→6 |
| P2 | 同源多样性采样 | ✅ 已实施 | `_diversify_by_source`（每文档 2 条，不足回填） |
| P2 | ES 加 match_phrase | ✅ 已实施 | bool should + match_phrase(slop=2, boost=2)，配合 IK 分词（已确认 ik_max_word/ik_smart 生效） |
| P2 | query 复杂度分级 | ✅ 已实施 | `_is_simple_query`（≤12 字且无推理动词 → 单 query，跳过改写/HyDE） |
| P3 | max_score 语义修正 | ✅ 注释说明 | 明确"向量参考分非排序分"，结构不动 |

遗留：rerank query 截断 200 字（HyDE 通道信号失真，低优先级）；无结果缓存（小知识库暂缓）。

依赖关系：P0 与 chunk 评审的 P0-1（embedding 窗口）一起修；改完需重灌 chunk 并重跑评测对比。

---

## 5. 待确认事项

1. **图谱补充链路**（routed_flow.py `vector_then_graph_supplement`）：向量检索后按需补图的具体逻辑、图谱 Observation 对 LLM 窗口的占用——未深入分析，待讨论
2. **min_relevance 实际分布**：现有库上跑几组 query 看相似度分布，决定相对截断参数
3. **评测基准**：是否有 eval 脚本（docs/eval/）可以对召回改动做前后对比
4. **rerank 候选扩容**：rrf_top_n 12-15 时 rerank 调用成本变化（6 条 query × 15 候选）是否可接受
