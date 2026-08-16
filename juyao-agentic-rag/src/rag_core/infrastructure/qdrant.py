# 向量存储封装：Qdrant，供入库与检索共用同一套配置。
#
# 多知识库物理隔离：每 kb 一个 collection（chunk_collection(kb) 命名，kb=0 沿用原名
# 兼容存量数据）——不再共享单 collection 用 metadata.kb_id 过滤（PITFALLS #24 同根：
# 过滤方案随数据量线性变慢且有串库风险）。

import logging
from uuid import NAMESPACE_URL, uuid5

from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

from rag_core.core.config import chunk_collection, get_settings, kg_card_collection
from rag_core.infrastructure.llm.factory import get_embeddings, get_kg_card_embeddings

logger = logging.getLogger(__name__)


def get_qdrant_client() -> QdrantClient:
    # 原生客户端：创建集合、删改数据等高级操作用；日常 add/search 可走 QdrantVectorStore。
    settings = get_settings()
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)


def _ensure_collection(name: str) -> None:
    # 确保指定 collection 存在；不存在则按当前 embedding 维度自动创建（探针取维度避免手写不一致）。
    client = get_qdrant_client()
    try:
        client.get_collection(collection_name=name)
        return
    except UnexpectedResponse as exc:
        # 仅处理集合不存在；其它网络/鉴权错误继续抛出
        if "doesn't exist" not in str(exc) and "Not found" not in str(exc):
            raise

    dim = len(get_embeddings().embed_query("dimension probe"))
    try:
        client.create_collection(
            collection_name=name,
            vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        )
    except UnexpectedResponse as exc:
        # 「查了不存在 → 再创建」不是原子的：并发入库/消息重试时集合可能已被
        # 另一线程创建（409 Conflict）——幂等容忍，直接复用（踩坑见 PITFALLS #28）
        if "already exists" in str(exc):
            logger.info("Qdrant collection 已存在（并发创建容忍，直接复用）：%s", name)
            return
        raise
    logger.info("Qdrant collection 已创建：%s dim=%s", name, dim)


def ensure_collection_exists(kb_id: int = 0) -> None:
    # 确保切片 collection 存在（按 kb 命名，kb=0 沿用原名兼容存量数据）。
    _ensure_collection(chunk_collection(kb_id))


def get_vector_store(kb_id: int = 0) -> QdrantVectorStore:
    # LangChain 向量库门面：similarity_search_*、add_documents 等（按 kb 选 collection）。
    return QdrantVectorStore(
        client=get_qdrant_client(),
        collection_name=chunk_collection(kb_id),
        embedding=get_embeddings(),
    )


def _qdrant_point_to_row(point: dict) -> dict:
    """Qdrant scroll point → 管理台行字典(与 ES 行结构对齐)。

    原生 client.scroll 返回 pydantic Record 而非 dict;统一归一化为 dict 再取字段。
    """
    if not isinstance(point, dict):
        point = point.model_dump()
    payload = point.get("payload") or {}
    meta = payload.get("metadata") or {}
    row = {
        "chunk_id": meta.get("chunk_id"),
        "chunk_index": meta.get("chunk_index"),
        "start_char": meta.get("start_char"),
        "end_char": meta.get("end_char"),
        "parent_chunk_id": meta.get("parent_chunk_id"),
        "source_name": meta.get("source_name"),
        "source_doc_id": meta.get("source_doc_id"),
        "content": payload.get("page_content"),
    }
    return {k: v for k, v in row.items() if v is not None}


