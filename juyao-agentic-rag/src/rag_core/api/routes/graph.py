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
from rag_core.knowledge_graph.admin_mutations import (
    create_edge,
    create_entity,
    delete_edge,
    delete_entity,
    rename_entity,
    update_edge,
)
from rag_core.knowledge_graph.admin_queries import (
    fetch_all_edges,
    full_graph,
    graph_stats,
    list_edges,
    list_entities,
    subgraph_from_seeds,
)

router = APIRouter(prefix="/api/v1/admin/graph", tags=["admin-graph"])


@router.get("/stats", response_model=GraphStatsResponse)
def admin_graph_stats(top_n: int = Query(10, alias="topN", ge=1, le=50)):
    return GraphStatsResponse(**graph_stats(top_n=top_n))


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
    limit: int = Query(0, ge=0, description="0 表示不截断"),
):
    seed_names = [s.strip() for s in seed.split(",") if s.strip()]
    eff_limit = None if limit <= 0 else limit
    data = subgraph_from_seeds(seed_names=seed_names, hops=hops, limit=eff_limit)
    return GraphSubgraphResponse(**data)


@router.get("/full", response_model=GraphSubgraphResponse)
def admin_full_graph(limit: int = Query(0, ge=0, description="0 表示不截断")):
    eff_limit = None if limit <= 0 else limit
    return GraphSubgraphResponse(**full_graph(limit=eff_limit))


@router.get("/edges/all", response_model=GraphListResponse)
def admin_list_all_edges():
    rows = fetch_all_edges()
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
