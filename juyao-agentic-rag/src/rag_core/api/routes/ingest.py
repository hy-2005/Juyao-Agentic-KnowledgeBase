"""内部入库 webhook。"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request

from rag_core.core.config import get_settings
from rag_core.ingestion.events import apply_kafka_ingest_payload

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
    await asyncio.to_thread(apply_kafka_ingest_payload, body)
    logger.info("[RAG-HTTP] ingest done doc=%s elapsedMs=%.0f", doc, (time.perf_counter() - t0) * 1000)
    return {"ok": True}
