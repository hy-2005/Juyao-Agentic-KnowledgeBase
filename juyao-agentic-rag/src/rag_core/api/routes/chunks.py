"""切片只读管理路由（数据源：Elasticsearch）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from rag_core.api.schemas_admin import ChunkListResponse, ChunkStatsResponse
from rag_core.indexing.elasticsearch import chunk_stats_by_source, get_chunk_by_id, list_chunks

router = APIRouter(prefix="/api/v1/admin/chunks", tags=["admin-chunks"])


@router.get("", response_model=ChunkListResponse)
def admin_list_chunks(
    source_name: str | None = Query(None, alias="sourceName"),
    keyword: str | None = Query(None),
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=100),
):
    rows, total = list_chunks(
        source_name=source_name or None,
        keyword=keyword or None,
        page_num=page_num,
        page_size=page_size,
    )
    return ChunkListResponse(rows=rows, total=total)


@router.get("/stats", response_model=ChunkStatsResponse)
def admin_chunk_stats(source_name: str | None = Query(None, alias="sourceName")):
    data = chunk_stats_by_source(source_name=source_name or None)
    return ChunkStatsResponse(**data)


@router.get("/{chunk_id}")
def admin_get_chunk(chunk_id: str):
    row = get_chunk_by_id(chunk_id)
    if not row:
        raise HTTPException(status_code=404, detail="切片不存在")
    return row