def list_child_chunks_by_parent(parent_chunk_id: str, kb_id: int = 0) -> list[dict]:
    """按 parent_chunk_id 查 Qdrant 返回子块行列表(按 chunk_index 升序)。

    filter 用顶层 key 匹配不到 Qdrant 嵌套 payload,必须走 metadata.parent_chunk_id。
    kb 物理隔离：只查该 kb 的 collection（kb=0 兼容存量）。
    """
    client = get_qdrant_client()
    scroll_filter = models.Filter(
        must=[
            models.FieldCondition(
                key="metadata.parent_chunk_id",
                match=models.MatchValue(value=parent_chunk_id),
            )
        ]
    )
    # scroll 返回的是 pydantic Record 而非 dict,标注为 list 即可(实际类型见 _qdrant_point_to_row)
    points: list = []
    offset: int | None = None
    try:
        while True:
            resp = client.scroll(
                collection_name=chunk_collection(kb_id),
                scroll_filter=scroll_filter,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            batch = resp[0] or []
            points.extend(batch)
            offset = resp[1]
            if offset is None or not batch:
                break
    except Exception as exc:
        # 与 list_chunks 一致:查询失败不阻断页面,返回空列表并告警
        logger.warning("Qdrant list_child_chunks_by_parent 失败：%s", exc)
        return []
    rows = [_qdrant_point_to_row(p) for p in points]
    # 防御:chunk_index 可能缺失或为 str(Qdrant payload 类型不保证),统一按 0 参与排序,避免 sort 比较时 TypeError
    rows.sort(key=lambda r: r.get("chunk_index") if isinstance(r.get("chunk_index"), int) else 0)
    return rows


def get_chunk_by_id_from_qdrant(chunk_id: str, kb_id: int = 0) -> dict | None:
    """按 chunk_id 查 Qdrant(payload metadata.chunk_id 精确匹配),返回完整行。"""
    client = get_qdrant_client()
    scroll_filter = models.Filter(
        must=[
            models.FieldCondition(
                key="metadata.chunk_id",
                match=models.MatchValue(value=chunk_id),
            )
        ]
    )
    try:
        resp = client.scroll(
            collection_name=chunk_collection(kb_id),
            scroll_filter=scroll_filter,
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as exc:
        logger.warning("Qdrant get_chunk_by_id_from_qdrant 失败：%s", exc)
        return None
    points = resp[0] or []
    if not points:
        return None
    return _qdrant_point_to_row(points[0])


# ---------------------------------------------------------------------------
# LightRAG 实体/关系卡片（LIGHTRAG_MIGRATION_REVIEW §4.3）：Neo4j 是事实源，
# 本 collection 是检索副本；type=entity|relation 元数据区分（payload index）。
# ---------------------------------------------------------------------------


def ensure_kg_card_collection_exists(kb_id: int = 0) -> None:
    """确保卡片 collection 存在（每 kb 独立；维度探针与主 embedding 同源）。

    创建后补 type 字段的 keyword payload index——local/global 检索都按 type 过滤，
    无 index 时 Qdrant 对全 collection 线性扫过滤，卡片多了会拖慢检索。
    """
    name = kg_card_collection(kb_id)
    client = get_qdrant_client()
    try:
        client.get_collection(collection_name=name)
        return
    except UnexpectedResponse as exc:
        if "doesn't exist" not in str(exc) and "Not found" not in str(exc):
            raise

    dim = len(get_kg_card_embeddings().embed_query("dimension probe"))
    try:
        client.create_collection(
            collection_name=name,
            vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        )
        logger.info("Qdrant 卡片 collection 已创建：%s dim=%s", name, dim)
    except UnexpectedResponse as exc:
        # 并发创建竞态（409）幂等容忍，与 _ensure_collection 同款
        if "already exists" not in str(exc):
            raise
    try:
        client.create_payload_index(
            collection_name=name,
            field_name="type",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
    except UnexpectedResponse as exc:
        # 已存在（409）不视为错误；其余告警不阻断——最坏只是检索慢一点
        if "already exists" not in str(exc):
            logger.warning("Qdrant 卡片 type payload index 创建失败（不阻断）：%s", exc)


def _kg_card_point_id(key: str) -> str:
    """卡片 key → 幂等 point id：同 key 重建覆盖而非重复（社区摘要同款 uuid5 模式）。"""
    return str(uuid5(NAMESPACE_URL, f"kg_card:{key}"))


def upsert_kg_cards(records: list[dict], *, kb: int | None) -> int:
    """批量写入实体/关系卡片；返回写入条数。

    records 每项 fields：
      - key: str（必填，幂等 id 来源；entity 卡=实体名，relation 卡="head|pred|tail"）
      - vector_text: str（必填，做 embedding 的锚定全文——关系卡必须含头尾实体防丢主客）
      - payload: dict（必填，type/name 或 head/predicate/tail/summary 等结构化字段）
    kb_id 由本函数注入 payload（冗余供对账，隔离由 collection 承担）。
    """
    if not records:
        return 0
    client = get_qdrant_client()
    # embedding 一次批处理：热门文档一次入库可能 touch 数百实体/关系
    vectors = get_kg_card_embeddings().embed_documents([str(r["vector_text"]) for r in records])
    points = []
    for record, vector in zip(records, vectors):
        payload = dict(record["payload"])
        payload["kb_id"] = int(kb) if kb is not None else 0
        points.append(
            models.PointStruct(
                id=_kg_card_point_id(str(record["key"])),
                vector=vector,
                payload=payload,
            )
        )
    name = kg_card_collection(kb)
    client.upsert(collection_name=name, points=points)
    logger.info("Qdrant 卡片写入：%s 条 → %s", len(points), name)
    return len(points)


def delete_kg_card_points(keys: list[str], kb_id: int = 0) -> int:
    """按卡片 key 列表删除点（purge 路径的副本清理；collection 不存在时视为 0）。"""
    if not keys:
        return 0
    client = get_qdrant_client()
    try:
        client.delete(
            collection_name=kg_card_collection(kb_id),
            points_selector=models.PointIdsList(points=[_kg_card_point_id(k) for k in keys]),
        )
        return len(keys)
    except UnexpectedResponse as exc:
        if "doesn't exist" in str(exc) or "Not found" in str(exc):
            return 0
        raise


def delete_all_kg_cards(kb: int | None) -> int:
    """清空该 kb 的全部卡片（rebuild 前重置；kb=0 沿用原名兼容存量）。"""
    client = get_qdrant_client()
    name = kg_card_collection(kb)
    try:
        # 空 Filter() = 匹配全部点（同 delete_community_summaries 的坑：FilterSelector 必填）
        result = client.delete(
            collection_name=name,
            points_selector=models.FilterSelector(filter=models.Filter()),
        )
    except UnexpectedResponse as exc:
        if "doesn't exist" not in str(exc) and "Not found" not in str(exc):
            raise
        return 0
    deleted = getattr(result, "result", None) or {}
    count = int(deleted.get("points_count", 0)) if isinstance(deleted, dict) else 0
    logger.info("Qdrant 卡片清空：kb=%s collection=%s count=%s", kb, name, count)
    return count
