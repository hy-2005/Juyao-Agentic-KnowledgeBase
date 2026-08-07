# 知识图谱社区展示方案

> 状态:✅ 已完成(2026-08-08 实施并验证)
> 创建:2026-08-08 · 更新:2026-08-08
> 关联:[GRAPH_QUERY_REVIEW.md](GRAPH_QUERY_REVIEW.md)(社区检测是其中的待办项,现补展示层)

## 实施验证(2026-08-08)

- 安装 `leidenalg`/`igraph` 依赖,`build_communities()` 跑通:12 个社区 + LLM 主题摘要 + Community 节点/MEMBER_OF 边入库
- 后端:全图/子图节点带 `community_id`;新接口 `GET /api/v1/admin/graph/communities`(Java 网关同步补 `/rag/graph/communities`)
- 前端:社区面板(摘要 + 实体数 + 成员实体标签 + 聚焦子图按钮);全图节点按社区 12 色板着色,悬停显示所属社区
- **入库自动构建**:`ingest.py` 图谱写入后自动调用 `build_communities(kb, reset=True)`(失败仅告警不阻断入库)——实测入库合同.txt 后社区 12→14 自动重建
- 验证:浏览器实测——社区面板 12 社区显示正常,展开见完整摘要与成员实体,全图渲染正常(测试单测 10 passed)

## 需求

知识图谱页(`/rag/graph`)体现「社区」:图谱节点按社区着色,左侧新增社区面板(社区列表 + 主题摘要 + 实体数,点击高亮/聚焦该社区)。

## 现状

- **社区检测代码已存在但从未启用**:`application/graph/community_build.py` 的 `build_communities`(Leiden 检测 + LLM 摘要 + Community 节点 + MEMBER_OF 边)无调用方;`leidenalg`/`igraph` 未安装
- 2026-08-08 已实测启用:安装依赖后 `build_communities()` 跑通,12 个社区 + 摘要生成成功,Community 节点已入库
- **前后端均无社区 API 与 UI**:`routes/graph.py` 无 communities 端点;前端 `KgGraphPanel.vue` 节点着色只有 seed/related 两色,无社区概念

## 设计

### 后端(2 处改动)

1. **节点带 community_id**(`domain/graph/query/admin_queries.py`)
   - `_edges_to_subgraph` 生成 nodes 后,批量查节点的社区归属(`MATCH (e:Entity)-[:MEMBER_OF]->(c:Community) WHERE e.name IN $names RETURN e.name, c.id`),塞进每个 node dict
   - 无社区归属的节点不带该字段(前端 fallback 默认色)

2. **新接口:社区列表**(`api/routes/graph.py`)
   ```
   GET /api/v1/admin/graph/communities
   ```
   - 复用 `community_build.list_community_summaries()`(已有:community_id/summary/entity_count)
   - 补充每个社区的成员实体名列表(前端点击社区时聚焦用):`MATCH (e:Entity)-[:MEMBER_OF]->(c:Community {id:$cid}) RETURN e.name`
   - 返回 `[{community_id, summary, entity_count, entities:[...]}]`

### 前端(3 处改动)

1. **API 层**(`juyao-ui/src/api/rag.js`):新增 `listCommunities()`

2. **社区面板**(`juyao-ui/src/views/rag/graph/index.vue`)
   - 左侧图谱数据区上方(或统计区下方)新增「社区」区块
   - 展示:社区名称(截断摘要)+ 实体数 badge
   - 点击社区 → 用 `getRagGraphSubgraph(seedNames=entities)` 加载该社区子图并高亮
   - 展开可看完整摘要(el-tooltip / el-collapse)

3. **按社区着色**(`KgGraphPanel.vue`)
   - 节点渲染时:若 `node.community_id` 存在 → 从社区色板取色(按 community_id hash 映射到预定义 12 色色板);否则维持现有 seed/related 逻辑
   - tooltip 追加「所属社区」行(节点 name 后显示社区摘要前缀)
   - 全图模式下按社区着色;子图模式维持种子高亮(避免颜色语义冲突)

