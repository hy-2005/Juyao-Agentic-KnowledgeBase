"""文档入库管线：切块 → Qdrant / Elasticsearch / Neo4j。"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path

from langchain_core.documents import Document

from tqdm import tqdm
from qdrant_client.http.exceptions import UnexpectedResponse

from rag_core.core.config import get_settings
from rag_core.infrastructure.elasticsearch import sync_chunks_to_elasticsearch
from rag_core.infrastructure.qdrant import ensure_collection_exists, get_qdrant_client, get_vector_store
from rag_core.application.ingest_flow.cleanup import delete_chunks_by_ids
from rag_core.application.ingest_flow.graph_writer import write_chunks_to_graph
from rag_core.infrastructure.loaders import load_document
from rag_core.application.ingest_flow.hash_guard import META_SHA_KEY, file_sha256_hex
from rag_core.domain.chunking.splitter import split_into_chunks, split_into_parent_child_chunks

logger = logging.getLogger(__name__)


def _collect_existing_chunk_ids(source_name: str, kb_id: int) -> list[str]:
    """按 (source_name, kb_id) 从 Qdrant 收集已存在的 chunk_id 列表。

    供先写后删的差集清理使用——不能按 source_name 整体删，
    否则新写入的同 key 数据会被一起删光（历史 bug）。
    """
    from qdrant_client.http import models

    client = get_qdrant_client()
    try:
        client.get_collection(collection_name=get_settings().qdrant_collection)
    except UnexpectedResponse as exc:
        if "404" in str(exc) or "Not found" in str(exc) or "doesn't exist" in str(exc):
            return []
        raise
    flt = models.Filter(
        must=[
            models.FieldCondition(key="metadata.source_name", match=models.MatchValue(value=source_name)),
            models.FieldCondition(key="metadata.kb_id", match=models.MatchValue(value=int(kb_id))),
        ]
    )
    ids: list[str] = []
    offset = None
    while True:
        records, offset = client.scroll(
            collection_name=get_settings().qdrant_collection,
            scroll_filter=flt,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not records:
            break
        for r in records:
            p = r.payload or {}
            meta = p.get("metadata") or p
            cid = str(meta.get("chunk_id") or "")
            if cid:
                ids.append(cid)
        if offset is None:
            break
    return ids


def ingest_file(
    file_path: str,
    *,
    source_name: str | None = None,
    enable_graph: bool = True,
    purge_before_write: bool = False,
    content_sha256: str | None = None,
    kb_id: int = 0,
) -> tuple[int, int]:
    """导入单个文件，返回（向量侧 chunk 数，图侧关系数）。

    purge_before_write=True 时先写后删：写入前记录旧 chunk_id 集合，
    三库全部写成功后按「旧 id − 新 id」差集精确清理（P0-2 原子性修复）；
    任一步失败抛错且旧数据保留。
    """
    begin = time.time()
    path = Path(file_path)
    logical_name = source_name if source_name else path.name
    doc_sha = (content_sha256 or file_sha256_hex(path)).strip().lower()

    # 先写后删的差集依据：写入前快照旧 chunk_id（不能按 source_name 整体删，
    # 新数据同 key 会被误删）
    old_chunk_ids = _collect_existing_chunk_ids(logical_name, kb_id) if purge_before_write else []

    logger.info("【入库】开始处理文件：%s source_name=%s kb=%s", file_path, logical_name, kb_id)
    content = load_document(str(path))
    logger.info("【入库】原文读取完成：source=%s 字符数=%s", logical_name, len(content))
    # 父子分块开关：开启时父块写 ES/图谱，子块写 Qdrant（检索精度）
    parent_enabled = bool(get_settings().chunk_parent_enabled)
    chunks = split_into_chunks(source_name=logical_name, content=content, kb_id=kb_id)
    child_chunks: list[Document] = []
    if parent_enabled:
        chunks, child_chunks = split_into_parent_child_chunks(
            source_name=logical_name, content=content, kb_id=kb_id
        )
    for chunk in chunks + child_chunks:
        chunk.metadata[META_SHA_KEY] = doc_sha
    logger.info(
        "【入库】切块完成：source=%s parents=%s children=%s（父子模式=%s）",
        logical_name,
        len(chunks),
        len(child_chunks),
        parent_enabled,
    )

    # 步骤 1：向量（Qdrant point id 用 chunk_id 的 UUID5，同 id 幂等覆盖）
    # 父子模式：子块与父块都写 Qdrant（子块带 chunk_type=child 供检索映射）
    logger.info("【入库】开始写入向量库 Qdrant")
    ensure_collection_exists()
    vector_store = get_vector_store()
    all_chunks = chunks + child_chunks
    ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.metadata["chunk_id"])) for chunk in all_chunks]
    vector_store.add_documents(documents=tqdm(all_chunks, desc="写入向量库"), ids=ids)
    logger.info("【入库】Qdrant 写入完成：%s 条（父 %s + 子 %s）", len(all_chunks), len(chunks), len(child_chunks))

    # 步骤 2：全文（ES _id=chunk_id，幂等覆盖）
    logger.info("【入库】开始同步 Elasticsearch")
    sync_chunks_to_elasticsearch(chunks)
    logger.info("【入库】Elasticsearch 同步完成：%s 条", len(chunks))

    # 步骤 3：图谱（MERGE 幂等累加 chunk_ids）
    triple_count = 0
    if enable_graph:
        _, triple_count = write_chunks_to_graph(chunks=chunks, source_name=logical_name, kb_id=kb_id)

    # 步骤 4：先写后删——按 chunk_id 差集精确清理旧数据（失败则保留旧数据）
    if purge_before_write and old_chunk_ids:
        new_ids = {str(c.metadata.get("chunk_id") or "") for c in chunks}
        stale_ids = [cid for cid in old_chunk_ids if cid not in new_ids]
        if stale_ids:
            logger.info(
                "【入库】清理旧 chunk %s 个（差集 %s → 新 %s）",
                len(stale_ids),
                len(old_chunk_ids),
                len(new_ids),
            )
            delete_chunks_by_ids(stale_ids, include_graph=enable_graph, kb_id=kb_id)

    cost = time.time() - begin
    logger.info(
        "【入库】全部完成：source=%s chunks=%s triples=%s 耗时=%.1fs",
        logical_name,
        len(chunks),
        triple_count,
        cost,
    )
    return len(chunks), triple_count
