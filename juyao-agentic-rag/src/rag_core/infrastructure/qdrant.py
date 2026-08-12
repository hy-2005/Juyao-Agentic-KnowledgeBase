# 向量存储封装：Ollama Embedding + Qdrant，供入库与检索共用同一套配置。

import logging
from uuid import NAMESPACE_URL, uuid5

from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

from rag_core.core.config import get_settings
from rag_core.infrastructure.llm.factory import get_embeddings

logger = logging.getLogger(__name__)


def get_qdrant_client() -> QdrantClient:
    # 原生客户端：创建集合、删改数据等高级操作用；日常 add/search 可走 QdrantVectorStore。
    settings = get_settings()
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)


def ensure_collection_exists() -> None:
    # 确保目标 collection 存在；不存在则按当前 embedding 维度自动创建。
    settings = get_settings()
    client = get_qdrant_client()
    try:
        client.get_collection(collection_name=settings.qdrant_collection)
        return
    except UnexpectedResponse as exc:
        # 仅处理集合不存在；其它网络/鉴权错误继续抛出
        if "doesn't exist" not in str(exc) and "Not found" not in str(exc):
            raise

    # 用一条探针文本取回 embedding 维度，避免手写维度与模型不一致。
    dim = len(get_embeddings().embed_query("dimension probe"))
    client.create_collection(
        collection_name=settings.qdrant_collection,
        vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
    )


