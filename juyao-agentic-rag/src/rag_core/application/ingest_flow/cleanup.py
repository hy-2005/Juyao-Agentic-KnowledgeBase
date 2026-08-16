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


def delete_from_qdrant_by_source_name(source_name: str, kb_id: int | None = None) -> int:
    # 物理隔离：只删该 kb 的 collection（kb=0 沿用原名兼容存量），无需 kb filter
    from rag_core.core.config import chunk_collection

    name = chunk_collection(kb_id)
    client = get_qdrant_client()
    try:
        client.get_collection(collection_name=name)
    except UnexpectedResponse as exc:
        if "404" in str(exc) or "Not found" in str(exc) or "doesn't exist" in str(exc):
            logger.info(
                "Qdrant 集合 %s 尚不存在，跳过按 source_name 删除（首次入库前常见）",
                name,
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
                collection_name=name,
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
                collection_name=name,
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
    # 物理隔离：只删该 kb 的 index（kb=0 沿用原名兼容存量），无需 kb term 过滤
    from rag_core.core.config import es_index

    name = es_index(kb_id)
    client = get_elasticsearch_client()
    if not client.indices.exists(index=name):
        return 0
    body = {"query": {"term": {"source_name": source_name}}}
    resp = client.delete_by_query(index=name, body=body, refresh=True)
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
        purged = Neo4jTripleStore().purge_document_edges(
            name_prefix=prefix, source_display_name=source_name, kb_id=kb_id
        )
        # LightRAG 卡片副本清理：删除的边卡/实体卡对应删除（幸存实体卡不回滚）
        try:
            from rag_core.application.graph.kg_card_sync import delete_kg_cards_for

            delete_kg_cards_for(
                int(kb_id or 0),
                deleted_edges=purged.get("deleted_edges", []),
                deleted_entities=purged.get("deleted_entities", []),
            )
        except Exception as exc:
            logger.warning("【删除】卡片副本清理失败（不阻断，可 rebuild 修复）：%s", exc)


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
    from rag_core.core.config import chunk_collection, es_index

    client = get_qdrant_client()
    # Qdrant：point id = uuid5(chunk_id)，按 id 列表删（该 kb 的 collection）
    try:
        client.get_collection(collection_name=chunk_collection(kb_id))
    except UnexpectedResponse as exc:
        if "404" in str(exc) or "Not found" in str(exc) or "doesn't exist" in str(exc):
            return
        raise
    point_ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, cid)) for cid in chunk_ids]
    client.delete(
        collection_name=chunk_collection(kb_id),
        points_selector=models.PointIdsList(points=point_ids),
    )
    # ES：按 _id 列表删（ES _id = chunk_id；该 kb 的 index）
    es = get_elasticsearch_client()
    if es.indices.exists(index=es_index(kb_id)):
        es.delete_by_query(
            index=es_index(kb_id),
            body={"query": {"terms": {"_id": chunk_ids}}},
            refresh=True,
        )
    if include_graph:
        purged = Neo4jTripleStore().purge_chunk_ids(chunk_ids, kb_id=kb_id)
        # LightRAG 卡片副本清理（差集清理同样会删边/实体）
        try:
            from rag_core.application.graph.kg_card_sync import delete_kg_cards_for

            delete_kg_cards_for(
                int(kb_id or 0),
                deleted_edges=purged.get("deleted_edges", []),
                deleted_entities=purged.get("deleted_entities", []),
            )
        except Exception as exc:
            logger.warning("【删除】卡片副本清理失败（不阻断，可 rebuild 修复）：%s", exc)
    from rag_core.infrastructure.mysql_chunks import delete_chunks_from_mysql_by_ids

    mysql_deleted = delete_chunks_from_mysql_by_ids(chunk_ids)
    if mysql_deleted:
        logger.info("MySQL 已按 chunk_id 差集删除 %s 条", mysql_deleted)


def purge_kb(kb_id: int) -> None:
    """按知识库清空全部数据（删除 kb 的级联清理，TENANT_PERMISSION P2）。

    Qdrant 按 kb 删容器（chunks + kg_cards）；ES 删 index；Neo4j 清该 kb 标签的全部节点。
    """
    from rag_core.core.config import chunk_collection, es_index, kg_card_collection
    from rag_core.infrastructure.neo4j import Neo4jTripleStore, entity_label

    # 物理隔离：Qdrant/ES 直接删该 kb 的容器（collection/index），
    # 不再 scroll 逐批按 kb filter 删——清 kb = 删容器，秒级完成且无残留风险
    client = get_qdrant_client()
    for collection in (chunk_collection(kb_id), kg_card_collection(kb_id)):
        try:
            client.delete_collection(collection_name=collection)
            logger.info("【清空 kb】Qdrant collection %s 已删除", collection)
        except UnexpectedResponse as exc:
            if "404" in str(exc) or "Not found" in str(exc) or "doesn't exist" in str(exc):
                pass
            else:
                raise

    es = get_elasticsearch_client()
    if es.indices.exists(index=es_index(kb_id)):
        es.indices.delete(index=es_index(kb_id))
        logger.info("【清空 kb】ES index %s 已删除", es_index(kb_id))

    # 标签隔离版：按 EntityKb{id} 标签整片 DETACH DELETE（连带 RELATED/MEMBER_OF）；
    # CommunityKb{id} 是已废弃社区功能的存量节点，一并清掉防残留
    store = Neo4jTripleStore()
    with store._driver.session() as session:
        session.run(f"MATCH (n:{entity_label(kb_id)}) DETACH DELETE n")
        session.run(f"MATCH (c:CommunityKb{int(kb_id)}) DETACH DELETE c")
    logger.info("【清空 kb】Neo4j 清理完成 kb=%s", kb_id)

    from rag_core.infrastructure.mysql_chunks import purge_kb_from_mysql

    mysql_deleted = purge_kb_from_mysql(kb_id)
    logger.info("【清空 kb】MySQL 切片删除 %s 条", mysql_deleted)

    # 图谱快照四表也是 MySQL 持久化数据，删 kb 必须一并清掉，否则管理台留孤儿行
    from rag_core.infrastructure.mysql_graph import purge_kb_graph_snapshot

    purge_kb_graph_snapshot(kb_id)
