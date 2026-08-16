# 开发踩坑记录（PITFALLS）

> 维护规则（见 CLAUDE.md）：**每个踩坑必须记录到本文件**——现象、根因、修复、教训。
> 创建：2026-08-07
> 更新：2026-08-14

---

## 1. 目录重组合并文件时丢失模块级常量

- **场景**：阶段 4 目录重组，`knowledge_graph/client.py` + `store.py` 合并为 `infrastructure/neo4j.py`
- **现象**：图谱入库 triples=0，日志 `name '_UPSERT_RELATED' is not defined`
- **根因**：合并脚本从 `class Neo4jTripleStore:` 截取 store.py，**模块级 Cypher 常量 `_UPSERT_RELATED`（类定义之前）被丢弃**
- **修复**：从完整模板重建常量
- **教训**：合并文件时检查模块级常量/函数是否都在类定义之外；合并后必须跑端到端写入验证，不能只看 import 成功

## 2. 先写后删按 source_name 整体删 → 新数据被误删（库清空）

- **场景**：P0-2 原子性修复"先写后删"后，重灌故事文档 Qdrant 变 0 points
- **现象**：终评 context_recall=0.0（检索全部 0 命中），Qdrant points_count=0
- **根因**：purge 按 `(source_name, kb_id)` 过滤删除，而**新写入的数据也是同 key**（只有 chunk_id 的 content hash 前缀不同）→ 差集清理未实现前，purge 把新旧一起删光
- **修复**：写入前快照旧 chunk_id 列表（`_collect_existing_chunk_ids`），写成功后按「旧 id − 新 id」差集精确删除（`delete_chunks_by_ids`）
- **教训**："先写后删"的删除必须按 chunk_id 差集，不能按文档级 key——新旧数据同 key 是常态

## 3. Qdrant filter 的 key 路径：metadata.kb_id（嵌套）而非 kb_id（顶层）

- **场景**：kbId 贯通后检索/删除 filter 不生效
- **现象**：`filter kb_id=0` 返回 0 条（数据明明有 kb_id=0）；DELETE(kb=1) 删不掉
- **根因**：langchain-qdrant 的 payload 是 `{page_content, metadata: {...}}` 嵌套结构，kb_id 实际路径是 **`metadata.kb_id`**；顶层 key 匹配不到静默返回空
- **修复**：所有 Qdrant filter（检索/判重/删除）统一用 `metadata.kb_id`
- **教训**：Qdrant payload 结构必须先查实际数据再写 filter；静默空结果最危险（不报错）

## 4. kb=0 不过滤会串库（filter 不能"只在 kb>0 时加"）

- **场景**：设计"kb=0 单库不加 filter 兼容旧数据"——意图是好的
- **现象**：kb=0 检索命中 kb=1 的文档（跨库泄露！）
- **根因**：库里同时有 kb=0 和 kb=1 数据时，kb=0 不带 filter = 检索全部
- **修复**：只要明确传了 kb_id 就过滤（含 0）；旧数据（无 kb_id 字段）靠重灌消除
- **教训**：租户隔离的 filter 必须无条件生效，"兼容旧数据"的捷径会变成数据泄露

## 5. LLM 语义切分 marker 模式失败率极高（100% → 部分）

- **场景**：切分链路初版 LLM 主通道
- **现象**：两次入库（72 字符 + 8078 字符）全部"标记解析失败"走硬切兜底；deepseek 回传的文本常被改写（漏字/改标点）导致 strict/regex 校验失败
- **根因**：marker 模式要求 LLM **逐字回传整篇原文+标记**——模型输出不稳定时校验必失败；整篇一次提交超出模型可靠处理长度
- **修复**：① 长文本按段落贪心预分批（CHUNK_DIRECT_MAX_CHARS=4000）② 切分优先级反转——**规则切分主通道，LLM 仅对无空行/超大段落文本介入优化**，失败自动回退规则
- **教训**：LLM 输出不可复现（同文重切结果不同：6/8/7 chunks）——语义切分只能做补充，不能做主通道

## 6. 全角破折号漏在映射表外

- **场景**：实体归一化全角转半角
- **现象**：`ＺＴＥ－９０００` → `ZTE－9000`（破折号没转）
- **根因**：`str.maketrans` 映射表只列了数字/字母/括号/逗号等，漏了 `－`（U+FF0D）、`～`、全角空格（U+3000）
- **修复**：补全常见全角字符映射
- **教训**：字符映射表要覆盖"实体名里可能出现的所有全角标点"——破折号/连字符在型号名里很常见

## 7. 新增代码引用未 import（re / get_settings / get_qdrant_client / UnexpectedResponse）

- **场景**：query 分级、差集清理等增量修改
- **现象**：运行时 `NameError: name 're' is not defined` 等，每次只暴露一个
- **根因**：在已有文件追加函数时，新函数用到的模块级 import 未补（原文件恰好没 import re）
- **修复**：逐个补 import；`python -m compileall` 只能查语法不能查名字
- **教训**：**追加代码后必须跑真实调用路径**（不是 compileall），或在函数内 import（惰性）避免模块级遗漏

## 8. Neo4j 跨连接因果不一致：DELETE 后新连接 MERGE 读到旧快照

- **场景**：社区构建 reset（DELETE 全部 Community）后立即 MERGE 重建
- **现象**：`ConstraintError: Node(N) already exists with label Community and property id='kb0:community:1'`——明明 DELETE 了，MERGE 却说节点已存在；节点号每次 +1（每次真的创建了新节点）
- **根因**：reset 用 store 实例 A，_store_community 用新 store 实例 B——**不同 Neo4jGraph 连接之间 DELETE 的写入对 B 不可见**（驱动连接级因果不一致）
- **根因（已定位）**：**MERGE 模式中未绑定的约束节点**——`MERGE (e)-[:MEMBER_OF]->(c:Community {id: $cid})` 里 `c` 未先绑定，唯一约束索引匹配 miss 时 MERGE 尝试**创建 c** → 约束检查发现已存在 → ConstraintError。Node 号递增 = 每次真的尝试创建被拦截（事务回滚）
- **修复**：边语句改为**显式 MATCH 先绑定**——`MATCH (c:Community {id: $cid})` 再 `MERGE (e)-[:MEMBER_OF]->(c)`；reset/ensure/写入同一 session 串行 + 原生驱动
- **验证**：10 社区构建成功、78 实体覆盖、0 重复
- **教训**：**MERGE 模式里带唯一约束的未绑定节点是陷阱**——约束节点必须先 MATCH 再 MERGE 关系；排查过程：手动成功 → 程序失败 → 逐语句拆分定位（错误来自"边语句"而非"节点语句"）——**保留程序内最小复现逐语句排查**

