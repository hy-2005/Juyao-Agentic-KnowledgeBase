"""
检索层：从 Qdrant 取 TopK，并按最低相关度过滤。
"""

from dataclasses import dataclass

from langchain_core.documents import Document
from qdrant_client.http.exceptions import UnexpectedResponse

from rag_core.config import get_settings
from rag_core.rag.vector_store import get_vector_store


@dataclass
class RetrievedContext:
    # 一次检索结果：过滤后的文档列表 + 原始最高分（用于日志与调试）。
    documents: list[Document]
    max_score: float


# 向量相似度检索：返回分数 ≥ MIN_RELEVANCE_SCORE 的片段。
# 若全部被过滤，documents 为空，上层应走「证据不足」分支。
def search_context(query: str) -> RetrievedContext:
    settings = get_settings()
    try:
        vector_store = get_vector_store()
        # Qdrant relevance score 越大越相关，范围通常在 [0, 1]。
        docs_with_score = vector_store.similarity_search_with_relevance_scores(query, k=settings.top_k)
    except UnexpectedResponse as exc:
        # 测试阶段若尚未导入数据，集合不存在时按“无检索结果”处理而非抛错。
        if "doesn't exist" in str(exc) or "Not found" in str(exc):
            return RetrievedContext(documents=[], max_score=0.0)
        raise
    if not docs_with_score:
        return RetrievedContext(documents=[], max_score=0.0)

    # 过滤低分片段，避免噪声证据干扰生成。
    docs = [item[0] for item in docs_with_score if item[1] >= settings.min_relevance_score]
    max_score = max(score for _, score in docs_with_score)
    return RetrievedContext(documents=docs, max_score=max_score)
