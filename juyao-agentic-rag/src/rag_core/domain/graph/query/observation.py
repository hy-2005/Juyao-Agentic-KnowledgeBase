"""图谱 Observation 文本格式化与构建。"""

from __future__ import annotations

import logging

from rag_core.core.config import Settings, get_settings
from rag_core.domain.graph.query.edge_queries import (
    query_edges_for_chunks,
    query_edges_from_entity_seeds,
    resolve_entity_names,
)
# query_edges_for_chunks 仍保留在 imports 中——可能未来用于社区子图内精排（Step 8 后评估）
# 但 build_graph_observation_text 已删除（chunk_id 锚定路径废弃，见 GRAPH_QUERY_REVIEW §6.5）

from rag_core.domain.graph.query.edge_view import GraphEdgeView

logger = logging.getLogger(__name__)


def format_edges_for_prompt(edges: list[GraphEdgeView]) -> str:
    # 体积控制（P2）：evidence 摘录截到 120 字/条，关系表述 120 字，控制 Observation 总长
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
        # time/location hints 格式化（P2）：时间线/位置类问题可直接作答
        if e.time_hints:
            bits.append(f"时间: {' / '.join(e.time_hints[:2])}")
        if e.location_hints:
            bits.append(f"位置: {' / '.join(e.location_hints[:2])}")
        if e.relation_full_hints:
            rf = " | ".join(e.relation_full_hints[:1])
            if len(rf) > 120:
                rf = rf[:120] + "…"
            bits.append(f"关系表述: {rf}")
        if e.evidence_snippets:
            ev = " | ".join(e.evidence_snippets[:2])
            if sum(len(s) for s in e.evidence_snippets[:2]) > 120:
                ev = ev[:120] + "…"
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
    kb: int | None = None,
) -> tuple[str, int, list[str]]:
    from rag_core.domain.graph.query.question_seed import QuestionGraphSeedExtractor

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
        # global 检索兜底（GRAPH_QUERY_REVIEW §6）：实体未命中时用社区摘要
        global_text = _community_summaries_for_question(question, kb=kb)
        preview = "、".join(entities[:8])
        if global_text:
            return (
                f"Observation（第 {round_idx} 次图谱补充）："
                f"问句实体（{preview}）未匹配到节点，以下为知识库主题社区摘要：\n{global_text}",
                0,
                [],
            )
        return (
            f"Observation（第 {round_idx} 次图谱补充）："
            f"问句实体（{preview}）在图谱中未匹配到节点。",
            0,
            [],
        )

    try:
        edges = query_edges_from_entity_seeds(matched, settings=cfg, relation_hints=hints, kb=kb)
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


def build_graph_observation_text(*args, **kwargs):
    """已删除：chunk_id 锚定路径（派系 2 改造，GRAPH_QUERY_REVIEW §6.5）。

    保留函数定义仅为兼容旧 import；调用会抛错。如需 chunk 锚定的"确定性信号"
    保留场景，未来可重新引入（Step 8 评测后再决定是否恢复）。
    """
    raise NotImplementedError(
        "build_graph_observation_text 已删除（派系 2 改造，GRAPH_QUERY_REVIEW §6.5）。"
        "使用 domain.graph.query.graph_search.run_graph_search 替代。"
    )


def _char_ngrams(text: str, n: int) -> list[str]:
    """中文字符 n-gram（global 兜底的轻量相似度用，无分词依赖）。"""
    return [text[i : i + n] for i in range(len(text) - n + 1) if text[i : i + n].strip()]


def _community_summaries_for_question(question: str, kb: int | None) -> str:
    """global 检索兜底：问句与社区摘要按 2/3-gram 重叠度粗筛，取 top 2。"""
    from rag_core.application.graph.community_build import list_community_summaries

    summaries = list_community_summaries(kb=kb)
    if not summaries:
        return ""
    q_grams = set(_char_ngrams(question, 2)) | set(_char_ngrams(question, 3))
    scored: list[tuple[int, dict]] = []
    for s in summaries:
        s_grams = set(_char_ngrams(str(s.get("summary") or ""), 2)) | set(
            _char_ngrams(str(s.get("summary") or ""), 3)
        )
        scored.append((len(q_grams & s_grams), s))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [s for overlap, s in scored[:2] if overlap > 0]
    if not top:
        return ""
    return "\n".join(
        f"[社区 {s['community_id']}]（{s['entity_count']} 实体）：{s['summary']}" for s in top
    )
