# Chunk 拆分方案评审与规划

> 状态：🔄 进行中（预分批/规则主通道/父子分块已完成；多模态/Contextual Retrieval 待办） · 更新：2026-08-07
> 范围：juyao-agentic-rag 文档切分链路（`rag_core/ingestion/`）
> 配套代码：`splitter.py`（入口）、`split_ai.py`（LLM 语义切分）、`split_spans.py`（span 算法）、`loader.py`（解析）、`config.py`（配置）
> 关联文档：`RETRIEVAL_REVIEW.md`（检索层面评审）、`GRAPH_QUERY_REVIEW.md`（图谱查询评审）、`INGESTION_UPDATE_REVIEW.md`（文档更新/增量入库；chunk_id 改造方案）

---

## 1. 背景

针对 RAG 系统 chunk 拆分环节做全面评审，当前主要关注：

1. chunk 拆分流程是否合理、是否真正生效
2. 拆分结果与 embedding 模型 / 检索链路是否匹配
3. 后续是否支持多模态（图片、表格、扫描件）的拆分方案

---

## 2. 现状：完整拆分链路

```
上传(Kafka juyao.rag.documents)
  → loader.load_document()        解析：txt/md → 多编码文本；PDF → PyMuPDF 抽文本；
                                  docx → python-docx 抽段落+表格文本；csv → 多编码表格
  → splitter.split_into_chunks()  切分入口：
      ① build_semantic_spans()     LLM 语义切分（主通道）
      ② apply_overlap()            左右字符扩展 overlap
      ③ enrich_chunk_metadata()    写 chunk_id / source_doc_id / span 元数据
  → 三路索引：Qdrant(向量) / Elasticsearch(全文) / Neo4j(图)
```

### 2.1 关键配置（config/default.toml）

| 参数 | 当前值 | 含义 |
|---|---|---|
| chunk_size | 800 | LLM 软参考目标字数（字符） |
| chunk_max_chars | 1400 | 硬上限（字符），overlap 扩展后上限 1640 |
| chunk_overlap | 120 | 左右各扩展字符数 |
| chunk_ai_split_enabled | true | 是否启用 LLM 语义切分 |
| chunk_split_mode | marker | marker=整篇插 `<<<<CUT>>>>` 标记；auto=多一个 JSON 窗口断点路径 |
| embed_model | mxbai-embed-large (Ollama) | **上下文窗口仅 512 token** |
| chunk_llm / chunk_gen_model | .env 中配置（值未确认） | 切分专用 LLM |
| chunk_llm_timeout_s | 300 | 单次切分调用超时 |

### 2.2 LLM 语义切分的工作方式（split_ai.py）

- **marker 模式（默认）**：整篇原文一次发给 LLM，要求只插入 `<<<<CUT>>>>` 标记并逐字回传全文 → 解析切点
  - strict 校验：去掉标记后与原文逐字相同（`build_spans_from_marked_text`）
  - regex 宽松校验：标记间片段在原文按序定位，slack ≤ 50 字符（`extract_spans_by_cut_markers`）
  - 两者都失败 → 整篇视为一块，按 1400 字符 + 句号附近硬切兜底
- **auto 模式**：额外支持"候选单元（180 字）→ LLM 选断点"的 JSON 窗口路径
- 规则兜底：空行分段落 → 超长段落按强标点（。！？；）→ 弱标点（，：）→ 换行 → 空格 回溯找软切点

---

## 3. 问题清单

### 🔴 P0：chunk 长度远超 embedding 模型上下文窗口（✅ 事实修正 2026-08-07：不成立）

- **位置**：config.toml（chunk_size=800 / chunk_max_chars=1400）；dashscope_embeddings.py:32 无截断处理
- **原问题**：embedding 模型 mxbai-embed-large 窗口仅 **512 token**，1400 中文字符 ≈ 1400-2100+ token 为窗口 3-4 倍
- **事实修正**：实际 .env 用 **dashscope text-embedding-v4（8192 token 窗口）**，1400 字符不超窗——P0 不成立，降级为**参数校准**（网格 600/800/1000 进行中，见 CALIBRATION_DECISION.md）
- **保留风险**：若部署切换回 Ollama mxbai-embed-large（512 token），必须同步缩小 chunk——参数与 embedding 模型强耦合，切换部署环境时注意

### 🔴 P1：整篇一次交 LLM，长文档 100% 走兜底硬切