## 9. Neo4j 5.x 语法：size() 模式表达式被废弃

- **场景**：社区实体计数 `size((:Entity)-[:MEMBER_OF]->(c))`
- **现象**：`CypherSyntaxError: A pattern expression should only be used in order to test the existence of a pattern`
- **根因**：Neo4j 5.x 不允许在 size() 里用模式表达式
- **修复**：改 `COUNT { (:Entity)-[:MEMBER_OF]->(c) }`（COUNT 子查询）
- **教训**：Neo4j 4→5 有语法迁移（size 模式 → COUNT 子查询），写 Cypher 前确认版本

## 10. LLM 输出 think 块污染摘要

- **场景**：社区摘要生成（deepseek 模型）
- **现象**：Community.summary 存了 `<think>...</think>` 思考内容
- **根因**：deepseek 默认输出思考块，prompt 只约束"不要思考过程"不够
- **修复**：Python 侧正则剥离 `<think>...</think>`（`_THINK_BLOCK_RE`）
- **教训**：对输出不稳定模型（deepseek）的处理：prompt 约束 + 代码兜底剥离双保险

## 11. 评测基线被旧数据污染 / 全 0 指标的"假失败"

- **场景**：终评对比
- **现象**：story_qa 全 0（faithfulness 0.056, recall 0.0）——第一次以为检索坏了，实际是**库被清空**（坑 #2）；第二次以为是数据问题，实际是**读了旧评测文件**（15:04 的旧 JSON 未被覆盖）
- **根因**：① 先写后删 bug ② 评测任务失败时旧 reports 文件残留
- **修复**：① 差集清理 ② 核对 reports 文件时间戳
- **教训**：异常指标先查"数据在不在 + 文件是不是新的"，再查逻辑

## 12. 校准/评测时默认配置被临时修改后未恢复

- **场景**：chunk_size 参数校准（600/1000 网格）
- **现象**：default.toml 被改成 1000/1600，校准完成忘了恢复
- **根因**：校准流程改配置 → 评测 → 决策，恢复环节遗漏
- **修复**：校准前备份（`cp default.toml /tmp/...`），完成后恢复并 grep 确认
- **教训**：临时改配置必须配套"恢复 + 验证恢复"步骤；校准结论写进决策文档时同步恢复配置

---


## 13. 合并分支时旧路径代码覆盖新结构 + 功能文件丢失

- **场景**：合并另一个开发分支的 admin 管理功能（chunks/graph 页面）到重组后的 main
- **现象**：`ModuleNotFoundError: No module named 'rag_core.indexing'`（合并代码引用旧目录）；`admin_queries/admin_mutations` 模块完全缺失（路由引用了但实现没合进来）；前端 `api/rag.js` 的 kb 管理 API 被覆盖丢失
- **根因**：① 合并来源基于**目录重组前**的代码（indexing 还在时写的 import）② 合并只带了"路由/前端/Java"，**支撑函数没带** ③ api/rag.js 整体被旧版本覆盖
- **修复**：① 用 module_map 映射修旧路径（indexing → infrastructure、knowledge_graph → domain.graph.query）② 按路由调用签名**补建** admin_queries.py + admin_mutations.py（基于现有 domain/graph 能力）③ kb API 重新补回
- **验证**：55 测试全绿（含 4 个 admin 测试）；admin API 实调（stats/list/mutation）；Java 编译；前端构建
- **教训**：合并前先 `git diff` 确认受影响文件；合并后**三端全量验证**（compileall + pytest + mvn + npm build）——特别是**被修改过的文件**（api/rag.js、elasticsearch.py）要 diff 确认我们的改动还在

## 14. qdrant-client 的 scroll() 返回 pydantic Record 对象而非 dict

- **场景**：实现子块查询（children 接口 scroll `metadata.parent_chunk_id`）时
- **现象**：冒烟 `AttributeError`——`point.get("payload")` 报错，point 不是 dict
- **根因**：对 qdrant-client 返回类型假设错误——`scroll()` 返回的是 pydantic `Record` 对象而非 dict，直接按 dict 取字段必崩
- **修复**：取字段前先归一化——`if not isinstance(point, dict): point = point.model_dump()`
- **教训**：调用外部 SDK 前先确认返回对象类型（或先跑一次真实调用），不能凭经验假设返回 dict

## 15. Neo4j `purge_chunk_ids` 用 chunk_ids 当 filter 清 doc_ids —— 跨字段语义错误

- **场景**：`infrastructure/neo4j.py:Neo4jTripleStore.purge_chunk_ids` 先写后删差集清理
- **现象**：原 Cypher `SET r.doc_ids = [d IN coalesce(r.doc_ids, []) WHERE NOT d IN $chunk_ids]` 看起来"顺手也清 doc_ids"，但 **chunk_ids 存的是 chunk_id（`source_doc_id:idx:digest`），doc_ids 存的是 source_doc_id（`kb_id:safe_name:digest`），两个字段是不同字符串**——过滤条件不会命中，实际行为是 doc_ids 保持原状（看似无害，但语义错误 + 误导）
- **根因**：① 字段语义混淆（chunk_id ≠ source_doc_id） ② 想"顺手清理"的思维陷阱（觉得删 chunk_ids 时 doc_ids 也应该跟着）—— 但 doc_ids 是文档级引用，跟 chunk 级删除解耦
- **修复**：移除 `r.doc_ids = ...` 那行，只清 `r.chunk_ids`；docstring 写明"不动 doc_ids"和跨 kb 共享边的保留逻辑
- **教训**：**用 A 字段当 filter 去改 B 字段前，必须先验证两个字段的取值空间是否真的相交**——这里是不同字符串，硬套同 filter 是错误语义；代码注释里说"清空引用后删边"就够了，不要"顺手"清无关字段

## 16. Spring Boot `${VAR:default}` 占位符：空字符串 ≠ null，会覆盖默认值

