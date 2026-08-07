# chunk 参数校准决策（2026-08-07）

> 评测集：story_qa（胸大熊二猎奇小故事.txt，长文档对 chunk 粒度敏感）
> 方法：chunk_size 网格 600/800/1000（chunk_max_chars 联动 1000/1400/1600），每组重灌 story（--no-graph）+ RAGAS 四指标

## 三组对比

| 指标 | 组A(600/1000) | 组B(800/1400) | 组C(1000/1600) |
|---|---|---|---|
| faithfulness | 0.880 | **0.932** | 0.799 |
| answer_relevancy | **0.896** | 0.829 | 0.868 |
| context_recall | 1.000 | 1.000 | 1.000 |
| context_precision | 0.902 | **0.962** | 0.962 |

## 决策：保持现状 chunk_size=800 / chunk_max_chars=1400（组 B）

**理由**：
1. faithfulness 最高（0.932）——生成忠实度是最关键指标
2. context_precision 与组 C 并列最高（0.962）——检索精准度好
3. context_recall 三组全满分（1.0）
4. 组 A（600）answer_relevancy 略高（0.896）但 faithfulness/precision 双降——块过碎导致上下文不完整
5. 组 C（1000）faithfulness 明显下降（0.799）——块过大噪声增多

**趋势结论**：chunk_size 在 600-1000 区间内，**800 是平衡点**（600 过碎精度降、1000 过大忠实度降）；检索漏斗参数（top_k=15/rrf_top_n=12/rerank_top_n=6）保持 RETRIEVAL_REVIEW 优化后的值。

## 记录

- 组 A/B/C 评测结果存档：`reports/calib600/`、`reports/final/`（B 组）、`reports/calib1000/`
- 配置已恢复 default.toml = 800/1400/120
- 遗留：overlap（120）未做网格（影响小于 chunk_size，优先级低）；父子分块参数（child_chunk_size=200）待开关开启后验证
