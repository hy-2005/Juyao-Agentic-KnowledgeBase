"""文档入库：加载、切分、管线、事件、清理。"""

from rag_core.application.ingest_flow.events import apply_kafka_ingest_payload
from rag_core.application.ingest_flow.graph_writer import ingest_graph_from_file, write_chunks_to_graph
from rag_core.infrastructure.loaders import load_document, load_text
from rag_core.application.ingest_flow.ingest import ingest_file
from rag_core.domain.chunking.splitter import split_into_chunks

__all__ = [
    "apply_kafka_ingest_payload",
    "ingest_file",
    "ingest_graph_from_file",
    "load_document",
    "load_text",
    "split_into_chunks",
    "write_chunks_to_graph",
]