- **场景**：Java 管理端 `application.yml:internal-token: ${RAG_INGEST_INTERNAL_TOKEN:"hejuyao"}` 与 Python RAG `.env:RAG_INGEST_INTERNAL_TOKEN=hejuyao` 都想用 token 鉴权防止 8000 端口直连
- **现象**：所有 chat/sessions 请求都 403；Python 端诊断日志 `expected_len=7 expected_preview=heju***`，Java 端 `got_len=0 got_preview=<EMPTY>`
- **根因**：IntelliJ Run Configuration 把 `RAG_INGEST_INTERNAL_TOKEN` 环境变量设成了**空字符串**（某些"清空配置"操作会把变量值清成空但保留键名）；Spring Boot `${VAR:default}` 占位符在变量值为**空字符串**时**不会 fallback 到 default**，而是直接用空字符串 → Java 端 `internalToken=""` → 发出去的 header 是空 → Python 端期望 `hejuyao` 必 403
- **修复**：① 临时——把 Python `.env` 的 `RAG_INGEST_INTERNAL_TOKEN=` 留空（本地开发模式直接放行） ② 治本——`application.yml` 默认值改成 `${RAG_INGEST_INTERNAL_TOKEN:}`（空字符串默认 = 不校验），生产环境靠环境变量强制注入
- **教训**：**Spring `${VAR:default}` 占位符的 fallback 语义对空字符串不生效**——空字符串是合法值；想"未设置 = 走默认"必须确认环境变量是 unset 而不是 `=`；配置文件里默认值用空字符串而不是具体字符串，让"未设置 = 不校验 / 设置 = 启用"语义更清晰；Java/Python 跨端鉴权必须在两端启动日志打 token 长度+前缀方便对比（前面诊断日志改动一并落地）

## 17. 意图路由规则硬编码 → 配置化（intent_rules.yaml + intent_rules.py）

- **场景**：`application/chat_flow/steps/route.py:route_question_intent_rules` 之前用 4 个模块级正则（`_VECTOR_LITERAL_RE`/`_GRAPH_COMPLEX_RE`/`_MULTI_ENTITY_AND_RE`/`_DIRECT_GREETING_RE`）做意图快路径判定
- **现象**：① 加一条规则要改源码 + 重启服务 ② 没有可观测性——不知道某次请求命中哪条规则 ③ 没有置信度——只命中/不命中，无法做"半信半疑" ④ direct 路径**完全靠字符串长度 + 问候词正则**判定（不调 LLM），"价格？"等短查询会被误判为 direct
- **根因**：规则引擎天生适合数据驱动，硬编码是把"业务策略"塞进"代码逻辑"——策略迭代速度慢于工程能力
- **修复**：
  - `config/intent_rules.yaml` 定义规则（name/branch/type/patterns/min_length/max_length/case_insensitive/description）
  - `src/rag_core/domain/routing/intent_rules.py` 提供 `load_intent_rules` / `match_rule` / `route_by_rules` 三个核心函数
  - `route.py` 启动时预加载（`load_intent_rules`），优先用 YAML；YAML 不存在/解析失败时回退硬编码默认（保持向后兼容）
  - 命中时打印 `matched_rule=<name> branch=<branch>`，便于排查 + 收集真实流量命中分布
- **优先级规则**（冲突解决）：
  1. direct 命中即返回；strict 模式下退化为 vector_only
  2. graph_only 之间是 OR（首个命中即生效）
  3. vector_only 仅在没有任何 graph_only 命中时生效
  4. 都没命中 → None，进 LLM
- **教训**：**业务规则（判定策略/特征词表/阈值）应该配置化，不应该硬编码**——硬编码规则迭代速度 = 工程发布节奏；配置化规则迭代速度 = 业务人员改 YAML 节奏；规则本身需要可观测（命中日志/计数）才能基于真实流量打磨；规则引擎通用化不一定要上 LLM，先把规则本身的数据驱动做到位就解决 80% 的可调性问题

## 18. 双写源不同步：代码 Field default 改了但 config/default.toml 还有旧值覆盖

- **场景**：`src/rag_core/core/config.py:min_relevance_score` 从 0.35 调到 0.5，`min_relevance_relative_ratio` 从 0.6 调到 0.0（相对截断关闭）
- **现象**：改完代码后实跑 `get_settings()` 仍然读到 `min_relevance_score = 0.35`——因为 `config/default.toml:48` 还有 `min_relevance_score = 0.35`，**toml 优先级高于代码 Field default**，代码改了没用
- **根因**：pydantic-settings 的优先级是 **环境变量 > .env > config/local.toml > config/default.toml > 代码 Field default**——代码里的 default 只是最底层 fallback，**config/default.toml 里显式写了的 key 永远覆盖代码默认值**
- **修复**：`config/default.toml` 同步改为 `min_relevance_score = 0.5`（并把相对截断比例保持默认 0，见 #19）；以后改配置类默认值必须**两处都改**（代码 + default.toml），改完跑一次 `get_settings()` 验证实际读到的值
- **教训**：**pydantic-settings 的"默认值"是代码 Field default 与 default.toml 的双写源**——改了代码 Field default 不更新 default.toml = 改动无效；配置验证必须"读实际值"而不是"看代码改了没有"

## 19. 相对截断（min(绝对, 最高分×比例)）的"自动放水"风险 → 改为纯绝对阈值

- **场景**：`retriever._retrieve_for_single_query` 的向量过滤门槛 `threshold = min(min_relevance, max_vec_score * rel_ratio)`（P1 相对截断，默认 ratio=0.6）
- **现象**：整库最高分低（0.20/0.10）时，相对比例把 threshold 压到 0.12/0.06——**几乎不设防**，弱相关 chunk 大量进 RRF → LLM 拿到低相关证据强行凑答案 → "假 KB 依据"幻觉
- **根因**：相对截断假设"最高分高=库里有好答案，最高分低=库里没相关"——但"最高分低"恰恰是**"整个库都偏离 query"**的信号，此时应该**更严**而不是放水；相对截断把"最高分低"误当成"可以放宽"
- **修复**：`min_relevance_relative_ratio` 默认改为 0.0（纯绝对阈值 0.5），所有 query 一律硬门槛；需要小幅放宽时显式覆盖为非 0（如 0.85）
- **教训**：**"最高分低"是"库里没有相关"的信号，不是"可以放宽"的信号**——相对截断的初衷（漏召回比多检索代价高）搞反了方向；多检索的代价是 LLM 幻觉（用户痛），少检索的代价是"通用知识兜底"（用户可接受）；搜索引擎阈值应该是**全局硬性指标**，不能按单次 query 最高分动态放宽

## 20. 批量入库 N 文档 = N 次全量社区重建（并行踩踏 + 白烧 LLM）→ 静默窗口合并重建

