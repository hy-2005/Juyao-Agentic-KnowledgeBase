"""SSE 契约快照录制：跑一组覆盖各分支的问题，把 SSE 事件流落盘 JSONL。

用途：编排重构前后契约对比（阶段 5 的回归基准）。事件名与 meta 字段
结构变化会被 diff 脚本检出，防止前端依赖的契约被破坏。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from rag_core.application.chat_flow.entry import astream_chat_events

# 覆盖分支：direct（问候）/ graph_only（关系）/ vector_only（事实）/ 补图（向量不足）
QUESTIONS = [
    "你好",
    "熊大和森林是什么关系？",
    "感冒通常由什么引起？",
    "合同编号是多少？",
    "光头强为什么走不出狗熊岭？",
]


async def main() -> None:
    out_dir = Path("reports/sse_snapshots")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "before_refactor.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for i, q in enumerate(QUESTIONS, start=1):
            print(f"[{i}/{len(QUESTIONS)}] {q}", flush=True)
            events: list[dict] = []
            holder: list[str] = []
            try:
                async for ev, payload in astream_chat_events(
                    q,
                    history=[],
                    assistant_holder=holder,
                ):
                    events.append({"event": ev, "data": payload})
            except Exception as exc:  # 单条失败不中断录制
                events.append({"event": "error", "data": {"error": str(exc)}})
            f.write(json.dumps({"question": q, "events": events}, ensure_ascii=False) + "\n")
            f.flush()
    print(f"快照已写入 {out}")


if __name__ == "__main__":
    asyncio.run(main())
