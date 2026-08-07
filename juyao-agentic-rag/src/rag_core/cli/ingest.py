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
    parser.add_argument(
        "--purge",
        action="store_true",
        help="先按 source_name 清理旧索引再写入（重灌用，避免旧 chunk 残留）",
    )
    parser.add_argument(
        "--kb-id",
        type=int,
        default=0,
        help="知识库 ID（租户隔离用，默认 0 单库）",
    )
    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    args = build_parser().parse_args()
    chunk_count, triple_count = ingest_file(
        args.file,
        enable_graph=not args.no_graph,
        purge_before_write=args.purge,
        kb_id=args.kb_id,
    )
    if args.no_graph:
        print(f"导入完成，共写入 {chunk_count} 个 chunk（图谱构建已关闭）。")
    else:
        print(f"导入完成，共写入 {chunk_count} 个 chunk，并写入 {triple_count} 条图关系。")


if __name__ == "__main__":
    main()
