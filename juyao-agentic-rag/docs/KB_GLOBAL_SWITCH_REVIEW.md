# 全局知识库选择 UX 方案

> 状态:✅ 已完成（2026-08-14 实施，前端构建通过；浏览器实测待用户验证）
> 创建:2026-08-14 · 更新:2026-08-14

## 背景

多知识库上线后，每个 rag 页面（文档/切片/图谱/对话）各自维护本页 kb 选择且互不同步——用户在文档页选了 kb9，跳转到切片/图谱页还要重新选一遍，频繁切换时体验很差。

## 方案

**「全局知识库选择」**：kb 选择提为全局状态，任一入口切换后所有页面跟随；localStorage 持久化（刷新浏览器不丢）。

### 实现（juyao-ui 前端）

1. **Vuex 模块 `store/modules/kb.js`**（新增）
   - state `currentKbId`：null=未全局选择（各页回落自身默认），数字=选中 kb（0=默认库，合法值不走 truthy 判断）
   - mutation `SET_CURRENT_KB_ID`：`''/undefined/null` 统一归一化为 null；同步写/清 localStorage（key `juyao-rag-current-kb`）
2. **顶栏切换器**（`layout/components/Navbar.vue`）
   - 仅 `/rag` 路由显示（`showKbSwitcher` 计算属性），下拉数据源 `listKbs` + 前端补「默认知识库」行
   - 路由变化进入 rag 页面时刷新下拉（知识库管理页新建库后同步）
3. **四个页面接线**
   - 初始值：`created/data()` 读 store（ingest 默认 null=全部；chunks/graph 回落 0；chat 直接取）
   - 本页切换：`@change` → `handleKbChange` 先 commit store 再查（graph 含全屏内切换 `handleFullKbChange`）
   - 跟随他页/顶栏：`watch $store.state.kb.currentKbId` → 同步本地值 + 刷新查询；值未变直接 return 防重复查询
   - keep-alive 回页：`activated()` 对比 store，变了才重查（离页期间被改过的情况）
4. **删除边界**（`rag/kb/index.vue`）：删除的库恰为全局选中 → 重置全局为 0（默认库），避免其他页挂在已删库上

### 语义约定

- 文档页选「全部」（清空）＝ 解除全局选择（null）→ 其他页回落各自默认
- 文档页「重置」按钮同时解除全局选择

## 验证

- `npm run build:prod` 通过（vue-cli-service build exit 0）
- 浏览器实测点（待用户验证）：顶栏在 rag 页面出现「选择知识库」；文档页选 kb9 → 跳切片/图谱/对话页默认即为 kb9；清空顶栏选择 → 各页回落默认；刷新浏览器 → 选中保留

## 遗留

- 对话页切换全局 kb 只改提问选库，不重载会话列表（会话与 kb 无关，符合现状）
- 未做「按用户分别记住选择」（localStorage 是浏览器级的，多用户共用浏览器不区分）
