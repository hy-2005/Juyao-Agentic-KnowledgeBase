# Elasticsearch：全文（BM25）侧存储，与 Qdrant 向量检索组成混合检索。
#
# 【职责】
#   - 入库：把 splitter 产出的 LangChain Document（含 contracts 元数据）写入 ES，供关键词 / BM25 检索。
#   - 与 Qdrant 的关系：同一份 chunk 写两处——Qdrant 存向量，ES 存全文；检索阶段可做分数融合（RRF、加权等）。
#
# 【版本】Python 客户端 elasticsearch 7.x，与服务端 7.17.x（如镜像 elasticsearch/elasticsearch:7.17.18）一致。
#   建索引须使用 body={"mappings": ...}；勿混用 8.x 客户端的顶层 mappings= 写法。
#
# 【配置】见 rag_core.config.Settings：elasticsearch_url、elasticsearch_index。

import logging

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from langchain_core.documents import Document

from rag_core.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


def get_elasticsearch_client() -> Elasticsearch:
    # 返回当前配置下的 ES 客户端；地址为 Settings.elasticsearch_url，默认 http://localhost:9201
    settings = get_settings()
    return Elasticsearch(settings.elasticsearch_url)


def ensure_es_index_exists() -> None:
    # 索引不存在则创建，已存在则跳过。
    # mapping：content 为 text（BM25；未配 IK 等则用默认分词）；
    # chunk_id / source_doc_id / source_name 为 keyword（过滤、与 Qdrant chunk_id 对齐）；
    # chunk_index、字符区间、overlap_* 为 integer（溯源）。
    settings = get_settings()
    client = get_elasticsearch_client()
    if client.indices.exists(index=settings.elasticsearch_index):
        return
    client.indices.create(
        index=settings.elasticsearch_index,
        body={
            "mappings": {
                "properties": {
                    "content": {"type": "text"},
                    "chunk_id": {"type": "keyword"},
                    "source_doc_id": {"type": "keyword"},
                    "source_name": {"type": "keyword"},
                    "chunk_index": {"type": "integer"},
                    "start_char": {"type": "integer"},
                    "end_char": {"type": "integer"},
                    "overlap_left": {"type": "integer"},
                    "overlap_right": {"type": "integer"},
                }
            }
        },
    )


def _chunk_to_source(doc: Document) -> dict:
    # LangChain Document → ES _source；字段对齐 ChunkContract 与 splitter 的 source_name。
    # 无 chunk_id 则视为异常，避免脏数据静默入库。
    meta = doc.metadata or {}
    chunk_id = meta.get("chunk_id")
    if not chunk_id:
        raise ValueError("Document 缺少 chunk_id，无法写入 Elasticsearch")
    return {
        "content": doc.page_content,
        "chunk_id": chunk_id,
        "source_doc_id": meta.get("source_doc_id"),
        "source_name": meta.get("source_name"),
        "chunk_index": meta.get("chunk_index"),
        "start_char": meta.get("start_char"),
        "end_char": meta.get("end_char"),
        "overlap_left": meta.get("overlap_left"),
        "overlap_right": meta.get("overlap_right"),
    }


def _bulk_actions(settings: Settings, chunks: list[Document]):
    # 生成 bulk 动作：_op_type=index 同 _id 覆盖，chunk_id 重复导入幂等；_id 用 chunk_id 便于对账。
    for doc in chunks:
        src = _chunk_to_source(doc)
        yield {
            "_op_type": "index",
            "_index": settings.elasticsearch_index,
            "_id": src["chunk_id"],
            "_source": src,
        }


def sync_chunks_to_elasticsearch(chunks: list[Document]) -> int:
    # 批量写入 ES；返回 bulk 成功条数（与 len(chunks) 一致即全部成功）。
    # refresh=wait_for：写完即可搜；大批量可改 False 再手动 refresh。
    # raise_on_error=False：汇总 errors 后统一抛错，便于带 ES 原文排查。
    if not chunks:
        return 0
    settings = get_settings()
    ensure_es_index_exists()
    client = get_elasticsearch_client()
    success, errors = bulk(
        client,
        _bulk_actions(settings, chunks),
        refresh="wait_for",
        raise_on_error=False,
    )
    if errors:
        raise RuntimeError(f"Elasticsearch bulk 失败: {errors}")
    return success


def _hit_source_to_document(src: dict) -> Document:
    # _source 与入库字段一致；正文用 content。
    content = src.get("content") or ""
    meta = {
        "chunk_id": src.get("chunk_id"),
        "source_doc_id": src.get("source_doc_id"),
        "source_name": src.get("source_name"),
        "chunk_index": src.get("chunk_index"),
        "start_char": src.get("start_char"),
        "end_char": src.get("end_char"),
        "overlap_left": src.get("overlap_left"),
        "overlap_right": src.get("overlap_right"),
    }
    meta = {k: v for k, v in meta.items() if v is not None}
    return Document(page_content=content, metadata=meta)


def search_elasticsearch(query: str, k: int | None = None) -> list[tuple[Document, float]]:
    # 对 content 做 multi_match（BM25），返回 (Document, _score) 列表，顺序即该路「名次」：第 1 条 rank=1。
    # 与向量路 top_k 结果在 retriever 中做 RRF 融合；RRF 只认名次不认 BM25 绝对值（见 _reciprocal_rank_fusion）。
    # 索引不存在或失败时返回空列表并 warning，不阻断向量侧。
    settings = get_settings()
    k = settings.top_k if k is None else k
    client = get_elasticsearch_client()
    try:
        if not client.indices.exists(index=settings.elasticsearch_index):
            logger.warning("ES 索引不存在，跳过全文检索：%s", settings.elasticsearch_index)
            return []
    except Exception as exc:
        logger.warning("ES 检查索引失败，跳过全文检索：%s", exc)
        return []
    body = {
        "query": {"multi_match": {"query": query, "fields": ["content"]}},
        "size": k,
    }
    try:
        resp = client.search(index=settings.elasticsearch_index, body=body)
    except Exception as exc:
        logger.warning("ES search 失败，跳过全文检索：%s", exc)
        return []
    try:
        hits = resp["hits"]["hits"]
    except (KeyError, TypeError):
        hits = []
    out: list[tuple[Document, float]] = []
    for hit in hits:
        src = hit.get("_source") or {}
        score = float(hit.get("_score") or 0.0)
        out.append((_hit_source_to_document(src), score))
    return out
