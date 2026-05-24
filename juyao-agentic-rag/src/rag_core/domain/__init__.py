"""领域模型与跨存储公约。"""

from rag_core.domain.chunk import (
    ChunkContract,
    build_chunk_id,
    build_source_doc_id,
    enrich_chunk_metadata,
)

__all__ = [
    "ChunkContract",
    "build_chunk_id",
    "build_source_doc_id",
    "enrich_chunk_metadata",
]
