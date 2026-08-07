# 文档更新与增量入库评审及方案

> 状态：评审中（待讨论） · 更新：2026-08-07
> 范围：juyao-agentic-rag 文档更新/重灌链路（Java 上传 → Kafka → Python 入库），含增量入库方案
> 配套代码：`RagDocIngestService.java`（Java 上传/Kafka 生产）、`cli/kafka_consumer.py`（消费）、`ingestion/events.py`（事件处理）、`ingestion/hash_guard.py`（判重）、`ingestion/pipeline.py`（入库）、`ingestion/cleanup.py`（删除）、`knowledge_graph/store.py`（图写入/purge）、`domain/chunk.py`（chunk_id）
> 关联文档：`CHUNK_SPLITTING_REVIEW.md`（chunk_id 设计）、`GRAPH_QUERY_REVIEW.md`（图谱入库/查询）、`TENANT_PERMISSION_REVIEW.md`（P0-1 kbId 同一病根）

---

## 1. 现状：更新流程

```
Java 上传 (kbId, file) → 存文件 upload/rag/{kbId}/{文件名}
  → Kafka (key=kb:logicalKey, payload: action=UPSERT/DELETE,
           docLogicalKey=文件名, contentSha256=文件字节sha, localPath)
  → Python apply_kafka_ingest_payload:
      UPSERT → prepare_upsert 判重（文件 sha vs Qdrant 存 sha）→ 相同 skip / 不同 proceed
      proceed → ingest_file(purge_before_write=True)
                ① 先删（Qdrant/ES 按 source_name、Neo4j 按前缀清边）
                ② LLM 切分 → ③ 写 Qdrant → ④ 写 ES → ⑤ 图谱全量重抽
      DELETE → 按 source_name 删三库
```

**结论：一点增量都没有——任何内容变化 = 全量重建**（文档级 hash 相同才 skip）。

---

## 2. 问题清单

### 🔴 P0-1：kbId 被 Python 侧忽略——多知识库同名文档互相覆盖

- 位置：events.py:22（只用 `docLogicalKey` 纯文件名当 source_name）；RagDocIngestService.java:79/109（Java 明确支持多 kb：目录 rag/{kb}/、Kafka key=kb:logicalKey）
- 问题：kb=0 和 kb=1 各传一份"合同.txt" → 第二个 UPSERT 的 purge_before_write 按 source_name 把第一个知识库的索引删光
- 修复：source_name 用 `{kbId}:{logicalKey}`，Qdrant/ES filter、Neo4j 前缀全部对齐

### 🔴 P0-2：先删后写非原子——更新失败 = 文档从索引消失

- 位置：pipeline.py:37（purge_before_write=True）
- 问题：先全删三库再重新切分写入；LLM 切分 300s 超时 / Neo4j 挂 / ES bulk 失败 → 旧数据已删新数据没进，无回滚；长文档窗口期（数分钟）完全不可检索
- 修复：**先写后删**——新 chunk_id 与旧 chunk_id 天然不同（含 content hash），可先写新数据，成功后再删旧 source_name 数据；失败保留旧数据

### 🔴 P0-3：三库写一致性缺口 + skip 无补偿

- 位置：hash_guard.py:43（判重只查 Qdrant）；kafka_consumer.py（enable_auto_commit=True）
- 问题：Qdrant 写成功 → ES bulk 失败 → ingest_file 异常 → Kafka 已自动提交 → 消息丢失 → 下次同文件上传 hash 相同 → skip → **ES/Neo4j 缺口永不修复**（上次图谱构建失败同理）
- 修复：判重时三库都校验；处理失败不自动提交（手动 commit / 重试 / DLQ）

### 🟡 P1：其他

1. **Kafka 无失败重试/无 DLQ**：处理失败消息直接丢（只打日志）；长文档处理可能超 max.poll.interval.ms（5 分钟）触发 rebalance → 重复消费 → 并发重复入库竞态
2. **图谱每次更新全量重抽**：文档只改一个数字 → Neo4j 清边 → 所有 chunk 重新 LLM 抽取（几十次调用、数分钟），期间该文档图谱数据为空
3. **同文档并发 UPSERT 无锁**：无按 docLogicalKey 互斥，重复消费时双删双写竞态
4. **hash 判重 fallback 语义混乱**（hash_guard.py:83）：`file_sha.startswith(source_doc_id 的 content sha 前16位)`——文件字节 sha 与 content sha 是两种不同哈希做前缀比较（碰撞概率极低，纯属侥幸可用）

