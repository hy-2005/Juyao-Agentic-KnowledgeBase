"""单次向量检索步骤。"""

from langchain_core.documents import Document

from rag_core.orchestration.observations import build_retrieval_observation
from rag_core.orchestration.types import ExecuteResult
from rag_core.retrieval.retriever import search_context


def execute_retrieval_step(query: str, round_idx: int) -> ExecuteResult:
    ctx = search_context(query)
    docs_by_id: dict[str, Document] = {}
    for doc in ctx.documents:
        cid = str(doc.metadata.get("chunk_id", "unknown_chunk"))
        docs_by_id[cid] = doc
    return ExecuteResult(
        observation=build_retrieval_observation(ctx, round_idx),
        max_score=float(ctx.max_score),
        documents=docs_by_id,
        is_empty=not bool(ctx.documents),
    )
