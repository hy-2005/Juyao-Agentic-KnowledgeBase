# 重排（Cross-encoder rerank）：精排层的"递归 RRF"——多 query 各自精排，再做跨 query 名次融合。
#
# 设计动机：
# 单 query rerank 的"信息瓶颈"——如果只用原 query 做 rerank，召回层用 N 条 query 拿到的丰富信号
# 会被压缩回 1 条，多 sub-query / HyDE 的努力部分被浪费。
#
# 解决方式：把召回层的"递归 RRF"思路延伸到精排层：
# - 召回层：N 条 query × 2 路（向量+ES）→ 单 query 内 RRF → 跨 query RRF；
# - 精排层：N 条 query × 1 路（rerank）        → 直接得到该 query 视角下的名次 → 跨 query rerank RRF。
# 两层使用同一个 fusion.fuse_query_rankings 公式（架构一致 + 零额外聚合代码）。
#
# 兼容两种 provider：dashscope（gte-rerank-v2）/ ollama（本地 /api/rerank）。
# 失败哲学：任意一路 rerank 失败 → 该路不贡献名次（其他路继续）；全部失败 → 回退 RRF 截断顺序。

import logging
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from json import dumps, loads

from langchain_core.documents import Document

from rag_core.core.config import get_settings
from rag_core.retrieval.fusion import fuse_query_rankings

logger = logging.getLogger(__name__)


# 长 query 自动截断阈值：HyDE 文本可能 200~600 字；cross-encoder rerank 模型对长 query 不友好。
# 截断到 200 字以内，保留前段关键词密度高的部分。
_RERANK_QUERY_MAX_LEN = 200


def rerank_documents_multi(queries: list[str], fused_docs: list[Document]) -> list[Document]:
    # 多 query 精排入口：每条 query 单独 rerank → 跨 query RRF 聚合 → 取 settings.rerank_top_n。
    if not fused_docs or not queries:
        return []

    settings = get_settings()
    top_n = max(1, min(settings.rerank_top_n, len(fused_docs)))

    # Step 1: 并行对每条 query 调用一次 rerank，得到该 query 视角下的完整名次列表（不截断）。
    per_query_rankings = _parallel_rerank_per_query(queries=queries, fused_docs=fused_docs)
    valid_rankings = [r for r in per_query_rankings if r]

    if not valid_rankings:
        logger.warning("【rerank · 多 query】所有路 rerank 调用均失败，回退 RRF 顺序前 %s 条", top_n)
        return fused_docs[:top_n]

    # Step 2: 跨 query rerank RRF（复用召回层同款 fusion.fuse_query_rankings；rrf_k 与召回层一致）。
    fused_by_rerank_rrf = fuse_query_rankings(valid_rankings, rrf_k=settings.rrf_k)
    final_docs = [doc for doc, _ in fused_by_rerank_rrf[:top_n]]

    logger.info(
        "【rerank · 多 query 聚合】%s 条 query 参与（成功 %s 条）→ 跨 query RRF 后取 top %s",
        len(queries),
        len(valid_rankings),
        len(final_docs),
    )
    for i, (doc, score) in enumerate(fused_by_rerank_rrf[:top_n], 1):
        cid = doc.metadata.get("chunk_id", "?")
        logger.info("  [输出 %s] chunk_id=%s rerank_rrf=%.6f preview=%s", i, cid, score, _preview(doc.page_content))
    return final_docs


def _parallel_rerank_per_query(
    queries: list[str],
    fused_docs: list[Document],
) -> list[list[tuple[Document, float]]]:
    # 并行：每条 query 一次 rerank API 调用；返回与 queries 同序的名次列表（失败的那一路是 []）。
    results: list[list[tuple[Document, float]]] = [[] for _ in queries]

    def task(idx: int) -> tuple[int, list[tuple[Document, float]]]:
        return idx, _rerank_single(query=queries[idx], fused_docs=fused_docs, label=f"q{idx}")

    with ThreadPoolExecutor(max_workers=max(2, len(queries))) as pool:
        for idx, ranking in pool.map(task, range(len(queries))):
            results[idx] = ranking
    return results


