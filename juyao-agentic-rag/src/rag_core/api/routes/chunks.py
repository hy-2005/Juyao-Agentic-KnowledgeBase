"""切片只读管理路由（数据源：MySQL rag_chunk；ES 仅保留做全文检索）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from rag_core.api.schemas_admin import ChunkListResponse, ChunkStatsResponse
from rag_core.infrastructure.mysql_chunks import (
    chunk_stats_by_source_mysql,
    get_chunk_by_id_mysql,
    list_chunks_mysql,
)

router = APIRouter(prefix="/api/v1/admin/chunks", tags=["admin-chunks"])


@router.get("", response_model=ChunkListResponse)
def admin_list_chunks(
    kb_id: int = Query(0, alias="kbId"),
    source_name: str | None = Query(None, alias="sourceName"),
    keyword: str | None = Query(None),
    page_num: int = Query(1, alias="pageNum", ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=100),
):
    rows, total = list_chunks_mysql(
        source_name=source_name or None,
        keyword=keyword or None,
        kb_id=kb_id,
        page_num=page_num,
        page_size=page_size,
    )
    return ChunkListResponse(rows=rows, total=total)


@router.get("/stats", response_model=ChunkStatsResponse)
def admin_chunk_stats(
    kb_id: int = Query(0, alias="kbId"),
    source_name: str | None = Query(None, alias="sourceName"),
):
    data = chunk_stats_by_source_mysql(source_name=source_name or None, kb_id=kb_id)
    return ChunkStatsResponse(**data)


@router.get("/{chunk_id}/children")
def admin_list_chunk_children(chunk_id: str):
    """父子分块:按父 chunk_id 查子块列表(MySQL 按 parent_chunk_id 过滤)。"""
    conn_rows = _query_children(chunk_id)
    return {"rows": conn_rows, "total": len(conn_rows)}


def _query_children(parent_chunk_id: str) -> list[dict]:
    """按 parent_chunk_id 查子块（子块也在 rag_chunk 表,含完整正文）。

    include_full_content=True：展开区直接展示子块正文（前端用 content 预览），
    缺省只给 content_preview 会导致展开区空白。
    """
    from rag_core.infrastructure.mysql_chunks import _connect, _row_to_chunk_row

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM rag_chunk WHERE parent_chunk_id = %s ORDER BY chunk_index ASC",
                (parent_chunk_id,),
            )
            return [_row_to_chunk_row(r, include_full_content=True) for r in cur.fetchall()]
    finally:
        conn.close()


@router.get("/{chunk_id}")
def admin_get_chunk(chunk_id: str):
    row = get_chunk_by_id_mysql(chunk_id)
    if not row:
        raise HTTPException(status_code=404, detail="切片不存在")
    return row
