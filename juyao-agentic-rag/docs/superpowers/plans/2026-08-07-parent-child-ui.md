# 父切片展开查看子切片 UI 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 父子分块模式下,前端「切片管理」页面父 chunk 行可展开查看子 chunk 列表,子 chunk 可查看完整详情。

**Architecture:** 后端 3 处改动——ES 同步补 `chunk_type`/`child_ids` 字段(列表可区分父子)、新增子块查询接口(查 Qdrant 按 `metadata.parent_chunk_id` 过滤)、详情接口 ES 未命中回退 Qdrant;前端表格加展开行(懒加载),复用现有详情抽屉。

**Tech Stack:** FastAPI + Qdrant(qdrant_client)/Elasticsearch(elasticsearch-py)/LangChain Document、Vue2 + ElementUI(el-table/el-drawer)

**设计文档:** `juyao-agentic-rag/docs/PARENT_CHILD_UI_REVIEW.md`

## Global Constraints

- 代码规范见根目录 `CLAUDE.md`:注释密度 3:1、类/函数必须有 docstring、废弃代码直接删除
- Qdrant payload 是 `{page_content, metadata}` 嵌套结构,过滤字段路径必须是 `metadata.parent_chunk_id`(顶层 key 匹配不到,踩坑见 PITFALLS.md)
- 子块 metadata 约定(splitter.py):`chunk_type="child"`、`parent_chunk_id=<父id>`、`chunk_id={父id}:sub:{hash[:12]}`
- 前端 API 统一走 `juyao-ui/src/api/rag.js`,request 封装返回 `{code, rows, total}` 结构
- 测试风格:纯函数单元测试(不 mock 外部服务),`pytest tests/test_*.py` 运行
- 运行环境:venv 在仓库根 `venv/`(相对 `juyao-agentic-rag/` 为 `../venv/Scripts/python.exe`),基础设施 Docker 已起(ES 9201 / Qdrant 6333)

---

### Task 1: ES 同步与行映射补父子字段

**Files:**
- Modify: `juyao-agentic-rag/src/rag_core/infrastructure/elasticsearch.py`(`_chunk_to_source` 与 `_source_to_chunk_row`)
- Test: `juyao-agentic-rag/tests/test_admin.py`

**Interfaces:**
- Consumes: 无(现有函数改造)
- Produces: `_source_to_chunk_row(src)` 返回的 row 新增 `chunk_type`、`child_ids`(存在才带);`_chunk_to_source(doc)` 写入 `chunk_type`、`child_ids`(metadata 有才写)

- [ ] **Step 1: 写失败测试**(追加到 `tests/test_admin.py`)

```python
def test_source_to_chunk_row_parent_fields() -> None:
    # 父块:带 child_ids
    src = {
        "chunk_id": "doc.txt:abc:0:def",
        "source_name": "doc.txt",
        "content": "正文",
        "chunk_index": 0,
        "chunk_type": "parent",
        "child_ids": ["doc.txt:abc:0:def:sub:aaa111bbb222"],
    }
    row = _source_to_chunk_row(src)
    assert row["chunk_type"] == "parent"
    assert row["child_ids"] == src["child_ids"]

def test_source_to_chunk_row_without_parent_fields() -> None:
    # 普通 chunk:无 chunk_type 字段时 row 不含该 key
    src = {"chunk_id": "a:1:h", "source_name": "doc", "content": "x", "chunk_index": 0}
    row = _source_to_chunk_row(src)
    assert "chunk_type" not in row
    assert "child_ids" not in row
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /d/code/juyao-agentic-rag/juyao-agentic-rag
../venv/Scripts/python.exe -m pytest tests/test_admin.py -k parent_fields -v
```
预期:`AssertionError`(row 里没有 chunk_type)

- [ ] **Step 3: 实现**——`_source_to_chunk_row` 加字段,返回行末尾 `{k: v for k, v in row.items() if v is not None}` 前补:

```python
    if src.get("chunk_type"):
        row["chunk_type"] = src.get("chunk_type")
    if src.get("child_ids"):
        row["child_ids"] = src.get("child_ids")
```

`_chunk_to_source` 的返回 dict 加(metadata 有值才带,保持普通 chunk 不污染):

```python
        "chunk_type": meta.get("chunk_type"),
        "child_ids": meta.get("child_ids"),
```

(该函数外层已有 `{k: v for k, v in ... if v is not None}` 类过滤吗?没有——`_chunk_to_source` 直接返回 dict,含 None 字段。为保证普通 chunk 不带空字段,改为构建后过滤:`return {k: v for k, v in src.items() if v is not None}`,`src` 即当前返回字面量。)

- [ ] **Step 4: 运行测试确认通过**

```bash
../venv/Scripts/python.exe -m pytest tests/test_admin.py -k parent_fields -v
```
预期:PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
cd /d/code/juyao-agentic-rag
git add juyao-agentic-rag/src/rag_core/infrastructure/elasticsearch.py juyao-agentic-rag/tests/test_admin.py
git commit -m "feat: ES 同步/行映射补 chunk_type 与 child_ids 字段"
```

---

### Task 2: Qdrant 子块查询与按 id 查 chunk

**Files:**
- Modify: `juyao-agentic-rag/src/rag_core/infrastructure/qdrant.py`
- Test: `juyao-agentic-rag/tests/test_admin.py`

**Interfaces:**
- Consumes: `get_qdrant_client()`(qdrant.py:12)、`get_settings().qdrant_collection`
- Produces:
  - `list_child_chunks_by_parent(parent_chunk_id: str) -> list[dict]` — 返回子块行列表(`chunk_id/chunk_index/content/start_char/end_char/parent_chunk_id`,按 chunk_index 升序)
  - `get_chunk_by_id_from_qdrant(chunk_id: str) -> dict | None` — 按 chunk_id 精确匹配,返回带完整 content 的行
  - 行映射纯函数 `_qdrant_point_to_row(point: dict) -> dict`(可单测)

- [ ] **Step 1: 写失败测试**

```python
def test_qdrant_point_to_row_child() -> None:
    # Qdrant scroll 返回的 point:payload 为 {page_content, metadata} 嵌套
    point = {
        "payload": {
            "page_content": "子块正文",
            "metadata": {
                "chunk_id": "doc.txt:abc:0:def:sub:aaa111bbb222",
                "chunk_index": 2,
                "start_char": 500,
                "end_char": 700,
                "parent_chunk_id": "doc.txt:abc:0:def",
            },
        }
    }
    row = _qdrant_point_to_row(point)
    assert row["chunk_id"] == "doc.txt:abc:0:def:sub:aaa111bbb222"
    assert row["chunk_index"] == 2
    assert row["content"] == "子块正文"
    assert row["parent_chunk_id"] == "doc.txt:abc:0:def"
```

- [ ] **Step 2: 运行确认失败**:`pytest tests/test_admin.py -k qdrant_point_to_row` → ImportError/AttributeError

- [ ] **Step 3: 实现**(追加到 `qdrant.py`。注意:文件顶部补 `import logging` 与 `logger = logging.getLogger(__name__)`;含 CLAUDE.md 踩坑注释:filter 必须走 `metadata.` 前缀)

```python
def _qdrant_point_to_row(point: dict) -> dict:
    """Qdrant scroll point → 管理台行字典(与 ES 行结构对齐)。"""
    payload = point.get("payload") or {}
    meta = payload.get("metadata") or {}
    row = {
        "chunk_id": meta.get("chunk_id"),
        "chunk_index": meta.get("chunk_index"),
        "start_char": meta.get("start_char"),
        "end_char": meta.get("end_char"),
        "parent_chunk_id": meta.get("parent_chunk_id"),
        "content": payload.get("page_content"),
    }
    return {k: v for k, v in row.items() if v is not None}