- **位置**：split_ai.py:193 `split_by_llm_direct`（无长度预分批）
- **问题**：
  - 整篇原文 + 回传全文（输出 ≈ 输入长度），18-23KB 小说 ≈ 2 万+ token 输入 + 2 万+ token 输出，必超窗口或触发截断
  - strict 校验对任何细微差异（漏字/改标点/截断）直接失败；regex 宽松模式对片段改写也失败
  - 失败后 marker 模式兜底 = 整篇一块按 1400 字符硬切 → **LLM 语义切分在长文档上实际不生效**
- **影响**：当前上传的 5 篇小说（最长 23KB）大概率全部走规则硬切；日志中未发现"【语义切分】成功"记录，需确认实际运行模式
- **修复**：LLM 切分前按 6000-8000 字符预分批，每批单独切分后拼接 span

### 🟡 P2：chunk 无文档上下文（Contextual Retrieval 缺失）

- **位置**：splitter.py:115（metadata 仅 source_name）
- **问题**：chunk 是孤立文本片段，不含"属于哪份文档 / 哪个章节 / 哪个条款"的上下文。query 常含文档级信息（如"合同里怎么交货"），而 chunk 里没有"合同/交货"字样 → 检索不到
- **修复**：入库前用便宜 LLM 为每个 chunk 生成 1-2 句文档级上下文摘要拼进 chunk（Contextual Retrieval）；或做父子分块（检索小块、返回父块）

### 🟡 P3：无结构感知，所有文档类型一套切分

- **位置**：split_ai.py / split_spans.py（纯语义/纯字符）
- **问题**：
  - 合同（"第X条/1.1"条款结构）、报告（【】标题）、小说（"第一章"）的结构边界比语义相似度更可靠的切点，完全未利用
  - 结构切分失败时，切出的 chunk 跨条款/跨章节
  - PDF 抽文本通常无空行分段，`split_paragraph_spans` 把整页当一个段落 → 直接硬切
- **修复**：切分前先扫结构边界（`第[一二三四五六七八九十百]+条`、`第[一二三四五六七八九十]+章`、`【...】`），有结构走结构切，无结构才走 LLM/规则切；chunk 元数据带章节路径

### 🟡 P4：overlap 实现粗糙

- **位置**：split_spans.py:89 `apply_overlap`
- **问题**：纯字符扩展，overlap 区域可能从句子中间开始/结束；相邻 chunk 重复文本同时命中 Top-K（无去重，RRF 部分缓解）；长 span 扩展后被迫收缩 overlap（上限 1640）
- **修复**：overlap 按句子边界取整；检索端对同源 chunk 去重

### 🟡 P5：LLM 切分成本与时延

- **问题**：每次入库 = 一次输入+输出均 ≈ 全文长度的 LLM 调用（23KB 文档 ≈ 4 万+ token）；300s 超时；Kafka 并发 3
- **修复**：配合 P1 分批方案，单批调用成本可降 10 倍+；失败时降级更快

### 🟢 P6：编码与损坏文件处理

- **位置**：loader.py:8 `load_text`（utf-8 → utf-16 → gbk）
- **问题**：`sample_medical.txt`（148B 乱码）三编码全失败会抛异常，整篇入库失败且无告警跳过；GB18030 等编码未覆盖
- **修复**：加 GB18030；失败时标记损坏并告警跳过，不阻断整批

### 🟢 P7：chunk_size 与 chunk_max_chars 耦合隐晦

- **位置**：config.py:166 `get_chunk_max_chars`（默认 max(size+400, size*1.5)）
- **修复**：显式配置；或按 embedding 窗口统一推导

---

## 4. 目标拆分流程（纯文本正规做法）

```
文档 → 解析层（按类型分流）
         ├─ PDF：抽文本 + 保留标题层级/段落边界（扫描件走 OCR）
         ├─ docx：按 heading 样式还原结构
         ├─ txt/md：按空行/标题符号分段
     → 文档对象树（章节/小节/段落/表格节点，带层级路径）
     → 分块：
         ① 结构感知切分：有标题/条款的文档按结构边界切，
            块带章节路径元数据（如"销售合同 > 第一条 > 1.2"）
         ② 超长块递归细分：标题 → 段落 → 句子
            （中文 separators：段落→句号→分号→逗号）
         ③ 块大小按 embedding 模型 token 窗口定（≤512 token）
         ④ overlap 10-15%，按句子边界取整
     → 语义优化（可选）：LLM 语义切分只在规则兜不住时用（无结构长文本），
       且按 ≤ 窗口大小分批喂
     → 上下文增强：Contextual Retrieval 摘要 或 父子分块
```

