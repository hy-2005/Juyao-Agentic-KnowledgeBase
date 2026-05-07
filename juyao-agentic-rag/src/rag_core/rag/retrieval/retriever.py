# 检索层：向量（Qdrant）与 ES（BM25）并行各取 top_k，再用 RRF 融合排序。
#
# 读代码顺序建议：
# 1) search_context：一次问答的取证据入口；
# 2) 并行：_vector_similarity_topk 与 elasticsearch_store.search_elasticsearch；
# 3) 融合：_reciprocal_rank_fusion（RRF，常数 rrf_k 见 config，默认 60）；
# 4) top_k / min_relevance_score / rrf_k 均在 rag_core.config.Settings。
#
# ─── 一次 search_context(query) 在做什么（按时间顺序）────────────────────────
#   ① 用同一个 query，线程池里同时跑：向量相似度 TopK、ES(BM25) TopK。
#   ② 向量结果先按「相似度分数 ≥ min_relevance_score」删掉太弱的；剩下的顺序不变，
#      第 1 条在该路记为 rank=1，第 2 条 rank=2 …（只用于 RRF，不再用原始分数和 ES 比）。
#   ③ ES 结果按 BM25 从高到低，同样是第 1 条 rank=1 …（两路的 rank 各自从 1 编号，互不干扰）。
#   ④ 用 metadata「chunk_id」把两路里出现的文档对上号；同一 chunk 在两路都有则 RRF 分数为两路贡献之和。
#   ⑤ 按 RRF 分数从高到低排序，得到最终喂给 LLM 的 documents 顺序。

import logging
import urllib.error
import urllib.request
from json import dumps, loads
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from langchain_core.documents import Document
from qdrant_client.http.exceptions import UnexpectedResponse

from rag_core.config import get_settings
from rag_core.rag.elasticsearch_store import search_elasticsearch
from rag_core.rag.vector_store import get_vector_store

logger = logging.getLogger(__name__)


def _preview_text(text: str, max_len: int = 120) -> str:
    return text.replace("\n", " ").replace("\r", " ").strip()[:max_len]


@dataclass
class RetrievedContext:
    # 一次检索结果：RRF 融合后的文档列表 + 向量侧原始最高分（给问答结果里的「相关度」展示用）。
    documents: list[Document]
    max_score: float


def _reciprocal_rank_fusion(
    vector_pairs: list[tuple[Document, float]],
    es_pairs: list[tuple[Document, float]],
    rrf_k: int,
) -> list[tuple[Document, float]]:
    # RRF（Reciprocal Rank Fusion，倒数排名融合）：
    # 不直接比较向量相似度与 BM25 的数值，只使用「在各路上的名次 rank」（从 1 起，1 最靠前）。
    # 对同一 chunk_id（若两路都出现会加和）：
    #   RRF_score(d) = sum_i  1 / (rrf_k + rank_i(d))
    # 其中 i 为检索路（这里两路：向量、ES）；某路未命中该 d 则该路不贡献项。
    # rrf_k 为平滑常数，常见取 60（与「每路取几条 top_k」无关）；k 越大名次差异被压得越平。
    # 返回：(Document, RRF_score) 按 RRF_score 降序。
    doc_by_cid: dict[str, Document] = {}  # chunk_id -> 任一路带来的 Document（用于最后还原正文）
    vec_rank: dict[str, int] = {}  # chunk_id -> 在向量列表里的名次（1 表示该路最靠前）
    es_rank: dict[str, int] = {}  # chunk_id -> 在 ES 列表里的名次

    # 列表顺序即相似度/BM25 排序：enumerate(..., start=1) 把「第几条」变成 rank。
    for rank, (doc, _) in enumerate(vector_pairs, start=1):
        cid = doc.metadata.get("chunk_id")
        if not cid:
            continue
        vec_rank[cid] = rank
        if cid not in doc_by_cid:
            doc_by_cid[cid] = doc

    for rank, (doc, _) in enumerate(es_pairs, start=1):
        cid = doc.metadata.get("chunk_id")
        if not cid:
            continue
        es_rank[cid] = rank
        if cid not in doc_by_cid:
            doc_by_cid[cid] = doc

    # 并集：出现在任一路 top 结果里的 chunk 都要算分（只在一路出现的也能排进最终结果）。
    all_cids = set(vec_rank) | set(es_rank)
    if not all_cids:
        return []

    rrf_scores: dict[str, float] = {}
    for cid in all_cids:
        s = 0.0
        if cid in vec_rank:  # 该 chunk 在向量 top 里：加上这一路倒数排名
            s += 1.0 / (rrf_k + vec_rank[cid])
        if cid in es_rank:  # 该 chunk 在 ES top 里：再加一路（两路都有则分数更高）
            s += 1.0 / (rrf_k + es_rank[cid])
        rrf_scores[cid] = s

    # 分数高的排前；tuple 里第二个 float 是融合分，仅用于排序/日志，不再表示「相似度」。
    ordered = sorted(rrf_scores.keys(), key=lambda c: rrf_scores[c], reverse=True)
    return [(doc_by_cid[c], rrf_scores[c]) for c in ordered]


