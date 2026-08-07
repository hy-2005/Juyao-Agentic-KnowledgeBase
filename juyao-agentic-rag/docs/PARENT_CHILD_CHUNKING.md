# 父子分块 + 结构化识别方案

> 状态：🔄 进行中（父子分块/结构化识别已完成；PDF 表格布局/子块大小验证遗留） · 创建：2026-08-07 · 更新：2026-08-07
> 范围：切分层（结构识别 + 父子生成）+ 检索层（子块检索 → 父块映射聚合）
> 关联文档：CHUNK_SPLITTING_REVIEW.md（§4 目标流程）、INGESTION_UPDATE_REVIEW.md（chunk_id 增量）、RETRIEVAL_REVIEW.md（检索漏斗）

---

## 1. 背景

用户确认采用**父子 chunk 策略**（Small-to-Big）：子块做 embedding 检索（精准命中），父块提供生成上下文（完整语义）。同时补上当前缺失的结构化识别：标题层级、代码块、表格。

## 2. 现状缺口（代码事实）

| 元素 | 现状 | 位置 |
|---|---|---|
| Markdown 标题 | 只保留 `#` 符号，切分不感知层级 | loaders.py / span_utils.split_paragraph_spans |
| 代码块 | 无识别（围栏代码当普通段落，软切会切断代码） | 无 |
| docx 标题 | 样式丢失（只取 p.text 不看 p.style.name） | loaders.py _load_docx_as_text |
| 表格（docx/csv） | 单元格 tab 连接提取，切分可能拆散表格行 | loaders.py |
| 表格（PDF） | 无布局保留，get_text 顺序混乱 | loaders.py PDF 分支 |
| 父子关系 | 无（单层 chunk，检索与生成同粒度） | - |

## 3. 主流父子方案参考

- **LangChain ParentDocumentRetriever**：子块（128-256 token）embedding 检索 → 按 parent_chunk_id 映射父块 → 父块去重 → rerank → 生成；RRF 融合在**父块名次层面**
- **LlamaIndex AutoMergingRetriever**：层级树（叶子→中间→根），命中阈值内自动合并到父块；复杂度高，两层够用时不用
- **混合检索共识**：向量路检索子块、BM25 路检索父块（或子块再映射）；多子块命中同一父块 → 合并；rerank 在父块层面

## 4. 落地方案

### 4.1 切分层改造

```
① 结构识别（父块边界）：
   - 标题层级：md 的 # 前缀 / docx Heading 样式 → 按标题切父块，标题路径进元数据
   - 代码块：``` 围栏整体作为一个父块（不参与句子软切）
   - 表格：docx/csv 表格、md 表格 → 整个表格一个父块
   - 其余正文：现有规则切分（段落→句边界）+ LLM 语义介入（无结构文本）
② 父子生成：
   - 父块（≈ 现有 chunk_size 粒度）→ 再切子块（128-256 字，句边界）
   - 子块 metadata：parent_chunk_id / parent_start / parent_end；父块 metadata：child_ids
③ 存储：
   - 父块 → Qdrant + ES（正文检索/BM25）
   - 子块 → Qdrant（embedding 检索），同 collection 加 chunk_type=parent|child 字段
④ chunk_id 兼容：
   - 父块：{kb}:{doc}:{正文hash}（现有内容寻址不变）
   - 子块：{父chunk_id}:sub:{子文本hash}
   - 增量方案（INGESTION_UPDATE §3.2）不受破坏
```

### 4.2 检索层改造（search_context）

```
① 向量路：子块 top_k=30 → 按 parent_chunk_id 映射聚合 → 父块去重（同源合并）
② BM25 路：父块 top_k=15（标题/表格关键词在父块正文）
③ RRF 在父块名次层面融合（fusion.py 只认名次，天然适配，零改动）
④ rerank 父块（rerank_top_n 不变）
⑤ 返回父块 → 生成（上下文完整）
```

### 4.3 配置

```
chunk_parent_enabled: bool = False   # 开关（默认关→开，灰度）
child_chunk_size: int = 200          # 子块大小（字符）
parent_chunk_size 复用 chunk_size    # 父块大小
chunk_type 字段用于检索过滤与调试
```

### 4.4 兼容性

- fusion.py RRF 只认名次 → 父子映射后直接复用 ✓
- kb 隔离：子块 metadata 带 kb_id（Qdrant filter 不变）✓
- SSE 契约：citations 返回父块 chunk_id（子块不对外）✓
- 单测：结构识别（标题/代码块/表格边界）、父子映射聚合（多子块→一父块）补测试

## 5. 实施范围与顺序

| 步骤 | 内容 | 文件 |
|---|---|---|
| 1 | 结构识别：md 标题 / docx Heading / 代码块 / 表格 | domain/chunking/span_utils.py、infrastructure/loaders.py |
| 2 | 父子生成：父块 → 子块切分 + 元数据 | domain/chunking/splitter.py |
| 3 | 存储：子块写 Qdrant（chunk_type 字段） | infrastructure/qdrant.py、application/ingest_flow/ingest.py |
| 4 | 检索改造：子块检索 → 父块映射聚合 → RRF/rerank | domain/retrieval/retriever.py |
| 5 | 配置开关 + 单测 + 重灌评测对比 | core/config.py、tests/ |

依赖：终评对比完成后实施（当前代码基线先存档）；实施后重灌评测数据做前后对比。

## 6. 实施记录（2026-08-07）

**已实现**：
- `span_utils.split_structural_blocks`：结构化块识别（md 标题/代码块围栏/markdown 表格），修复段落吞标题/表格 bug；真实文档验证（fastapi 30 标题+12 代码块、pandas 13 标题+1 表格+5 代码块）
- `splitter.build_parent_blocks`：结构感知父块（标题聚合/代码块表格独立/段落超限细分）
- `splitter.split_into_parent_child_chunks`：父块 chunk_type=parent+child_ids、子块 chunk_type=child+parent_chunk_id（内容寻址，增量方案兼容）
- `ingest`：chunk_parent_enabled 时父块写 ES+Qdrant、子块写 Qdrant（同一 collection，chunk_type 区分）
- `retriever._vector_topk`：子块命中 → parent_chunk_id 映射聚合父块去重
- 配置：`chunk_parent_enabled`（默认 False 灰度）、`child_chunk_size=200`

**验证数据**：
- 若依中文 README：13 父块 + 54 子块（标题聚合正常，中文句子边界完整）
- pandas README：表格独立成父块 ✓
- 检索映射："pandas 如何读取 CSV" → 子块命中映射 5 个父块（含代码块/标题聚合父块）✓

**遗留**：PDF 表格布局保留（get_text 方案表格质量差，优先级低）；子块大小 200 是否最优（跟随统一参数校准）。
