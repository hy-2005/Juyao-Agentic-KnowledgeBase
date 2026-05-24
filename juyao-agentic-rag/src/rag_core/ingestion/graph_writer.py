"""GraphRAG 离线写入：chunk 文本 → 三元组 → Neo4j。"""

from __future__ import annotations

import logging

from langchain_core.documents import Document
from tqdm import tqdm

from rag_core.ingestion.loader import load_document
from rag_core.ingestion.splitter import split_into_chunks
from rag_core.knowledge_graph.extractor import TripleExtractor
from rag_core.knowledge_graph.store import Neo4jTripleStore

logger = logging.getLogger(__name__)


def write_chunks_to_graph(*, chunks: list[Document], source_name: str) -> tuple[int, int]:
    """将已切块文档写入 Neo4j，返回 (处理 chunk 数, 关系条数)。"""
    logger.info("【GraphRAG】开始图谱构建：source=%s chunks=%s", source_name, len(chunks))
    extractor = TripleExtractor()
    store = Neo4jTripleStore()
    store.ensure_schema()

    chunk_count = 0
    triple_count = 0
    total = len(chunks)
    for idx, chunk in enumerate(tqdm(chunks, desc="构建 Neo4j 图谱"), start=1):
        metadata = chunk.metadata or {}
        chunk_id = str(metadata.get("chunk_id", ""))
        source_doc_id = str(metadata.get("source_doc_id", ""))
        if not chunk_id or not source_doc_id:
            logger.warning("【GraphRAG】跳过 chunk：缺少 chunk_id/source_doc_id（%s/%s）", idx, total)
            continue
        try:
            triples = extractor.extract(chunk.page_content)
        except Exception as exc:
            logger.warning(
                "【GraphRAG】chunk进度 %s/%s chunk_id=%s 抽取失败，已跳过：%s",
                idx,
                total,
                chunk_id,
                exc,
            )
            continue
        written = store.upsert_triples(
            triples=triples,
            source_doc_id=source_doc_id,
            chunk_id=chunk_id,
            source_name=source_name,
        )
        triple_count += written
        chunk_count += 1
        logger.info(
            "【GraphRAG】chunk进度 %s/%s chunk_id=%s 抽取=%s 累计关系=%s",
            idx,
            total,
            chunk_id,
            len(triples),
            triple_count,
        )
    logger.info("【GraphRAG】图谱构建完成：处理chunk=%s 写入关系=%s", chunk_count, triple_count)
    return chunk_count, triple_count


def ingest_graph_from_file(file_path: str, *, source_name: str | None = None) -> tuple[int, int]:
    """从文件读取、切块并仅写入 Neo4j（不写向量/ES）。"""
    from pathlib import Path

    path = Path(file_path)
    logical_name = source_name or path.name
    content = load_document(str(path))
    chunks = split_into_chunks(source_name=logical_name, content=content)
    return write_chunks_to_graph(chunks=chunks, source_name=logical_name)
