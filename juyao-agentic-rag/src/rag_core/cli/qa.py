"""CLI：单次问答（检索 + 生成）。"""

from __future__ import annotations

import argparse
import logging

from rag_core.orchestration.qa import answer_question


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="通用超级知识库问答入口")
    parser.add_argument("--question", required=True, help="用户问题")
    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )
    args = build_parser().parse_args()
    result = answer_question(args.question)
    print("\n=== 回答 ===")
    print(result.answer)
    print("\n=== 引用 chunk_id ===")
    if result.citations:
        for cid in result.citations:
            print(f"- {cid}")
    else:
        print("- 无")
    print(f"\n=== 最高相关度 ===\n{result.score:.3f}")


if __name__ == "__main__":
    main()