- **场景**：Java 上传批量文档 → Kafka → Java KafkaListener（concurrency=3）→ HTTP 直调 FastAPI → 每个文档 ingest_file 后都 `build_communities(reset=True)`
- **现象**：① 批量 10 文档 = 10 次全量重建（每次 30 社区 × LLM 摘要 ≈ 60 秒），前 9 次成果被最后一次覆盖（白烧 token）② concurrency=3 时多个重建并行执行，互相清空对方刚写入的社区（PITFALLS #8 跨连接一致性被放大）③ 删除文档也触发全量重建（删 1 个文档 ≈ 60 秒）
- **根因**：社区重建触发粒度 = 单文档，没有"批量合并"概念；生产链路是 Java KafkaListener → HTTP（Python kafka_consumer 是备选，生产不走），合并逻辑必须做在 HTTP 入口层
- **修复**（组合拳）：
  1. `ingest_file(build_communities=False)`：HTTP 入口入库不再立即重建，只标记 kb dirty
  2. `community_scheduler.py`：后台线程「连续 N 秒无新入库请求」（静默窗口，默认 30s）→ 统一重建一次；lifespan shutdown 时立即重建剩余 dirty kb
  3. 删除改轻量清理 `_prune_orphan_communities`：只删无成员实体的孤儿 Community 节点 + 对应 Qdrant 摘要，**不调 LLM**（<1 秒）；全量刷新靠下次入库调度
  4. CLI 直跑保留立即重建（build_communities=True 默认）
- **验证**：调度器冒烟——单次 mark_dirty 0.5s 后重建 1 次；连续 mark_dirty（批量场景）只在停止后重建 1 次
- **教训**：**"批量操作"的聚合副作用（重建/刷新/同步）必须在入口层做防抖合并，不能在单条处理路径上重复执行**；识别真实生产链路（Java KafkaListener → HTTP 而非 Python 消费者）再做方案；删 1 个文档全量重建 30 社区是明显的设计失配——副作用触发粒度要与操作粒度匹配

## 21. LLM 供应商切换（MiniMax → DeepSeek）：thinking 字段语义因供应商而异

- **场景**：全 LLM 切换（对话/JSON/切分）从 MiniMax-M3 切到 DeepSeek v4 flash
- **现象**：`get_chat_llm` 对非 MiniMax base_url 一律发 `enable_thinking=false`——切到 DeepSeek 后这个字段 DeepSeek 不识别（可能 400 或忽略）；`get_json_chat_llm` 同样对非 MiniMax 路径补发 `enable_thinking`
- **根因**：代码只区分了 MiniMax（`thinking.type`）和"其他"（一律 `enable_thinking`），没有把"第三方不认识任何 thinking 字段"的情况考虑进去——DeepSeek 属于"其他"却被发了百炼风格字段
- **修复**：三处统一改为按供应商三分支——MiniMax 发 `thinking.type=disabled`；百炼（dashscope/aliyuncs）发 `enable_thinking`；**DeepSeek 等第三方一律不发任何 thinking 字段**（`extra_body={}`）；`get_json_chat_llm` 的 `enable_thinking=True` 显式传入时才补发
- **教训**：**LLM 供应商的 extra_body 字段不是通用约定，切换供应商必须逐字段核对**——MiniMax 的 thinking.type、百炼的 enable_thinking、DeepSeek 的不认识任何 thinking 字段；"else 分支发百炼字段"是危险默认，未知供应商应该什么都不发（宁可多试一次）

## 22. 全图「全量展示」仍被截断：`limit or 300` 把 0 当 falsy + edges/all 硬编码 LIMIT 500

- **场景**：图谱页前端加「显示上限」下拉后，选「全量展示」（limit=0）全屏打开仍只显示 500 条边
- **现象**：全屏标题「实体 383 · 关系 500」——期望 1690 条全量；浏览器实测确认
- **根因**（两层）：
  1. `full_graph(limit)`: `params={"limit": limit or 300}`——Python 的 `or` 把显式 0 当 falsy，回退 300；且路由层 `eff_limit = None if limit <= 0 else limit` 传 None 也回退 300（**全量请求永远得到 300**）
  2. `fetch_all_edges()`: Cypher **硬编码 `LIMIT 500`**——前端取"full(300) vs edges/all(500) 更多的一份"→ 显示 500
- **修复**：
  - `full_graph` / `fetch_all_edges`：`limit=None` 才用默认（300/500）；`limit=0` → **不加 LIMIT 子句**（注意 Cypher `LIMIT 0` 返回 0 条，全量必须不拼 LIMIT）
  - 路由 `/edges/all` 加 `limit` 参数（0=全量）；Java 网关转发 limit
  - 前端 `fetchAllGraphEdges({ limit: this.fullLimit })` 同步传参
  - **路由层不得做 0→None 转换**（2026-08-12 复发补修）：`eff_limit = None if limit <= 0 else limit` 会把 0 转成 None，而函数层 `None=默认上限`——「全量」请求永远拿到 300/500。必须把 `limit` 原样传给函数，0/正数/None 三种语义只在函数层一处判定
- **教训**：**Python 的 `x or default` 无法区分「未传」和「显式 falsy 值（0/空）」**——参数有"0 表示特殊语义"时必须用 `if x is None`；**Cypher 的 LIMIT 0 不是"不限"而是"0 条"**，全量必须动态拼接不带 LIMIT 的查询；前端"取更多一份"的兜底逻辑会掩盖单个接口的截断 bug——接口层就该返回正确数据。**「0/None/默认」三态语义的参数跨层传递时，任何一层做 falsy 转换都会静默改变语义——转换只能发生在唯一一处**

---

## 23. ECharts `graphic` 元素不随 series roam 变换——社区聚类虚线框「写死不动」

- **场景**：全图聚类布局的社区边界气泡（虚线椭圆）在缩放/平移/拖拽后留在原地，节点已走远，气泡仍盖在旧位置
- **现象**：用户反馈「社区聚类的虚线框是写死的，不会动态改变」；拖动全图后气泡与社区成员分离
- **根因**：气泡用 `graphic` 元素绘制——graphic 挂在 chart 的 viewRoot 下，**不参与 graph series（layout:'none'）的 roam 变换**：series 数据点随缩放平移更新，graphic 元素原地不动；且 rx/ry 写死 `ring+18` 正圆，不随成员分布变化
- **修复**：气泡改为 graph series 的**虚拟节点**（`symbol:'circle'` + `symbolSize:[rx*2, ry*2]` 拉伸成椭圆——官方 `normalizeSymbolSize`/`graphHelper.getSymbolSize` 均支持数组宽高），坐标随 series 一起 roam；椭圆参数改为按成员实际坐标包围盒动态计算；`silent:true` + `emphasis.disabled:true` 保持纯装饰（不响应事件、不参与 focus/blur 淡化）
- **教训**：**ECharts 中需要跟随某系列 roam/拖拽的装饰元素，必须是该系列的数据点（或自定义 symbol），不能用 graphic 元素**——graphic 只适合画与坐标无关的固定装饰；「装饰随数据动」优先考虑 series 虚拟节点

---

## 24. 多知识库图谱隔离：kb_ids 数组过滤「越来越慢」→ 标签命名空间隔离

