"""L1 · 派系 2 主路径入口：问题 → community_summaries embedding 检索 → top-K 社区。

返回 CommunityMatch 列表（按相似度降序）；空列表 = L1 未命中，调用方降级到 L2。

设计要点：
- 与 `juyao_knowledge_chunks` collection 物理隔离（独立 collection `community_summaries`）
- 失败兜底：collection 不存在 / embedding 失败 / Qdrant 异常 一律返回 []，不抛错给主链路
- 阈值过滤在客户端做（score_threshold=None），避免 Qdrant 默认 0.0 阈值误放行低相似度点
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from qdrant_client.http import models

from rag_core.core.config import get_settings
from rag_core.infrastructure.qdrant import (
    _get_community_summary_embeddings,
    get_qdrant_client,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommunityMatch:
    """社区检索命中结果。"""

    community_id: str
    summary: str
    similarity: float  # 余弦相似度，0~1
    entity_count: int
    entities: tuple[str, ...]  # 该社区的实体名列表
    kb_id: int


def _safe_entities(payload_entities) -> tuple[str, ...]:
    """payload.entities 可能为 None / list / str，统一转 tuple[str]。"""
    if not payload_entities:
        return ()
    if isinstance(payload_entities, list):
        return tuple(str(x).strip() for x in payload_entities if str(x or "").strip())
    if isinstance(payload_entities, str):
        s = payload_entities.strip()
        return (s,) if s else ()
    return ()


def community_search(
    question: str,
    *,
    kb_id: int,
    top_k: int | None = None,
    min_similarity: float | None = None,
) -> list[CommunityMatch]:
    """问题 → community_summaries embedding 检索 → top-K 社区（按相似度降序）。

    返回空列表 = L1 未命中，调用方应降级到 L2 全图检索。

    Args:
        question: 用户原问句（已 A 改写后或原值均可）
        kb_id: 知识库 ID（必填；用于 filter 隔离）
        top_k: top K 社区数；默认 settings.community_summary_top_k
        min_similarity: 相似度阈值；默认 settings.community_summary_min_similarity

    Returns:
        list[CommunityMatch] 按 similarity 降序；过滤掉 < min_similarity 的；
        collection 不存在 / 任何异常 返回 []
    """
    q = (question or "").strip()
    if not q:
        return []

    settings = get_settings()
    top_k = top_k if top_k is not None else int(settings.community_summary_top_k)
    min_similarity = (
        min_similarity
        if min_similarity is not None
        else float(settings.community_summary_min_similarity)
    )

    client = get_qdrant_client()
    collection = settings.community_summary_collection

    # collection 不存在 = 0 命中（不抛错，best-effort；常见于冷启动 / kb 未建社区）
    try:
        client.get_collection(collection_name=collection)
    except Exception as exc:
        logger.info(
            "community_search: collection %s 不存在（视为 0 命中）：%s",
            collection,
            exc,
        )
        return []

    # 1. 嵌入问题
    try:
        embed = _get_community_summary_embeddings()
        q_vec = embed.embed_query(q)
    except Exception as exc:
        logger.warning("community_search: 问题 embed 失败：%s", exc)
        return []

    # 2. 按 kb 过滤 + 余弦相似度检索 top_k
    flt = models.Filter(
        must=[
            models.FieldCondition(
                key="kb_id", match=models.MatchValue(value=int(kb_id))
            )
        ]
    )
    try:
        # 多取一些再阈值过滤（避免恰好卡边界）
        raw = client.search(
            collection_name=collection,
            query_vector=q_vec,
            query_filter=flt,
            limit=max(top_k * 2, top_k),
            with_payload=True,
            with_vectors=False,
            score_threshold=None,  # 客户端阈值过滤
        )
    except Exception as exc:
        logger.warning("community_search: Qdrant search 失败：%s", exc)
        return []

    # 3. 阈值过滤 + 构造结果
    matches: list[CommunityMatch] = []
    for hit in raw:
        score = float(getattr(hit, "score", 0.0) or 0.0)
        if score < min_similarity:
            continue
        payload = getattr(hit, "payload", None) or {}
        cid = str(payload.get("community_id") or "").strip()
        if not cid:
            continue
        matches.append(
            CommunityMatch(
                community_id=cid,
                summary=str(payload.get("summary") or "").strip(),
                similarity=score,
                entity_count=int(payload.get("entity_count") or 0),
                entities=_safe_entities(payload.get("entities")),
                kb_id=int(payload.get("kb_id") or kb_id),
            )
        )

    # 4. 排序 + 截断 top_k
    matches.sort(key=lambda m: m.similarity, reverse=True)
    truncated = matches[:top_k]

    logger.info(
        "community_search q_len=%d kb=%d hits=%d/%d top1=%.3f threshold=%.2f",
        len(q),
        kb_id,
        len(truncated),
        len(raw),
        truncated[0].similarity if truncated else 0.0,
        min_similarity,
    )
    return truncated