def _vector_similarity_topk(query: str, k: int) -> list[tuple[Document, float]]:
    # float 为向量相似度 relevance（如 cosine），仅用于后面阈值过滤与 max_score 展示，不参与和 ES 分数直接相加。
    try:
        vector_store = get_vector_store()
        return vector_store.similarity_search_with_relevance_scores(query, k=k)
    except UnexpectedResponse as exc:
        if "doesn't exist" in str(exc) or "Not found" in str(exc):
            return []
        raise


def _rerank_after_rrf(query: str, fused_docs: list[Document]) -> list[Document]:
    # 对 RRF 结果做二次精排（优先 DashScope，失败时回退到 RRF 顺序）。
    if not fused_docs:
        return []

    settings = get_settings()
    top_n = max(1, min(settings.rerank_top_n, len(fused_docs)))
    documents_payload = [doc.page_content for doc in fused_docs]
    provider = (settings.rerank_provider or "").strip().lower()
    if provider == "dashscope":
        if not settings.dashscope_api_key:
            logger.warning("【重排】DashScope API Key 为空，回退 RRF 顺序。")
            return fused_docs[:top_n]
        request_body = dumps(
            {
                "model": settings.dashscope_rerank_model,
                "input": {"query": query, "documents": documents_payload},
                "parameters": {"return_documents": True, "top_n": top_n},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            settings.dashscope_rerank_url,
            data=request_body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.dashscope_api_key}",
            },
            method="POST",
        )
    else:
        request_body = dumps(
            {
                "model": settings.rerank_model,
                "query": query,
                "documents": documents_payload,
                "top_n": top_n,
            }
        ).encode("utf-8")
        rerank_url = f"{settings.ollama_base_url.rstrip('/')}/api/rerank"
        req = urllib.request.Request(
            rerank_url,
            data=request_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            body = response.read().decode("utf-8")
        payload = loads(body)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        logger.warning("【重排】调用 Ollama rerank 失败，回退 RRF 顺序。err=%s", exc)
        return fused_docs[:top_n]

    results = payload.get("results")
    if not isinstance(results, list):
        output = payload.get("output")
        if isinstance(output, dict):
            results = output.get("results")
    if not isinstance(results, list) or not results:
        logger.warning("【重排】返回结果为空或格式异常，回退 RRF 顺序。payload=%s", payload)
        return fused_docs[:top_n]

    selected_docs: list[Document] = []
    seen_idx: set[int] = set()
    for item in results:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int):
            continue
        if index < 0 or index >= len(fused_docs) or index in seen_idx:
            continue
        seen_idx.add(index)
        selected_docs.append(fused_docs[index])
        if len(selected_docs) >= top_n:
            break

    if not selected_docs:
        logger.warning("【重排】未解析到有效 index，回退 RRF 顺序。payload=%s", payload)
        return fused_docs[:top_n]

    model_name = settings.dashscope_rerank_model if provider == "dashscope" else settings.rerank_model
    logger.info(
        "【重排】provider=%s model=%s，RRF %s 条 -> 重排后 %s 条",
        provider or "ollama",
        model_name,
        len(fused_docs),
        len(selected_docs),
    )
    for i, doc in enumerate(selected_docs, 1):
        cid = doc.metadata.get("chunk_id", "?")
        logger.info("  [输出 %s] chunk_id=%s preview=%s", i, cid, _preview_text(doc.page_content))
    return selected_docs