- **场景**：企业多知识库（Dify 模式）需要每 kb 独立图谱。Neo4j 社区版无多数据库（`CREATE DATABASE` 是企业版功能），最初用边/社区上的 `kb_ids` 数组 + `WHERE $kb IN r.kb_ids` 过滤
- **现象**：社区重建（`fetch_entity_graph`）随全库边数线性变慢——kb 越多、全库越大，每次重建扫描全库所有 RELATED 边；且共享实体/共享边导致删除逻辑（清理 kb_ids 残留）越来越复杂
- **根因**：
  1. **数组属性建不了索引**——`WHERE $kb IN r.kb_ids` 只能全表扫描逐条判断（类比 MySQL `FIND_IN_SET` 废索引）；Neo4j 的 label 则有自己的 token 索引，`MATCH (a:EntityKb1)` 由标签索引 O(1) 定位节点集合，只遍历本 kb 内部边——**数据局部性**，扫描量不随全库/kb 数量增长
  2. 共享数据模型（实体全库共享）在 kb 增多后查询处处要过滤、删除处处要清残留
- **修复**：
  - 标签命名空间隔离：`EntityKb{id}` / `CommunityKb{id}`（kb_id 是 int，f-string 拼接无注入风险）
  - 全链路 20+ 处 Cypher 按标签查询，**零 WHERE kb_ids 过滤**；`ensure_schema(kb_id)` 按 kb 建唯一约束（自带索引）
  - `purge_kb` 简化为按标签 DETACH DELETE 整片删；同名实体跨 kb 独立（Dify 语义）
  - 管理台展示数据落 MySQL 快照表（`rag_graph_*`，社区重建后 30s debounce 分批同步），管理查询按 `kb_id` 过滤
  - **Qdrant/ES 同样物理隔离**（2026-08-13 追加）：每 kb 独立 collection/index
    （`chunk_collection(kb)` 等命名函数，**kb=0 沿用原名 = 存量零迁移**）；写入/检索/删除
    全部按 kb 选容器，去掉 payload/term 级 kb filter；purge_kb 升级为直接删容器
  - 存量迁移：`scripts/migrate_neo4j_labels.py`
- **教训**：**「元数据过滤」不等于「标签过滤」——Neo4j 对 label 与属性是两套机制：label 有索引定位（数据分类），属性数组过滤只能全表扫描**。多租户/多实例隔离优先考虑结构隔离（标签/分表/多库），不要用查询时过滤；过滤方案在数据量增长后是不可逆的性能债
- **备选**：Neo4j 企业版多数据库（`CREATE DATABASE`）是物理隔离的更强方案；Desktop 免费带企业版开发者许可可先测，生产需授权（≤50 人公司可申请 Startup License）

---

## 25. 上传文档「选了新知识库但数据没绑定」：弹窗 kb 默认 0 + 裸 axios 把业务失败当成功

- **场景**：多知识库上线后，用户新建知识库「测试」(kb=2) 并在文档管理页上传文件，随后用库名过滤「测试」，列表空空如也
- **现象**：排查一圈发现数据全在默认库——上传目录只生成 `rag/0/`（无 `rag/2/`）、`rag_document_hash` 中 `kb_id>0` 行数为 0、Qdrant 只有 kb=0 的 collection；且前端提示「已提交 1 个文件」，用户完全无感知
- **根因**（两层）：
  1. **UX 层**：列表过滤的下拉（`queryParams.kbId`）与上传弹窗的下拉（`uploadForm.kbId`）是两套状态，弹窗默认「默认知识库」——用户以为过滤条件会带入上传，实际 FormData 里 `kbId=0`
  2. **错误吞噬层**：`uploadRagDocument` 用裸 axios（绕过 RuoYi 拦截器），RuoYi 后端业务失败也是 HTTP 200 + `body.code=500`，axios 正常 resolve → 前端 `data.skipped ? 'skipped' : 'ok'` 把失败响应计成成功——即使后端拒绝（如 checkKbAdmin 无权限）也提示「已提交」
- **修复**：`handleUpload` 默认继承列表过滤的 kb；`submitUpload` 显示后端真实错误且不关弹窗；新增 `activated()` 钩子刷新 kb 下拉（keep-alive 缓存页从知识库管理页新建库后 created 不再触发）
- **二次踩坑（2026-08-13）**：修 submitUpload 时按「axios 原始响应」再解了一次包——`const body = resp.data` 取到的是内层 data（无 code 字段），`body.code !== 200` 恒成立，**上传成功也弹「上传失败」**。实际 `uploadRagDocument` 内部已经 `.then(res => res.data)` 解包且失败时 reject（后端 msg 在 rejection 里）。修复：直接用解包后的 body，读 `body.data.skipped`
- **教训**：**凡绕过统一拦截器（裸 axios/fetch）的请求，必须自己补业务码判断——拦截器承担的「code!=200 即报错」责任不会自动存在**；同时**调用自封装 API 前先确认它的返回契约（已解包 body / 原始 AxiosResponse / rejection 内容），不要按惯例猜**——同一次修复里先漏判断、后双重解包，两个方向都错了一遍；「选库 A 上传 → 库 B 展示」这类跨控件状态不一致，优先做「状态继承」而不是让用户重复选择

---

## 26. qdrant-client `FilterSelector()` 无参构造直接抛 validation error——社区摘要永远写不进向量库

- **场景**：多知识库物理隔离后，首次对 kb=2 做社区重建，摘要要写进 `community_summaries_kb2`
- **现象**：日志「Qdrant 社区摘要 collection 已创建：community_summaries_kb2」之后紧跟「【社区构建】摘要向量写入失败（不阻断）：1 validation error for FilterSelector / filter Field required [type=missing, input_value={}]」——collection 建了，摘要一个都没写进去；用户看到的现象是「社区摘要没进新库的向量库」
- **根因**：`delete_community_summaries` 用 `models.FilterSelector()`（不带参）想表达「删全部点」，但 qdrant-client 的 pydantic 模型里 `FilterSelector.filter` 是**必填字段**（无默认值），无参构造直接抛 validation error；外层「不阻断」包装把异常吞成 warning，导致后续 upsert 也没执行。代码注释里「FilterSelector() 不带 filter = 删全 collection」的假设从未被验证过（此路径此前没跑过 kb>0 的重建）
- **修复**：`models.FilterSelector(filter=models.Filter())`——空 Filter 序列化为 `{}`，Qdrant 语义 = 匹配全部点（删全 collection）；修正注释并记录本坑
- **教训**：**外部 SDK 的模型构造器带不带默认值，只有跑一遍才知道——「看起来可以省略的字段」被 pydantic 定义为 required 时，运行时第一行就炸**；best-effort（不阻断）的 try 包装必须把异常打全（异常类型或 traceback），否则真实根因被吞成一行 warning，排查时只能从现象反推

