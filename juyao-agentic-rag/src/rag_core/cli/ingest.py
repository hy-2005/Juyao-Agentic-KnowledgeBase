"""CLI：文档入库（向量 + ES + 可选 Neo4j）。"""

from __future__ import annotations

import argparse
import logging

from rag_core.ingestion.pipeline import ingest_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="通用超级知识库入库入口（默认同步构建图谱）")
    parser.add_argument("--file", required=True, help="待导入的 utf-8 文本文件路径")
    parser.add_argument(
        "--no-graph",
        action="store_true",
        help="仅写入向量库与 ES，不构建 Neo4j 图谱",
    )
    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    args = build_parser().parse_args()
    chunk_count, triple_count = ingest_file(args.file, enable_graph=not args.no_graph)
    if args.no_graph:
        print(f"导入完成，共写入 {chunk_count} 个 chunk（图谱构建已关闭）。")
    else:
        print(f"导入完成，共写入 {chunk_count} 个 chunk，并写入 {triple_count} 条图关系。")


if __name__ == "__main__":
    main()
