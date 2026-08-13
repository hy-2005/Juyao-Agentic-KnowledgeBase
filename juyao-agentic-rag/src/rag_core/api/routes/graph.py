"""知识图谱管理路由（数据源：MySQL 快照表 + Neo4j 标签隔离图；按 kbId 隔离）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from rag_core.api.schemas_admin import (
    EdgeCreateRequest,
    EdgeUpdateRequest,
    EntityCreateRequest,
    EntityRenameRequest,
    GraphListResponse,
    GraphStatsResponse,
    GraphSubgraphResponse,
)
from rag_core.domain.graph.query.admin_mutations import (
    create_edge,
    create_entity,
    delete_edge,
    delete_entity,
    rename_entity,
    update_edge,
)
from rag_core.domain.graph.query.admin_queries import (
    fetch_all_edges,
    full_graph,
    graph_stats,
    list_communities,
    list_edges,
    list_entities,
    subgraph_from_seeds,
)

router = APIRouter(prefix="/api/v1/admin/graph", tags=["admin-graph"])


def _kb(kb_id: int | None) -> int:
    """kbId 参数归一化：缺省 0（单库默认）。"""
    return int(kb_id or 0)


def _mark_graph_dirty(kb_id: int) -> None:
    """图谱写操作后标记 kb dirty：30s 静默窗口后调度器重建社区 + 同步 MySQL 快照。

    管理查询已切 MySQL 快照——手工增删改图后若不触发同步，管理台列表/全图
    看不到刚做的修改（旧版直查 Neo4j 无此问题）。写操作都走这里，失败静默
    （标记失败只影响快照刷新时机，不影响写操作本身成功）。
    """
    try:
        from rag_core.application.ingest_flow.community_scheduler import get_scheduler

        get_scheduler().mark_dirty(kb_id)
    except Exception:
        pass


@router.get("/stats", response_model=GraphStatsResponse)
def admin_graph_stats(
    kb_id: int = Query(0, alias="kbId"),
    top_n: int = Query(10, alias="topN", ge=1, le=50),
):
    return GraphStatsResponse(**graph_stats(kb_id=_kb(kb_id), top_n=top_n))


@router.get("/communities")
def admin_list_communities(
    kb_id: int = Query(0, alias="kbId"),
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(10, alias="pageSize", ge=1, le=100),
):
    """社区列表（分页：id/摘要/实体数/成员实体），社区面板 + 点击聚焦用。"""
    rows, total = list_communities(kb_id=_kb(kb_id), page_num=page_num, page_size=page_size)
    return {"rows": rows, "total": total}


@router.get("/edges", response_model=GraphListResponse)
def admin_list_edges(
    kb_id: int = Query(0, alias="kbId"),
    source_name: str | None = Query(None, alias="sourceName"),
    entity: str | None = Query(None),
    relation: str | None = Query(None),
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1),
):
    rows, total = list_edges(
        kb_id=_kb(kb_id),
        source_name=source_name or None,
        entity=entity or None,
        relation=relation or None,
        page_num=page_num,
        page_size=page_size,
    )
    return GraphListResponse(rows=rows, total=total)


@router.get("/entities", response_model=GraphListResponse)
def admin_list_entities(
    kb_id: int = Query(0, alias="kbId"),
    keyword: str | None = Query(None),
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1),
):
    rows, total = list_entities(
        kb_id=_kb(kb_id),
        keyword=keyword or None,
        page_num=page_num,
        page_size=page_size,
    )
    return GraphListResponse(rows=rows, total=total)


@router.get("/subgraph", response_model=GraphSubgraphResponse)
def admin_subgraph(
    kb_id: int = Query(0, alias="kbId"),
    seed: str = Query(..., min_length=1),
    hops: int = Query(1, ge=1),
    limit: int = Query(0, ge=0, description="路径上限，0 使用默认 200"),
):
    seed_names = [s.strip() for s in seed.split(",") if s.strip()]
    data = subgraph_from_seeds(
        kb_id=_kb(kb_id), seed_names=seed_names, hops=hops, limit=limit
    )
    return GraphSubgraphResponse(**data)


@router.get("/full", response_model=GraphSubgraphResponse)
def admin_full_graph(
    kb_id: int = Query(0, alias="kbId"),
    limit: int = Query(0, ge=0, description="0 表示不截断"),
):
    # 禁止把 limit=0 转成 None 再传：full_graph 内 None=默认 300（防卡死兜底）、
    # 0=全量不加 LIMIT，转换会把「全量」请求静默降级成 300 条（PITFALLS #22 扩展）
    return GraphSubgraphResponse(**full_graph(kb_id=_kb(kb_id), limit=limit))


@router.get("/edges/all", response_model=GraphListResponse)
def admin_list_all_edges(
    kb_id: int = Query(0, alias="kbId"),
    limit: int = Query(0, ge=0, description="0 表示不截断"),
):
    # 同上：fetch_all_edges 内 None=默认 500、0=全量，路由层不得做 0→None 转换
    rows = fetch_all_edges(kb_id=_kb(kb_id), limit=limit)
    return GraphListResponse(rows=rows, total=len(rows))


@router.post("/entities")
def admin_create_entity(body: EntityCreateRequest, kb_id: int = Query(0, alias="kbId")):
    try:
        result = create_entity(body.name, kb_id=_kb(kb_id))
        _mark_graph_dirty(_kb(kb_id))
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/entities")
def admin_rename_entity(body: EntityRenameRequest, kb_id: int = Query(0, alias="kbId")):
    try:
        result = rename_entity(body.old_name, body.new_name, kb_id=_kb(kb_id))
        _mark_graph_dirty(_kb(kb_id))
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/entities")
def admin_delete_entity(
    name: str = Query(..., min_length=1), kb_id: int = Query(0, alias="kbId")
):
    try:
        result = delete_entity(name, kb_id=_kb(kb_id))
        _mark_graph_dirty(_kb(kb_id))
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/edges")
def admin_create_edge(body: EdgeCreateRequest, kb_id: int = Query(0, alias="kbId")):
    try:
        result = create_edge(
            head_name=body.head_name,
            relation_predicate=body.relation_predicate,
            tail_name=body.tail_name,
            evidence=body.evidence,
            kb_id=_kb(kb_id),
        )
        _mark_graph_dirty(_kb(kb_id))
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/edges")
def admin_update_edge(body: EdgeUpdateRequest, kb_id: int = Query(0, alias="kbId")):
    try:
        result = update_edge(
            head_name=body.head_name,
            relation_predicate=body.relation_predicate,
            tail_name=body.tail_name,
            new_head_name=body.new_head_name,
            new_relation_predicate=body.new_relation_predicate,
            new_tail_name=body.new_tail_name,
            evidence=body.evidence,
            kb_id=_kb(kb_id),
        )
        _mark_graph_dirty(_kb(kb_id))
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/edges")
def admin_delete_edge(
    head_name: str = Query(..., alias="headName"),
    relation_predicate: str = Query(..., alias="relationPredicate"),
    tail_name: str = Query(..., alias="tailName"),
    kb_id: int = Query(0, alias="kbId"),
):
    try:
        result = delete_edge(
            head_name=head_name,
            relation_predicate=relation_predicate,
            tail_name=tail_name,
            kb_id=_kb(kb_id),
        )
        _mark_graph_dirty(_kb(kb_id))
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