---

## 27. llama-swap 长得像 Ollama 但只支持 OpenAI 兼容协议：/api/embed、/api/rerank 全是 404

- **场景**：内网模型服务器 192.168.15.208:11435（llama-swap）提供 bge-m3-Q8_0 / bge-reranker-v2-m3-Q8_0；同机 11434 才是原生 Ollama（只有 qwen）。配置切换时想当然按「Ollama 服务器」处理
- **现象**：`/api/embed`、`/api/rerank` 请求 404（空响应）；`/v1/models`、`/v1/embeddings`、`/v1/rerank` 正常——服务是 OpenAI 兼容协议
- **根因**：llama-swap 是 OpenAI 兼容网关，不实现 Ollama 原生 `/api/*` 接口；「端口挨着 + 模型名像 Ollama」造成误判（实际用 `/v1/models` 一探便知，模型 owned_by 字段写的就是 llama-swap）
- **修复**：embedding 走 `OpenAIEmbeddings(base_url=host:port/v1)`（新增 `embed_provider=openai` 分支）；rerank URL 改 `/v1/rerank`（响应格式与 Ollama 同构：results[{index, relevance_score}]，bge 输出为原始 logits 负值，仅排序有意义——下游 RRF 只用名次不用分值，无需归一化）
- **教训**：**内网自建模型服务先探协议再写代码**——`/v1/models` + `/v1/embeddings` 探一次就知道是不是 OpenAI 兼容，别被「11434/11435 相邻端口 + Ollama 风格模型名」带偏；Windows bash 里 curl 中文 body 是 GBK 编码，会被服务端判成 ill-formed UTF-8（看着像服务端 500，实为本地编码问题），验证一律用 Python UTF-8 发请求

---

## 28. Qdrant/ES「查了不存在再创建」不是原子的：并发入库/重试触发 409/400 打爆整条 ingest

- **场景**：Kafka 消息重试 + 并发上传同一 kb，`ensure_collection_exists` 的 get→create 两步之间另一线程已建好 collection
- **现象**：ASGI 异常 `UnexpectedResponse: 409 (Conflict) Collection juyao_knowledge_chunks_kb7 already exists`，整条 ingest event 失败；Kafka 手动 commit 下消息重试再次 409，形成失败循环
- **根因**：`_ensure_collection` 与 `ensure_es_index_exists` 都是「exists 检查 → create」两步非原子操作；Qdrant 409 / ES 400（resource_already_exists_exception）未做幂等容忍，异常一路抛穿 API 层
- **修复**：两处 create 都 catch「已存在」类错误（Qdrant 匹配 "already exists"，ES 匹配 "resource_already_exists_exception"），幂等复用已建容器并打 info 日志；ES 顺带修正了 create 调用块的缩进
- **教训**：**「确保存在」类操作必须按幂等接口写——并发场景下 exists-check 和 create 之间的窗口永远存在，容忍「已存在」错误比加锁更简单可靠**；多知识库物理隔离后同一 kb 的并发 create 概率显著上升（重试、多文件并发上传都走同一入口）

---

## 29. qdrant-client 1.10+ 移除 `client.search`——L1 社区检索静默全灭，悄悄降级 L2

- **场景**：qdrant-client 升级到 1.18.0 后，图谱 L1（社区摘要检索）一直静默异常
- **现象**：每次提问日志 `community_search: Qdrant search 失败：'QdrantClient' object has no attribute 'search'` → 返回 [] → L1 恒降级 L2 全图检索——**功能上「还活着」（有 L2 兜底），质量上 L1 已死**，无任何报错表面
- **根因**：`client.search()` 是旧 API，qdrant-client ≥1.10 改名 `query_points`；调用被 try/except 吞成 warning + 返回 []（best-effort 设计把「API 不存在」和「没检索到」混为一谈）
- **修复**：改 `client.query_points(collection_name=..., query=q_vec, limit=..., with_payload=True).points`（query 直接传原始向量）；同轮顺带修了另一个 L1 死因：**切换 bge 后存量摘要还是百炼向量空间**，余弦分数 0.03~0.06 全部低于阈值——kb0 社区重建后（bge 重嵌入）分数恢复正常
- **教训**：**best-effort 的 except 分支必须区分「外部系统故障/API 变更」与「正常空结果」——前者至少打 error 级日志（或告警），否则功能死掉无人知晓**；依赖升级（qdrant-client 这种频繁破坏性改名的库）后要跑一遍真实检索冒烟测试，不能只看 import/编译通过

---

## 30. qwen3 自适应思考：简单 prompt 不思考、复杂任务思考——且思考内容走 reasoning_content 字段

- **场景**：LLM 切回本地 qwen3-30B 后想关闭思考提速；先用「1+1=？」测试——输出无 think 块、13s，曾误判「默认不思考/思考影响不大」
- **现象**：换真实抽取 prompt 后同一模型耗时 93s，content 里仍无 `<think>` 块，但响应 `reasoning_content` 字段有 1447 字思考
- **根因**：qwen3 是**自适应思考**——按任务难度决定是否思考（简单题直接答）；llama-swap 把思考过程映射到 OpenAI 兼容的 `reasoning_content` 字段，而非 content 内 `<think>` 块。用简单 prompt 测、或只看 content 判断思考，都会误判
- **修复**：请求体下发 `chat_template_kwargs={"enable_thinking": false}`（实测 93s→7s、reasoning_content=0、三元组质量无损）；封装为 `local_think` 配置（默认 false，只对本地 base_url 生效），抽取（json_client）与切分（factory）生效，对话 LLM 保留思考
- **教训**：判断模型是否思考要看「复杂任务 + reasoning_content 字段」，不能拿简单 prompt 或 content 里的 think 块当依据；本地模型行为开关优先用服务端协议字段（chat_template_kwargs），比改 prompt 前缀（/no_think）干净

---

## 踩坑模式总结（教训提炼）

