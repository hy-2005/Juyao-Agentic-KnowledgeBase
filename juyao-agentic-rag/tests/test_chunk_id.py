"""chunk 标识稳定性测试：内容寻址、kb 前缀、元数据写入。

chunk_id 是 Qdrant point id / ES _id / Neo4j chunk_ids 的共用键，
稳定性直接决定增量入库与租户隔离的正确性。
"""

from langchain_core.documents import Document

from rag_core.domain.chunking.contracts import (
    build_chunk_id,
    build_source_doc_id,
    enrich_chunk_metadata,
)


def test_build_source_doc_id_stable_for_same_content() -> None:
    a = build_source_doc_id(content="同一内容", source_name="doc.txt")
    b = build_source_doc_id(content="同一内容", source_name="doc.txt")
    assert a == b


def test_build_source_doc_id_changes_with_content() -> None:
    a = build_source_doc_id(content="内容一", source_name="doc.txt")
    b = build_source_doc_id(content="内容二", source_name="doc.txt")
    assert a != b


def test_build_source_doc_id_includes_kb_prefix() -> None:
    kb0 = build_source_doc_id(content="内容", source_name="doc.txt", kb_id=0)
    kb1 = build_source_doc_id(content="内容", source_name="doc.txt", kb_id=1)
    assert kb0.startswith("0:")
    assert kb1.startswith("1:")
    assert kb0 != kb1


def test_build_chunk_id_stable_for_same_text() -> None:
    sid = build_source_doc_id(content="全文", source_name="doc.txt", kb_id=0)
    a = build_chunk_id(sid, 0, "片段A")
    b = build_chunk_id(sid, 0, "片段A")
    assert a == b


def test_build_chunk_id_changes_with_text_or_index() -> None:
    sid = build_source_doc_id(content="全文", source_name="doc.txt", kb_id=0)
    t1 = build_chunk_id(sid, 0, "片段A")
    t2 = build_chunk_id(sid, 0, "片段B")
    t3 = build_chunk_id(sid, 1, "片段A")
    assert len({t1, t2, t3}) == 3


def test_enrich_chunk_metadata_writes_kb_id() -> None:
    doc = Document(page_content="片段", metadata={"source_name": "doc.txt"})
    sid = build_source_doc_id(content="全文", source_name="doc.txt", kb_id=7)
    enriched = enrich_chunk_metadata(
        document=doc,
        source_doc_id=sid,
        chunk_index=0,
        start_char=0,
        end_char=2,
        overlap_left=0,
        overlap_right=0,
        kb_id=7,
    )
    assert enriched.metadata["kb_id"] == 7
    assert enriched.metadata["chunk_id"].startswith(sid)
