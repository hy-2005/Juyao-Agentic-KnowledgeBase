"""知识图谱管理路由（数据源：Neo4j）。"""

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


@router.get("/stats", response_model=GraphStatsResponse)
def admin_graph_stats(top_n: int = Query(10, alias="topN", ge=1, le=50)):
    return GraphStatsResponse(**graph_stats(top_n=top_n))


@router.get("/communities")
def admin_list_communities(
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(10, alias="pageSize", ge=1, le=100),
):
    """社区列表（分页：id/摘要/实体数/成员实体），社区面板 + 点击聚焦用。"""
    rows, total = list_communities(page_num=page_num, page_size=page_size)
    return {"rows": rows, "total": total}


@router.get("/edges", response_model=GraphListResponse)
def admin_list_edges(
    source_name: str | None = Query(None, alias="sourceName"),
    entity: str | None = Query(None),
    relation: str | None = Query(None),
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1),
):
    rows, total = list_edges(
        source_name=source_name or None,
        entity=entity or None,
        relation=relation or None,
        page_num=page_num,
        page_size=page_size,
    )
    return GraphListResponse(rows=rows, total=total)


@router.get("/entities", response_model=GraphListResponse)
def admin_list_entities(
    keyword: str | None = Query(None),
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1),
):
    rows, total = list_entities(
        keyword=keyword or None,
        page_num=page_num,
        page_size=page_size,
    )
    return GraphListResponse(rows=rows, total=total)


@router.get("/subgraph", response_model=GraphSubgraphResponse)
def admin_subgraph(
    seed: str = Query(..., min_length=1),
    hops: int = Query(1, ge=1),
    limit: int = Query(0, ge=0, description="路径上限，0 使用默认 200"),
):
    seed_names = [s.strip() for s in seed.split(",") if s.strip()]
    data = subgraph_from_seeds(seed_names=seed_names, hops=hops, limit=limit)
    return GraphSubgraphResponse(**data)


@router.get("/full", response_model=GraphSubgraphResponse)
def admin_full_graph(limit: int = Query(0, ge=0, description="0 表示不截断")):
    # 禁止把 limit=0 转成 None 再传：full_graph 内 None=默认 300（防卡死兜底）、
    # 0=全量不加 LIMIT，转换会把「全量」请求静默降级成 300 条（PITFALLS #22 扩展）
    return GraphSubgraphResponse(**full_graph(limit=limit))


@router.get("/edges/all", response_model=GraphListResponse)
def admin_list_all_edges(limit: int = Query(0, ge=0, description="0 表示不截断")):
    # 同上：fetch_all_edges 内 None=默认 500、0=全量，路由层不得做 0→None 转换
    rows = fetch_all_edges(limit=limit)
    return GraphListResponse(rows=rows, total=len(rows))


@router.post("/entities")
def admin_create_entity(body: EntityCreateRequest):
    try:
        return create_entity(body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/entities")
def admin_rename_entity(body: EntityRenameRequest):
    try:
        return rename_entity(body.old_name, body.new_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/entities")
def admin_delete_entity(name: str = Query(..., min_length=1)):
    try:
        return delete_entity(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/edges")
def admin_create_edge(body: EdgeCreateRequest):
    try:
        return create_edge(
            head_name=body.head_name,
            relation_predicate=body.relation_predicate,
            tail_name=body.tail_name,
            evidence=body.evidence,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/edges")
def admin_update_edge(body: EdgeUpdateRequest):
    try:
        return update_edge(
            head_name=body.head_name,
            relation_predicate=body.relation_predicate,
            tail_name=body.tail_name,
            new_head_name=body.new_head_name,
            new_relation_predicate=body.new_relation_predicate,
            new_tail_name=body.new_tail_name,
            evidence=body.evidence,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/edges")
def admin_delete_edge(
    head_name: str = Query(..., alias="headName"),
    relation_predicate: str = Query(..., alias="relationPredicate"),
    tail_name: str = Query(..., alias="tailName"),
):
    try:
        return delete_edge(
            head_name=head_name,
            relation_predicate=relation_predicate,
            tail_name=tail_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
