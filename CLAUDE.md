# CLAUDE.md

本项目是聚耀 RAG 知识库系统（Java 管理端 + Python RAG 服务）。本文件为 Claude Code 在本仓库内工作的行为规范。

## 注释规范（必须遵守）

整体目标：代码行数与注释行数比例控制在 **3:1** 左右（不刻意凑数，但注释密度不得低于此标准；复杂模块可更高）。

### 规则

1. **只对复杂逻辑、业务规则、特殊兼容写法、边界判断、算法逻辑写注释**；清晰命名的 CRUD、简单循环、普通变量**不写复述式注释**。
2. **类、公共函数必须写文档注释**，说明用途、入参、返回值（Python 用 docstring，Java 用 Javadoc）。
3. **晦涩写法、为性能妥协的代码，必须加注释说明「为什么这么写」**——解释动机而非行为。
4. **修改代码时同步更新对应注释；废弃代码直接删除，不要注释封存**（git 历史可追溯）。
5. **禁止无效注释**：禁止出现复述代码行为的注释（如 `// i=0`、`x = x + 1  # 加一`）。

### 正例 / 反例

```python
# 反例（复述行为，禁止）：
x = x + 1  # x 加一

# 正例（解释为什么）：
# Qdrant payload 是 {page_content, metadata} 嵌套结构，kb_id 实际路径是 metadata.kb_id；
# filter 用顶层 key 匹配不到，会静默返回空 → 租户隔离失效
flt = models.Filter(
    must=[models.FieldCondition(key="metadata.kb_id", match=models.MatchValue(value=int(kb_id)))]
)
```

### 其他约定

- 本项目 Python 侧为 `juyao-agentic-rag/`，Java 侧为 `juyao-admin/` 等模块；两处同样适用本规范。
- 评审/方案文档统一放 `juyao-agentic-rag/docs/`（REVIEW.md 系列），代码改动前先读对应评审文档。
- **需求完成一项必须同步更新文档**：每完成一个功能/修复/重构项，须在对应 REVIEW.md 或 `docs/eval/RESULTS_*.md` 记录实现结果、验证数据与遗留问题；不允许代码完成而文档空白。
