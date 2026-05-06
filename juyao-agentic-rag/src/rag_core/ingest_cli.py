"""
知识入库入口：文本文件 → 切块 → 写入 Qdrant。

本地开发：在 juyao-agentic-rag 目录执行 ``pip install -e .`` 后，可直接：
``python ingest.py --file data/sample_medical.txt``
"""

import argparse
import uuid
from pathlib import Path

from tqdm import tqdm

from rag_core.ingestion.loader import load_text
from rag_core.ingestion.splitter import split_into_chunks
from rag_core.vector_store import ensure_collection_exists, get_vector_store


def ingest_file(file_path: str) -> int:
    """导入单个文件，返回写入的 chunk 数量。"""
    source_name = Path(file_path).name
    content = load_text(file_path)
    chunks = split_into_chunks(source_name=source_name, content=content)

    # 首次导入时自动建库，避免手工初始化 Qdrant collection。
    ensure_collection_exists()
    vector_store = get_vector_store()
    # Qdrant 仅接受 uint64 或 UUID 作为点 ID。
    # 用 chunk_id 生成稳定 UUID，可保持幂等（同一 chunk 再次导入会覆盖更新）。
    ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.metadata["chunk_id"])) for chunk in chunks]
    vector_store.add_documents(documents=tqdm(chunks, desc="写入向量库"), ids=ids)
    return len(chunks)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="通用超级知识库入库入口")
    parser.add_argument("--file", required=True, help="待导入的 utf-8 文本文件路径")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    count = ingest_file(args.file)
    print(f"导入完成，共写入 {count} 个 chunk。")


if __name__ == "__main__":
    main()
