"""单元测试。"""

from langchain_core.documents import Document

from rag_core.knowledge_graph.schema import parse_triples
from rag_core.retrieval.fusion import fuse_query_rankings, fuse_two_rankings


def _doc(cid: str) -> Document:
    return Document(page_content="x", metadata={"chunk_id": cid})


def test_fuse_two_rankings_merges_vector_and_es() -> None:
    vec = [(_doc("a"), 0.9), (_doc("b"), 0.8)]
    es = [(_doc("b"), 10.0), (_doc("c"), 5.0)]
    fused = fuse_two_rankings(vec, es, rrf_k=60)
    ids = [d.metadata["chunk_id"] for d, _ in fused]
    assert ids == ["b", "a", "c"]


def test_fuse_query_rankings_boosts_shared_chunks() -> None:
    q1 = [(_doc("a"), 1.0), (_doc("b"), 0.5)]
    q2 = [(_doc("a"), 1.0), (_doc("c"), 0.5)]
    fused = fuse_query_rankings([q1, q2], rrf_k=60)
    assert fused[0][0].metadata["chunk_id"] == "a"


def test_parse_triples_requires_relation_predicate() -> None:
    payload = {
        "triples": [
            {
                "head_name": "甲",
                "tail_name": "乙",
                "relation_predicate": "位于",
            },
            {"head_name": "无关系", "tail_name": "节点"},
        ]
    }
    triples = parse_triples(payload)
    assert len(triples) == 1
    assert triples[0].head_name == "甲"


def test_load_prompt_system() -> None:
    from rag_core.prompts.loader import load_prompt

    text = load_prompt("system")
    assert "通用超级知识库助手" in text


def test_split_paragraph_spans() -> None:
    from rag_core.ingestion.split_spans import split_paragraph_spans

    content = "第一段\n\n第二段"
    spans = split_paragraph_spans(content)
    assert len(spans) == 2
