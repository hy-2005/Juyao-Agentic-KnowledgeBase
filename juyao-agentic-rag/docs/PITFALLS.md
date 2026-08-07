# 开发踩坑记录（PITFALLS）

> 维护规则（见 CLAUDE.md）：**每个踩坑必须记录到本文件**——现象、根因、修复、教训。
> 更新：2026-08-07

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
