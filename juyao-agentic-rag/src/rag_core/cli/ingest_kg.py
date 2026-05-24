"""CLI：仅构建 Neo4j 知识图谱。"""

from __future__ import annotations

import argparse
import logging

from rag_core.ingestion.graph_writer import ingest_graph_from_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GraphRAG 知识图谱构建入口")
    parser.add_argument("--file", required=True, help="待导入的 utf-8 文本文件路径")
    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    args = build_parser().parse_args()
    chunk_count, triple_count = ingest_graph_from_file(args.file)
    print(f"GraphRAG 构建完成：处理 {chunk_count} 个 chunk，写入 {triple_count} 条关系。")


if __name__ == "__main__":
    main()