1. **"先 X 后 Y"的顺序改动，Y 的删除/清理条件必须精确到原子键**（坑 2）
2. **外部系统（Qdrant/Neo4j）的 payload 结构/语法先实测再写代码**（坑 3、9）
3. **过滤/隔离逻辑不允许"兼容旧数据的捷径"**（坑 4）
4. **LLM 输出不可复现 → 规则优先、LLM 补充**（坑 5、10）
5. **文件合并/追加后必须跑真实路径验证，不能只看编译/import**（坑 1、7）
6. **跨连接一致性是隐性问题，写入链路尽量共用连接**（坑 8）
7. **评测/校准的"数据状态"与"文件时间戳"先核对**（坑 11）
8. **临时配置改动必须配套恢复步骤**（坑 12）
9. **合并分支前先 diff 受影响文件，合并后三端全量验证**（坑 13）
10. **外部 SDK 返回 pydantic 对象而非 dict，先归一化（model_dump）再取字段**（坑 14）
11. **框架（uvicorn）启动时会接管 logging 配置——自定义 handler 必须在其配置完成后的生命周期钩子里挂**（坑 15）
12. **用 chunk_ids 当 filter 去清 doc_ids 是错误语义——两个字段存的是不同字符串（chunk_id vs source_doc_id），过滤条件不匹配**（坑 15）
12. **"页面是否含图片"不能依赖 get_images()（整页扫描件返回 0）——兜底逻辑宁多勿漏**（坑 16）
13. **供应商限流错误会伪装成业务拒绝（422 文案误导）——偶发 422 先按供应商并发上限重测，别急着换模型/换供应商**（坑 17）
14. **大面积 422/400 且看似按内容特征分布时，先查账户状态（欠费/额度），再怀疑业务逻辑**——欠费错误码与审核/限流同形（坑 18）
15. **Spring `${VAR:default}` 占位符的 fallback 对空字符串不生效——空字符串是合法值**；跨端鉴权必须在两端启动日志打 token 长度+前缀方便对比（坑 16）
16. **业务规则应该配置化（YAML/TOML），不硬编码在源码里**；规则命中要打日志便于收集真实流量分布（坑 17）
17. **pydantic-settings 默认值是双写源（代码 Field + default.toml）——改代码默认值必须同步改 default.toml**（坑 18）
18. **"最高分低"是"库里没相关"的信号，不是"可以放宽"的信号——搜索阈值用全局硬性指标**（坑 19）
19. **批量操作的聚合副作用（重建/刷新/同步）要在入口层防抖合并，不能在单条路径重复执行；副作用触发粒度要与操作粒度匹配**（坑 20）
20. **LLM 供应商的 extra_body 字段不是通用约定，切换供应商必须逐字段核对；未知供应商什么都不发**（坑 21）
22. **「0=特殊语义（全量）」的参数跨层传递时，任何一层做 falsy 转换（0→None）都会静默改变语义——转换只能发生在唯一一处判定**（坑 22）
23. **ECharts 中跟随系列 roam 的装饰元素必须做成 series 数据点（虚拟节点/自定义 symbol），graphic 元素固定不动**（坑 23）
24. **「元数据过滤」≠「标签过滤」——Neo4j 的 label 有索引定位（数据分类），属性数组过滤只能全表扫描**；多租户隔离优先结构隔离（标签/独立容器），过滤方案是数据量增长后的不可逆性能债（坑 24）
21. **Python `x or default` 无法区分「未传」和「显式 falsy（0/空）」——"0 表示特殊语义"的参数必须用 `if x is None`**；Cypher `LIMIT 0` 是 0 条不是不限（坑 22）
25. **绕过统一拦截器的请求（裸 axios）必须自己补业务码判断，否则后端错误被当成成功**；多控件共享同一业务状态时做「状态继承」，不让用户重复选择（坑 25）
26. **调用自封装 API 前先确认返回契约（已解包 body / AxiosResponse）**——一次修复里「漏判断」和「双重解包」两个方向各错一遍（坑 25 续）
27. **外部 SDK pydantic 模型字段是否必填，实测为准**——`FilterSelector()` 无参构造直接抛 validation error；best-effort try 必须打全异常，别吞成一行 warning（坑 26）
28. **判断模型是否思考要看「复杂任务 + reasoning_content 字段」**——qwen3 自适应思考，简单 prompt 或 content 里找 think 块都会误判；关闭思考用服务端协议字段（chat_template_kwargs）而非 prompt 前缀（坑 30）

## 15. uvicorn 启动时 dictConfig 会清掉 import 阶段添加的 root 日志 handler

- **场景**：给 API 引擎加"日志自动落盘 rag.log"（FileHandler 挂 root logger）
- **现象**：import 时 `configure_rag_logging()` 添加的 FileHandler 在服务启动后消失，rag.log 未生成（0 字节或不存在）
- **根因**：uvicorn 启动时会执行自己的 logging dictConfig，**重置 root logger 的 handlers**——import 阶段（app 模块加载）添加的 handler 被清掉；且 uvicorn 的 `uvicorn.access` logger `propagate=False`，访问日志不经过 root
- **修复**：FileHandler 添加逻辑拆成独立函数，在 **lifespan 阶段**（uvicorn 完成自身日志配置后）再补一次；文件固定 `encoding="utf-8"`，规避 Windows 控制台 GBK 乱码
- **教训**：框架（uvicorn/星协议栈）启动时会接管 logging 配置——自定义日志 handler 必须在框架配置完成后的生命周期钩子里挂，不能只在模块 import 时挂

## 17. MiniMax 只支持 3 并发：超限 422 曾被误判为"内容审核拒绝敏感词"

- **场景**：RAGAS 评测跑 100 条 QA（含医疗类问题），用 16 线程并发检索生成 + batch_size=8 评判
- **现象**：间歇性报 `422 new_sensitive`，单条重试医疗问题也偶发 422 → 曾误判为"MiniMax 审核拒绝医疗/敏感内容"，把评测 LLM 换成 qwen（被用户否决，用户只要 MiniMax）
- **根因**：**MiniMax 并发上限 3**——16 线程/8 批量同时打 API 触发服务端限流，返回 422（错误文案带 sensitive 字样误导排查方向）；降到 3 并发后医疗问题全部 200 OK，无任何审核拒绝
- **修复**：所有调 MiniMax 的并发一律 ≤3——评测 `_EVAL_WORKERS=3`、ragas `batch_size=3`、QA 生成 `workers=3`、图谱抽取 `ingest_graph_workers=3`；顺带修复 `get_chat_llm` 对 MiniMax 发错 thinking 字段（`enable_thinking` → `thinking.type=disabled`），消除输出 `<think>` 前缀污染
- **教训**：供应商限流错误码可能长得像业务拒绝（422 文案误导）；遇"偶发 422 + 含敏感词数据"先怀疑并发超限，按供应商并发上限重测再下结论；供应商参数语义（thinking 字段名）也要按供应商实测，不能按 OpenAI 兼容想当然

## 18. 云服务欠费伪装成业务错误：MiniMax 422 / 百炼 400 Access denied

