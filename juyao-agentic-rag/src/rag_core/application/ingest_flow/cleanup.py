# 按「逻辑文档名」从 Qdrant / ES / Neo4j 撤掉该文档产生的数据（与入库 metadata.source_name 对齐）。

from __future__ import annotations

import logging

from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

from rag_core.core.config import get_settings
from rag_core.infrastructure.neo4j import Neo4jTripleStore
from rag_core.infrastructure.elasticsearch import get_elasticsearch_client
from rag_core.infrastructure.qdrant import get_qdrant_client

logger = logging.getLogger(__name__)


def _rebuild_communities_after_delete(kb_id: int | None) -> None:
    """删除后重建社区：实体被删后 Community/MEMBER_OF 会残留悬空引用、摘要过时。

    与入库侧对称（入库后 build_communities），保证删除后社区与图谱一致；
    失败仅告警不阻断删除（社区可后续手动重建）。
    """
    try:
        from rag_core.application.graph.community_build import build_communities

        community_count = build_communities(kb=kb_id, reset=True)
        logger.info("【删除】社区重建完成：%s 个（kb=%s）", community_count, kb_id)
    except Exception as exc:
        logger.warning("【删除】社区重建失败（不阻断删除）：%s", exc)


def delete_from_qdrant_by_source_name(source_name: str, kb_id: int | None = None) -> int:
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
        conditions = [models.FieldCondition(key=key, match=models.MatchValue(value=source_name))]
        if kb_id is not None:
            conditions.append(
                models.FieldCondition(key="metadata.kb_id", match=models.MatchValue(value=int(kb_id)))
            )
        flt = models.Filter(must=conditions)
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
        logger.info("Qdrant 已按 source_name=%s kb=%s 删除 %s 个点", source_name, kb_id, total)
    return total


def delete_from_elasticsearch_by_source_name(source_name: str, kb_id: int | None = None) -> int:
    settings = get_settings()
    client = get_elasticsearch_client()
    if not client.indices.exists(index=settings.elasticsearch_index):
        return 0
    if kb_id is not None:
        body = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"source_name": source_name}},
                        {"term": {"kb_id": int(kb_id)}},
                    ]
                }
            }
        }
    else:
        body = {"query": {"term": {"source_name": source_name}}}
    resp = client.delete_by_query(index=settings.elasticsearch_index, body=body, refresh=True)
    deleted = int(resp.get("deleted", 0) or 0)
    if deleted:
        logger.info("Elasticsearch 已按 source_name=%s kb=%s 删除 %s 条", source_name, kb_id, deleted)
    return deleted


def delete_document_from_indexes(
    source_name: str, *, include_graph: bool = True, kb_id: int | None = None
) -> None:
    """与入库时 split_into_chunks 的 source_name 一致（通常为逻辑文件名）。"""
    delete_from_qdrant_by_source_name(source_name, kb_id=kb_id)
    delete_from_elasticsearch_by_source_name(source_name, kb_id=kb_id)
    from rag_core.infrastructure.mysql_chunks import delete_chunks_from_mysql_by_source

    mysql_deleted = delete_chunks_from_mysql_by_source(source_name, kb_id=kb_id)
    if mysql_deleted:
        logger.info("MySQL 已按 source_name=%s kb=%s 删除 %s 条", source_name, kb_id, mysql_deleted)
    if include_graph:
        prefix = f"{kb_id}:{source_name.replace(' ', '_')}:" if kb_id is not None else source_name.replace(" ", "_") + ":"
        Neo4jTripleStore().purge_document_edges(
            name_prefix=prefix, source_display_name=source_name, kb_id=kb_id
        )
        # 社区同步维护：实体删除后 Community/MEMBER_OF 悬空引用与摘要需重建
        _rebuild_communities_after_delete(kb_id)


