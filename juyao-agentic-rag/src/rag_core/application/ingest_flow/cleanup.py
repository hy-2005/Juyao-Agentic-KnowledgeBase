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


def _prune_orphan_communities(kb_id: int | None) -> None:
    """删除后轻量清理社区：只删「没有成员实体的孤儿 Community 节点」+ 对应 Qdrant 摘要。

    不重跑 Leiden、不调 LLM 摘要——存活社区的摘要保留旧版（略过时可接受，
    下次任何入库会由调度器全量重建刷新，见 community_scheduler.py）。
    相比旧版全量重建（每次 30 社区 × LLM 摘要 ≈ 60 秒），本路径 <1 秒。
    失败仅告警不阻断删除。
    """
    try:
        from rag_core.infrastructure.neo4j import Neo4jTripleStore, community_label, entity_label
        from rag_core.infrastructure.qdrant import delete_community_summaries_by_ids

        store = Neo4jTripleStore()
        # 1. 查孤儿社区（无任何 MEMBER_OF 成员；MEMBER_OF 边在 purge 时已被 DETACH 清掉，这里兜底确认）
        # 标签隔离版：直接按 CommunityKb{id} 标签圈定本 kb 社区，无需 kb_ids 过滤
        clabel = community_label(kb_id or 0)
        elabel = entity_label(kb_id or 0)
        result = store._driver.execute_query(
            f"MATCH (c:{clabel}) WHERE NOT EXISTS {{ MATCH (:{elabel})-[:MEMBER_OF]->(c) }} "
            "RETURN c.id AS cid"
        )
        orphan_ids = [str(rec["cid"]) for rec in result.records]
        if not orphan_ids:
            return
        # 2. 删孤儿 Community 节点（DETACH 兜底清掉残留关系）
        store._run(f"MATCH (c:{clabel}) WHERE c.id IN $ids DETACH DELETE c", {"ids": orphan_ids})
        # 3. 删 Qdrant 摘要向量（避免检索命中已在 Neo4j 消失的社区）
        deleted = delete_community_summaries_by_ids(orphan_ids)
        logger.info(
            "【删除】孤儿社区清理完成：%s 个（kb=%s，Qdrant 摘要 %s 条）",
            len(orphan_ids),
            kb_id,
            deleted,
        )
    except Exception as exc:
        logger.warning("【删除】孤儿社区清理失败（不阻断删除）：%s", exc)


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
        Neo4jTripleStore().purge_document_edges(
            name_prefix=prefix, source_display_name=source_name, kb_id=kb_id
        )
        # 社区同步维护：实体删除后清理孤儿社区（轻量，不调 LLM；全量刷新靠下次入库调度）
        _prune_orphan_communities(kb_id)


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
        Neo4jTripleStore().purge_chunk_ids(chunk_ids, kb_id=kb_id)
        # 社区同步维护（差集清理同样会删实体）：轻量清理孤儿社区，不调 LLM
        _prune_orphan_communities(kb_id)
    from rag_core.infrastructure.mysql_chunks import delete_chunks_from_mysql_by_ids

    mysql_deleted = delete_chunks_from_mysql_by_ids(chunk_ids)
    if mysql_deleted:
        logger.info("MySQL 已按 chunk_id 差集删除 %s 条", mysql_deleted)


def purge_kb(kb_id: int) -> None:
    """按知识库清空全部数据（删除 kb 的级联清理，TENANT_PERMISSION P2）。

    Qdrant 按 kb_id 删全部点；ES delete_by_query；Neo4j 清该 kb 的边 + 孤立节点。
    """
    from rag_core.core.config import chunk_collection, community_collection, es_index
    from rag_core.infrastructure.neo4j import Neo4jTripleStore

    # 物理隔离：Qdrant/ES 直接删该 kb 的容器（collection/index），
    # 不再 scroll 逐批按 kb filter 删——清 kb = 删容器，秒级完成且无残留风险
    client = get_qdrant_client()
    for collection in (chunk_collection(kb_id), community_collection(kb_id)):
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

    # 标签隔离版：按 EntityKb{id}/CommunityKb{id} 标签整片 DETACH DELETE——
    # 每 kb 的图谱是独立标签集合，清 kb = 删两个标签的全部节点（连带 RELATED/MEMBER_OF），
    # 不再需要共享边/共享实体的数组过滤与残留清理
    store = Neo4jTripleStore()
    from rag_core.infrastructure.neo4j import community_label, entity_label

    with store._driver.session() as session:
        session.run(f"MATCH (n:{entity_label(kb_id)}) DETACH DELETE n")
        session.run(f"MATCH (c:{community_label(kb_id)}) DETACH DELETE c")
    logger.info("【清空 kb】Neo4j 清理完成 kb=%s", kb_id)

    from rag_core.infrastructure.mysql_chunks import purge_kb_from_mysql

    mysql_deleted = purge_kb_from_mysql(kb_id)
    logger.info("【清空 kb】MySQL 切片删除 %s 条", mysql_deleted)

    # 图谱快照四表也是 MySQL 持久化数据，删 kb 必须一并清掉，否则管理台留孤儿行
    from rag_core.infrastructure.mysql_graph import purge_kb_graph_snapshot

    purge_kb_graph_snapshot(kb_id)

    # 社区同步维护：kb 清空后图谱为空 → 所有社区变孤儿，轻量清理即可删光（等价全量重建的空结果）
    _prune_orphan_communities(kb_id)