- **场景**：RAGAS 评测第 3 次运行，68/100 条 answer 生成被拒；同批 QA 前两次几乎全过
- **现象**：MiniMax 报 `422 new_sensitive (1026)`（与内容审核同文案）、百炼 embedding 报 `400 Access denied`——大面积且集中在历史政治类文档，曾误判为"MiniMax 审核拒绝历史内容"
- **根因**：**MiniMax 账户欠费**，付费服务请求被拒；阿里云百炼（embedding/rerank）同步欠费 400。欠费错误码与业务拒绝（422 审核/限流）完全同形，无法从文案区分
- **修复**：用户确认欠费后，评测加"重试 3 次 + 失败跳过不崩进程"，欠费期间仍能跑完并出部分报告（32/100 条有效）；文档标注欠费影响与补跑计划
- **教训**：422/400 大面积出现且与"内容特征"强相关（看似有规律）时，先查账户状态/配额（欠费、额度耗尽），再怀疑业务逻辑；错误码同形问题要留"验证供应商账户状态"的排查步骤

- **场景**：RAGAS 评测跑 100 条 QA（含医疗类问题），用 16 线程并发检索生成 + batch_size=8 评判
- **现象**：间歇性报 `422 new_sensitive`，单条重试医疗问题也偶发 422 → 曾误判为"MiniMax 审核拒绝医疗/敏感内容"，把评测 LLM 换成 qwen（被用户否决，用户只要 MiniMax）
- **根因**：**MiniMax 并发上限 3**——16 线程/8 批量同时打 API 触发服务端限流，返回 422（错误文案带 sensitive 字样误导排查方向）；降到 3 并发后医疗问题全部 200 OK，无任何审核拒绝
- **修复**：所有调 MiniMax 的并发一律 ≤3——评测 `_EVAL_WORKERS=3`、ragas `batch_size=3`、QA 生成 `workers=3`、图谱抽取 `ingest_graph_workers=3`；顺带修复 `get_chat_llm` 对 MiniMax 发错 thinking 字段（`enable_thinking` → `thinking.type=disabled`），消除输出 `<think>` 前缀污染
- **教训**：供应商限流错误码可能长得像业务拒绝（422 文案误导）；遇"偶发 422 + 含敏感词数据"先怀疑并发超限，按供应商并发上限重测再下结论；供应商参数语义（thinking 字段名）也要按供应商实测，不能按 OpenAI 兼容想当然

- **场景**：上传国务院公报扫描件 PDF（6 页全部为图片渲染），只解析出封面 79 字符
- **现象**：6 页扫描件只入库 1 个切片（封面），其余 5 页内容静默丢失；日志无 OCR 记录
- **根因**：OCR 触发条件为「文本 <20 字符 **且 page.get_images() 非空」——整页图片渲染的扫描件页面级图片不被 get_images() 列出（返回 0），条件不满足 → 不 OCR
- **修复**：去掉「含图片」条件——页面文本过少即尝试 OCR；纯空白页 OCR 为空，不会更差（实测 79 → 6470 字符，全部 6 页 OCR 成功）
- **教训**：判断"页面是否含图片"不能依赖 get_images()（它只列嵌入图片对象）；扫描件判定以文本量为准，OCR 兜底宁多勿漏

## 29. Qdrant collection 不存在时静默返回空：全链路排查时"没命中"与"库不存在"无法区分

- **场景**：LightRAG 卡片检索全链路日志排查（用户要看卡），跑完只看到关键词输出、无检索/一跳/重排任何日志，最终 Observation 为空
- **现象**：检索函数返回 0 命中且**不打印任何日志**——从日志上完全看不出"检索了但没命中"还是"根本没检索"
- **根因**：`kg_card_search._query_card_collection` 对 collection 不存在（UnexpectedResponse 404）走"空结果而非异常"设计（并行架构下不能因图谱路炸穿向量路），但该分支**静默 return [] 无日志**；实际触发是 kb13 被删除、卡片 collection 随 purge_kb 一并消失（用户删库重建 kb14）
- **修复**：collection 不存在分支补 INFO 日志「collection 不存在（新库未入库或已删除），本路空返回」；检索命中明细/一跳展开/融合去重/重排分数全链路日志埋入 kg_card_search（供逐卡观测）
- **教训**：任何"静默降级"的分支都必须留日志——降级路径恰恰是故障高发路径，没日志等于排查时先猜一遍数据状态；全链路观测日志要覆盖"入口→召回→展开→融合→重排"每一段，缺一段就无法定位

## 30. docker compose v5 的 config/up 需显式 --profile：default profile 服务被误判 undefined

- **场景**：192.168.15.208 上给 llama-swap 双模型组部署（补 -card 实例），`docker compose config -q` 报 `service "cube-llamafactory" depends on undefined service "cube-llm"`
- **现象**：compose 文件服务树完整（python yaml 解析正常、cube-llm 在 default profile 列表里），但 `docker compose config` 默认解析看不到 cube-llm，依赖校验误报 undefined；容器却一直正常跑
- **根因**：docker compose v5 的 `config`/`up` 命令**只解析当前激活的 profile**（默认只激活隐式 default）；服务显式写了 `profiles: [default, dual-primary, single]` 时，"default" 不再保证默认可见——必须显式 `--profile default` 或 `COMPOSE_PROFILES=...` 才激活
- **修复**：部署/重启一律 `docker compose -f docker-compose_amd.yaml --profile default up -d <svc>`；本次服务器历史启动命令本就带 profile，所以一直正常
- **教训**：compose 报"undefined service"先怀疑 profile 过滤而非文件破坏（先 `--profile default config --services` 对照）；改 compose 文件后校验命令要和实际启动命令带相同的 profile 参数

## 31. 容器内 sed r 是"锚点后插入"：劈开目标服务映射导致 duplicate key

- **场景**：compose 文件插入新服务块，用 `sed -i '/^  cube-llamafactory:/r /block.txt'` 在锚点行后追加
- **现象**：`compose config` 报 `mapping key "image" already defined at line 114`——新服务块的属性被塞进了 cube-llamafactory 服务映射内部
- **根因**：sed r 命令语义是"在匹配行**之后**插入"，锚点行本身是服务名（缩进 2 空格 + 冒号），其后续属性行缩进更深，插入块接在服务名行后 = 变成该服务的属性，同名 image 键重复
- **修复**：改用 awk 在锚点行**之前**插入（`awk '/^  cube-llamafactory:/ && !done {while ((getline l < f)>0) print l; done=1} {print}'`）；已破坏版本用插入前的 cp 备份回滚
- **教训**：向 YAML 插入块务必先想清楚锚点语义（sed r = 行后、awk = 行前）；任何文件修改先 cp 备份再操作，回滚才有依据
