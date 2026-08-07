# 向量存储封装：Ollama Embedding + Qdrant，供入库与检索共用同一套配置。

import logging

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
    points: list[dict] = []
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
    rows.sort(key=lambda r: r.get("chunk_index") or 0)
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
