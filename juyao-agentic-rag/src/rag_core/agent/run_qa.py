"""
问答运行入口：检索 + LLM 生成 + 引用输出。

本地开发：在项目根（含 ``setup.py``）执行 ``pip install -e .`` 后，可直接：
``python ask.py --question "你的问题"``，或 ``python -m rag_core.agent.run_qa ...``。
"""

import argparse

from rag_core.agent.qa_chain import answer_question


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="通用超级知识库问答入口")
    parser.add_argument("--question", required=True, help="用户问题")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    # answer_question 内部会完成：检索 -> 组 prompt -> 调用 LLM -> 拼接引用信息。
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
