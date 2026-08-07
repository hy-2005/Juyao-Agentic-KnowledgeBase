"""CLI：单次问答（走完整编排管线，同步收集流式结果）。

替代旧 orchestration/qa.py 的单轮直查实现（决策 4：统一走 chat_flow 管线，
保留 CLI 调试能力）。
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from rag_core.application.chat_flow.entry import astream_chat_events


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="通用超级知识库问答入口（完整编排管线）")
    parser.add_argument("--question", required=True, help="用户问题")
    parser.add_argument("--kb-id", type=int, default=0, help="知识库 ID（默认 0）")
    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )
    args = build_parser().parse_args()

    async def run() -> tuple[str, list[str]]:
        answer_parts: list[str] = []
        citations: list[str] = []
        holder: list[str] = []
        async for ev, payload in astream_chat_events(
            args.question,
            history=[],
            assistant_holder=holder,
            kb_id=args.kb_id,
        ):
            if ev == "meta":
                citations = list(payload.get("citations") or [])
            elif ev == "token":
                answer_parts.append(payload.get("content") or "")
        return "".join(answer_parts), citations

    answer, citations = asyncio.run(run())
    print("\n=== 回答 ===")
    print(answer)
    print("\n=== 引用 chunk_id ===")
    if citations:
        for cid in citations:
            print(f"- {cid}")
    else:
        print("- 无")


if __name__ == "__main__":
    main()