原则：**结构边界 > 语义相似度 > 字符切**。LLM 语义切分降级为补充手段，不是主通道。

---

## 5. 多模态扩展路径（现状：未实现多模态）

> ⚠️ 现状澄清：当前代码无任何多模态处理——PDF 只抽文本不抽图、无 OCR、无图像 embedding、生成模型 qwen3.6-35b-a3b 为纯文本模型。已实测当前样本 `工地建设工程落地手册.pdf`：6 页纯文本、0 张图片，恰好未踩坑。

### 5.1 解析层扩容

| 输入 | 正规做法 |
|---|---|
| 文本型 PDF | PyMuPDF 抽文本 + 布局分析（get_text("dict") 拿坐标，识别标题/表格/图片锚点） |
| 扫描型 PDF / 图片 | OCR（RapidOCR/PaddleOCR）+ 版面分析 |
| docx | 保留 style.name（Heading 1/2...）重建结构树，图片单独抽取 |
| 纯图片（jpg/png） | 直接走图片通道 |

### 5.2 内容分通道拆块

```
文档对象树节点打类型标签：
  ├─ text 节点  → 正常文本切块，chunk 保留图片占位符 [IMAGE: img_0003]
  ├─ table 节点 → 转 Markdown 表格，一个表格一个 chunk（>20 行再按行分）
  └─ image 节点 → 一个"图文单元"：
        ① 图片存对象存储
        ② 视觉 LLM（qwen-vl-max 等）生成 caption
        ③ 单元 = 图片 URL + caption + 上下文文本（图前 300 字 + 图后 300 字）
        ④ caption+上下文进文本向量库；可选 CLIP 类图像 embedding 进独立集合
```

### 5.3 索引与检索

- **轻量路径（推荐先做）**：caption + 上下文拼成文本 chunk → 复用现有 Qdrant/ES；答案生成时把图片 URL 传给视觉模型
- **重量路径（后期）**：图像 embedding 独立 collection（clip-ViT / qwen-vl 视觉向量），或 ColPali 类整页多模态向量化
- **配套**：生成模型需支持视觉输入（qwen-vl 系列）

### 5.4 多模态落地优先级

1. 轻量路径：图片 → 视觉模型 caption → 文本 chunk（1 天内可接入，完全复用现有链路）
2. 解析层 OCR + 布局保留（扫描件/带图 PDF 现在会静默丢信息，最隐蔽）
3. 图像 embedding 双轨（重，后期再说）

---

## 6. 落地路线图

| 优先级 | 改动 | 涉及文件 | 收益 |
|---|---|---|---|
| P0-1 | chunk_size 压到 400-600 字符（或换 embedding 模型） | config | 立竿见影，零代码 |
| P0-2 | LLM 切分长文档预分批（6000-8000 字符/批） | split_ai.py | 长文档语义切分真正生效 |
| P1 | 结构优先切分（条款/章节/标题） | split_ai.py / 新增 | 合同、报告检索质量提升 |
| P2 | Contextual Retrieval（chunk 上下文摘要） | splitter.py + pipeline | 检索召回显著提升 |
| P3 | overlap 句子边界 + 同源去重 | split_spans.py | 边界更干净 |
| P4 | 编码补充 GB18030 + 损坏文件告警跳过 | loader.py | 容错 |
| P5 | 多模态轻量路径（caption） | loader + 新增 | 支持图片内容 |

重灌策略：切分策略变更 → chunk_id 变化 → 按 source_doc_id 增量重灌（现有 hash_guard 机制）。

---

## 7. 待确认事项（后续讨论）

1. **.env 实际配置**：CHUNK_GEN_MODEL / CHUNK_LLM_BASE_URL / EMBED_MODEL 实际值（决定窗口判断与成本估算）
2. **实际运行日志**：Python 侧是否有"【语义切分】"成功/失败记录，确认长文档当前真实走的路径
3. **embedding 模型选型**：是否可换 ≥2048 token 窗口的模型（如 bge-m3 / text-embedding-v3）
4. **chunk 大小取舍**：400 vs 600 字符对检索质量的影响，是否需要小批量实测对比
5. **多模态范围**：是否需要支持纯图片上传 / 扫描件 PDF / 表格为主文档
6. **GraphRAG 配合**：chunk 变更后 Neo4j 图谱是否需要重灌（ingest_graph_workers 已有，确认成本）
