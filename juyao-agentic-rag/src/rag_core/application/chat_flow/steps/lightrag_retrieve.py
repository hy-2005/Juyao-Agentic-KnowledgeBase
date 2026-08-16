"""LightRAG 图谱检索步骤（与传统向量检索并行执行，LIGHTRAG_MIGRATION_REVIEW §3/§5）。

写入 state：observation（卡片 Observation）、graph_snapshots、had_graph_edges、
executed_steps（tool=query_knowledge_graph，SSE 契约字段与旧图谱步骤一致）。
"""

from __future__ import annotations

import logging

from rag_core.application.chat_flow.state import StepRecord

logger = logging.getLogger(__name__)


async def run_lightrag_retrieve_step(state, round_idx: int = 1) -> None:
    """并行分支之一：kg_cards 双路检索 → 状态落盘。任何失败只记日志不抛错。"""
    from rag_core.domain.graph.query.kg_card_search import run_kg_card_search

    try:
        result = await run_kg_card_search(
            question=state.question,
            history=state.history,
            kb_id=state.kb_id,
            round_idx=round_idx,
        )
    except Exception as exc:
        # 双保险：run_kg_card_search 内部已兜底，这里再兜一层保证并行 gather 不被单路炸穿
        logger.warning("【lightrag_retrieve】步骤异常（图谱路置空）：%s", exc)
        state.executed_steps.append(
            StepRecord(name="lightrag_retrieve", status="failed", tool="query_knowledge_graph")
        )
        return

    logger.info(
        "【lightrag_retrieve】cards=%d seeds=%d local_edges=%d global_hits=%d kw_high=%s kw_low=%s",
        result.n_cards,
        len(result.entity_seeds),
        result.local_edges,
        result.global_hits,
        list(result.keywords_high),
        list(result.keywords_low),
    )
    if result.observation:
        state.observation_lines.append(result.observation)
    state.graph_rounds = round_idx
    state.kg_card_count = result.n_cards
    if result.n_cards > 0:
        state.had_graph_edges = True
    state.graph_snapshots.append(
        {
            "edges": result.n_cards,
            "anchors": len(result.entity_seeds),
            "source": "lightrag_local_global",
            "entity_seeds": tuple(result.entity_seeds),
            "observation": result.observation,
            "chunk_sample": (),
        }
    )
    state.executed_steps.append(
        StepRecord(
            name="lightrag_retrieve",
            status="ok" if result.n_cards > 0 else "failed",
            tool="query_knowledge_graph",
            edge_count=result.n_cards,
            entity_seeds=list(result.entity_seeds),
            input_summary=(
                f"kw_high={','.join(result.keywords_high)}; kw_low={','.join(result.keywords_low)}"
            ),
            output_summary=f"local_edges={result.local_edges}; global_hits={result.global_hits}",
        )
    )
