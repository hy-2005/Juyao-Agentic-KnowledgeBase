"""图谱查询公开 API（原 knowledge_graph/query.py 的 re-export 迁移至此）。"""

from rag_core.domain.graph.query.edge_queries import (
    query_edges_for_chunks,
    query_edges_from_entity_seeds,
    resolve_entity_names,
)
from rag_core.domain.graph.query.edge_view import GraphEdgeView
from rag_core.domain.graph.query.observation import (
    build_graph_observation_question_driven,
    build_graph_observation_text,
    format_edges_for_prompt,
)

__all__ = [
    "GraphEdgeView",
    "build_graph_observation_question_driven",
    "build_graph_observation_text",
    "format_edges_for_prompt",
    "query_edges_for_chunks",
    "query_edges_from_entity_seeds",
    "resolve_entity_names",
]
