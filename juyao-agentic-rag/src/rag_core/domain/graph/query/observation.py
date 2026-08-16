"""图谱 Observation 文本格式化（LightRAG 迁移后仅保留边格式化工具）。

问句驱动的 Observation 构建（build_graph_observation_question_driven）与
社区摘要兜底已随 L1/L2/L3 级联废弃删除——新主路径见 kg_card_search.py。
format_edges_for_prompt 保留给管理台/调试场景（边列表 → 文本行）。
"""

from __future__ import annotations

import logging

from rag_core.domain.graph.query.edge_view import GraphEdgeView

logger = logging.getLogger(__name__)


def format_edges_for_prompt(edges: list[GraphEdgeView]) -> str:
    """边列表 → Observation 文本行（chunk 引用 + 类型/时间/关系表述/依据摘录）。"""
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
