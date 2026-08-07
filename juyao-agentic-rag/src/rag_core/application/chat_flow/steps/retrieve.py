"""单次向量检索步骤。"""

from langchain_core.documents import Document

from rag_core.application.chat_flow.observations import build_retrieval_observation
from rag_core.application.chat_flow.state import ExecuteResult, StepRecord
from rag_core.domain.retrieval.retriever import search_context


def execute_retrieval_step(query: str, round_idx: int, kb_id: int = 0) -> ExecuteResult:
    ctx = search_context(query, kb_id=kb_id)
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


def run_retrieve_step(state, round_idx: int = 1) -> None:
    """步骤 2b：向量检索，写入 merged_docs/max_score/observation/轨迹。"""
    result = execute_retrieval_step(state.question, round_idx, state.kb_id)
    state.retrieval_rounds = round_idx
    state.merged_docs = result.documents
    state.max_score = float(result.max_score)
    state.observation_lines.append(result.observation)
    state.executed_steps.append(
        StepRecord(
            name="retrieve",
            status="ok" if not result.is_empty else "failed",
            tool="search_knowledge_base",
            round=round_idx,
            query=state.question,
            doc_count=len(result.documents),
            max_score=result.max_score,
            is_empty=result.is_empty,
        )
    )
