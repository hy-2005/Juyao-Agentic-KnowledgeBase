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
# 【多知识库】每 kb 一个 index（es_index(kb) 命名，kb=0 沿用原名兼容存量数据），
#   不再共享单 index 用 kb_id term 过滤（物理隔离，PITFALLS #24 同根）。

import logging

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from langchain_core.documents import Document

from rag_core.core.config import Settings, es_index, get_settings

logger = logging.getLogger(__name__)


def get_elasticsearch_client() -> Elasticsearch:
    # 返回当前配置下的 ES 客户端；地址为 Settings.elasticsearch_url，默认 http://localhost:9201
    settings = get_settings()
    return Elasticsearch(settings.elasticsearch_url)


def ensure_es_index_exists(kb_id: int = 0) -> None:
    # 索引不存在则创建，已存在则跳过（按 kb 命名，kb=0 沿用原名兼容存量数据）。
    # mapping：content 为 text + IK 分词（ik_max_word 索引 / ik_smart 检索）；
    # chunk_id / source_doc_id / source_name 为 keyword（过滤、与 Qdrant chunk_id 对齐）；
    # chunk_index、字符区间、overlap_* 为 integer（溯源）。
    name = es_index(kb_id)
    client = get_elasticsearch_client()
    if client.indices.exists(index=name):
        return
    # exists 检查与 create 非原子：并发入库/消息重试时另一线程可能已建（400 already_exists）
    # —— 幂等容忍（与 Qdrant 409 同款竞态，见 PITFALLS #28）
    try:
        client.indices.create(
            index=name,
            body={
                "mappings": {
                    "properties": {
                        "content": {
                            "type": "text",
                            "analyzer": "ik_max_word",
                            "search_analyzer": "ik_smart",
                        },
                        "chunk_id": {"type": "keyword"},
                        "source_doc_id": {"type": "keyword"},
                        "source_name": {"type": "keyword"},
                        "kb_id": {"type": "integer"},
                        "chunk_index": {"type": "integer"},
                        "start_char": {"type": "integer"},
                        "end_char": {"type": "integer"},
                        "overlap_left": {"type": "integer"},
                        "overlap_right": {"type": "integer"},
                    }
                }
            },
        )
    except Exception as exc:
        if "resource_already_exists_exception" in str(exc):
            logger.info("ES index 已存在（并发创建容忍，直接复用）：%s", name)
            return
        raise


def _chunk_to_source(doc: Document) -> dict:
    # LangChain Document → ES _source；字段对齐 ChunkContract 与 splitter 的 source_name。
    # 无 chunk_id 则视为异常，避免脏数据静默入库。
    meta = doc.metadata or {}
    chunk_id = meta.get("chunk_id")
    if not chunk_id:
        raise ValueError("Document 缺少 chunk_id，无法写入 Elasticsearch")
    src = {
        "content": doc.page_content,
        "chunk_id": chunk_id,
        "source_doc_id": meta.get("source_doc_id"),
        "source_name": meta.get("source_name"),
        "kb_id": meta.get("kb_id"),
        "chunk_index": meta.get("chunk_index"),
        "start_char": meta.get("start_char"),
        "end_char": meta.get("end_char"),
        "overlap_left": meta.get("overlap_left"),
        "overlap_right": meta.get("overlap_right"),
        "chunk_type": meta.get("chunk_type"),
        "child_ids": meta.get("child_ids"),
    }
    # 过滤 None：普通 chunk 不带空字段，父/子块只写各自存在的父子字段
    return {k: v for k, v in src.items() if v is not None}


def _bulk_actions(index: str, chunks: list[Document]):
    # 生成 bulk 动作：_op_type=index 同 _id 覆盖，chunk_id 重复导入幂等；_id 用 chunk_id 便于对账。
    for doc in chunks:
        src = _chunk_to_source(doc)
        yield {
            "_op_type": "index",
            "_index": index,
            "_id": src["chunk_id"],
            "_source": src,
        }


