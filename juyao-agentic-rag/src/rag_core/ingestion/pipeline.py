"""文档入库管线：切块 → Qdrant / Elasticsearch / Neo4j。"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from tqdm import tqdm

from rag_core.indexing.elasticsearch import sync_chunks_to_elasticsearch
from rag_core.indexing.qdrant import ensure_collection_exists, get_vector_store
from rag_core.ingestion.cleanup import delete_document_from_indexes
from rag_core.ingestion.graph_writer import write_chunks_to_graph
from rag_core.ingestion.loader import load_document
from rag_core.ingestion.splitter import split_into_chunks

logger = logging.getLogger(__name__)


def ingest_file(
    file_path: str,
    *,
    source_name: str | None = None,
    enable_graph: bool = True,
    purge_before_write: bool = False,
) -> tuple[int, int]:
    """导入单个文件，返回（向量侧 chunk 数，图侧关系数）。"""
    begin = time.time()
    path = Path(file_path)
    logical_name = source_name if source_name else path.name

    if purge_before_write:
        logger.info("【入库】先按逻辑名清理旧索引：%s", logical_name)
        delete_document_from_indexes(logical_name, include_graph=enable_graph)

    logger.info("【入库】开始处理文件：%s source_name=%s", file_path, logical_name)
    content = load_document(str(path))
    logger.info("【入库】原文读取完成：source=%s 字符数=%s", logical_name, len(content))
    chunks = split_into_chunks(source_name=logical_name, content=content)
    logger.info("【入库】切块完成：source=%s chunks=%s", logical_name, len(chunks))

    logger.info("【入库】开始写入向量库 Qdrant")
    ensure_collection_exists()
    vector_store = get_vector_store()
    # Qdrant point id 用 chunk_id 的 UUID5：同一 chunk_id 重复写入会覆盖，实现幂等
    ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.metadata["chunk_id"])) for chunk in chunks]
    vector_store.add_documents(documents=tqdm(chunks, desc="写入向量库"), ids=ids)
    logger.info("【入库】Qdrant 写入完成：%s 条", len(chunks))

    logger.info("【入库】开始同步 Elasticsearch")
    sync_chunks_to_elasticsearch(chunks)
    logger.info("【入库】Elasticsearch 同步完成：%s 条", len(chunks))

    triple_count = 0
    if enable_graph:
        _, triple_count = write_chunks_to_graph(chunks=chunks, source_name=logical_name)

    cost = time.time() - begin
    logger.info(
        "【入库】全部完成：source=%s chunks=%s triples=%s 耗时=%.1fs",
        logical_name,
        len(chunks),
        triple_count,
        cost,
    )
    return len(chunks), triple_count
