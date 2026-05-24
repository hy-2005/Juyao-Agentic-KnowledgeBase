# 按「逻辑文档名」从 Qdrant / ES / Neo4j 撤掉该文档产生的数据（与入库 metadata.source_name 对齐）。

from __future__ import annotations

import logging

from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

from rag_core.core.config import get_settings
from rag_core.knowledge_graph.store import Neo4jTripleStore
from rag_core.indexing.elasticsearch import get_elasticsearch_client
from rag_core.indexing.qdrant import get_qdrant_client

logger = logging.getLogger(__name__)


def delete_from_qdrant_by_source_name(source_name: str) -> int:
    settings = get_settings()
    client = get_qdrant_client()
    try:
        client.get_collection(collection_name=settings.qdrant_collection)
    except UnexpectedResponse as exc:
        if "404" in str(exc) or "Not found" in str(exc) or "doesn't exist" in str(exc):
            logger.info(
                "Qdrant 集合 %s 尚不存在，跳过按 source_name 删除（首次入库前常见）",
                settings.qdrant_collection,
            )
            return 0
        raise
    total = 0
    for key in ("metadata.source_name", "source_name"):
        flt = models.Filter(
            must=[models.FieldCondition(key=key, match=models.MatchValue(value=source_name))]
        )
        offset = None
        batch = 0
        while True:
            records, offset = client.scroll(
                collection_name=settings.qdrant_collection,
                scroll_filter=flt,
                limit=256,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            if not records:
                break
            ids = [r.id for r in records]
            client.delete(
                collection_name=settings.qdrant_collection,
                points_selector=models.PointIdsList(points=ids),
            )
            batch += len(ids)
            if offset is None:
                break
        total += batch
        if batch > 0:
            break
    if total:
        logger.info("Qdrant 已按 source_name=%s 删除 %s 个点", source_name, total)
    return total


def delete_from_elasticsearch_by_source_name(source_name: str) -> int:
    settings = get_settings()
    client = get_elasticsearch_client()
    if not client.indices.exists(index=settings.elasticsearch_index):
        return 0
    body = {"query": {"term": {"source_name": source_name}}}
    resp = client.delete_by_query(index=settings.elasticsearch_index, body=body, refresh=True)
    deleted = int(resp.get("deleted", 0) or 0)
    if deleted:
        logger.info("Elasticsearch 已按 source_name=%s 删除 %s 条", source_name, deleted)
    return deleted


def delete_document_from_indexes(source_name: str, *, include_graph: bool = True) -> None:
    """与入库时 split_into_chunks 的 source_name 一致（通常为逻辑文件名）。"""
    delete_from_qdrant_by_source_name(source_name)
    delete_from_elasticsearch_by_source_name(source_name)
    if include_graph:
        prefix = source_name.replace(" ", "_") + ":"
        Neo4jTripleStore().purge_document_edges(name_prefix=prefix, source_display_name=source_name)