def sync_chunks_to_elasticsearch(chunks: list[Document], kb_id: int = 0) -> int:
    # 批量写入 ES（该 kb 的 index）；返回 bulk 成功条数（与 len(chunks) 一致即全部成功）。
    # refresh=wait_for：写完即可搜；大批量可改 False 再手动 refresh。
    # raise_on_error=False：汇总 errors 后统一抛错，便于带 ES 原文排查。
    if not chunks:
        return 0
    ensure_es_index_exists(kb_id)
    client = get_elasticsearch_client()
    success, errors = bulk(
        client,
        _bulk_actions(es_index(kb_id), chunks),
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
        "kb_id": src.get("kb_id"),
        "chunk_index": src.get("chunk_index"),
        "start_char": src.get("start_char"),
        "end_char": src.get("end_char"),
        "overlap_left": src.get("overlap_left"),
        "overlap_right": src.get("overlap_right"),
    }
    meta = {k: v for k, v in meta.items() if v is not None}
    return Document(page_content=content, metadata=meta)


def search_elasticsearch(
    query: str, k: int | None = None, kb_id: int = 0
) -> list[tuple[Document, float]]:
    # 对 content 做 multi_match（BM25），返回 (Document, _score) 列表，顺序即该路「名次」：第 1 条 rank=1。
    # 与向量路 top_k 结果在 retriever 中做 RRF 融合；RRF 只认名次不认 BM25 绝对值（见 _reciprocal_rank_fusion）。
    # 物理隔离：只搜该 kb 的 index（kb=0 沿用原名兼容存量）；索引不存在或失败时返回空列表并 warning，不阻断向量侧。
    settings = get_settings()
    k = settings.top_k if k is None else k
    name = es_index(kb_id)
    client = get_elasticsearch_client()
    try:
        if not client.indices.exists(index=name):
            logger.warning("ES 索引不存在，跳过全文检索：%s", name)
            return []
    except Exception as exc:
        logger.warning("ES 检查索引失败，跳过全文检索：%s", exc)
        return []
    # match_phrase 补充（P2）：专有名词/条款名等词序敏感检索，
    # 多词 query 整句精确出现时 boost——BM25 分词会丢失词序信息
    body = {
        "query": {
            "bool": {
                "must": [
                    {
                        "bool": {
                            "should": [
                                {"multi_match": {"query": query, "fields": ["content"]}},
                                {
                                    "match_phrase": {
                                        "content": {"query": query, "slop": 2, "boost": 2.0}
                                    }
                                },
                            ],
                            "minimum_should_match": 1,
                        }
                    }
                ]
            }
        },
        "size": k,
    }
    try:
        resp = client.search(index=name, body=body)
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


_CONTENT_PREVIEW_LEN = 200


def _source_to_chunk_row(src: dict, *, include_full_content: bool = False) -> dict:
    content = src.get("content") or ""
    row = {
        "chunk_id": src.get("chunk_id"),
        "source_doc_id": src.get("source_doc_id"),
        "source_name": src.get("source_name"),
        "chunk_index": src.get("chunk_index"),
        "start_char": src.get("start_char"),
        "end_char": src.get("end_char"),
        "overlap_left": src.get("overlap_left"),
        "overlap_right": src.get("overlap_right"),
    }
    if include_full_content:
        row["content"] = content
    else:
        row["content_preview"] = (
            content[:_CONTENT_PREVIEW_LEN] + "..." if len(content) > _CONTENT_PREVIEW_LEN else content
        )
    if src.get("chunk_type"):
        row["chunk_type"] = src.get("chunk_type")
    if src.get("child_ids"):
        row["child_ids"] = src.get("child_ids")
    return {k: v for k, v in row.items() if v is not None}


def _es_index_ready(client: Elasticsearch, index: str) -> bool:
    try:
        return bool(client.indices.exists(index=index))
    except Exception as exc:
        logger.warning("ES 检查索引失败：%s", exc)
        return False


def _build_list_query(source_name: str | None, keyword: str | None) -> dict:
    filters: list[dict] = []
    if source_name:
        filters.append({"term": {"source_name": source_name}})
    must: list[dict] = []
    if keyword:
        must.append({"multi_match": {"query": keyword, "fields": ["content"]}})
    if must and filters:
        return {"bool": {"must": must, "filter": filters}}
    if must:
        return {"bool": {"must": must}}
    if filters:
        return {"bool": {"filter": filters}}
    return {"match_all": {}}


