# Kafka / HTTP 共用的「文档入库事件」处理：与 Java RagDocIngestService 发出的 JSON 字段一致。

from __future__ import annotations

import logging
from typing import Any

from rag_core.application.ingest_flow.ingest import ingest_file
from rag_core.application.ingest_flow.cleanup import delete_document_from_indexes
from rag_core.application.ingest_flow.hash_guard import prepare_upsert

logger = logging.getLogger(__name__)


def apply_kafka_ingest_payload(payload: dict[str, Any], *, build_communities: bool = True) -> None:
    """执行 UPSERT（先删后写）或 DELETE；供 Kafka 消费者与 FastAPI 内部 HTTP 共用。

    build_communities=False 时入库不立即同步图谱快照（由 graph_sync_scheduler 静默窗口统一同步）。
    返回 (kb_id, changed)：changed=True 表示内容真正写库（hash 判重通过），
    上层据此标记 dirty 等待调度器同步；CLI 等直接调用方保持默认 True。
    """
    v = int(payload.get("v") or 1)
    if v != 1:
        logger.warning("未知消息版本 v=%s，跳过", v)
        return None, False
    action = str(payload.get("action") or "").upper()
    logical = str(payload.get("docLogicalKey") or "").strip()
    if not logical:
        logger.warning("缺少 docLogicalKey，跳过：%s", payload)
        return None, False
    # Java 侧 payload 用 camelCase kbId（见 RagDocIngestService）；缺省 0（单库）
    kb_id = int(payload.get("kbId") or 0)
    if action == "DELETE":
        logger.info("DELETE 索引：%s kb=%s", logical, kb_id)
        delete_document_from_indexes(logical, include_graph=True, kb_id=kb_id)
        return kb_id, False
    if action == "UPSERT":
        path = str(payload.get("localPath") or "").strip()
        if not path:
            logger.warning("UPSERT 缺少 localPath，跳过：%s", payload)
            return kb_id, False
        payload_sha = str(payload.get("contentSha256") or "")
        decision, file_sha = prepare_upsert(logical, path, payload_sha256=payload_sha, kb_id=kb_id)
        if decision != "proceed":
            return kb_id, False
        logger.info("UPSERT 先删后写：logical=%s kb=%s path=%s sha=%s…", logical, kb_id, path, file_sha[:12])
        ingest_file(
            path,
            source_name=logical,
            enable_graph=True,
            purge_before_write=True,
            content_sha256=file_sha,
            kb_id=kb_id,
            build_communities=build_communities,
        )
        return kb_id, True
    logger.warning("未知 action=%s，跳过", action)
    return kb_id, False
