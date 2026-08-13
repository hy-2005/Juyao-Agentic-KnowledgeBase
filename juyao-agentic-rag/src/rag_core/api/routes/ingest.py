"""内部入库 webhook。"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request

from rag_core.core.config import get_settings
from rag_core.api.security import require_internal_token
from rag_core.application.ingest_flow.cleanup import purge_kb
from rag_core.application.ingest_flow.community_scheduler import get_scheduler
from rag_core.application.ingest_flow.events import apply_kafka_ingest_payload

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ingest"])


def _require_ingest_internal_token(request: Request) -> None:
    expected = (get_settings().rag_ingest_internal_token or "").strip()
    if not expected:
        return
    got = request.headers.get("X-Internal-Token") or request.headers.get("x-internal-token") or ""
    if got != expected:
        raise HTTPException(status_code=403, detail="invalid or missing X-Internal-Token")


@router.post("/api/v1/internal/rag/ingest/event")
async def internal_rag_ingest_event(request: Request, body: dict[str, Any] = Body(...)):
    _require_ingest_internal_token(request)
    action = str(body.get("action") or "")
    doc = str(body.get("docLogicalKey") or "")
    logger.info("[RAG-HTTP] 内部入库开始 action=%s doc=%s", action, doc)
    t0 = time.perf_counter()
    # 入库不立即重建社区：标记 dirty，由调度器在 30s 静默窗口统一重建（批量上传只重建一次）
    _, changed = await asyncio.to_thread(apply_kafka_ingest_payload, body, build_communities=False)
    if changed:
        scheduler = get_scheduler()
        scheduler.mark_dirty(int(body.get("kbId") or 0))
        scheduler.start()
    logger.info("[RAG-HTTP] ingest done doc=%s changed=%s elapsedMs=%.0f", doc, changed, (time.perf_counter() - t0) * 1000)
    return {"ok": True}



@router.get("/api/v1/internal/rag/community/status")
async def internal_community_status(request: Request):
    """社区重建调度状态（管理台批量模式开关展示）：自动重建开关 + 待重建/重建中的 kb。"""
    _require_ingest_internal_token(request)
    return get_scheduler().status()


@router.post("/api/v1/internal/rag/community/auto-rebuild")
async def internal_community_auto_rebuild(request: Request, body: dict[str, Any] = Body(...)):
    """批量入库模式开关：enabled=false 暂停自动重建（dirty 只积累），true 恢复。"""
    _require_ingest_internal_token(request)
    enabled = bool(body.get("enabled", True))
    get_scheduler().set_paused(not enabled)
    return {"ok": True, "autoRebuildEnabled": enabled}


@router.post("/api/v1/internal/rag/community/rebuild")
async def internal_community_rebuild(request: Request, body: dict[str, Any] = Body(...)):
    """手动立即重建：kbId 为空 = 全部 dirty kb；后台线程执行，立即返回。"""
    _require_ingest_internal_token(request)
    kb_id = body.get("kbId")
    get_scheduler().trigger_rebuild_now(int(kb_id) if kb_id is not None else None)
    return {"ok": True}


@router.delete("/api/v1/internal/rag/kb/{kb_id}")
async def internal_rag_purge_kb(kb_id: int, request: Request):
    """删除知识库的级联清理（TENANT_PERMISSION P2）：清空该 kb 的三库数据。"""
    require_internal_token(request)
    logger.info("[RAG-HTTP] 清空知识库开始 kb_id=%s", kb_id)
    await asyncio.to_thread(purge_kb, kb_id)
    logger.info("[RAG-HTTP] 清空知识库完成 kb_id=%s", kb_id)
    return {"ok": True}