def search_context(query: str) -> RetrievedContext:
    # 1) 两路并行：各取 top_k 条（名次用于 RRF）；2) 向量侧先按 min_relevance_score 过滤再赋名次；
    # 3) ES 侧保持 BM25 排序名次；4) RRF 融合得到最终顺序。
    settings = get_settings()
    k = settings.top_k  # 每路最多取几条参与后面步骤（不是 RRF 公式里的常数 rrf_k）
    rrf_k = settings.rrf_k  # 仅出现在 1/(rrf_k+rank) 里，和 top_k 含义不同
    rrf_top_n = max(1, settings.rrf_top_n)

    def run_vector() -> list[tuple[Document, float]]:
        return _vector_similarity_topk(query, k)

    def run_es() -> list[tuple[Document, float]]:
        return search_elasticsearch(query, k)

    # 两路同时请求，缩短总耗时；谁先返回无所谓，最后都会等两个 future 都完成。
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_v = pool.submit(run_vector)
        fut_e = pool.submit(run_es)
        vec_pairs_raw = fut_v.result()
        es_pairs = fut_e.result()

    logger.info("【向量检索】top_k=%s，原始命中 %s 条（阈值过滤前）", k, len(vec_pairs_raw))
    for i, (doc, score) in enumerate(vec_pairs_raw, 1):
        cid = doc.metadata.get("chunk_id", "?")
        logger.info("  [%s] chunk_id=%s relevance=%.4f", i, cid, score)

    logger.info("【ES 检索】top_k=%s，命中 %s 条", k, len(es_pairs))
    for i, (doc, score) in enumerate(es_pairs, 1):
        cid = doc.metadata.get("chunk_id", "?")
        logger.info("  [%s] chunk_id=%s bm25=%.4f", i, cid, score)

    # max_score：过滤前向量里的最高分，给上层展示「本轮检索相似度上限」，不参与 RRF。
    if not vec_pairs_raw:
        max_score = 0.0
    else:
        max_score = max(s for _, s in vec_pairs_raw)

    # 向量：仅保留达到阈值的命中，并按原相似度顺序重新编号为 rank=1..n，作为该路在 RRF 中的名次依据。
    # 注意：被阈值扔掉的条目不会进入 vec_pairs_for_rrf，等同「向量这一路没检索到该 chunk」。
    vec_pairs_for_rrf = [(d, s) for d, s in vec_pairs_raw if s >= settings.min_relevance_score]
    logger.info(
        "【向量参与 RRF】min_relevance=%.2f 过滤后 %s 条，名次按过滤后顺序从 1 起编",
        settings.min_relevance_score,
        len(vec_pairs_for_rrf),
    )

    fused = _reciprocal_rank_fusion(vec_pairs_for_rrf, es_pairs, rrf_k)
    # RRF 融合结果先截断到 rrf_top_n，再交给重排模型二次精排。
    fused_docs = [doc for doc, _ in fused[:rrf_top_n]]

    logger.info(
        "【RRF 融合】rrf_k=%s（公式：Σ 1/(rrf_k+rank)，两路名次各自独立从 1 起）→ 融合后 %s 条（截断后参与重排 %s 条）",
        rrf_k,
        len(fused),
        len(fused_docs),
    )
    for i, (doc, rrf_s) in enumerate(fused, 1):
        cid = doc.metadata.get("chunk_id", "?")
        logger.info("  [%s] chunk_id=%s rrf_score=%.6f preview=%s", i, cid, rrf_s, _preview_text(doc.page_content))
    logger.info("【重排输入】来自 RRF 前 %s 条，重排取 top_n=%s", len(fused_docs), settings.rerank_top_n)
    for i, doc in enumerate(fused_docs, 1):
        cid = doc.metadata.get("chunk_id", "?")
        logger.info("  [输入 %s] chunk_id=%s preview=%s", i, cid, _preview_text(doc.page_content))

    documents = _rerank_after_rrf(query, fused_docs)

    return RetrievedContext(documents=documents, max_score=max_score)