def list_chunks(
    *,
    source_name: str | None = None,
    keyword: str | None = None,
    page_num: int = 1,
    page_size: int = 20,
    kb_id: int = 0,
) -> tuple[list[dict], int]:
    name = es_index(kb_id)
    client = get_elasticsearch_client()
    if not _es_index_ready(client, name):
        return [], 0
    page_num = max(1, page_num)
    page_size = max(1, min(page_size, 100))
    from_idx = (page_num - 1) * page_size
    query = _build_list_query(source_name, keyword)
    sort = [{"_score": "desc"}, {"chunk_index": "asc"}] if keyword else [{"chunk_index": "asc"}]
    body = {"query": query, "from": from_idx, "size": page_size, "sort": sort}
    try:
        resp = client.search(index=name, body=body)
    except Exception as exc:
        logger.warning("ES list_chunks 失败：%s", exc)
        return [], 0
    hits = (resp.get("hits") or {}).get("hits") or []
    total_raw = (resp.get("hits") or {}).get("total")
    if isinstance(total_raw, dict):
        total = int(total_raw.get("value") or 0)
    else:
        total = int(total_raw or 0)
    rows = [_source_to_chunk_row(hit.get("_source") or {}) for hit in hits]
    return rows, total


def get_chunk_by_id(chunk_id: str, kb_id: int = 0) -> dict | None:
    """按 chunk_id 查切片详情(含完整正文)。

    子块只存 Qdrant,ES 未命中时回退按 chunk_id 查 Qdrant payload(metadata.chunk_id 精确匹配);
    两处都查不到返回 None(上游据此 404)。
    """
    name = es_index(kb_id)
    client = get_elasticsearch_client()
    if not _es_index_ready(client, name):
        return None
    try:
        resp = client.get(index=name, id=chunk_id, ignore=[404])
    except Exception as exc:
        logger.warning("ES get_chunk_by_id 失败：%s", exc)
        return None
    if not resp or not resp.get("found"):
        # 子块只存 Qdrant,ES 未命中时回退按 chunk_id 查 Qdrant
        from rag_core.infrastructure.qdrant import get_chunk_by_id_from_qdrant

        return get_chunk_by_id_from_qdrant(chunk_id, kb_id=kb_id)
    return _source_to_chunk_row(resp.get("_source") or {}, include_full_content=True)


def count_chunks(source_name: str | None = None, kb_id: int = 0) -> int:
    name = es_index(kb_id)
    client = get_elasticsearch_client()
    if not _es_index_ready(client, name):
        return 0
    query = _build_list_query(source_name, None)
    try:
        resp = client.count(index=name, body={"query": query})
    except Exception as exc:
        logger.warning("ES count_chunks 失败：%s", exc)
        return 0
    return int(resp.get("count") or 0)


def chunk_stats_by_source(source_name: str | None = None, top_n: int = 50, kb_id: int = 0) -> dict:
    name = es_index(kb_id)
    client = get_elasticsearch_client()
    if not _es_index_ready(client, name):
        return {"total": 0, "by_source": []}
    if source_name:
        total = count_chunks(source_name, kb_id=kb_id)
        return {"total": total, "by_source": [{"source_name": source_name, "count": total}]}
    body = {
        "size": 0,
        "aggs": {
            "by_source": {
                "terms": {"field": "source_name", "size": top_n, "order": {"_count": "desc"}},
            }
        },
    }
    try:
        resp = client.search(index=name, body=body)
    except Exception as exc:
        logger.warning("ES chunk_stats_by_source 失败：%s", exc)
        return {"total": 0, "by_source": []}
    buckets = (((resp.get("aggregations") or {}).get("by_source") or {}).get("buckets")) or []
    by_source = [{"source_name": b.get("key"), "count": int(b.get("doc_count") or 0)} for b in buckets]
    total = sum(item["count"] for item in by_source)
    return {"total": total, "by_source": by_source}