def get_vector_store() -> QdrantVectorStore:
    # LangChain 向量库门面：similarity_search_*、add_documents 等。
    settings = get_settings()
    return QdrantVectorStore(
        client=get_qdrant_client(),
        collection_name=settings.qdrant_collection,
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


def list_child_chunks_by_parent(parent_chunk_id: str) -> list[dict]:
    """按 parent_chunk_id 查 Qdrant 返回子块行列表(按 chunk_index 升序)。

    filter 用顶层 key 匹配不到 Qdrant 嵌套 payload,必须走 metadata.parent_chunk_id。
    """
    settings = get_settings()
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
                collection_name=settings.qdrant_collection,
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


def get_chunk_by_id_from_qdrant(chunk_id: str) -> dict | None:
    """按 chunk_id 查 Qdrant(payload metadata.chunk_id 精确匹配),返回完整行。"""
    settings = get_settings()
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
            collection_name=settings.qdrant_collection,
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
# 社区摘要独立 collection（派系 2 Step 2）：与 chunks 物理隔离，独立 upsert/delete
# ---------------------------------------------------------------------------


def _get_community_summary_embeddings():
    """社区摘要 embedding：默认跟随 settings.embed_provider/embed_model，可独立覆盖。

    派系 2 设计：摘要和 chunk 用同一套 embedding 便于后续 step 3 复用检索栈；
    若后续评估发现摘要用更大模型更合适，可通过 settings.community_summary_embed_provider
    /community_summary_embedding_model 单独指定（需在 factory 扩展 provider）。
    """
    settings = get_settings()
    if settings.community_summary_embed_provider or settings.community_summary_embedding_model:
        # 独立 provider/model 暂未在 factory 暴露，落到这里时回退到默认 embedding，
        # 避免误用主 embedding 模型导致维度不一致（参考 chunk/embedding 维度对齐）
        logger.info(
            "社区摘要 embedding 独立配置尚未实现，按主 embedding 走：provider=%s",
            settings.embed_provider,
        )
    return get_embeddings()


def ensure_community_collection_exists() -> None:
    """确保社区摘要 collection 存在；维度用探针取，避免手写与 embedding 模型不一致。

    复用 get_embeddings() 的同源模型，保证 collection 维度与实际写入向量严格匹配。
    """
    settings = get_settings()
    client = get_qdrant_client()
    try:
        client.get_collection(collection_name=settings.community_summary_collection)
        return
    except UnexpectedResponse as exc:
        if "doesn't exist" not in str(exc) and "Not found" not in str(exc):
            raise

    # 探针文本取 embedding 维度（与 chunk collection 走同一套 embedding 模型）
    dim = len(_get_community_summary_embeddings().embed_query("dimension probe"))
    client.create_collection(
        collection_name=settings.community_summary_collection,
        vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
    )
    logger.info(
        "Qdrant 社区摘要 collection 已创建：%s dim=%s",
        settings.community_summary_collection,
        dim,
    )


def upsert_community_summaries(communities: list[dict], *, kb: int | None) -> int:
    """把社区摘要批量写入 Qdrant 独立 collection；返回写入条数。

    输入项 fields：
      - community_id: str（必填，Neo4j Community.id 同源，如 "kb0:community:1"）
      - summary: str（必填，LLM 摘要文本）
      - entity_count: int（社区实体数）
      - entities: list[str]（实体名列表，写入 payload 便于检索结果直接展示）

    payload 顶层字段：community_id / summary / entity_count / entities / kb_id
    （保持扁平结构避免嵌套路径，Qdrant filter 走顶层 key 即可）。
    """
    settings = get_settings()
    if not communities:
        return 0

    client = get_qdrant_client()
    texts = [str(c.get("summary") or "") for c in communities]
    # embedding 调用一次批处理，避免逐条调用 N 次 LLM/Embedding 调用
    vectors = _get_community_summary_embeddings().embed_documents(texts)

    points = []
    for community, vector in zip(communities, vectors):
        community_id = str(community["community_id"])
        # 用 community_id 派生 UUID，保证 upsert 幂等（同一社区重建会覆盖而非重复）
        point_id = uuid5(NAMESPACE_URL, f"community_summary:{community_id}")
        points.append(
            models.PointStruct(
                id=str(point_id),
                vector=vector,
                payload={
                    "community_id": community_id,
                    "summary": community.get("summary", ""),
                    "entity_count": int(community.get("entity_count") or 0),
                    "entities": list(community.get("entities") or []),
                    "kb_id": int(kb) if kb is not None else None,
                },
            )
        )

    client.upsert(
        collection_name=settings.community_summary_collection,
        points=points,
    )
    logger.info(
        "Qdrant 社区摘要写入：%s 条 → %s",
        len(points),
        settings.community_summary_collection,
    )
    return len(points)


def delete_community_summaries_by_ids(community_ids: list[str]) -> int:
    """按 community_id 列表删除摘要点（孤儿社区清理用，不调 LLM 的轻量路径）。

    payload 里 community_id 是顶层 key（见 upsert_community_summaries），filter 走顶层。
    """
    if not community_ids:
        return 0
    settings = get_settings()
    client = get_qdrant_client()
    flt = models.Filter(
        must=[
            models.FieldCondition(
                key="community_id",
                match=models.MatchAny(any=community_ids),
            )
        ]
    )
    try:
        result = client.delete(
            collection_name=settings.community_summary_collection,
            points_selector=models.FilterSelector(filter=flt),
        )
    except UnexpectedResponse as exc:
        # collection 还没建好时直接视为 0
        if "doesn't exist" in str(exc) or "Not found" in str(exc):
            return 0
        raise
    deleted = getattr(result, "result", None) or {}
    count = int(deleted.get("points_count", 0)) if isinstance(deleted, dict) else 0
    logger.info("Qdrant 社区摘要按 id 删除：%s 个 community_ids → %s 条", len(community_ids), count)
    return count


def delete_community_summaries(kb: int | None) -> int:
    """按 kb_id 删社区摘要 collection 中的点；返回删除条数（0 也正常返回）。

    kb_id 顶层 payload 字段（见 upsert_community_summaries）；None 时不限 kb，
    但通常只在 reset=True + 已知 kb 的场景下调用，避免误删。
    """
    settings = get_settings()
    client = get_qdrant_client()
    must: list = []
    if kb is not None:
        must.append(
            models.FieldCondition(
                key="kb_id",
                match=models.MatchValue(value=int(kb)),
            )
        )
    flt = models.Filter(must=must) if must else None
    try:
        result = client.delete(
            collection_name=settings.community_summary_collection,
            points_selector=models.FilterSelector(filter=flt) if flt else models.FilterSelector(),
        )
    except UnexpectedResponse as exc:
        # collection 还没建好时直接视为 0
        if "doesn't exist" in str(exc) or "Not found" in str(exc):
            return 0
        raise
    deleted = getattr(result, "result", None) or {}
    # collection_status / points_count 之类的字段；统一只取数字
    count = int(deleted.get("points_count", 0)) if isinstance(deleted, dict) else 0
    logger.info(
        "Qdrant 社区摘要删除：kb=%s count=%s", kb, count,
    )
    return count
