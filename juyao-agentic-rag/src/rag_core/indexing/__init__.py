"""向量与全文索引适配器。"""

from rag_core.indexing.elasticsearch import (
    get_elasticsearch_client,
    search_elasticsearch,
    sync_chunks_to_elasticsearch,
)
from rag_core.indexing.qdrant import (
    ensure_collection_exists,
    get_qdrant_client,
    get_vector_store,
)

__all__ = [
    "ensure_collection_exists",
    "get_elasticsearch_client",
    "get_qdrant_client",
    "get_vector_store",
    "search_elasticsearch",
    "sync_chunks_to_elasticsearch",
]
