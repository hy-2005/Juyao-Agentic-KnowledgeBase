"""混合检索：Query 改写 + HyDE → 多路召回 → 双层 RRF → 重排。

管线（search_context）：
  1. _build_query_specs   原问 + 改写 sub-queries + HyDE 假答案
  2. _search_one_query    每条 query 并行走向量库 + ES
  3. fuse_two_rankings    单 query 内向量 rank + ES rank → RRF
  4. fuse_query_rankings  跨 query 再 RRF 一次
  5. rerank_documents_multi  Cross-Encoder / LLM 重排（按配置）

难点：HyDE 通道标记 vector_only=True，ES 不参与，避免假答案污染关键词检索。
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from langchain_core.documents import Document
from qdrant_client.http.exceptions import UnexpectedResponse

from rag_core.core.config import Settings, get_settings
from rag_core.indexing.elasticsearch import search_elasticsearch
from rag_core.retrieval.fusion import fuse_query_rankings, fuse_two_rankings
from rag_core.retrieval.hyde import generate_hypothetical_answer
from rag_core.retrieval.query_rewrite import rewrite_query
from rag_core.retrieval.reranker import rerank_documents_multi
from rag_core.indexing.qdrant import get_vector_store

logger = logging.getLogger(__name__)


@dataclass
class RetrievedContext:
    # 一次检索结果：跨 query 融合 + 重排后的最终文档列表，加上向量侧原始最高分（给上层展示用）。
    documents: list[Document]
    max_score: float


@dataclass
class _QuerySpec:
    # 一条参与多 query 检索的"逻辑 query"；通过 vector_only 标记区分 HyDE 通道。
    label: str
    text: str
    vector_only: bool = field(default=False)


def search_context(query: str) -> RetrievedContext:
    settings = get_settings()

    # Step 1: 收集所有参与检索的 query（原 query + sub-queries + HyDE）。
    specs = _build_query_specs(query=query, settings=settings)
    logger.info(
        "【Multi-Query 检索】共 %s 条 query 参与（其中 HyDE 通道 %s 条）",
        len(specs),
        sum(1 for s in specs if s.vector_only),
    )

    # Step 2: 多 query 并行执行单 query 检索 + 单 query 内 RRF。
    per_query_results, max_vec_scores = _parallel_retrieve(specs=specs, settings=settings)

    # Step 3: 跨 query RRF 二次融合（多个 query 都命中的 chunk 自然加分）。
    cross_fused = fuse_query_rankings(per_query_results, rrf_k=settings.rrf_k)
    rrf_top_n = max(1, settings.rrf_top_n)
    truncated_pairs = cross_fused[:rrf_top_n]
    truncated_docs = [doc for doc, _ in truncated_pairs]
    _log_cross_fusion(spec_count=len(specs), cross_fused=cross_fused, truncated_n=len(truncated_docs))

    # Step 4: 多 query rerank + 跨 query rerank RRF 聚合（详见 reranker 模块注释）。
    # 把召回阶段用过的所有 query（原 + sub + HyDE）都送给 rerank 各打一次分，让精排层也"听到"
    # 多角度信号，避免"召回多 query / 精排单 query"的信息瓶颈。
    rerank_query_texts = [s.text for s in specs]
    documents = rerank_documents_multi(rerank_query_texts, truncated_docs)

    # max_score：取所有 query 中向量原始相似度的最高值，仅用于上层「相关度」展示，不参与排序。
    max_score = max(max_vec_scores, default=0.0)
    return RetrievedContext(documents=documents, max_score=max_score)


def _build_query_specs(query: str, settings: Settings) -> list[_QuerySpec]:
    # 把三种 query 来源（原 / 改写 / HyDE）统一成 _QuerySpec 列表，让下游一视同仁地并行处理。
    specs: list[_QuerySpec] = [_QuerySpec(label="q0·原", text=query)]

    sub_queries = rewrite_query(query)
    for i, sub in enumerate(sub_queries, start=1):
        specs.append(_QuerySpec(label=f"q{len(specs)}·sub{i}", text=sub))

    # HyDE 通道仅参与向量召回（vector_only=True）；BM25 对长假答案文本会稀释关键词命中。
    if settings.hyde_enabled:
        hyde_text = generate_hypothetical_answer(query)
        if hyde_text:
            specs.append(_QuerySpec(label=f"q{len(specs)}·hyde", text=hyde_text, vector_only=True))
    return specs


def _parallel_retrieve(
    specs: list[_QuerySpec],
    settings: Settings,
) -> tuple[list[list[tuple[Document, float]]], list[float]]:
    # 多 query 并行：每条 query 跑 _retrieve_for_single_query；返回与 specs 同序的两个列表。
    per_query_results: list[list[tuple[Document, float]]] = [[] for _ in specs]
    max_vec_scores: list[float] = [0.0 for _ in specs]

    def task(idx: int) -> tuple[int, list[tuple[Document, float]], float]:
        spec = specs[idx]
        fused, max_v = _retrieve_for_single_query(
            query=spec.text,
            label=spec.label,
            k=settings.top_k,
            rrf_k=settings.rrf_k,
            min_relevance=settings.min_relevance_score,
            vector_only=spec.vector_only,
        )
        return idx, fused, max_v

    with ThreadPoolExecutor(max_workers=max(2, len(specs))) as pool:
        for idx, fused, max_v in pool.map(task, range(len(specs))):
            per_query_results[idx] = fused
            max_vec_scores[idx] = max_v
    return per_query_results, max_vec_scores


def _retrieve_for_single_query(
    query: str,
    *,
    label: str,
    k: int,
    rrf_k: int,
    min_relevance: float,
    vector_only: bool,
) -> tuple[list[tuple[Document, float]], float]:
    # 单条 query：向量 top_k +（非 HyDE 时）ES top_k → 向量阈值过滤 → 单 query RRF。
    # vector_only=True 时跳过 ES 调用，单 query RRF 退化为"按向量名次排序"。
    vec_pairs_raw = _vector_topk(query=query, k=k)

    es_label = "HyDE 通道，跳过 ES" if vector_only else "阈值过滤前"
    logger.info("【%s · 向量召回】top_k=%s，命中 %s 条（%s）", label, k, len(vec_pairs_raw), es_label)
    for i, (doc, score) in enumerate(vec_pairs_raw, 1):
        cid = doc.metadata.get("chunk_id", "?")
        logger.debug("  [%s] chunk_id=%s relevance=%.4f", i, cid, score)

    es_pairs: list[tuple[Document, float]] = []
    if not vector_only:
        es_pairs = search_elasticsearch(query, k)
        logger.info("【%s · ES 召回】top_k=%s，命中 %s 条", label, k, len(es_pairs))
        for i, (doc, score) in enumerate(es_pairs, 1):
            cid = doc.metadata.get("chunk_id", "?")
            logger.debug("  [%s] chunk_id=%s bm25=%.4f", i, cid, score)

    max_vec_score = max((s for _, s in vec_pairs_raw), default=0.0)

    vec_for_rrf = [(d, s) for d, s in vec_pairs_raw if s >= min_relevance]
    logger.info(
        "【%s · 向量进 RRF】min_relevance=%.2f 过滤后 %s 条，名次按过滤后顺序从 1 起编",
        label,
        min_relevance,
        len(vec_for_rrf),
    )

    # ES 列表为空时，fuse_two_rankings 等同"按向量名次排序"（仅一路贡献），符合 HyDE 通道预期。
    fused = fuse_two_rankings(vec_for_rrf, es_pairs, rrf_k=rrf_k)
    logger.info("【%s · 单 query RRF】融合后 %s 条", label, len(fused))
    for i, (doc, score) in enumerate(fused, 1):
        cid = doc.metadata.get("chunk_id", "?")
        logger.debug("  [%s] chunk_id=%s rrf_score=%.6f preview=%s", i, cid, score, _preview(doc.page_content))
    return fused, max_vec_score


def _vector_topk(query: str, k: int) -> list[tuple[Document, float]]:
    # 向量召回；float 为相似度 relevance（如 cosine），仅用于阈值过滤与 max_score 展示，
    # 不参与与 ES 分数的直接相加（RRF 只看名次）。索引尚未建好时返回空列表。
    try:
        vector_store = get_vector_store()
        return vector_store.similarity_search_with_relevance_scores(query, k=k)
    except UnexpectedResponse as exc:
        if "doesn't exist" in str(exc) or "Not found" in str(exc):
            return []
        raise


def _log_cross_fusion(
    spec_count: int,
    cross_fused: list[tuple[Document, float]],
    truncated_n: int,
) -> None:
    logger.info(
        "【跨 query RRF 融合】%s 条 query 的结果合并 → 总 %s 条；截断到 top %s 进入 rerank",
        spec_count,
        len(cross_fused),
        truncated_n,
    )
    for i, (doc, score) in enumerate(cross_fused[:truncated_n], 1):
        cid = doc.metadata.get("chunk_id", "?")
        logger.debug("  [%s] chunk_id=%s cross_rrf=%.6f preview=%s", i, cid, score, _preview(doc.page_content))


def _preview(text: str, max_len: int = 120) -> str:
    return text.replace("\n", " ").replace("\r", " ").strip()[:max_len]