def delete_chunks_by_ids(chunk_ids: list[str], *, include_graph: bool = True, kb_id: int | None = None) -> None:
    """按 chunk_id 列表精确删除（先写后删的差集清理用）。

    不能按 source_name 整体删——新写入的同 key 数据会被一起删光（历史 bug），
    必须用「旧 id − 新 id」的差集逐 id 删。
    """
    import uuid

    from rag_core.infrastructure.elasticsearch import get_elasticsearch_client
    from rag_core.infrastructure.qdrant import get_qdrant_client

    if not chunk_ids:
        return
    settings = get_settings()
    client = get_qdrant_client()
    # Qdrant：point id = uuid5(chunk_id)，按 id 列表删
    try:
        client.get_collection(collection_name=settings.qdrant_collection)
    except UnexpectedResponse as exc:
        if "404" in str(exc) or "Not found" in str(exc) or "doesn't exist" in str(exc):
            return
        raise
    point_ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, cid)) for cid in chunk_ids]
    client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=models.PointIdsList(points=point_ids),
    )
    # ES：按 _id 列表删（ES _id = chunk_id）
    es = get_elasticsearch_client()
    if es.indices.exists(index=settings.elasticsearch_index):
        es.delete_by_query(
            index=settings.elasticsearch_index,
            body={"query": {"terms": {"_id": chunk_ids}}},
            refresh=True,
        )
    if include_graph:
        Neo4jTripleStore().purge_chunk_ids(chunk_ids, kb_id=kb_id)
        # 社区同步维护（差集清理同样会删实体）
        _rebuild_communities_after_delete(kb_id)
    from rag_core.infrastructure.mysql_chunks import delete_chunks_from_mysql_by_ids

    mysql_deleted = delete_chunks_from_mysql_by_ids(chunk_ids)
    if mysql_deleted:
        logger.info("MySQL 已按 chunk_id 差集删除 %s 条", mysql_deleted)


def purge_kb(kb_id: int) -> None:
    """按知识库清空全部数据（删除 kb 的级联清理，TENANT_PERMISSION P2）。

    Qdrant 按 kb_id 删全部点；ES delete_by_query；Neo4j 清该 kb 的边 + 孤立节点。
    """
    from rag_core.infrastructure.neo4j import Neo4jTripleStore

    settings = get_settings()
    client = get_qdrant_client()
    try:
        client.get_collection(collection_name=settings.qdrant_collection)
        flt = models.Filter(
            must=[models.FieldCondition(key="metadata.kb_id", match=models.MatchValue(value=int(kb_id)))]
        )
        cnt = 0
        offset = None
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
            cnt += len(ids)
            if offset is None:
                break
        logger.info("【清空 kb】Qdrant 删除 %s 个点", cnt)
    except UnexpectedResponse as exc:
        if "404" in str(exc) or "Not found" in str(exc) or "doesn't exist" in str(exc):
            pass
        else:
            raise

    es = get_elasticsearch_client()
    if es.indices.exists(index=settings.elasticsearch_index):
        resp = es.delete_by_query(
            index=settings.elasticsearch_index,
            body={"query": {"term": {"kb_id": int(kb_id)}}},
            refresh=True,
        )
        logger.info("【清空 kb】ES 删除 %s 条", resp.get("deleted", 0))

    store = Neo4jTripleStore()
    with store._driver.session() as session:
        session.run(
            """
            MATCH ()-[r:RELATED]->()
            WHERE $kb IN coalesce(r.kb_ids, [])
            SET r.chunk_ids = [c IN coalesce(r.chunk_ids, []) WHERE NOT c STARTS WITH $prefix],
                r.doc_ids = [d IN coalesce(r.doc_ids, []) WHERE NOT d STARTS WITH $prefix],
                r.kb_ids = [k IN coalesce(r.kb_ids, []) WHERE k <> $kb]
            """,
            {"kb": int(kb_id), "prefix": f"{kb_id}:"},
        )
        session.run(
            """
            MATCH ()-[r:RELATED]->()
            WHERE size(coalesce(r.kb_ids, [])) = 0 AND size(coalesce(r.chunk_ids, [])) = 0
            DELETE r
            """
        )
        session.run("MATCH (e:Entity) WHERE NOT (e)-[:RELATED]-() DELETE e")
    logger.info("【清空 kb】Neo4j 清理完成 kb=%s", kb_id)

    from rag_core.infrastructure.mysql_chunks import purge_kb_from_mysql

    mysql_deleted = purge_kb_from_mysql(kb_id)
    logger.info("【清空 kb】MySQL 删除 %s 条", mysql_deleted)

    # 社区同步维护：kb 清空后 Community/MEMBER_OF 一并重建（此时图谱为空 → 0 社区）
    _rebuild_communities_after_delete(kb_id)
