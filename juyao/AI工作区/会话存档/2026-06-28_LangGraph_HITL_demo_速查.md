# LangGraph Human-in-the-Loop 示例速查

> 2026-06-28 · 会话闪记

## 位置

`juyao-agentic-rag/demos/langgraph_hitl/`

## 三件套

| API | 作用 |
|-----|------|
| `interrupt(payload)` | 节点内暂停，payload 返回给调用方 |
| `MemorySaver()` | compile 时传入 checkpointer（生产换 Postgres/Redis） |
| `Command(resume=value)` | 同一 `thread_id` 再次 invoke，value 成为 interrupt 返回值 |

## 四个 demo

1. **01** — approve/reject 二选一
2. **02** — approve / edit / reject，可改任务再执行
3. **03** — 输入校验失败 → conditional_edges 循环回审核节点
4. **04** — RAG 风格：检索 chunk 人工勾选后再 synthesize

## 运行

```bash
cd juyao-agentic-rag
pip install -r demos/langgraph_hitl/requirements.txt
python demos/langgraph_hitl/01_basic_approve_reject.py
```

## 注意

- resume 时节点**从头重跑**，interrupt 前副作用需幂等
- 节点内勿 `while True` + interrupt，用条件边循环
- Windows 控制台避免 ✓✗ 等符号（GBK 编码问题）
