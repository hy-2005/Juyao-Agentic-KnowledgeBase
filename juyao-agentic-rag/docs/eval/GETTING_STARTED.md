# RAGAS 测评快速启动

## 环境要求

与 RAG 引擎相同，另需安装测评依赖：

```powershell
cd juyao-agentic-rag
python -m pip install -e ".[eval]"
```

`[eval]` 会安装 `ragas`，并将 `langchain-community` 锁定为 **0.4.1**（与 ragas 0.4.3 兼容）。

## 前置检查

1. Qdrant、Elasticsearch 已启动
2. 测评对应文档已入库（`juyao-ingest`）
3. `.env` 中配置 `DASHSCOPE_API_KEY` 或 `LLM_API_KEY`
4. Embedding 服务可用（默认 Ollama）

验证 ragas 可导入：

```powershell
python -c "from ragas import evaluate; print('ok')"
```

## 启动测评

```powershell
# 使用内置默认数据集（医疗样例 3 题）
juyao-rag-eval

# 指定 datasets 子包内路径
juyao-rag-eval --dataset default/sample_qa.jsonl

# 保存 JSON 报告
juyao-rag-eval --output reports/eval_run.json
```

等价模块调用：

```powershell
python -m rag_eval.cli.main
```

## 包结构

```
src/rag_eval/
├── core/           # 测评引擎（RAG 调用、RAGAS 客户端、报告）
├── datasets/       # 人工标注标准答案（JSONL + manifest.yaml）
└── cli/            # 命令行入口
```

## 常见问题

| 现象 | 处理 |
|------|------|
| `缺少 ragas` / `vertexai` 导入失败 | 执行 `pip install -e ".[eval]"`，确认 `langchain-community==0.4.1` |
| 检索片段数为 0 | 确认文档已入库且 Qdrant 有数据 |
| 测评很慢 | 正常；每题含检索、生成、RAGAS 多指标 LLM 评判 |

更多流程见 [WORKFLOW.md](WORKFLOW.md)，指标说明见 [METRICS.md](METRICS.md)。