### 社区色板

预定义 12 色(与 ECharts 默认视觉一致,同社区同色):
```
['#5B8FF9', '#5AD8A6', '#5D7092', '#F6BD16', '#E86452', '#6DC8EC',
 '#945FB9', '#FF9845', '#1E9493', '#FF99C3', '#3FC1C9', '#B084CC']
```
按 `community_id` 的 hash 取模映射,保证同社区恒定同色。

## 增强版:社区在图谱上的视觉体现(2026-08-08 追加,✅ 已实施验证)

> 实测:全图全屏 shell 新增「社区视图」按钮,切换后聚合节点(社区圆点+实体数)渲染正常,点击社区节点展开成员子图;实体视图节点按社区聚类布局 + 气泡边界,无渲染错误。

用户确认三项都要(聚类布局 / 边界气泡 / 聚合节点):

### 1. 社区聚类布局(KgGraphPanel)
- 全图模式且有 community_id 时,改用**固定坐标布局**(`layout: 'none'`,节点带 x/y):
  - 社区中心均匀分布在大圆上(半径 = min(w,h) × 0.3)
  - 成员实体在社区中心周围同心圆展开(半径按 √成员数 扩展)
- 非全图/无社区数据保持 force 布局
- 效果:同社区节点聚成「团」,与着色叠加,社区结构一目了然

### 2. 社区边界气泡(KgGraphPanel)
- 用 ECharts `graphic` 元素在 series 之下画半透明椭圆:
  - cx/cy = 社区成员平均位置,rx/ry = 成员分布半径(最小半径兜底)
  - fill = 社区色 10% 透明度,stroke = 社区色,虚线
- 气泡绘制在 series 之前(底层),节点在上层不遮挡
- 限制:节点被手动拖动后气泡不跟随(静态布局,可接受)

### 3. 社区聚合节点(index.vue + KgGraphPanel)
- 全图模式下新增「社区视图」切换(controls 区按钮):
  - 聚合视图:节点 = 社区(圆点 + 实体数徽标),边 = 社区间关系(聚合计数,标签显示条数)
  - 点击社区节点 → 展开该社区成员子图(用成员实体做 seed 加载子图)
  - 数据纯前端计算:从 fullGraphData(nodes 带 community_id)按社区分组,聚合跨社区边
- 交互:社区视图 ↔ 实体视图切换;展开后回到子图模式

### 实现文件
- `KgGraphPanel.vue`:聚类布局算法 + 气泡 graphic + 聚合视图渲染(props 增加 `communityView`)
- `index.vue`:社区视图开关按钮 + 聚合数据计算 + 展开交互

## 数据流

```
图谱页加载 → GET /api/v1/admin/graph/communities → 社区面板(摘要+实体数)
点击「全图」→ GET /api/v1/admin/graph/full → nodes 带 community_id → 按社区着色
点击社区 → GET /api/v1/admin/graph/subgraph?seed=成员实体 → 社区子图聚焦
```

## 错误处理

- 社区接口失败:面板显示空态「暂无社区数据(需先运行社区构建)」,不阻断图谱主功能
- 节点无 community_id:fallback 现有 seed/related 着色逻辑

## 测试

- 后端:单测覆盖 `_edges_to_subgraph` 带 community_id 的映射、communities 接口的响应结构(复用现有 test_admin.py 模式)
- 前端:build 编译通过;浏览器手动验证——社区面板显示 12 个社区、全图按社区着色、点击社区加载子图

## 验收标准

1. 图谱页显示社区面板:社区摘要 + 实体数
2. 全图节点按社区着色(同社区同色,悬停显示社区名)
3. 点击社区可加载该社区子图
4. 无社区数据时不报错,显示空态