def _rerank_single(
    query: str,
    fused_docs: list[Document],
    label: str = "",
) -> list[tuple[Document, float]]:
    # 单条 query 的 rerank：对全部 fused_docs 打分排序，返回完整名次列表（不截断 top_n，由上层决定）。
    settings = get_settings()
    documents_payload = [doc.page_content for doc in fused_docs]
    provider = (settings.rerank_provider or "").strip().lower()
    rerank_query = query[:_RERANK_QUERY_MAX_LEN]

    req = _build_request(
        provider=provider,
        query=rerank_query,
        documents=documents_payload,
        top_n=len(fused_docs),  # 让 API 返回所有候选的名次，避免低位 chunk 在该路完全没贡献
    )
    if req is None:
        logger.warning("【rerank · %s】配置不完整（缺 API key 等），跳过该路", label)
        return []

    payload = _call_rerank(req, label=label)
    if payload is None:
        return []

    ranking = _payload_to_ranking(payload=payload, fused_docs=fused_docs)
    if not ranking:
        logger.warning("【rerank · %s】未解析到有效结果，跳过该路。payload=%s", label, payload)
        return []

    logger.info(
        "【rerank · %s】query='%s'... 候选 %s 条 → 排序前 3：%s",
        label,
        rerank_query[:60].replace("\n", " "),
        len(fused_docs),
        [(d.metadata.get("chunk_id", "?"), round(s, 4)) for d, s in ranking[:3]],
    )
    return ranking


def _build_request(
    provider: str,
    query: str,
    documents: list[str],
    top_n: int,
) -> urllib.request.Request | None:
    settings = get_settings()
    if provider == "dashscope":
        if not settings.dashscope_api_key:
            return None
        body = dumps(
            {
                "model": settings.dashscope_rerank_model,
                "input": {"query": query, "documents": documents},
                "parameters": {"return_documents": True, "top_n": top_n},
            }
        ).encode("utf-8")
        return urllib.request.Request(
            settings.dashscope_rerank_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.dashscope_api_key}",
            },
            method="POST",
        )

    body = dumps(
        {
            "model": settings.rerank_model,
            "query": query,
            "documents": documents,
            "top_n": top_n,
        }
    ).encode("utf-8")
    rerank_url = f"{settings.ollama_base_url.rstrip('/')}/api/rerank"
    return urllib.request.Request(
        rerank_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def _call_rerank(req: urllib.request.Request, *, label: str) -> dict | None:
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            body = response.read().decode("utf-8")
        return loads(body)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        logger.warning("【rerank · %s】调用失败，跳过该路。err=%s", label, exc)
        return None


def _payload_to_ranking(
    payload: dict,
    fused_docs: list[Document],
) -> list[tuple[Document, float]]:
    # 把 rerank API 返回（含 index + relevance_score）转成 (Document, score) 排序列表（按分数降序，不截断）。
    # DashScope 把 results 包了一层 output；Ollama 一般直接 results；两种都兼容。
    results = payload.get("results")
    if not isinstance(results, list):
        output = payload.get("output")
        if isinstance(output, dict):
            results = output.get("results")
    if not isinstance(results, list) or not results:
        return []

    out: list[tuple[Document, float]] = []
    seen: set[int] = set()
    for item in results:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int) or index < 0 or index >= len(fused_docs) or index in seen:
            continue
        seen.add(index)
        score = float(item.get("relevance_score") or item.get("score") or 0.0)
        out.append((fused_docs[index], score))
    out.sort(key=lambda t: t[1], reverse=True)
    return out


def _preview(text: str, max_len: int = 120) -> str:
    return text.replace("\n", " ").replace("\r", " ").strip()[:max_len]
