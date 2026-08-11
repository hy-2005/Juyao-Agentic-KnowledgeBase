# 派系 2 GraphRAG 改造评测（2026-08-12）

> 评测目标：验证 Step 1-7 派系 2 改造（社区优先 + L1/L2/L3 级联 + A+B+C + Prompt 同构 + 独立 collection + 删除 chunk_id 锚定）的效果。
> **状态：⏸ 未跑（用户确认：代码未启动，跳过单元测试与 RAGAS 评测，待实际部署后再跑）**
> 评测环境：（待 Step 8 实施时填写）
> 创建：2026-08-12 · 更新：2026-08-12

## 测试集

| 数据集 | 用途 | 来源 |
|---|---|---|
| 关系型问题集 | 验证 L1 命中 + 实体匹配 | （待定） |
| 主题/汇总型问题集 | 验证社区摘要直接命中 | （待定） |
| 具体到某条款/某实体 | 验证 L3 真没有的退化 | （待定） |
| 推理型问题 | 验证 L2 全图降级 | （待定） |
| 现有 RAGAS 测试集 | 全指标对比 | `RESULTS_20260807.md` / `RESULTS_20260808.md` |

## 评测维度

| 指标 | 说明 | 目标 |
|---|---|---|
| **L1 命中率** | 派系 2 主路径命中比例 | ≥ 60%（关系型 + 主题型） |
| **L2 降级率** | 全图降级触发比例 | 20~40%（具体型 + 推理型） |
| **L3 放弃率** | 真没有的比例 | ≤ 10%（冷启动 / 摘要质量不足） |
| **chunk_id 污染消除** | 图谱路径不再依赖向量结果 | 100%（grep 验证 0 命中） |
| **RAGAS context_recall** | 检索召回 | 不下降 / 略升 |
| **RAGAS context_precision** | 检索精度 | 不下降 / 略升 |
| **RAGAS faithfulness** | 生成忠实度 | 不下降 |
| **平均延迟** | 3 次 LLM 调用（A+B+C）开销 | ≤ +2s |

## 结果（占位）

```
待 Step 8 跑通后填入：
- 各项指标前后对比
- 失败模式统计（L1/L2/L3 触发分布）
- 异常案例（社区摘要质量问题 / 阈值需校准的证据）
```

## 决策（待 Step 8 后填写）

- `community_summary_min_similarity` 阈值是否需要调整
- A+B+C 是否合并为单次 LLM 调用以降低延迟
- L2 全图降级是否需要继续保留
- 是否需要社区摘要重写 / 重新检测

## 实施状态

- ✅ Step 1：Prompt 同构
- ✅ Step 2：社区摘要独立 collection
- ✅ Step 3：community_search
- ✅ Step 4：A+B+C 改写链路
- ✅ Step 5：run_graph_search 统一入口
- ✅ Step 6：graph_only / graph_supplement 切换
- ✅ Step 7：删除 chunk_id 锚定
- ⏸ Step 8：**未跑**（代码未启动，待部署后由用户自行跑 RAGAS 评测）

## 待跑时需要的操作（部署后）

```bash
cd juyao-agentic-rag

# 1. 重灌数据（社区摘要 collection 会自动重建）
python -m rag_core.cli.ingest --reset --kb=0

# 2. 跑 RAGAS 评测（与 RESULTS_20260808 同一脚本/同一测试集）
python -m rag_eval.cli.main run --config configs/graphv2.yaml

# 3. 重点对比维度（填入本文件）
# - L1 命中率 / L2 降级率 / L3 放弃率
# - RAGAS context_recall / context_precision / faithfulness
# - 平均延迟变化（3 次 LLM 调用开销）
```
