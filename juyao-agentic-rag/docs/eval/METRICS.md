# RAGAS 指标说明

默认启用四个指标（可在 `--metrics` 中按需裁剪）。

| 指标 | 含义 | 需要 ground_truth |
|------|------|-------------------|
| `faithfulness` | 回答是否忠实于检索上下文，有无幻觉 | 否 |
| `answer_relevancy` | 回答与问题的相关程度 | 否 |
| `context_precision` | 检索到的上下文是否精准 | 是（reference） |
| `context_recall` | 检索上下文是否覆盖标准答案所需信息 | 是（reference） |

## 分数解读（经验参考）

- **0.8+**：较好
- **0.6–0.8**：可用，有优化空间
- **< 0.6**：需排查检索或生成

具体阈值因领域与标注质量而异，建议以同一数据集上的**前后对比**为主，而非绝对分数。

## 低分常见原因

| 指标偏低 | 可能原因 |
|----------|----------|
| faithfulness | 生成幻觉、上下文不足仍强行作答 |
| answer_relevancy | 答非所问、thinking 残留未清洗 |
| context_precision | 检索噪声多、重排效果差 |
| context_recall | 切分过粗/过细、未入库、query 改写偏离 |

## 参考

- [RAGAS 官方文档](https://docs.ragas.io/)
