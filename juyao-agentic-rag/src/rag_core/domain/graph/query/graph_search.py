"""图谱主路径统一入口：L1 派系 2 社区优先 → L2 全图降级 → L3 真没有（终态放弃）。

设计要点：
- 不读 state.merged_docs —— 图谱与向量完全解耦（错 chunk 不污染图谱扩展）
- 任何步骤失败不抛错给主链路，最坏返回 L3 EMPTY
- hops/max_edges/timeout 区分 L1（宽松）vs L2（严格收紧）
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from rag_core.core.config import Settings, get_settings
from rag_core.domain.graph.query.community_search import (
    CommunityMatch,
    community_search,
)
from rag_core.domain.graph.query.edge_queries import (
    resolve_entity_names,
)
from rag_core.domain.graph.query.observation import (
    _community_summaries_for_question,
    format_edges_for_prompt,
)
from rag_core.domain.graph.query.question_pipeline import prepare_graph_query
from rag_core.infrastructure.neo4j import get_read_graph

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GraphSearchResult:
    """run_graph_search 返回值。"""

    observation: str  # Observation 文本片段
    n_edges: int
    entities: tuple[str, ...]
    level: str  # "L1" | "L2" | "EMPTY"
    community_ids: tuple[str, ...]  # L1 命中的社区（用于 SSE source 标签）
    source: str  # "graph_search_L1" / "graph_search_L2" / "graph_search_EMPTY"


def _filter_entities_to_scope(
    entities: tuple[str, ...], matches: list[CommunityMatch]
) -> tuple[str, ...]:
    """把 A+B+C 抽取的实体过滤到 K 社区子图范围内（交集）。

    无交集时返回空 tuple，调用方判 0 实体 → 进入 L2。
    """
    scope: set[str] = set()
    for m in matches:
        scope.update(m.entities)
    if not scope:
        return ()
    out = tuple(e for e in entities if e in scope)
    return out


def _entities_in_scope(matches: list[CommunityMatch]) -> set[str]:
    """社区子图所有实体（用于 resolve_entity_names 兜底匹配 + 给 LLM 看上下文）。"""
    s: set[str] = set()
    for m in matches:
        s.update(m.entities)
    return s


async def _do_query_edges(
    *,
    entities: tuple[str, ...],
    hints: tuple[str, ...],
    kb_id: int,
    round_idx: int,
) -> tuple[str, int, tuple[str, ...]]:
    """已抽取实体 → resolve_entity_names → query_edges_from_entity_seeds → Observation。

    与 build_graph_observation_question_driven 类似，但接收外部传入的 entities+hints
    （避免 L1/L2 重复抽取 LLM）。

    Returns:
        (observation_text, n_edges, matched_entities)
    """
    if not entities:
        return (
            f"Observation（第 {round_idx} 次图谱补充）：未能抽取有效实体。",
            0,
            (),
        )

    cfg = get_settings()
    matched = resolve_entity_names(list(entities), settings=cfg, kb=kb_id)
    matched_t = tuple(matched) if matched else ()

    if not matched:
        return (
            f"Observation（第 {round_idx} 次图谱补充）：实体（{','.join(entities[:8])}）未匹配到节点。",
            0,
            (),
        )

    # 多跳查询
    try:
        from rag_core.domain.graph.query.edge_queries import (
            query_edges_from_entity_seeds,
        )

        edges = query_edges_from_entity_seeds(
            matched, settings=cfg, relation_hints=list(hints), kb=kb_id
        )
    except Exception as exc:
        logger.warning("Neo4j 问句驱动图谱查询失败：%s", exc)
        return (
            f"Observation（第 {round_idx} 次图谱补充）：图谱查询暂时不可用（{exc.__class__.__name__}）。",
            0,
            matched_t,
        )

    if not edges:
        joined = "、".join(matched[:12])
        return (
            f"Observation（第 {round_idx} 次图谱补充）："
            f"从种子实体（{joined}）出发未展开到关系边。",
            0,
            matched_t,
        )

    body = format_edges_for_prompt(edges)
    text = (
        f"Observation（第 {round_idx} 次图谱补充，共 {len(edges)} 条关系）：\n"
        f"{body}"
    )
    return text, len(edges), matched_t


async def run_graph_search(
    *,
    question: str,
    kb_id: int,
    round_idx: int = 1,
    settings: Settings | None = None,
) -> GraphSearchResult:
    """图谱主路径统一入口：L1 派系 2 社区优先 → L2 全图降级 → L3 真没有。

    Args:
        question: 用户原问句（直接来自 state.question）
        kb_id: 知识库 ID
        round_idx: 轮次（用于 Observation 文本标注）
        settings: 配置覆盖（默认 None）

    Returns:
        GraphSearchResult 含 level（L1/L2/EMPTY）与 SSE source 标签。
        失败兜底：任何异常都返回 EMPTY，不抛错给主链路。
    """
    q = (question or "").strip()
    if not q:
        return GraphSearchResult(
            observation="",
            n_edges=0,
            entities=(),
            level="EMPTY",
            community_ids=(),
            source="graph_search_EMPTY",
        )

    cfg = settings or get_settings()

    # === L1 · 派系 2 社区优先 ===
    try:
        matches = await asyncio.to_thread(community_search, q, kb_id=kb_id)
    except Exception as exc:
        logger.warning("L1 community_search 异常，进入 L2：%s", exc)
        matches = []

    if matches:
        logger.info(
            "L1 命中 %d 社区（top1=%.3f），进入子图约束",
            len(matches),
            matches[0].similarity,
        )
        # A+B+C pipeline（一次 LLM 调用 A+B 并行 + 一次 C）
        try:
            prep = await prepare_graph_query(q, kb=kb_id)
        except Exception as exc:
            logger.warning("A+B+C pipeline 异常，进入 L2：%s", exc)
            prep = None

        if prep and prep.entities:
            # 子图约束：实体必须落在 K 社区范围内
            scoped = _filter_entities_to_scope(prep.entities, matches)
            if scoped:
                try:
                    obs, n_edges, matched = await _do_query_edges(
                        entities=scoped,
                        hints=prep.relation_hints,
                        kb_id=kb_id,
                        round_idx=round_idx,
                    )
                except Exception as exc:
                    logger.warning("L1 _do_query_edges 异常，进入 L2：%s", exc)
                    obs, n_edges, matched = "", 0, ()

                if n_edges > 0:
                    return GraphSearchResult(
                        observation=obs,
                        n_edges=n_edges,
                        entities=matched,
                        level="L1",
                        community_ids=tuple(m.community_id for m in matches),
                        source="graph_search_L1",
                    )

                # L1 子图内 0 边 → 仍可尝试把 matched 之外的全图实体也试一遍
                # 但根据「派系 2 严格」原则：直接降级 L2，不再回扩到全图
                logger.info("L1 子图 0 边，降级 L2 全图")
            else:
                logger.info(
                    "L1 A+B+C 抽取的实体（%d 个）全部不在 %d 社区子图内，降级 L2",
                    len(prep.entities),
                    len(matches),
                )
    else:
        logger.info("L1 community_search 未命中（top-1 < 阈值），直接进入 L2")

    # === L2 · 全图降级（严格参数：hops=2, max_edges=20, timeout=5s）===
    try:
        prep2 = await prepare_graph_query(q, kb=kb_id)
    except Exception as exc:
        logger.warning("L2 A+B+C pipeline 异常：%s", exc)
        prep2 = None

    if prep2 and prep2.entities:
        try:
            obs, n_edges, matched = await _do_query_edges(
                entities=prep2.entities,
                hints=prep2.relation_hints,
                kb_id=kb_id,
                round_idx=round_idx,
            )
        except Exception as exc:
            logger.warning("L2 _do_query_edges 异常：%s", exc)
            obs, n_edges, matched = "", 0, ()

        if n_edges > 0:
            return GraphSearchResult(
                observation=obs,
                n_edges=n_edges,
                entities=matched,
                level="L2",
                community_ids=(),
                source="graph_search_L2",
            )

    # === L3 · 真没有（终态放弃，不再兜底）===
    logger.info("L1/L2 均无结果，L3 真没有")
    return GraphSearchResult(
        observation="",
        n_edges=0,
        entities=(),
        level="EMPTY",
        community_ids=(),
        source="graph_search_EMPTY",
    )


async def run_graph_search_l1_strict(
    *,
    question: str,
    kb_id: int,
    round_idx: int = 1,
    settings: Settings | None = None,
) -> GraphSearchResult:
    """仅 L1（不降级到 L2）—— 测试 / 调试专用。"""
    q = (question or "").strip()
    if not q:
        return GraphSearchResult(
            observation="",
            n_edges=0,
            entities=(),
            level="EMPTY",
            community_ids=(),
            source="graph_search_EMPTY",
        )

    matches = await asyncio.to_thread(community_search, q, kb_id=kb_id)
    if not matches:
        return GraphSearchResult(
            observation="",
            n_edges=0,
            entities=(),
            level="EMPTY",
            community_ids=(),
            source="graph_search_EMPTY",
        )

    prep = await prepare_graph_query(q, kb=kb_id)
    if not prep or not prep.entities:
        return GraphSearchResult(
            observation="",
            n_edges=0,
            entities=(),
            level="EMPTY",
            community_ids=tuple(m.community_id for m in matches),
            source="graph_search_EMPTY",
        )

    scoped = _filter_entities_to_scope(prep.entities, matches)
    if not scoped:
        return GraphSearchResult(
            observation="",
            n_edges=0,
            entities=(),
            level="EMPTY",
            community_ids=tuple(m.community_id for m in matches),
            source="graph_search_EMPTY",
        )

    obs, n_edges, matched = await _do_query_edges(
        entities=scoped,
        hints=prep.relation_hints,
        kb_id=kb_id,
        round_idx=round_idx,
    )
    return GraphSearchResult(
        observation=obs,
        n_edges=n_edges,
        entities=matched,
        level="L1" if n_edges > 0 else "EMPTY",
        community_ids=tuple(m.community_id for m in matches),
        source="graph_search_L1" if n_edges > 0 else "graph_search_EMPTY",
    )
