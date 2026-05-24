"""文档切块入口：语义切分 + overlap + metadata。

输出 Document.metadata 含 chunk_id / source_doc_id 等公约字段（见 domain/chunk.py），
供 Qdrant、ES、Neo4j 三处索引共用同一标识。
"""

from __future__ import annotations

import logging

from langchain_core.documents import Document

from rag_core.core.config import get_settings
from rag_core.domain.chunk import build_source_doc_id, enrich_chunk_metadata
from rag_core.ingestion.split_ai import build_semantic_spans
from rag_core.ingestion.split_spans import apply_overlap

logger = logging.getLogger(__name__)


def split_into_chunks(source_name: str, content: str) -> list[Document]:
    settings = get_settings()
    semantic_spans = build_semantic_spans(content=content, target_chars=settings.chunk_size)
    if not semantic_spans:
        logger.warning("【语义切分】source=%s 未生成有效分块（content_len=%s）", source_name, len(content))
        return []

    logger.info(
        "【语义切分】source=%s content_len=%s chunks=%s (size=%s overlap=%s)",
        source_name,
        len(content),
        len(semantic_spans),
        settings.chunk_size,
        settings.chunk_overlap,
    )

    source_doc_id = build_source_doc_id(content=content, source_name=source_name)
    chunks: list[Document] = []
    total_len = len(content)

    for idx, span in enumerate(semantic_spans):
        start_char, end_char, overlap_left, overlap_right = apply_overlap(
            span,
            total_len=total_len,
            overlap=settings.chunk_overlap,
            max_chunk_chars=settings.chunk_size,
        )
        actual_start = start_char - overlap_left
        actual_end = end_char + overlap_right
        chunk_text = content[actual_start:actual_end].strip()
        chunk = Document(page_content=chunk_text, metadata={"source_name": source_name})
        chunks.append(
            enrich_chunk_metadata(
                document=chunk,
                source_doc_id=source_doc_id,
                chunk_index=idx,
                start_char=start_char,
                end_char=end_char,
                overlap_left=overlap_left,
                overlap_right=overlap_right,
            )
        )
        logger.debug(
            "chunk %s id=%s span=[%s,%s) len=%s",
            idx + 1,
            chunks[-1].metadata.get("chunk_id"),
            start_char,
            end_char,
            len(chunk_text),
        )

    return chunks
