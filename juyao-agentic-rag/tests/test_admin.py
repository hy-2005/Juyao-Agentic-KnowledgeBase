"""管理台 API 单元测试。"""

from rag_core.infrastructure.elasticsearch import _build_list_query, _source_to_chunk_row
from rag_core.domain.graph.query.admin_queries import _edge_view_to_dict
from rag_core.domain.graph.query.edge_view import GraphEdgeView
from rag_core.infrastructure.qdrant import _qdrant_point_to_row


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


def test_source_to_chunk_row_parent_fields() -> None:
    # 父块 _source 行映射应透出 chunk_type 与 child_ids
    src = {
        "chunk_id": "doc.txt:abc:0:def",
        "source_name": "doc.txt",
        "content": "正文",
        "chunk_index": 0,
        "chunk_type": "parent",
        "child_ids": ["doc.txt:abc:0:def:sub:aaa111bbb222"],
    }
    row = _source_to_chunk_row(src)
    assert row["chunk_type"] == "parent"
    assert row["child_ids"] == src["child_ids"]


def test_source_to_chunk_row_without_parent_fields() -> None:
    # 普通 chunk:无 chunk_type 字段时 row 不含该 key
    src = {"chunk_id": "a:1:h", "source_name": "doc", "content": "x", "chunk_index": 0}
    row = _source_to_chunk_row(src)
    assert "chunk_type" not in row
    assert "child_ids" not in row


def test_qdrant_point_to_row_child() -> None:
    # Qdrant scroll 返回的 point:payload 为 {page_content, metadata} 嵌套
    point = {
        "payload": {
            "page_content": "子块正文",
            "metadata": {
                "chunk_id": "doc.txt:abc:0:def:sub:aaa111bbb222",
                "chunk_index": 2,
                "start_char": 500,
                "end_char": 700,
                "parent_chunk_id": "doc.txt:abc:0:def",
            },
        }
    }
    row = _qdrant_point_to_row(point)
    assert row["chunk_id"] == "doc.txt:abc:0:def:sub:aaa111bbb222"
    assert row["chunk_index"] == 2
    assert row["content"] == "子块正文"
    assert row["parent_chunk_id"] == "doc.txt:abc:0:def"
