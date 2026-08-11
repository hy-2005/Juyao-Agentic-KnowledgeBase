"""图谱查询公开 API（原 knowledge_graph/query.py 的 re-export 迁移至此）。

派系 2 改造（GRAPH_QUERY_REVIEW §6.5）：build_graph_observation_text 已废弃——
chunk_id 锚定路径被删除（错 chunk 污染图谱扩展）。新主路径走 graph_search.run_graph_search。
"""

from rag_core.domain.graph.query.edge_queries import (
    query_edges_for_chunks,
    query_edges_from_entity_seeds,
    resolve_entity_names,
)
from rag_core.domain.graph.query.edge_view import GraphEdgeView
from rag_core.domain.graph.query.observation import (
    build_graph_observation_question_driven,
    format_edges_for_prompt,
)

__all__ = [
    "GraphEdgeView",
    "build_graph_observation_question_driven",
    "format_edges_for_prompt",
    "query_edges_for_chunks",
    "query_edges_from_entity_seeds",
    "resolve_entity_names",
]
