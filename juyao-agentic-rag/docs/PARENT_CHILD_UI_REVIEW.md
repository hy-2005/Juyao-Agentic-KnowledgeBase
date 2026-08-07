# 父切片展开查看子切片 UI 方案

> 状态:🔄 进行中(方案已确认,待实施)
> 关联:[PARENT_CHILD_CHUNKING.md](PARENT_CHILD_CHUNKING.md)
> 创建：2026-08-07 · 更新：2026-08-07

## 需求

父子分块开启后,前端「切片管理」页面(`/rag/chunks`)点击父 chunk 可展开查看其子 chunk 列表,每条子 chunk 可查看详情。

## 现状

- **数据分布**:父块写 ES + Qdrant + 图谱;子块只写 Qdrant(`ingest.py:100-129`),ES 里无子块
- **ES 字段缺失**:父块同步到 ES 时 `_bulk_actions` 只写基础字段,`chunk_type` / `child_ids` **未写入** → 前端无法区分哪些行有子块
- **详情接口**:`GET /api/v1/admin/chunks/{chunk_id}` 只查 ES → 子块详情必然 404
- **前端**:`juyao-ui/src/views/rag/chunks/index.vue` 表格 + 详情抽屉,无父子结构

## 设计

### 后端(3 处改动)

1. **ES 同步补父子字段**(`infrastructure/elasticsearch.py`)
   - `_bulk_actions` 写入父块时带上 `chunk_type`、`child_ids`
   - `_source_to_chunk_row` 透出 `chunk_type`、`child_ids`(列表行可判断是否有子块)

2. **新接口:查子块列表**(`api/routes/chunks.py`)
   ```
   GET /api/v1/admin/chunks/{chunk_id}/children
   ```
   - 查 Qdrant:scroll `metadata.parent_chunk_id == {chunk_id}`,按 `chunk_index` 升序
   - 返回子块列表:`chunk_id / chunk_index / content / parent_chunk_id / start_char / end_char`(复用 row 映射逻辑)
   - 无子块返回空列表(200),不抛 404
   - 注册路由注意:必须放在 `/{chunk_id}` 之前,避免 `children` 被 `{chunk_id}` 捕获

3. **详情接口回退 Qdrant**(`get_chunk_by_id`)
   - ES 查不到 → 按 `chunk_id` 查 Qdrant payload(`metadata.chunk_id` 精确匹配),取 `page_content` + metadata
   - 两处都查不到才 404(维持现状语义)

### 前端(`juyao-ui/src/views/rag/chunks/index.vue`)

1. **展开行**:`el-table` 加 `type="expand"` 列,`child_ids` 非空才渲染展开箭头(列表接口透出后判断)
2. **懒加载**:点展开箭头 → 调 `listChunkChildren(chunkId)`,首次展开才请求;展开缓存按行内 key 存,收起再展开不重复请求
3. **展开区**:子块简表(`chunk_index` + 正文预览截断 + 「详情」按钮);空列表显示「该父块暂无子切片」
4. **详情**:子块「详情」按钮复用现有 `handleDetail` → `getRagChunk`(后端已回退 Qdrant,子块可查到)

### API 层(`juyao-ui/src/api/rag.js`)

新增 `listChunkChildren(chunkId)` → `GET /rag/chunks/{chunkId}/children`(走 request 封装)

## 数据流

```
点击展开箭头 → GET /dev-api/rag/chunks/{id}/children
  → Java 8080 转发 → FastAPI 8000
  → Qdrant scroll (metadata.parent_chunk_id == id)
  → 返回子块列表 → 前端渲染展开区
点击子块详情 → GET /dev-api/rag/chunks/{childId}
  → ES 无 → 回退 Qdrant 按 chunk_id 查 → 返回完整内容 → 抽屉展示
```

## 错误处理

- Qdrant 查询失败:返回空列表 + warning 日志(与 `list_chunks` 现状一致),不阻断页面
- ES 回退 Qdrant 时 Qdrant 也查不到:404,前端 catch 后 fallback 显示行数据(现有 `handleDetail` 已有 catch 逻辑)

## 测试

- 后端:单测覆盖 `list_chunk_children`(有子块/无子块)、`get_chunk_by_id` 回退路径(ES 空 → Qdrant 命中;双空 → None)
- 前端:手动验证——父子模式入库后列表可见父块,展开见子块,子块详情抽屉正常;非父子模式(普通 chunk)行无展开箭头

## 验收标准

1. 父子模式入库文档后,切片管理页父块行可展开,子块按序号排列,点详情显示完整内容
2. 普通模式(无父子)所有行无展开箭头,详情行为不变
3. 无子块的父块展开显示空态文案
