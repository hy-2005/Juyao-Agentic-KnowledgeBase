"""图谱详情持久化测试（GRAPH_DETAIL_PERSIST_REVIEW）：增量聚合携带 gloss/hints 进 MySQL 快照。"""

from langchain_core.documents import Document

from rag_core.application.ingest_flow.graph_writer import _accumulate_snapshot_delta
from rag_core.domain.graph.schema import Triple


def _triple(head, rel, tail, **kw):
    return Triple(head_name=head, relation_predicate=rel, tail_name=tail, **kw)


def test_accumulate_carries_gloss_and_hints():
    entities: dict = {}
    edges: dict = {}
    chunk = Document(page_content="x", metadata={"chunk_id": "doc:abc:0"})
    _accumulate_snapshot_delta(
        [
            _triple(
                "财政部", "提供补贴", "集成电路企业",
                head_gloss="负责财政收支的部门", tail_gloss="芯片制造企业",
                relation_full="补贴标准提高", relation_category="政策支持",
                time_text="2026年", evidence="原文摘录", modality="事实确定",
            )
        ],
        chunk,
        entities,
        edges,
    )
    # 实体：度数增量 + gloss 累积
    assert entities["财政部"][1] == 1 and entities["财政部"][0] == 0
    assert entities["财政部"][2] == {"负责财政收支的部门"}
    assert entities["集成电路企业"][0] == 1
    # 边：chunk_id + 全部 hints 集合
    edge = edges[("财政部", "提供补贴", "集成电路企业")]
    assert edge["chunk_ids"] == ["doc:abc:0"]
    assert edge["relation_full"] == {"补贴标准提高"}
    assert edge["categories"] == {"政策支持"}
    assert edge["time"] == {"2026年"}
    assert edge["evidence"] == {"原文摘录"}
    assert edge["modality"] == {"事实确定"}


def test_accumulate_merges_same_edge_across_chunks():
    """同一 (h,r,t) 跨 chunk：chunk_ids 追加、hints 集合去重合并（与 Neo4j 累积语义一致）。"""
    entities: dict = {}
    edges: dict = {}
    for i, gloss in enumerate(["角色A", "角色A", "角色B"]):
        _accumulate_snapshot_delta(
            [_triple("A", "关联", "B", head_gloss=gloss, relation_full=f"概括{i}")],
            Document(page_content="x", metadata={"chunk_id": f"doc:{i}"}),
            entities,
            edges,
        )
    edge = edges[("A", "关联", "B")]
    assert edge["chunk_ids"] == ["doc:0", "doc:1", "doc:2"]
    assert entities["A"][2] == {"角色A", "角色B"}  # 重复 gloss 去重
    assert edge["relation_full"] == {"概括0", "概括1", "概括2"}


def test_accumulate_skips_self_loop_and_empty():
    """自环/空实体名不进快照（与入库侧 upsert 过滤一致）。"""
    entities: dict = {}
    edges: dict = {}
    _accumulate_snapshot_delta(
        [_triple("A", "自指", "A"), _triple("", "空", "B")],
        Document(page_content="x", metadata={"chunk_id": "c"}),
        entities,
        edges,
    )
    assert entities == {} and edges == {}