### 🟢 P2：payload_sha 与 file_sha 不一致时"以本地为准"（告警合理，但文件落地后被改会静默不一致）

---

## 3. 增量入库方案（设计）

### 3.1 根源障碍：chunk_id 设计杀死增量

当前（domain/chunk.py:24-36）：

```
source_doc_id = {文件名}:{全文content hash前16位}
chunk_id      = {source_doc_id}:{chunk_index}:{正文hash前12位}
```

**文档任何一处内容变化 → 全文 hash 变 → 整篇所有 chunk_id 全变** → 系统无法识别"哪个 chunk 没变" → 只能全量重建。

### 3.2 改造：chunk_id 内容寻址

```python
doc_stable_id = {文件名}:{文档稳定UUID}        # 文件不变则稳定（不含全文 hash）
chunk_id      = {doc_stable_id}:{正文hash前12位}  # 去掉 chunk_index！
```

- 只改第 3 段 → 只有 chunk 3 的正文 hash 变 → 只有它变
- **不能带 chunk_index**（文档中间删一段，后面所有 index 全变）；正文 hash 才是稳定键

### 3.3 入库顺序：先写后清 + chunk 级 skip

```
① 对每个 chunk：chunk_id 已在库 → 跳过（不调 LLM 抽取）
② 只对变化 chunk：LLM 抽取 → MERGE 写边（幂等）
③ 全部写完后 → 清除旧 chunk 引用（只清不在新集合里的）
```

- chunk 判重查询（图侧）：`MATCH ()-[r:RELATED]->() WHERE $chunk_id IN r.chunk_ids RETURN count(r)`——边上的 chunk_ids 列表是天然标记
- 向量侧：Qdrant point id = uuid5(chunk_id) 幂等覆盖（pipeline.py:53）、ES _id = chunk_id 幂等覆盖（elasticsearch.py:87）——已具备

### 3.4 部分更新/删除：引用计数式（现有代码已支持）

store.py:172-185 的 `purge_document_edges` 已是引用计数式删除：

```
清掉边上匹配前缀的 chunk_ids → 清空则删边 → 孤立节点删
```

**边的生命周期 = 引用它的 chunk 的生命周期，天然正确**：
- 文档删一段 → 该段所在旧 chunk_id 不在新集合 → 只由旧 chunk 支持的边自动删除；多 chunk 共享的边保留
- 文档整体删除 → 现有 DELETE action 直接复用

两处微调：
- 执行时机：从"更新前全清"改为"更新后清"（配合 3.3，失败时旧数据保留）
- 精度：`WHERE cid IN 旧前缀 AND cid NOT IN $keep_chunk_ids`——只删不存在的引用

### 3.5 注意点：evidence 悬空

边的 evidence_snippets 来自旧 chunk（store.py:42）；引用计数删除时若边幸存（还有其他 chunk 支持），旧 chunk 贡献的 evidence 摘录悬空。实现时顺带把被移除 chunk 对应的 evidence 移除，或接受"证据冗余但不错误"。

### 3.6 落地成本

| 事项 | 成本 | 说明 |
|---|---|---|
| chunk_id 改造 | 中 | 一次全量重灌迁移（Qdrant/ES/Neo4j 重建）——**现在数据量小，正是时候，越晚越贵** |
| 入库顺序调整（先写后清） | 低 | pipeline 两处改动，顺带解决 P0-2 原子性 |
| chunk 级 skip 判重 | 低 | 复用 hash_guard 思路，粒度降到 chunk |
| purge 增量化（keep 集合） | 低 | cleanup.py 传参 |
| kbId 并入 source_name | 低 | 堵多库串数据 |

**收益**：内容不变的 chunk 全部跳过 LLM 抽取（图入库最大成本项）；图谱更新从"数分钟全量"降到"秒级局部"；获得失败原子性。

**建议**：图增量与向量/ES 侧一起改（同 chunk_id + 先写后删一次落地），避免两边标识不一致二次迁移。

---

## 4. 待确认事项

1. **文档稳定 UUID 来源**：Java 侧是否已有文档 ID（kbId+文件名可作组合键，或 Java 生成 UUID 随 payload 下发）
2. **重灌迁移时机**：chunk_id 改造的一次性全量重灌安排在何时（现在数据量小，建议尽快）
3. **Kafka 可靠性升级**：手动 commit / 重试 topic / DLQ 的取舍（当前量级是否需要）
4. **增量效果实测**：重灌后对"只改一段"的文档跑一次更新，验证 skip 率与耗时