def list_child_chunks_by_parent(parent_chunk_id: str) -> list[dict]:
    """按 parent_chunk_id 查 Qdrant 返回子块行列表(按 chunk_index 升序)。

    filter 用顶层 key 匹配不到 Qdrant 嵌套 payload,必须走 metadata.parent_chunk_id。
    """
    settings = get_settings()
    client = get_qdrant_client()
    scroll_filter = models.Filter(
        must=[
            models.FieldCondition(
                key="metadata.parent_chunk_id",
                match=models.MatchValue(value=parent_chunk_id),
            )
        ]
    )
    points: list[dict] = []
    offset: int | None = None
    try:
        while True:
            resp = client.scroll(
                collection_name=settings.qdrant_collection,
                scroll_filter=scroll_filter,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            batch = resp[0] or []
            points.extend(batch)
            offset = resp[1]
            if offset is None or not batch:
                break
    except Exception as exc:
        # 与 list_chunks 一致:查询失败不阻断页面,返回空列表并告警
        logger.warning("Qdrant list_child_chunks_by_parent 失败：%s", exc)
        return []
    rows = [_qdrant_point_to_row(p) for p in points]
    rows.sort(key=lambda r: r.get("chunk_index") or 0)
    return rows


def get_chunk_by_id_from_qdrant(chunk_id: str) -> dict | None:
    """按 chunk_id 查 Qdrant(payload metadata.chunk_id 精确匹配),返回完整行。"""
    settings = get_settings()
    client = get_qdrant_client()
    scroll_filter = models.Filter(
        must=[
            models.FieldCondition(
                key="metadata.chunk_id",
                match=models.MatchValue(value=chunk_id),
            )
        ]
    )
    try:
        resp = client.scroll(
            collection_name=settings.qdrant_collection,
            scroll_filter=scroll_filter,
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as exc:
        logger.warning("Qdrant get_chunk_by_id_from_qdrant 失败：%s", exc)
        return None
    points = resp[0] or []
    if not points:
        return None
    return _qdrant_point_to_row(points[0])
```

- [ ] **Step 4: 运行测试确认通过**(纯函数部分)

```bash
../venv/Scripts/python.exe -m pytest tests/test_admin.py -k qdrant_point_to_row -v
```
预期:PASS

- [ ] **Step 5: 冒烟验证**(真实 Qdrant,已有 合同.txt 父子数据)

```bash
../venv/Scripts/python.exe -c "
from rag_core.infrastructure.qdrant import list_child_chunks_by_parent
rows = list_child_chunks_by_parent('0:合同.txt:69b916b2b6117b19:0:39da71440fd5')
print('子块数:', len(rows))
print('首条:', rows[0] if rows else None)
"
```
预期:子块数 > 0,首条含 content

- [ ] **Step 6: 提交**

```bash
cd /d/code/juyao-agentic-rag
git add juyao-agentic-rag/src/rag_core/infrastructure/qdrant.py juyao-agentic-rag/tests/test_admin.py
git commit -m "feat: Qdrant 子块列表查询与按 id 查询"
```

---

### Task 3: 详情回退 Qdrant + children 路由

**Files:**
- Modify: `juyao-agentic-rag/src/rag_core/infrastructure/elasticsearch.py`(`get_chunk_by_id`)
- Modify: `juyao-agentic-rag/src/rag_core/api/routes/chunks.py`
- Test: `juyao-agentic-rag/tests/test_admin.py`

**Interfaces:**
- Consumes: `list_child_chunks_by_parent`、`get_chunk_by_id_from_qdrant`(Task 2)、`get_chunk_by_id`(ES 现有)
- Produces: 路由 `GET /api/v1/admin/chunks/{chunk_id}/children`;`get_chunk_by_id` 增强(ES 未命中 → Qdrant)

- [ ] **Step 1: 写失败测试**(`get_chunk_by_id` 回退逻辑改为可注入依赖后测;此处测 children 路由函数的行为——用 FastAPI TestClient 需起服务,改为测核心函数)

```python
def test_children_route_registered() -> None:
    # 路由注册顺序:children 必须在 {chunk_id} 之前,否则被捕获为 chunk_id
    from rag_core.api.routes.chunks import router
    paths = [r.path for r in router.routes]
    assert "/{chunk_id}/children" in paths
    assert paths.index("/{chunk_id}/children") < paths.index("/{chunk_id}")
```

- [ ] **Step 2: 运行确认失败**:IndexError / assertion(children 未注册)

- [ ] **Step 3: 实现**

`elasticsearch.py` 的 `get_chunk_by_id` 末尾改为(ES 未命中回退 Qdrant):

```python
    if not resp or not resp.get("found"):
        # 子块只存 Qdrant,ES 未命中时回退按 chunk_id 查 Qdrant
        from rag_core.infrastructure.qdrant import get_chunk_by_id_from_qdrant

        return get_chunk_by_id_from_qdrant(chunk_id)
    return _source_to_chunk_row(resp.get("_source") or {}, include_full_content=True)
```

`api/routes/chunks.py` 新增(必须放在 `/{chunk_id}` 路由定义**之前**):

```python
@router.get("/{chunk_id}/children")
def admin_list_chunk_children(chunk_id: str):
    """父子分块:按父 chunk_id 查子块列表(数据源 Qdrant)。"""
    from rag_core.infrastructure.qdrant import list_child_chunks_by_parent

    rows = list_child_chunks_by_parent(chunk_id)
    return {"rows": rows, "total": len(rows)}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
../venv/Scripts/python.exe -m pytest tests/test_admin.py -k children_route -v
```
预期:PASS

- [ ] **Step 5: 重启 RAG 引擎并端到端验证**

```bash
# 重启 8000 服务后(uvicorn 后台),验证:
curl -s http://localhost:8000/api/v1/admin/chunks/0:合同.txt:69b916b2b6117b19:0:39da71440fd5/children | head -c 500
# 预期:{"rows":[...子块...], "total":13} 之类
# 详情回退验证:取一个子块 chunk_id 调详情接口,预期 200 带 content
curl -s "http://localhost:8000/api/v1/admin/chunks/<子块id>" | head -c 300
```

- [ ] **Step 6: 提交**

```bash
cd /d/code/juyao-agentic-rag
git add juyao-agentic-rag/src/rag_core/infrastructure/elasticsearch.py juyao-agentic-rag/src/rag_core/api/routes/chunks.py juyao-agentic-rag/tests/test_admin.py
git commit -m "feat: 子块列表接口 + 详情 ES 回退 Qdrant"
```

---

### Task 4: 前端 API 函数与展开行

**Files:**
- Modify: `juyao-ui/src/api/rag.js`(新增 `listChunkChildren`)
- Modify: `juyao-ui/src/views/rag/chunks/index.vue`

**Interfaces:**
- Consumes: 后端路由 `GET /api/v1/admin/chunks/{chunk_id}/children`(经 Java 网关 `/rag/chunks/{chunk_id}/children`)
- Produces: `listChunkChildren(chunkId)` 返回 `{rows, total}`;页面展开行为

- [ ] **Step 1: `rag.js` 新增函数**(追加到文件末尾,注释说明用途)

```js
/** 父子分块:按父 chunk_id 查子块列表(懒加载,展开时调用) */
export function listChunkChildren(chunkId) {
  return request({
    url: `${BASE}/chunks/${encodeURIComponent(chunkId)}/children`,
    method: 'get'
  })
}
```

- [ ] **Step 2: `index.vue` 模板加展开列**(`el-table` 内、`el-table-column` 序号列之前插入):

```html
<el-table-column type="expand">
  <template slot-scope="scope">
    <div v-if="scope.row.child_ids && scope.row.child_ids.length" class="child-chunks">
      <div class="child-chunks-header">子切片（共 {{ childChunks[scope.row.chunk_id] ? childChunks[scope.row.chunk_id].length : 0 }} 条）</div>
      <el-table :data="childChunks[scope.row.chunk_id] || []" size="mini" border>
        <el-table-column label="序号" prop="chunk_index" width="60" align="center" />
        <el-table-column label="正文预览" prop="content" min-width="300" :show-overflow-tooltip="true">
          <template slot-scope="c">
            <span>{{ (c.row.content || '').slice(0, 100) }}{{ c.row.content && c.row.content.length > 100 ? '...' : '' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" align="center">
          <template slot-scope="c">
            <el-button size="mini" type="text" icon="el-icon-view" @click="handleDetail(c.row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <div v-else class="child-chunks-empty">该父块暂无子切片</div>
  </template>
</el-table-column>
```

- [ ] **Step 3: script 部分**(data 加 `childChunks: {}`,methods 加加载函数):

```js
import { listRagChunks, getRagChunk, getRagChunkStats, listRagDocuments, listChunkChildren } from '@/api/rag'
// data 中加:
//   childChunks: {}  // chunk_id -> 子块行数组(展开缓存)

handleExpand(row) {
  // 懒加载:仅首次展开时请求;缓存后重复展开不再请求
  if (this.childChunks[row.chunk_id]) return
  if (!row.child_ids || !row.child_ids.length) return
  listChunkChildren(row.chunk_id).then((res) => {
    this.$set(this.childChunks, row.chunk_id, (res && res.rows) || [])
  }).catch(() => {
    this.$set(this.childChunks, row.chunk_id, [])
  })
}
```

`el-table` 加 `@expand-change="handleExpand"`(注意:expand-change 在展开和收起都触发,用 childChunks 缓存天然幂等;child_ids 为空的行用户点不了箭头,但兜底返回)。

- [ ] **Step 4: 前端构建验证**

```bash
cd /d/code/juyao-agentic-rag/juyao-ui
npm run build:prod 2>&1 | tail -5
```
预期:编译成功无报错(dev server 在 80 端口跑着,语法错会热更失败;build 是最终确认)

- [ ] **Step 5: 手动端到端验证**(浏览器或 curl 走 Java 网关)

```bash
# 前端 dev server 80 端口热更后:
# 1. http://localhost/rag/chunks 列表应看到 合同.txt 父块行带展开箭头
# 2. 点击展开 → 子块列表出现(序号/预览/详情)
# 3. 点子块详情 → 抽屉显示完整内容(走 ES 回退 Qdrant)
curl -s "http://localhost:8080/rag/chunks/0:合同.txt:69b916b2b6117b19:0:39da71440fd5/children" -H "Authorization: Bearer <登录token>" | head -c 300
```
注意:Java 网关需要登录 token 才能测,前端页面登录后即可用。若无 token,后端直连 8000 已验证(Task 3 Step 5)。

- [ ] **Step 6: 提交**

```bash
cd /d/code/juyao-agentic-rag
git add juyao-ui/src/api/rag.js juyao-ui/src/views/rag/chunks/index.vue
git commit -m "feat: 切片管理页父块展开查看子块"
```

---

### Task 5: 文档收尾(问题记录规则 + 时间规则)

**Files:**
- Modify: `juyao-agentic-rag/docs/PARENT_CHILD_UI_REVIEW.md`(状态改为 ✅ 已完成、补验证数据)
- Modify: `juyao-agentic-rag/docs/README.md`(索引状态同步)

- [ ] **Step 1: 更新 PARENT_CHILD_UI_REVIEW.md**

头部状态 `🔄 进行中(方案已确认,待实施)` → `✅ 已完成`;「验收标准」下补实测结果(展开箭头/子块列表/详情回退均验证);头部补 `> 创建：2026-08-07 · 更新：2026-08-07`(时间维护规则)。

- [ ] **Step 2: 更新 docs/README.md 索引**

`PARENT_CHILD_UI_REVIEW.md` 行状态 → `✅ 已完成`,说明更新为"父切片展开查看子切片已实施"。

- [ ] **Step 3: 提交**

```bash
cd /d/code/juyao-agentic-rag
git add juyao-agentic-rag/docs/
git commit -m "docs: 父子切片查看功能实施完成,更新状态与索引"
```
