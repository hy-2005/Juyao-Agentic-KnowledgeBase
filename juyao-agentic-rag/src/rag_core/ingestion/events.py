# Kafka / HTTP 共用的「文档入库事件」处理：与 Java RagDocIngestService 发出的 JSON 字段一致。

from __future__ import annotations

import logging
from typing import Any

from rag_core.ingestion.pipeline import ingest_file
from rag_core.ingestion.cleanup import delete_document_from_indexes

logger = logging.getLogger(__name__)


def apply_kafka_ingest_payload(payload: dict[str, Any]) -> None:
    """执行 UPSERT（先删后写）或 DELETE；供 Kafka 消费者与 FastAPI 内部 HTTP 共用。"""
    v = int(payload.get("v") or 1)
    if v != 1:
        logger.warning("未知消息版本 v=%s，跳过", v)
        return
    action = str(payload.get("action") or "").upper()
    logical = str(payload.get("docLogicalKey") or "").strip()
    if not logical:
        logger.warning("缺少 docLogicalKey，跳过：%s", payload)
        return
    if action == "DELETE":
        logger.info("DELETE 索引：%s", logical)
        delete_document_from_indexes(logical, include_graph=True)
        return
    if action == "UPSERT":
        path = str(payload.get("localPath") or "").strip()
        if not path:
            logger.warning("UPSERT 缺少 localPath，跳过：%s", payload)
            return
        logger.info("UPSERT 先删后写：logical=%s path=%s", logical, path)
        ingest_file(path, source_name=logical, enable_graph=True, purge_before_write=True)
        return
    logger.warning("未知 action=%s，跳过", action)
