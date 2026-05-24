"""图谱 Observation 文本格式化与构建。"""

from __future__ import annotations

import logging

from rag_core.core.config import Settings, get_settings
from rag_core.knowledge_graph.edge_queries import (
    query_edges_for_chunks,
    query_edges_from_entity_seeds,
    resolve_entity_names,
)
from rag_core.knowledge_graph.edge_view import GraphEdgeView

logger = logging.getLogger(__name__)


def format_edges_for_prompt(edges: list[GraphEdgeView]) -> str:
    lines: list[str] = []
    for e in edges:
        cite = ",".join(e.chunk_ids[:3])
        if len(e.chunk_ids) > 3:
            cite += ",..."
        bits: list[str] = [f"chunk: {cite}"]
        if e.head_kinds:
            bits.append(f"头类型: {' / '.join(e.head_kinds[:2])}")
        if e.tail_kinds:
            bits.append(f"尾类型: {' / '.join(e.tail_kinds[:2])}")
        if e.relation_category_hints:
            bits.append(f"关系大类: {' / '.join(e.relation_category_hints[:2])}")
        if e.relation_full_hints:
            rf = " | ".join(e.relation_full_hints[:1])
            if len(rf) > 160:
                rf = rf[:160] + "…"
            bits.append(f"关系表述: {rf}")
        if e.evidence_snippets:
            ev = " | ".join(e.evidence_snippets[:2])
            if sum(len(s) for s in e.evidence_snippets[:2]) > 220:
                ev = ev[:220] + "…"
            bits.append(f"依据摘录: {ev}")
        lines.append(
            f"- {e.head_name} —[{e.relation_predicate}]→ {e.tail_name}（{'；'.join(bits)}）"
        )
    return "\n".join(lines)


def build_graph_observation_question_driven(
    question: str,
    *,
    round_idx: int,
    settings: Settings | None = None,
) -> tuple[str, int, list[str]]:
    from rag_core.knowledge_graph.question_seed import QuestionGraphSeedExtractor

    cfg = settings or get_settings()
    try:
        entities, hints = QuestionGraphSeedExtractor().extract(question)
    except Exception as exc:
        logger.warning("问句实体抽取失败：%s", exc)
        return (
            f"Observation（第 {round_idx} 次图谱补充）：问句实体抽取失败（{exc.__class__.__name__}）。",
            0,
            [],
        )

    if not entities:
        return (
            f"Observation（第 {round_idx} 次图谱补充）：未能从问句中抽取有效实体入口。",
            0,
            [],
        )

    matched = resolve_entity_names(entities, settings=cfg)
    if not matched:
        preview = "、".join(entities[:8])
        return (
            f"Observation（第 {round_idx} 次图谱补充）："
            f"问句实体（{preview}）在图谱中未匹配到节点。",
            0,
            [],
        )

    try:
        edges = query_edges_from_entity_seeds(matched, settings=cfg, relation_hints=hints)
    except Exception as exc:
        logger.warning("Neo4j 问句驱动图谱查询失败：%s", exc)
        return (
            f"Observation（第 {round_idx} 次图谱补充）：图谱查询暂时不可用（{exc.__class__.__name__}）。",
            0,
            matched,
        )

    if not edges:
        joined = "、".join(matched[:12])
        return (
            f"Observation（第 {round_idx} 次图谱补充）："
            f"从种子实体（{joined}）出发未展开到关系边。",
            0,
            matched,
        )

    body = format_edges_for_prompt(edges)
    text = (
        f"Observation（第 {round_idx} 次图谱补充，共 {len(edges)} 条关系，来自问句实体多跳展开）：\n"
        f"{body}"
    )
    return text, len(edges), matched


def build_graph_observation_text(
    chunk_ids: list[str],
    *,
    round_idx: int,
    settings: Settings | None = None,
) -> tuple[str, int]:
    cfg = settings or get_settings()
    if not chunk_ids:
        return (
            f"Observation（第 {round_idx} 次图谱补充）：当前尚无检索 chunk 可作为锚点。",
            0,
        )
    try:
        edges = query_edges_for_chunks(chunk_ids, settings=cfg)
    except Exception as exc:
        logger.warning("Neo4j 图谱查询失败：%s", exc)
        return (
            f"Observation（第 {round_idx} 次图谱补充）：图谱查询暂时不可用（{exc.__class__.__name__}）。",
            0,
        )
    if not edges:
        return (
            f"Observation（第 {round_idx} 次图谱补充）：未找到与当前检索 chunk 关联的实体关系。",
            0,
        )
    body = format_edges_for_prompt(edges)
    text = (
        f"Observation（第 {round_idx} 次图谱补充，共 {len(edges)} 条关系，来自向量检索锚定）：\n"
        f"{body}"
    )
    return text, len(edges)
