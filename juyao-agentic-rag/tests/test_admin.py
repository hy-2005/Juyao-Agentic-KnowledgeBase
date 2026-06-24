"""管理台 API 单元测试。"""

from rag_core.indexing.elasticsearch import _build_list_query, _source_to_chunk_row
from rag_core.knowledge_graph.admin_queries import _edge_view_to_dict
from rag_core.knowledge_graph.edge_view import GraphEdgeView


def test_build_list_query_match_all() -> None:
    assert _build_list_query(None, None) == {"match_all": {}}


def test_build_list_query_with_filters() -> None:
    q = _build_list_query("doc.pdf", "合同")
    assert "bool" in q
    assert q["bool"]["filter"] == [{"term": {"source_name": "doc.pdf"}}]
    assert q["bool"]["must"] == [{"multi_match": {"query": "合同", "fields": ["content"]}}]


def test_source_to_chunk_row_preview() -> None:
    src = {
        "chunk_id": "a:1:hash",
        "source_name": "doc.pdf",
        "content": "x" * 250,
        "chunk_index": 0,
    }
    row = _source_to_chunk_row(src)
    assert row["content_preview"].endswith("...")
    assert len(row["content_preview"]) <= 203


def test_edge_view_to_dict() -> None:
    view = GraphEdgeView(
        head_name="甲",
        relation_predicate="位于",
        tail_name="北京",
        chunk_ids=("c1",),
    )
    d = _edge_view_to_dict(view)
    assert d["head_name"] == "甲"
    assert d["chunk_ids"] == ["c1"]
